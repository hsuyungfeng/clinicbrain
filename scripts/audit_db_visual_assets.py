#!/usr/bin/env python3
"""深度稽核 clinic.db 全部 visual_assets（語意器官映射 + 前端 pmPickAnatomyDrawer 派發）。"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.audit_manifest_anatomy import ORGAN_RULES

DEFAULT_DB = PROJECT_ROOT / "clinic.db"

# 非齲齒／非牙髓病變卻落入 pmDentalCariesSection 時即屬渲染層錯配
NON_CARIES_ORAL_MARKERS = (
    "念珠菌", "鵝口瘡", "口瘡", "口炎", "扁平苔", "白斑", "黏液囊", "舌下腺", "唾液腺",
    "牙齦纖", "牙齦瘤", "乾槽", "顳顎", "關節盤", "多生牙", "正中多生", "阻生", "齒列",
    "乳牙", "恆牙", "植體", "植牙", "三叉神經", "包皮", "龜頭",
)


def simulate_js_drawer(params: dict[str, Any]) -> str:
    """模擬 src/web/static/visual_engine.js pmPickAnatomyDrawer(p) 實際派發結果。"""
    osys = str(params.get("organ_system") or "")
    combined = f"{params.get('organ_label', '')} {params.get('anatomy_target', '')} {params.get('lesion_label', '')}"

    if any(k in combined for k in ("扁桃", "懸雍垂")):
        return "pmPharynxTonsil"
    if any(k in combined for k in ("落枕", "頸深筋膜", "項韌帶", "頸椎")):
        return "pmCervicalSpineFascia"
    if osys and osys not in ("dental_oral", "dental_periodontal", "respiratory_mucosa"):
        return osys
    if any(k in combined for k in ("三叉神經",)):
        return "pmVascular"
    if any(k in combined for k in ("顳顎", "關節盤")):
        return "pmTMJJoint"
    if any(k in combined for k in ("多生牙", "正中多生", "恆牙", "乳牙", "齒列", "阻生")):
        return "pmMesiodensArch"
    if any(k in combined for k in ("植體", "植牙")):
        return "pmDentalImplantPeri"
    if any(k in combined for k in ("乾槽",)):
        return "pmDentalPeriodontal"
    if osys == "dental_oral" and any(k in combined for k in ("念珠菌", "鵝口瘡", "扁平苔", "白斑", "黏膜", "唾液腺", "舌下腺", "口底", "黏液囊", "唇", "口瘡", "口炎", "牙齦纖", "牙齦瘤")):
        return "pmOralMucosaLesion"
    if osys == "dental_oral":
        return "pmDentalCariesSection"
    if osys == "dental_periodontal":
        return "pmDentalPeriodontal"
    return osys or "pmRespiratory"


def audit_db(db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    try:
        rows = conn.execute(
            "SELECT topic_key, title, keywords, ir_json, review_status FROM visual_assets ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    findings: list[dict[str, Any]] = []
    by_organ = Counter()
    non_pathology_skipped = 0

    for tk, title, kw_raw, ir_raw, r_status in rows:
        ir = json.loads(ir_raw)
        scenes = ir.get("scenes") or []
        s0 = scenes[0] if scenes else {}
        bp = s0.get("blueprint", "")
        if bp != "pathology_mechanism":
            non_pathology_skipped += 1
            continue

        params = s0.get("params") or {}
        organ = params.get("organ_system") or "MISSING"
        by_organ[organ] += 1

        try:
            kw_list = json.loads(kw_raw) if kw_raw else []
        except Exception:
            kw_list = []
        text = " ".join([str(title or ""), " ".join(str(x) for x in kw_list)])

        drawer = simulate_js_drawer(params)
        reasons: list[str] = []

        rule = ORGAN_RULES.get(organ)
        if rule is None and organ not in ("tcm_special_acup", "tcm_meridian"):
            reasons.append(f"未知或缺失 organ_system={organ}")
        elif rule is not None:
            hit_mismatch = [kw for kw in rule["mismatch_keywords"] if kw in text]
            hit_expected = [kw for kw in rule["expected_any"] if kw in text]
            if hit_mismatch:
                reasons.append(f"含非對應部位詞 {hit_mismatch}")
            elif not hit_expected:
                reasons.append(f"未命中預期器官關鍵字 ({'/'.join(rule['expected_any'][:4])}...)")

        if drawer == "pmDentalCariesSection" and any(m in text for m in NON_CARIES_ORAL_MARKERS):
            reasons.append("非齲齒/牙髓病變卻退化派發至 pmDentalCariesSection")

        if reasons:
            findings.append(
                {
                    "topic_key": tk,
                    "title": title,
                    "review_status": r_status,
                    "organ_system": organ,
                    "drawer": drawer,
                    "reasons": reasons,
                }
            )

    return {
        "total": len(rows),
        "pathology_checked": len(rows) - non_pathology_skipped,
        "non_pathology_skipped": non_pathology_skipped,
        "mismatch_count": len(findings),
        "by_organ": dict(by_organ),
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="深度稽核 clinic.db 全部 visual_assets 解剖映射與繪圖派發")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true")
    args = p.parse_args(argv)

    rep = audit_db(args.db)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(
            f"全庫 visual_assets: {rep['total']} 筆 | "
            f"pathology_mechanism 檢查: {rep['pathology_checked']} 筆 | "
            f"非 pathology 跳過: {rep['non_pathology_skipped']} 筆 | "
            f"錯配數: {rep['mismatch_count']}"
        )
        for f in rep["findings"]:
            print(
                f"  [{f['topic_key']}] {f['title']} | organ={f['organ_system']} | "
                f"drawer={f['drawer']} | {'; '.join(f['reasons'])}"
            )
    return 1 if (args.strict and rep["mismatch_count"] > 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
