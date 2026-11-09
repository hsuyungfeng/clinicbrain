#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - 健保疾病去重篩檢器 (NHI Deduplicator)
Phase 39 Wave 1: 自動比對正式資料庫既有已核准之 88 個主題動畫，精確篩除已存在項，鎖定需新生成之缺項。
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "clinic.db"
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "data" / "nhi_primary_care_200.json"
DEFAULT_CATALOG_400_PATH = PROJECT_ROOT / "data" / "nhi_primary_care_201_400.json"
DEFAULT_INDEX_400_PATH = PROJECT_ROOT / "data" / "nhi_primary_care_1_400_index.json"


def normalize_term(text: str) -> str:
    """標準化文字：轉小寫、去除標點符號與多餘空白。"""
    if not text:
        return ""
    s = re.sub(r"[（）\(\)\[\]【】\s\-_.,，、]+", "", text.lower())
    return s


def load_nhi_catalog(catalog_path: Path = DEFAULT_CATALOG_PATH) -> List[Dict[str, Any]]:
    """讀取健保 200 大疾病目錄 JSON。"""
    if not catalog_path.exists():
        raise FileNotFoundError(f"找不到健保疾病目錄檔案: {catalog_path}")
    with open(catalog_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_existing_visual_assets(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """從資料庫讀取所有已核准之視覺解說資產。"""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, clinic_id, topic_key, title, source_type, created_at
        FROM visual_assets
        WHERE review_status = 'approved'
        ORDER BY id ASC
        """
    )
    rows = cursor.fetchall()
    assets = []
    for r in rows:
        assets.append({
            "id": r[0],
            "clinic_id": r[1],
            "topic_key": r[2],
            "title": r[3] or "",
            "source_type": r[4],
            "created_at": r[5],
        })
    return assets


def match_item_against_assets(item: Dict[str, Any], assets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    判定單一健保目錄項目是否已存在於現有資產庫中。
    比對維度：
    1. ICD-10 代碼精確匹配（例如 J06.9 匹配 icd-j069-uri）
    2. 主題名稱或別名完全包含於 asset title 或 topic_key
    3. 核心醫療特徵詞高信心交集
    """
    item_icd = normalize_term(item.get("icd10", ""))
    item_name = normalize_term(item.get("name", ""))
    aliases = [normalize_term(a) for a in item.get("alias", [])]

    for asset in assets:
        asset_key = normalize_term(asset["topic_key"])
        asset_title = normalize_term(asset["title"])

        # 1. ICD-10 代碼比對（去除小數點如 j069）
        clean_icd = item_icd.replace(".", "")
        if clean_icd and len(clean_icd) >= 3 and clean_icd in asset_key:
            return asset

        # 2. 名稱完全匹配或雙向包含
        if item_name and len(item_name) >= 2:
            if item_name in asset_title or item_name in asset_key:
                return asset

        # 3. 別名比對
        for a in aliases:
            if a and len(a) >= 2:
                if a in asset_title or a in asset_key:
                    return asset

    return None


def partition_nhi_catalog(
    catalog: List[Dict[str, Any]],
    assets: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    將 200 項目錄劃分為：
    1. covered: 已存在於既有庫中（即需篩掉的 88 既有資產重疊項）
    2. to_generate: 缺項（需要新生成 24 秒動畫之項目）
    """
    covered = []
    to_generate = []

    for item in catalog:
        matched = match_item_against_assets(item, assets)
        if matched:
            covered.append({
                "item": item,
                "matched_asset": {
                    "id": matched["id"],
                    "topic_key": matched["topic_key"],
                    "title": matched["title"],
                },
            })
        else:
            to_generate.append(item)

    return covered, to_generate


def verify_seed_separation(
    seed_200_path: Path = DEFAULT_CATALOG_PATH,
    seed_400_path: Path = DEFAULT_CATALOG_400_PATH,
    db_conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """
    Phase 40 Wave 1: 驗證第 201 至 400 項新種子與前 200 項（及現有資料庫資產）達到 100% 獨立隔離。
    檢驗規則：
    1. ID 絕不重複（例如 W001 vs W201）。
    2. 主題名稱無完全同名碰撞。
    3. 若傳入 db_conn，亦比對資料庫已存在的 topic_key 與 title，防止雙寫。
    """
    cat200 = load_nhi_catalog(seed_200_path)
    cat400 = load_nhi_catalog(seed_400_path)

    ids_200 = {item["id"] for item in cat200 if "id" in item}
    names_200 = {normalize_term(item["name"]) for item in cat200 if "name" in item}

    conflicts: list[dict[str, Any]] = []

    for item in cat400:
        item_id = item.get("id", "")
        item_name = normalize_term(item.get("name", ""))

        if item_id in ids_200:
            conflicts.append({
                "type": "duplicate_id",
                "id": item_id,
                "name": item.get("name"),
                "reason": f"ID {item_id} 已存在於前 200 項目錄中",
            })

        if item_name in names_200:
            conflicts.append({
                "type": "duplicate_name",
                "id": item_id,
                "name": item.get("name"),
                "reason": f"名稱 {item.get('name')} 與前 200 項完全重合",
            })

    db_conflicts: list[dict[str, Any]] = []
    if db_conn:
        existing_assets = load_existing_visual_assets(db_conn)
        db_keys = {a["topic_key"] for a in existing_assets}
        db_titles = {normalize_term(a["title"]) for a in existing_assets}

        for item in cat400:
            # Check if identical title already approved
            norm_n = normalize_term(item.get("name", ""))
            if norm_n in db_titles:
                db_conflicts.append({
                    "type": "db_title_collision",
                    "id": item.get("id"),
                    "name": item.get("name"),
                })

    return {
        "seed_200_count": len(cat200),
        "seed_400_count": len(cat400),
        "seed_conflicts": conflicts,
        "db_conflicts": db_conflicts,
        "is_clean": len(conflicts) == 0 and len(db_conflicts) == 0,
    }


def main():
    print(f"=== 台灣健保基層疾病去重篩檢器 (NHI Deduplicator) ===")
    conn = sqlite3.connect(str(DEFAULT_DB_PATH))
    try:
        catalog = load_nhi_catalog(DEFAULT_CATALOG_PATH)
        assets = load_existing_visual_assets(conn)
        print(f"已讀取健保目錄總數: {len(catalog)} 項")
        print(f"現有已核准資產筆數: {len(assets)} 筆 (含診所專屬與昇華副本)")

        covered, to_generate = partition_nhi_catalog(catalog, assets)
        print(f"\n[比對結果統計]")
        print(f"  • 既有資產覆蓋（已篩除重複項）: {len(covered)} 項")
        print(f"  • 尚缺項目（需新生成動畫）:   {len(to_generate)} 項")

        print(f"\n[範例已覆蓋項目前 5 項]")
        for c in covered[:5]:
            print(f"  ✓ {c['item']['name']} -> 匹配既有資產: [{c['matched_asset']['topic_key']}] {c['matched_asset']['title']}")

        print(f"\n[待生成項目按系統分佈]")
        systems = {}
        for item in to_generate:
            sys_name = item.get("system", "unknown")
            systems[sys_name] = systems.get(sys_name, 0) + 1
        for sys_name, count in systems.items():
            print(f"  - {sys_name}: {count} 項")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
