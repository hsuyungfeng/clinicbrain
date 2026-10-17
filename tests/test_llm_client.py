"""
Taiwan Clinic Medical PageIndex RAG System - 本地 LLM 客戶端測試
涵蓋 Phase 02 Task 1:
- check_llm_health() 健康檢查回傳模型名稱
- local_llm_call() 基本連通性與 content 提取（忽略 reasoning_content）
- 連線失敗與無效 endpoint 正確引發 LocalLLMUnavailableError
"""

import urllib.error
from unittest.mock import patch, MagicMock
import pytest
from src.pageindex.llm_client import (
    check_llm_health,
    local_llm_call,
    LocalLLMUnavailableError,
    LLMEmptyOutputError,
    LLM_ENDPOINT,
    MODELS_ENDPOINT,
)


def test_check_llm_health_live():
    """驗證本地 llama-server 存活時能正常獲取模型資訊。"""
    mock_res = MagicMock()
    mock_res.status = 200
    mock_res.__enter__.return_value = mock_res
    mock_res.read.return_value = b'{"data": [{"id": "mock-qwen-27b"}]}'
    with patch("urllib.request.urlopen", return_value=mock_res):
        model_name = check_llm_health(timeout=5)
        assert isinstance(model_name, str)
        assert model_name == "mock-qwen-27b"


def test_check_llm_health_connection_failure():
    """驗證連線至未開放連接埠時拋出 LocalLLMUnavailableError 並附有友善提示。"""
    with patch("src.pageindex.llm_client.MODELS_ENDPOINT", "http://127.0.0.1:59999/v1/models"):
        with pytest.raises(LocalLLMUnavailableError, match="本地 LLM 服務未啟動於"):
            check_llm_health(timeout=1)


def test_local_llm_call_ignores_reasoning_content():
    """驗證 local_llm_call 只取用 content，嚴格排除 reasoning_content。"""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__.return_value = mock_response
    mock_body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "這是最終回答內容",
                    "reasoning_content": "這是一段思考過程，不應被輸出",
                }
            }
        ]
    }
    mock_response.read.return_value = (
        __import__("json").dumps(mock_body, ensure_ascii=False).encode("utf-8")
    )

    with patch("src.pageindex.llm_client.check_llm_health", return_value="test-model"):
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = local_llm_call("測試提示詞", timeout=10)
            assert result == "這是最終回答內容"
            assert "思考過程" not in result


def test_local_llm_call_empty_content_raises_error():
    """驗證當模型僅輸出思考過程而 content 為空時，拋出 LocalLLMUnavailableError。"""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__.return_value = mock_response
    mock_body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "模型只輸出了思考過程",
                }
            }
        ]
    }
    mock_response.read.return_value = (
        __import__("json").dumps(mock_body, ensure_ascii=False).encode("utf-8")
    )

    with patch("src.pageindex.llm_client.check_llm_health", return_value="test-model"):
        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LLMEmptyOutputError, match="本地 LLM 回應之 content 為空"):
                local_llm_call("測試提示詞", timeout=10)


def test_local_llm_call_timeout_raises_clear_exception():
    """驗證呼叫逾時拋出包含秒數說明的 LocalLLMUnavailableError。"""
    import socket
    with patch("src.pageindex.llm_client.check_llm_health", return_value="test-model"):
        with patch("urllib.request.urlopen", side_effect=socket.timeout("Operation timed out")):
            with pytest.raises(LocalLLMUnavailableError, match="呼叫本地 LLM 逾時（超過 10 秒）"):
                local_llm_call("測試提示詞", timeout=10)


def test_local_llm_call_truncated_raises_truncated_error():
    """Test 1: 驗證 finish_reason='length' 且 content 非空時，拋出 LLMTruncatedError。"""
    from src.pageindex.llm_client import LLMTruncatedError, LLMEmptyOutputError
    assert issubclass(LLMTruncatedError, LLMEmptyOutputError), "LLMTruncatedError 必須是 LLMEmptyOutputError 子類別"

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__.return_value = mock_response
    mock_body = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {
                    "role": "assistant",
                    "content": "這是尚未完成的截斷文字敏感資訊",
                },
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 3000, "total_tokens": 3100},
    }
    mock_response.read.return_value = (
        __import__("json").dumps(mock_body, ensure_ascii=False).encode("utf-8")
    )

    with patch("src.pageindex.llm_client.check_llm_health", return_value="test-model"):
        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LLMTruncatedError) as exc_info:
                local_llm_call("測試提示詞", timeout=10)
            err_msg = str(exc_info.value)
            assert "usage" in err_msg.lower() or "completion_tokens" in err_msg
            assert "這是尚未完成的截斷文字敏感資訊" not in err_msg, "例外訊息不得包含 content 原文"


def test_local_llm_call_finish_reason_stop_success():
    """Test 2: finish_reason='stop' 且 content 正常時照舊回傳。"""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__.return_value = mock_response
    mock_body = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "這是完整回答內容",
                },
            }
        ]
    }
    mock_response.read.return_value = (
        __import__("json").dumps(mock_body, ensure_ascii=False).encode("utf-8")
    )

    with patch("src.pageindex.llm_client.check_llm_health", return_value="test-model"):
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = local_llm_call("測試提示詞", timeout=10)
            assert result == "這是完整回答內容"


def test_sampling_constants_and_payload_capture():
    """Test 4: 驗證取樣常數結構，且傳入 PATIENT_COMPOSE_SAMPLING 時正確組裝 payload。"""
    import json
    from src.pageindex.llm_client import (
        FAITHFUL_SAMPLING,
        PATIENT_COMPOSE_SAMPLING,
        PATIENT_GENERAL_SAMPLING,
    )

    assert FAITHFUL_SAMPLING == {"temperature": 0.1, "dry_multiplier": 0.0, "repeat_penalty": 1.0}
    assert PATIENT_COMPOSE_SAMPLING["max_tokens"] == 3000
    assert PATIENT_COMPOSE_SAMPLING["reasoning_effort"] == "none"
    assert PATIENT_COMPOSE_SAMPLING["chat_template_kwargs"] == {"enable_thinking": False}
    assert PATIENT_COMPOSE_SAMPLING["temperature"] == 0.1
    assert PATIENT_COMPOSE_SAMPLING["dry_multiplier"] == 0.0
    assert PATIENT_COMPOSE_SAMPLING["repeat_penalty"] == 1.0

    assert PATIENT_GENERAL_SAMPLING["max_tokens"] == 3000
    assert PATIENT_GENERAL_SAMPLING["reasoning_effort"] == "none"
    assert PATIENT_GENERAL_SAMPLING["chat_template_kwargs"] == {"enable_thinking": False}

    captured_req = None

    def fake_urlopen(req, timeout):
        nonlocal captured_req
        captured_req = req
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response
        mock_body = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "測試回答"},
                }
            ]
        }
        mock_response.read.return_value = json.dumps(mock_body).encode("utf-8")
        return mock_response

    with patch("src.pageindex.llm_client.check_llm_health", return_value="test-model"):
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            # 使用 dict(...) 傳入，確保常數不被就地修改
            sampling_copy = dict(PATIENT_COMPOSE_SAMPLING)
            local_llm_call("測試提問", timeout=10, sampling=sampling_copy)

    assert captured_req is not None
    payload = json.loads(captured_req.data.decode("utf-8"))
    assert payload["reasoning_effort"] == "none"
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["max_tokens"] == 3000
    assert payload["temperature"] == 0.1
    assert payload["dry_multiplier"] == 0.0
    assert payload["repeat_penalty"] == 1.0
    assert PATIENT_COMPOSE_SAMPLING["max_tokens"] == 3000, "模組常數不得被污染"


def test_llm_lock_and_nightly_batch_running(tmp_path):
    """Test 5: llm_lock.GENERATION_LOCK 與 admin._GENERATION_LOCK 同一物件，nightly_batch_running 測試。"""
    from src.pageindex.llm_lock import GENERATION_LOCK, nightly_batch_running
    from src.api.routes.admin import _GENERATION_LOCK
    from src.batch import db_lock

    assert GENERATION_LOCK is _GENERATION_LOCK, "GENERATION_LOCK 與 admin._GENERATION_LOCK 必須是同一個物件實例"

    # 特殊無效路徑
    assert nightly_batch_running("") is False
    assert nightly_batch_running(":memory:") is False
    assert nightly_batch_running(str(tmp_path / "not_exist.db")) is False

    # 真實檔案
    test_db = tmp_path / "clinic_test.db"
    test_db.write_text("dummy")

    # 未持鎖 -> False
    assert nightly_batch_running(str(test_db)) is False

    # 模擬另一行程持有檔案鎖
    fd = db_lock.try_acquire(str(test_db))
    assert fd is not None
    try:
        assert nightly_batch_running(str(test_db)) is True
    finally:
        db_lock.release(fd)

    # 釋放後 -> False
    assert nightly_batch_running(str(test_db)) is False
