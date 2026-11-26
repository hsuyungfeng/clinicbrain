"""clinicbrain 夜間批次 Prefect 3 Flow / Task 包裝模組。

設計原則（零侵入）：
- 直接呼叫既有腳本進入點（`run_nightly_batch.main`、`run_web_research_batch.main`、
  `run_daily_knowledge_refresh.main`），不拆解內部 stage，完整保留 `<db>.nightly.lock`
  與 `src.batch.db_lock` 互斥機制。
- LLM 相關任務透過 Prefect 全域並發鎖 `local_llm_gpu` (limit=1) 與跨機制檔案鎖
  `/tmp/local_llm_8080.lock`（`fcntl.flock`）雙重保護本地 `8080` 推論伺服器。
- 設定 `@task(retries=2, retry_delay_seconds=60)` 與非致命 `on_failure` 失敗告警鉤子。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Iterator, Optional

from prefect import flow, task
from prefect.concurrency.sync import concurrency

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INFRA_PREFECT_DIR = PROJECT_ROOT.parent / "infra" / "prefect"

for _path in (str(PROJECT_ROOT), str(INFRA_PREFECT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from llm_lock import (  # noqa: E402
    DEFAULT_LLM_LOCK_PATH,
    acquire_llm_8080_lock,
    is_llm_blackout_window,
)

logger = logging.getLogger("clinicbrain.prefect")


@contextmanager
def _patched_argv(argv: list[str]) -> Iterator[None]:
    """暫時替換 sys.argv，供未接受 argv 參數的 CLI main() 使用。"""
    original = sys.argv[:]
    sys.argv = argv
    try:
        yield
    finally:
        sys.argv = original


def notify_flow_failure(flow_obj: Any, flow_run: Any, state: Any) -> None:
    """Flow 失敗告警鉤子（非致命）：記錄失敗日誌並嘗試發送本機 herdr 通知。"""
    flow_name = getattr(flow_obj, "name", str(flow_obj))
    run_id = getattr(flow_run, "id", "unknown")
    state_msg = getattr(state, "message", "") or str(state)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary = f"[{ts}] Prefect Flow 失敗: flow={flow_name} run_id={run_id} msg={state_msg}"

    logger.error(summary)

    try:
        log_file = PROJECT_ROOT / "logs" / "nightly_batch" / "prefect_failures.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(summary + "\n")
    except Exception:
        pass

    if os.environ.get("CLINICBRAIN_DISABLE_HERDR_NOTIFY") == "1":
        return

    herdr_bin = shutil.which("herdr")
    if not herdr_bin:
        return

    try:
        subprocess.run(
            [
                herdr_bin,
                "notification",
                "show",
                "--title",
                f"clinicbrain Prefect 失敗: {flow_name}",
                "--body",
                state_msg[:300],
            ],
            timeout=5,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        # 測試環境或無頭環境下通知工具失敗不可影響主流程例外傳遞
        pass


@task(
    name="clinicbrain-nightly-batch-task",
    retries=2,
    retry_delay_seconds=60,
)
def nightly_batch_task(
    *,
    db_path: Optional[str] = None,
    allow_prod_db: bool = True,
    dry_run: bool = False,
    max_faq_topics: int = 5,
    max_trees: int = 3,
    time_budget_seconds: float = 3600.0,
    include_pending_web_prefill: bool = True,
    llm_lock_path: Optional[str] = None,
) -> int:
    """執行 scripts/run_nightly_batch.py，受 local_llm_gpu 與 /tmp/local_llm_8080.lock 保護。"""
    from scripts import run_nightly_batch

    in_blackout, reason = is_llm_blackout_window()
    if in_blackout:
        logger.warning("目前處於本地 LLM 黑窗時段（%s），仍將依鎖排隊執行。", reason)

    argv: list[str] = [
        "--db",
        db_path or str(PROJECT_ROOT / "clinic.db"),
        "--max-faq-topics",
        str(max_faq_topics),
        "--max-trees",
        str(max_trees),
        "--time-budget-seconds",
        str(time_budget_seconds),
    ]
    if allow_prod_db:
        argv.append("--allow-prod-db")
    if dry_run:
        argv.append("--dry-run")
    if include_pending_web_prefill:
        argv.append("--include-pending-web-prefill")

    resolved_lock = Path(llm_lock_path) if llm_lock_path else DEFAULT_LLM_LOCK_PATH
    with concurrency("local_llm_gpu", occupy=1):
        with acquire_llm_8080_lock(resolved_lock):
            rc = run_nightly_batch.main(argv)

    if rc != 0:
        raise RuntimeError(f"run_nightly_batch.main() 回傳非零結束碼: {rc}")
    return rc


@task(
    name="clinicbrain-web-research-task",
    retries=2,
    retry_delay_seconds=60,
)
def web_research_batch_task(
    *,
    db_path: Optional[str] = None,
    source_db: Optional[str] = None,
    allow_prod_db: bool = True,
    dry_run: bool = False,
    limit: int = 10,
    time_budget_seconds: float = 2400.0,
    llm_lock_path: Optional[str] = None,
) -> int:
    """執行 scripts/run_web_research_batch.py，受 local_llm_gpu 與 /tmp/local_llm_8080.lock 保護。"""
    from scripts import run_web_research_batch

    in_blackout, reason = is_llm_blackout_window()
    if in_blackout:
        logger.warning("目前處於本地 LLM 黑窗時段（%s），仍將依鎖排隊執行。", reason)

    argv: list[str] = [
        "--db",
        db_path or str(PROJECT_ROOT / "clinic.db"),
        "--limit",
        str(limit),
        "--time-budget-seconds",
        str(time_budget_seconds),
    ]
    if source_db:
        argv.extend(["--source-db", source_db])
    if allow_prod_db:
        argv.append("--allow-prod-db")
    if dry_run:
        argv.append("--dry-run")

    resolved_lock = Path(llm_lock_path) if llm_lock_path else DEFAULT_LLM_LOCK_PATH
    with concurrency("local_llm_gpu", occupy=1):
        with acquire_llm_8080_lock(resolved_lock):
            rc = run_web_research_batch.main(argv)

    if rc != 0:
        raise RuntimeError(f"run_web_research_batch.main() 回傳非零結束碼: {rc}")
    return rc


@task(
    name="clinicbrain-daily-refresh-task",
    retries=2,
    retry_delay_seconds=60,
)
def daily_knowledge_refresh_task(
    *,
    db_path: Optional[str] = None,
    daily_quota: int = 15,
    target_type: str = "all",
    check_feeds: bool = True,
    dry_run: bool = False,
) -> int:
    """執行 scripts/run_daily_knowledge_refresh.py（RSS/PubMed 外部巡檢含網路重試）。"""
    from scripts import run_daily_knowledge_refresh

    argv: list[str] = [
        "--db",
        db_path or str(PROJECT_ROOT / "clinic.db"),
        "--daily-quota",
        str(daily_quota),
        "--target-type",
        target_type,
    ]
    if check_feeds:
        argv.append("--check-feeds")
    if dry_run:
        argv.append("--dry-run")

    with _patched_argv(["run_daily_knowledge_refresh.py", *argv]):
        rc = run_daily_knowledge_refresh.main()

    if rc != 0:
        raise RuntimeError(f"run_daily_knowledge_refresh.main() 回傳非零結束碼: {rc}")
    return rc


@flow(
    name="clinicbrain-nightly-batch",
    on_failure=[notify_flow_failure],
)
def nightly_batch_flow(
    db_path: Optional[str] = None,
    allow_prod_db: bool = True,
    dry_run: bool = False,
    max_faq_topics: int = 5,
    max_trees: int = 3,
    time_budget_seconds: float = 3600.0,
    include_pending_web_prefill: bool = True,
    llm_lock_path: Optional[str] = None,
) -> int:
    """clinicbrain 03:30 夜間批次排程 Flow。"""
    return nightly_batch_task(
        db_path=db_path,
        allow_prod_db=allow_prod_db,
        dry_run=dry_run,
        max_faq_topics=max_faq_topics,
        max_trees=max_trees,
        time_budget_seconds=time_budget_seconds,
        include_pending_web_prefill=include_pending_web_prefill,
        llm_lock_path=llm_lock_path,
    )


@flow(
    name="clinicbrain-web-research",
    on_failure=[notify_flow_failure],
)
def web_research_batch_flow(
    db_path: Optional[str] = None,
    source_db: Optional[str] = None,
    allow_prod_db: bool = True,
    dry_run: bool = False,
    limit: int = 10,
    time_budget_seconds: float = 2400.0,
    llm_lock_path: Optional[str] = None,
) -> int:
    """clinicbrain 週三/週日 04:15 外部診所官網爬蟲提煉 Flow。"""
    return web_research_batch_task(
        db_path=db_path,
        source_db=source_db,
        allow_prod_db=allow_prod_db,
        dry_run=dry_run,
        limit=limit,
        time_budget_seconds=time_budget_seconds,
        llm_lock_path=llm_lock_path,
    )


@flow(
    name="clinicbrain-daily-refresh",
    on_failure=[notify_flow_failure],
)
def daily_knowledge_refresh_flow(
    db_path: Optional[str] = None,
    daily_quota: int = 15,
    target_type: str = "all",
    check_feeds: bool = True,
    dry_run: bool = False,
) -> int:
    """clinicbrain 04:45 每日權威醫學新知巡檢 Flow。"""
    return daily_knowledge_refresh_task(
        db_path=db_path,
        daily_quota=daily_quota,
        target_type=target_type,
        check_feeds=check_feeds,
        dry_run=dry_run,
    )
