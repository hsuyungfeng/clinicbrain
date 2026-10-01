#!/usr/bin/env python3
"""
夜間批次排程 CLI 命令列工具（Phase 09 BATCH-03 Task 2）。

提供夜間自動化執行 FAQ 預生成與臨床推理樹重建之主進入點。
具備正式資料庫寫入防禦、非阻塞檔案鎖互斥、唯讀 dry-run 預演與結構化日誌記錄。
"""

import argparse
import fcntl
from functools import partial
from pathlib import Path
import sqlite3
import sys
from typing import Callable, Optional

# 將專案根目錄加入搜尋路徑
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.batch.run_log import RunLogger
from src.batch.runner import (
    BatchConfig,
    BatchPreflightError,
    BatchSummary,
    run_batch,
)
from src.batch.topic_sources import SeedFileError

PROD_DB_PATH = PROJECT_ROOT / "clinic.db"
DEFAULT_SEED_PATH = PROJECT_ROOT / "data" / "batch" / "faq_seeds.json"


def resolve_log_dir(arg: Optional[str]) -> Path:
    """解析日誌目錄：預設為專案根目錄下的絕對路徑 logs/nightly_batch。"""
    if arg is None:
        return PROJECT_ROOT / "logs" / "nightly_batch"
    return Path(arg).resolve()


def lock_path_for(db_path: Path | str) -> Path:
    """取得資料庫專屬的非阻塞檔案鎖路徑（與資料庫位於同目錄）。"""
    resolved_db = Path(db_path).resolve()
    return resolved_db.with_name(f"{resolved_db.name}.nightly.lock")


def _positive_int(val: str) -> int:
    try:
        ival = int(val)
        if ival <= 0:
            raise ValueError()
        return ival
    except ValueError:
        raise argparse.ArgumentTypeError(f"必須為正整數: '{val}'")


def _positive_float(val: str) -> float:
    try:
        fval = float(val)
        if fval <= 0.0:
            raise ValueError()
        return fval
    except ValueError:
        raise argparse.ArgumentTypeError(f"必須為正浮點數: '{val}'")


def create_parser() -> argparse.ArgumentParser:
    """建立命令列參數解析器。"""
    parser = argparse.ArgumentParser(
        description="clinicbrain 夜間批次自動化排程 CLI 工具",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=str,
        default=str(PROD_DB_PATH),
        help="目標 SQLite 資料庫路徑",
    )
    parser.add_argument(
        "--seed-file",
        type=str,
        default=str(DEFAULT_SEED_PATH),
        help="FAQ 與樹主題種子清單 JSON 檔路徑",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="預演模式：唯讀開啟資料庫，不呼叫 LLM，僅輸出規劃",
    )
    parser.add_argument(
        "--allow-prod-db",
        action="store_true",
        help="允許對正式 clinic.db 執行寫入之安全確認旗標",
    )
    parser.add_argument(
        "--skip-faq",
        action="store_true",
        help="略過 FAQ 預生成階段",
    )
    parser.add_argument(
        "--skip-trees",
        action="store_true",
        help="略過臨床推理樹重建階段",
    )
    parser.add_argument(
        "--max-faq-topics",
        type=_positive_int,
        default=5,
        help="單次批次處理之最大 FAQ 主題數量上限",
    )
    parser.add_argument(
        "--max-trees",
        type=_positive_int,
        default=3,
        help="單次批次重建之最大臨床推理樹數量上限",
    )
    parser.add_argument(
        "--since-days",
        type=_positive_int,
        default=14,
        help="統計未命中關鍵字之回溯天數",
    )
    parser.add_argument(
        "--min-miss-count",
        type=_positive_int,
        default=3,
        help="熱門未命中關鍵字選題門檻次數",
    )
    parser.add_argument(
        "--max-pending",
        type=_positive_int,
        default=200,
        help="待審核 pending 總數上限（達到時跳過 FAQ 預生成保護醫師審核負擔）",
    )
    parser.add_argument(
        "--time-budget-seconds",
        type=_positive_float,
        default=3600.0,
        help="批次整體時間預算秒數（超時優雅中斷）",
    )
    parser.add_argument(
        "--llm-timeout",
        type=_positive_int,
        default=120,
        help="單次呼叫本地 LLM 之逾時秒數",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default=None,
        help="執行日誌儲存目錄（預設為 logs/nightly_batch）",
    )
    return parser


def main(
    argv: Optional[list[str]] = None,
    *,
    llm_call: Optional[Callable[[str], str]] = None,
    health_check: Optional[Callable[[], Optional[str]]] = None,
) -> int:
    """夜間批次 CLI 主進入點。"""
    parser = create_parser()
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        sys.stderr.write(f"錯誤：找不到指定的目標資料庫檔案：{db_path}\n")
        return 2

    seed_path = Path(args.seed_file).resolve()
    if not seed_path.exists():
        sys.stderr.write(f"錯誤：找不到指定的種子清單檔案：{seed_path}\n")
        return 2

    is_prod = (db_path == PROD_DB_PATH.resolve())
    if not args.dry_run and is_prod and not args.allow_prod_db:
        sys.stderr.write(
            "====================================================================\n"
            "【安全性拒絕】目標為正式環境 clinic.db！\n"
            "非 dry-run 批次寫入具有覆蓋或異動資料風險。若確認要於正式庫執行：\n"
            "1. 請先手動建立備份：cp clinic.db clinic.db.bak-$(date +%Y%m%d)\n"
            "2. 於命令列明確帶入 --allow-prod-db 旗標。\n"
            "建議可先以 --dry-run 預演確認預計動作。\n"
            "====================================================================\n"
        )
        return 2

    log_dir = resolve_log_dir(args.log_dir)
    logger = RunLogger(log_dir, echo=True)

    lock_fd = None
    if not args.dry_run:
        lock_file = lock_path_for(db_path)
        try:
            lock_fd = open(lock_file, "a+")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            logger.warning("batch_locked_skip", lock_file=str(lock_file))
            print("已有另一個夜間批次行程執行中，本次執行安全略過。")
            if lock_fd is not None:
                lock_fd.close()
            logger.close()
            return 0

    conn = None
    try:
        if args.dry_run:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        else:
            conn = sqlite3.connect(str(db_path), timeout=30)
            conn.execute("PRAGMA foreign_keys = ON;")

        if not args.dry_run:
            if llm_call is None or health_check is None:
                from src.pageindex.llm_client import check_llm_health, local_llm_call
                if llm_call is None:
                    llm_call = partial(local_llm_call, timeout=args.llm_timeout)
                if health_check is None:
                    health_check = check_llm_health
        else:
            if llm_call is None:
                llm_call = lambda p: ""
            if health_check is None:
                health_check = lambda: None

        cfg = BatchConfig(
            seed_path=seed_path,
            snapshot_dir=log_dir / "tree_snapshots",
            dry_run=args.dry_run,
            skip_faq=args.skip_faq,
            skip_trees=args.skip_trees,
            max_faq_topics=args.max_faq_topics,
            max_trees=args.max_trees,
            since_days=args.since_days,
            min_miss_count=args.min_miss_count,
            max_pending=args.max_pending,
            time_budget_seconds=args.time_budget_seconds,
        )

        summary: BatchSummary = run_batch(
            conn,
            cfg,
            llm_call=llm_call,
            health_check=health_check,
            logger=logger,
        )

        print("\n==================== 批次執行摘要 ====================")
        print(f"執行狀態：{summary.status}")
        print(f"FAQ 主題：規劃 {summary.faq_topics_planned} 個，處理 {summary.faq_topics_processed} 個")
        print(f"FAQ 筆數：新增 {summary.faq_inserted} 筆，剔除 {summary.faq_rejected} 筆，略過既有 {summary.faq_skipped_existing} 筆")
        print(f"推理樹：規劃 {summary.trees_planned} 棵，重建 {summary.trees_rebuilt} 棵，未變 {summary.trees_unchanged} 棵，略過 {summary.trees_skipped} 棵")
        if summary.trees_overwrote_handwritten > 0:
            print(f"⚠️ 注意：共有 {summary.trees_overwrote_handwritten} 棵手寫或上傳之推理樹被重建覆蓋")
        print(f"錯誤數：{summary.errors}")
        print("======================================================")
        return 0

    except SeedFileError as e:
        sys.stderr.write("清單檔案結構驗證失敗：\n")
        for err in e.errors:
            sys.stderr.write(f"- {err}\n")
        return 2
    except BatchPreflightError as e:
        sys.stderr.write(f"批次前置環境檢查未通過：{e}\n")
        return 2
    except Exception as e:
        logger.error("unexpected_error", error_type=type(e).__name__)
        sys.stderr.write(f"執行夜間批次時發生未預期異常：{type(e).__name__}\n")
        return 1
    finally:
        if conn is not None:
            conn.close()
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            lock_fd.close()
        logger.close()


if __name__ == "__main__":
    sys.exit(main())
