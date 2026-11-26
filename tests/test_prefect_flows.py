"""clinicbrain Prefect 3 Flow / Task 與跨機制鎖單元測試。"""

from __future__ import annotations

from datetime import datetime
import fcntl
from pathlib import Path
import sys
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from prefect.testing.utilities import prefect_test_harness

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INFRA_PREFECT_DIR = PROJECT_ROOT.parent / "infra" / "prefect"
for _p in (str(PROJECT_ROOT), str(INFRA_PREFECT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from llm_lock import (  # noqa: E402
    LLMLockTimeoutError,
    acquire_llm_8080_lock,
    is_llm_blackout_window,
)
from src.batch import prefect_flows  # noqa: E402


@pytest.fixture(autouse=True)
def _disable_herdr_notify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLINICBRAIN_DISABLE_HERDR_NOTIFY", "1")


def test_task_retry_configuration() -> None:
    """三個核心 Task 皆必須設定 retries=2 與 retry_delay_seconds=60。"""
    for t in (
        prefect_flows.nightly_batch_task,
        prefect_flows.web_research_batch_task,
        prefect_flows.daily_knowledge_refresh_task,
    ):
        assert t.retries == 2
        assert t.retry_delay_seconds == 60


def test_nightly_batch_flow_wraps_entrypoint_and_acquires_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """nightly_batch_flow 應正確呼叫 run_nightly_batch.main 並取得/釋放共用鎖。"""
    from scripts import run_nightly_batch

    lock_file = tmp_path / "local_llm_8080.lock"
    captured_argv: list[list[str]] = []
    lock_held_during_call: list[bool] = []

    def fake_main(argv=None) -> int:
        captured_argv.append(list(argv or []))
        probe = open(lock_file, "a+")
        try:
            try:
                fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_held_during_call.append(False)
                fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
            except BlockingIOError:
                lock_held_during_call.append(True)
        finally:
            probe.close()
        return 0

    monkeypatch.setattr(run_nightly_batch, "main", fake_main)

    with prefect_test_harness():
        rc = prefect_flows.nightly_batch_flow(
            db_path=str(tmp_path / "test.db"),
            allow_prod_db=False,
            dry_run=True,
            max_faq_topics=2,
            max_trees=1,
            time_budget_seconds=120.0,
            include_pending_web_prefill=True,
            llm_lock_path=str(lock_file),
        )

    assert rc == 0
    assert lock_held_during_call == [True]
    assert "--dry-run" in captured_argv[0]
    assert "--include-pending-web-prefill" in captured_argv[0]

    # Flow 結束後鎖必須已釋放
    probe_after = open(lock_file, "a+")
    try:
        fcntl.flock(probe_after.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(probe_after.fileno(), fcntl.LOCK_UN)
    finally:
        probe_after.close()


def test_web_research_and_daily_refresh_flows_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """web_research_batch_flow 與 daily_knowledge_refresh_flow 應正確轉傳參數。"""
    from scripts import run_daily_knowledge_refresh, run_web_research_batch

    web_argv: list[list[str]] = []
    refresh_argv: list[list[str]] = []

    def fake_web_main(argv=None) -> int:
        web_argv.append(list(argv or []))
        return 0

    def fake_refresh_main() -> int:
        refresh_argv.append(list(sys.argv))
        return 0

    monkeypatch.setattr(run_web_research_batch, "main", fake_web_main)
    monkeypatch.setattr(run_daily_knowledge_refresh, "main", fake_refresh_main)

    with prefect_test_harness():
        rc_web = prefect_flows.web_research_batch_flow(
            db_path=str(tmp_path / "test.db"),
            allow_prod_db=False,
            dry_run=True,
            limit=3,
            time_budget_seconds=300.0,
            llm_lock_path=str(tmp_path / "llm.lock"),
        )
        rc_refresh = prefect_flows.daily_knowledge_refresh_flow(
            db_path=str(tmp_path / "test.db"),
            daily_quota=5,
            target_type="faq",
            check_feeds=True,
            dry_run=True,
        )

    assert rc_web == 0
    assert "--limit" in web_argv[0] and "3" in web_argv[0]
    assert rc_refresh == 0
    assert "--daily-quota" in refresh_argv[0] and "5" in refresh_argv[0]
    assert "--check-feeds" in refresh_argv[0]


def test_nonzero_exit_code_propagates_failure_and_triggers_hook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """腳本回傳非零結束碼時應觸發重試並最終失敗、呼叫 on_failure 通知鉤子。"""
    from scripts import run_nightly_batch

    calls = {"count": 0}
    hook_calls: list[str] = []

    def fake_fail_main(argv=None) -> int:
        calls["count"] += 1
        return 2

    def fake_notify(flow_obj, flow_run, state) -> None:
        hook_calls.append(getattr(flow_obj, "name", "unknown"))

    monkeypatch.setattr(run_nightly_batch, "main", fake_fail_main)
    # 測試時將 retry_delay_seconds 縮短為 0 避免等待 60s
    monkeypatch.setattr(prefect_flows.nightly_batch_task, "retry_delay_seconds", 0)
    monkeypatch.setattr(
        prefect_flows.nightly_batch_flow, "on_failure_hooks", [fake_notify]
    )

    with prefect_test_harness():
        with pytest.raises(RuntimeError, match="回傳非零結束碼: 2"):
            prefect_flows.nightly_batch_flow(
                db_path=str(tmp_path / "test.db"),
                allow_prod_db=False,
                dry_run=True,
                llm_lock_path=str(tmp_path / "llm.lock"),
            )

    # 1 次初始執行 + 2 次重試 = 3 次
    assert calls["count"] == 3
    assert hook_calls == ["clinicbrain-nightly-batch"]


def test_llm_lock_timeout_and_blackout_windows(tmp_path: Path) -> None:
    """驗證 /tmp/local_llm_8080.lock 互斥逾時與 08:00-09:30 / 22:30 黑窗判斷。"""
    lock_file = tmp_path / "llm.lock"
    with acquire_llm_8080_lock(lock_file):
        with pytest.raises(LLMLockTimeoutError):
            with acquire_llm_8080_lock(lock_file, timeout_seconds=0.1, poll_interval=0.05):
                pass

    tz = ZoneInfo("Asia/Taipei")
    assert is_llm_blackout_window(datetime(2026, 11, 25, 8, 30, tzinfo=tz))[0] is True
    assert is_llm_blackout_window(datetime(2026, 11, 25, 22, 35, tzinfo=tz))[0] is True
    assert is_llm_blackout_window(datetime(2026, 11, 25, 3, 30, tzinfo=tz))[0] is False


def test_notify_flow_failure_non_fatal_when_herdr_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """herdr 不存在時 notify_flow_failure 應安全完成而不拋出例外。"""
    monkeypatch.delenv("CLINICBRAIN_DISABLE_HERDR_NOTIFY", raising=False)
    monkeypatch.setattr(prefect_flows.shutil, "which", lambda _: None)

    flow_obj = MagicMock()
    flow_obj.name = "clinicbrain-nightly-batch"
    flow_run = MagicMock()
    flow_run.id = "test-run-id"
    state = MagicMock()
    state.message = "Simulated failure"

    prefect_flows.notify_flow_failure(flow_obj, flow_run, state)
