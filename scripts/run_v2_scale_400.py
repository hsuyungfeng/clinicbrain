#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/run_v2_scale_400.py

健保第 201-400 項專科疾病動畫端到端規模化調度腳本：
1. 階段一：前置全庫雙向去重比對 (verify_seed_separation)。
2. 階段二：任務清單編譯 (build_manifest 產出 200 筆)。
3. 階段三：批次自癒生成 (run_batch)。
4. 階段四：產出執行與審查統計報告。
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.visual.nhi_dedup import verify_seed_separation
from scripts.build_nhi400_manifest import build_manifest, OUTPUT_PATH as MANIFEST_PATH
from scripts.generate_nhi400_visual_batch import run_batch, DB_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_scale_400")


def run_pipeline(
    limit: int | None = None,
    mock_mode: bool = True,
    dry_run: bool = True,
    write_db: bool = False,
) -> dict:
    start_time = time.time()
    logger.info("==================================================")
    logger.info("🏁 啟動 Phase 40: 健保 201-400 專科動畫規模化管線")
    logger.info("==================================================")

    # 1. 雙向去重驗證
    logger.info("[步驟 1/4] 執行雙向去重檢驗...")
    dedup_report = verify_seed_separation()
    if not dedup_report.get("is_clean"):
        logger.error("❌ 去重檢驗未通過！發現衝突或格式錯誤：%s", dedup_report.get("seed_conflicts"))
        raise RuntimeError("去重檢驗失敗，終止管線")
    logger.info("✅ 去重檢驗合格：新種子 200 筆與現有庫完全隔離，0 衝突。")

    # 2. 編譯任務清單
    logger.info("[步驟 2/4] 編譯 201-400 任務清單 (Manifest)...")
    manifest = build_manifest()
    logger.info("✅ 任務清單編譯完成，共 %d 筆任務。", len(manifest))

    # 3. 批次自癒生成
    logger.info("[步驟 3/4] 執行批次自癒生成 (mock=%s, dry_run=%s, write_db=%s)...", mock_mode, dry_run, write_db)
    summary = run_batch(
        manifest_path=MANIFEST_PATH,
        limit=limit,
        mock_mode=mock_mode,
        dry_run=dry_run,
        write_db=write_db,
    )

    # 4. 統計報告
    elapsed = time.time() - start_time
    logger.info("==================================================")
    logger.info("📊 Phase 40 管線執行總結報告 (耗時 %.2f 秒)：", elapsed)
    logger.info("   - 總任務數：%d", summary.get("total", 0))
    logger.info("   - 成功筆數：%d", summary.get("success", 0))
    logger.info("   - 失敗筆數：%d", summary.get("failed", 0))
    logger.info("   - 成功率：%s", summary.get("success_rate", "0%"))
    logger.info("==================================================")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="健保 201-400 疾病動畫端到端規模化調度腳本")
    parser.add_argument("--limit", type=int, default=None, help="處理上限筆數")
    parser.add_argument("--mock", action="store_true", default=True, help="使用 Mock 模式（預設 True）")
    parser.add_argument("--live", dest="mock", action="store_false", help="使用真實 LLM 模式")
    parser.add_argument("--dry-run", action="store_true", default=False, help="僅產出檔案不寫入資料庫")
    parser.add_argument("--write-db", action="store_true", default=False, help="寫入資料庫 pending 狀態")
    args = parser.parse_args()

    run_pipeline(
        limit=args.limit,
        mock_mode=args.mock,
        dry_run=args.dry_run,
        write_db=args.write_db,
    )
