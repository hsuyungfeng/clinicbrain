#!/usr/bin/env python3
"""
scripts/build_nhi200_v2_manifest.py

建構 200 筆衛教動畫標準任務清單 (data/visual/nhi200_v2_manifest.json)：
1. 前 88 筆：診所既有核心動畫資產（保留原 topic_key 與 id，標記 is_v2_upgrade = True）
2. 後 112 筆：健保署門診高頻專科疾病（西醫、中醫、牙醫，標記 is_v2_upgrade = False）
總計剛好 200 筆。
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "clinic.db"
NHI_PATH = ROOT / "data" / "nhi_primary_care_200.json"
MANIFEST_PATH = ROOT / "data" / "visual" / "nhi200_v2_manifest.json"


def _clean_slug(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:64] or "nhi-disease"


def build_manifest() -> list[dict]:
    manifest: list[dict] = []

    # 1. 讀取 DB 前 88 筆既有資產
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    db_rows = cur.execute(
        "SELECT id, clinic_id, topic_key, title, keywords, ir_json FROM visual_assets ORDER BY id ASC LIMIT 88"
    ).fetchall()
    conn.close()

    for idx, row in enumerate(db_rows, start=1):
        asset_id, clinic_id, topic_key, title, kw_raw, ir_raw = row
        keywords = []
        if kw_raw:
            try:
                keywords = json.loads(kw_raw) if isinstance(kw_raw, str) else list(kw_raw)
            except Exception:
                keywords = [k.strip() for k in str(kw_raw).split(",") if k.strip()]

        # 推斷專科分類
        cat = "診所核心醫美與外科療程"
        t_clean = (title or "").replace("衛教圖解", "").replace("原理圖解", "").replace("原理", "").strip()

        manifest.append({
            "index": idx,
            "topic_key": topic_key,
            "title": f"{t_clean}原理圖解",
            "disease_name": t_clean,
            "category": cat,
            "icd10": None,
            "is_v2_upgrade": True,
            "existing_asset_id": asset_id,
            "clinic_id": clinic_id or "3503190424",
            "keywords": keywords[:6] or [t_clean]
        })

    # 2. 讀取 NHI 門診高頻疾病 (159 筆)，選取 112 筆非重複項目
    with open(NHI_PATH, "r", encoding="utf-8") as f:
        nhi_all = json.load(f)

    # 排除與前 88 筆語意高度重疊者
    existing_titles = {m["disease_name"] for m in manifest}
    nhi_candidates = []
    for d in nhi_all:
        name = d.get("name", "")
        # 簡易排除已完全相同的名稱
        if any(name in et or et in name for et in existing_titles if len(et) > 3):
            continue
        nhi_candidates.append(d)

    # 取剛好 112 筆 (補足至 200 筆)
    needed = 200 - len(manifest)
    selected_nhi = nhi_candidates[:needed]

    for offset, d in enumerate(selected_nhi):
        idx = len(manifest) + 1
        d_id = str(d.get("id", f"N{idx}")).lower()
        icd_raw = _clean_slug(d.get("icd10", ""))
        name = d.get("name", "專科疾病")
        slug_base = f"nhi-{d_id}-{icd_raw}" if icd_raw else f"nhi-{d_id}"
        topic_key = _clean_slug(slug_base)

        manifest.append({
            "index": idx,
            "topic_key": topic_key,
            "title": f"{name}衛教圖解",
            "disease_name": name,
            "category": d.get("category", "基層專科常見疾病"),
            "icd10": d.get("icd10"),
            "is_v2_upgrade": False,
            "existing_asset_id": None,
            "clinic_id": "3503190424",
            "keywords": d.get("keywords", [])[:6] or [name]
        })

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"✅ 成功生成 200 筆標準任務清單: {MANIFEST_PATH}")
    print(f"   - 既有資產升級 V2: {sum(1 for m in manifest if m['is_v2_upgrade'])} 筆")
    print(f"   - 新增專科疾病: {sum(1 for m in manifest if not m['is_v2_upgrade'])} 筆")
    print(f"   - 總計: {len(manifest)} 筆")
    return manifest


if __name__ == "__main__":
    build_manifest()
