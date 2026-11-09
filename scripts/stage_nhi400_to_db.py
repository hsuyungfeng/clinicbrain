#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/stage_nhi400_to_db.py

健保第 201-400 項動畫草稿安全入庫工具：
1. 讀取 data/visual/nhi400_generated.json（或 data/visual/nhi400_manifest.json）。
2. 安全防護：正式庫寫入強制要求 --allow-prod-db 旗標。
3. 自動備份資料庫快照。
4. 唯一權威路徑：透過 src/visual/writer.py:upsert_assets 以 review_status='pending' 入庫。
5. 冪等執行，輸出插入、更新與未變統計。
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.visual.writer import upsert_assets
from src.visual.ir import validate_ir
from scripts.generate_nhi400_visual_batch import (
    run_batch,
    MANIFEST_PATH,
    OUTPUT_DIR,
    DB_PATH,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("stage_nhi400")


def backup_database(db_path: Path) -> Path:
    """自動備份資料庫快照。"""
    if not db_path.exists():
        return db_path
    ts = int(time.time())
    bak_path = db_path.with_name(f"{db_path.name}.bak-nhi400-{ts}")
    shutil.copy2(db_path, bak_path)
    logger.info("📦 資料庫已備份至：%s", bak_path)
    return bak_path


def stage_assets_to_db(
    db_path: Path = DB_PATH,
    generated_path: Path = OUTPUT_DIR / "nhi400_generated.json",
    allow_prod_db: bool = False,
) -> dict[str, int]:
    """將生成的 200 筆 201-400 專科動畫安全入庫。"""
    if db_path.resolve() == DB_PATH.resolve() and not allow_prod_db:
        raise PermissionError(
            "⚠️ 嘗試寫入正式資料庫，必須明確指定 --allow-prod-db 旗標以防止意外覆寫！"
        )

    # 檢查生成產物是否存在，若無則先調用 run_batch
    if not generated_path.exists():
        logger.info("未發現生成產物 %s，自動執行 Mock 批次生成...", generated_path)
        run_batch(
            manifest_path=MANIFEST_PATH,
            mock_mode=True,
            dry_run=True,
            write_db=False,
        )

    with open(generated_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    results = payload.get("results", [])
    if not results:
        raise ValueError("生成產物中無有效結果 (results 為空)")

    logger.info("準備將 %d 筆專科動畫草稿入庫至：%s", len(results), db_path)

    # 備份資料庫
    if db_path.exists():
        backup_database(db_path)

    conn = sqlite3.connect(db_path)
    asset_rows = []
    for r in results:
        ir_obj = r["ir"]
        asset_rows.append({
            "clinic_id": None,
            "topic_key": ir_obj["topic_key"],
            "title": ir_obj["title"],
            "keywords": ir_obj["keywords"],
            "ir": ir_obj,
            "metadata": {"batch": "phase40_nhi400", "status": "draft"},
        })

    # 透過唯一權威路徑寫入
    summary = upsert_assets(
        conn=conn,
        assets=asset_rows,
        source_type="llm_generated",
        commit=True,
    )
    conn.close()

    logger.info("🎉 入庫完成！統計摘要：%s", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="健保 201-400 動畫草稿安全入庫工具")
    parser.add_argument("--db-path", type=Path, default=DB_PATH, help="目標 SQLite 資料庫路徑")
    parser.add_argument("--allow-prod-db", action="store_true", default=False, help="允許寫入正式資料庫旗標")
    args = parser.parse_args()

    stage_assets_to_db(
        db_path=args.db_path,
        allow_prod_db=args.allow_prod_db,
    )
