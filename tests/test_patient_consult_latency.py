"""病人端延遲控制、單次呼叫、鎖共用與防護測試 (Phase 28 Plan 01 Task 2)。"""

import pytest
import sqlite3
from unittest.mock import patch, MagicMock

from src.general import patient_consult as pc
from src.pageindex.general_fallback import generate_general_draft
from src.pageindex.llm_client import (
    LLMEmptyOutputError,
    LLMTruncatedError,
    PATIENT_COMPOSE_SAMPLING,
    PATIENT_GENERAL_SAMPLING,
)
from src.pageindex import llm_lock


LAT_Q = "延遲測試專屬罕見問題_XYZ_999"


def test_empty_output_calls_llm_only_once_and_returns_no_match(isolated_conn):
    """Test 1: 假 llm_call 拋 LLMEmptyOutputError，patient_consult 只呼叫 1 次，回 no_match。"""
    call_count = 0

    def bad_llm(prompt):
        nonlocal call_count
        call_count += 1
        raise LLMEmptyOutputError("empty")

    res = pc.patient_consult(isolated_conn, LAT_Q, bad_llm)
    assert call_count == 1, "病人端即時路徑遇到 LLMEmptyOutputError 只能呼叫 1 次，不得重試"
    assert res.status == "no_match"
    assert res.message == pc.NO_DATA_TEXT


def test_truncated_error_calls_llm_only_once_and_writes_nothing(isolated_conn):
    """Test 2: 假 llm_call 拋 LLMTruncatedError 只呼叫 1 次，回 no_match 且不寫入草稿。"""
    call_count = 0

    def trunc_llm(prompt):
        nonlocal call_count
        call_count += 1
        raise LLMTruncatedError("truncated")

    c_before = isolated_conn.execute("SELECT count(*) FROM faq_cache WHERE category='general'").fetchone()[0]

    res = pc.patient_consult(isolated_conn, LAT_Q, trunc_llm)
    assert call_count == 1, "病人端遇到 LLMTruncatedError 只能呼叫 1 次"
    assert res.status == "no_match"
    assert res.message == pc.NO_DATA_TEXT

    c_after = isolated_conn.execute("SELECT count(*) FROM faq_cache WHERE category='general'").fetchone()[0]
    assert c_after == c_before, "發生截斷時不得寫入任何草稿"


def test_admin_fallback_retains_retry_behavior(isolated_conn):
    """Test 3: 管理端/批次路徑（未帶 retry_on_empty=False）遇 LLMEmptyOutputError 仍重試 1 次（呼叫 2 次）。"""
    call_count = 0
    warning = "若出現胸痛、呼吸困難或高燒超過38.5度持續3天，請立即前往急診或儘速就醫。"

    def flaky_llm(prompt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise LLMEmptyOutputError("empty first time")
        return __import__("json").dumps(
            [{"question": LAT_Q, "answer": "管理端重試成功解答。" + warning}],
            ensure_ascii=False,
        )

    # 預設 retry_on_empty=True
    res = generate_general_draft(isolated_conn, LAT_Q, flaky_llm)
    assert call_count == 2, "管理端路徑應重試一次，總共呼叫 2 次"
    assert res["review_status"] == "pending"


def test_generation_lock_busy_returns_busy_without_calling_llm(isolated_conn):
    """Test 4: 手動持 GENERATION_LOCK 時，patient_consult 回 busy 且假 llm_call 呼叫 0 次，無殘鎖。"""
    call_count = 0

    def boom(prompt):
        nonlocal call_count
        call_count += 1
        raise AssertionError("持鎖時不得呼叫模型")

    assert llm_lock.GENERATION_LOCK.acquire(blocking=False), "測試前必須能取得鎖"
    try:
        res = pc.patient_consult(isolated_conn, LAT_Q, boom)
        assert res.status == "busy"
        assert res.message == pc.BUSY_TEXT
        assert call_count == 0
    finally:
        llm_lock.GENERATION_LOCK.release()

    # 驗證鎖可再次被取得（無殘鎖）
    assert llm_lock.GENERATION_LOCK.acquire(blocking=False)
    llm_lock.GENERATION_LOCK.release()


def test_nightly_batch_running_returns_busy_without_calling_llm(isolated_conn, monkeypatch):
    """Test 5: monkeypatch nightly_batch_running 為 True 時，回 busy 且 llm_call 呼叫 0 次。"""
    monkeypatch.setattr(pc, "nightly_batch_running", lambda db_path: True)

    call_count = 0

    def boom(prompt):
        nonlocal call_count
        call_count += 1
        raise AssertionError("夜間批次執行中不得呼叫模型")

    res = pc.patient_consult(isolated_conn, LAT_Q, boom)
    assert res.status == "busy"
    assert res.message == pc.BUSY_TEXT
    assert call_count == 0


def test_default_patient_llm_parameters(monkeypatch):
    """Test 6: 驗證 default_patient_llm 與 default_patient_compose_llm 取樣參數與逾時設定。"""
    from src.pageindex import llm_client

    captured_args = []

    def mock_local_call(prompt, timeout=420, sampling=None):
        captured_args.append({"prompt": prompt, "timeout": timeout, "sampling": sampling})
        return "mocked answer"

    # 延遲 import 的 local_llm_call
    monkeypatch.setattr(llm_client, "local_llm_call", mock_local_call)

    # 恢復真實預設函式實作進行參數捕捉測試（已被 mock_local_call 攔截，不連真實 LLM）
    monkeypatch.setattr(pc, "default_patient_llm", pc._orig_default_patient_llm)
    monkeypatch.setattr(pc, "default_patient_compose_llm", pc._orig_default_patient_compose_llm)

    # 1. 測試 default_patient_llm
    pc.default_patient_llm("test prompt 1")
    assert len(captured_args) == 1
    call1 = captured_args[0]
    assert call1["timeout"] <= 240
    assert call1["sampling"] == PATIENT_GENERAL_SAMPLING

    # 2. 測試 default_patient_compose_llm
    pc.default_patient_compose_llm("test prompt 2")
    assert len(captured_args) == 2
    call2 = captured_args[1]
    assert call2["timeout"] <= 240
    assert call2["sampling"] == PATIENT_COMPOSE_SAMPLING


def test_test_suite_forbid_real_llm_protection():
    """Test 7: 驗證 conftest 中的 autouse 防護確實阻擋對 127.0.0.1:8080 的連線與真實函式。"""
    import urllib.request

    # 1. 直接呼叫 urlopen 連向 127.0.0.1:8080 必須被攔截
    with pytest.raises(AssertionError, match="測試不得呼叫真實 LLM"):
        urllib.request.urlopen("http://127.0.0.1:8080/v1/models")

    with pytest.raises(AssertionError, match="測試不得呼叫真實 LLM"):
        urllib.request.urlopen("http://localhost:8080/v1/models")

    # 2. 未被測試自訂 mock 時，呼叫 default_patient_llm 必須被 conftest 的 autouse 攔截
    from src.general.patient_consult import default_patient_llm
    with pytest.raises(AssertionError, match="測試不得呼叫真實 LLM"):
        default_patient_llm("prompt")
