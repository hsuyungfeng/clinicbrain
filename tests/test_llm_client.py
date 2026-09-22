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
    LLM_ENDPOINT,
    MODELS_ENDPOINT,
)


def test_check_llm_health_live():
    """驗證本地 llama-server 存活時能正常獲取模型資訊。"""
    model_name = check_llm_health(timeout=5)
    assert isinstance(model_name, str)
    assert len(model_name) > 0


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
            with pytest.raises(LocalLLMUnavailableError, match="本地 LLM 回應之 content 為空"):
                local_llm_call("測試提示詞", timeout=10)


def test_local_llm_call_timeout_raises_clear_exception():
    """驗證呼叫逾時拋出包含秒數說明的 LocalLLMUnavailableError。"""
    import socket
    with patch("src.pageindex.llm_client.check_llm_health", return_value="test-model"):
        with patch("urllib.request.urlopen", side_effect=socket.timeout("Operation timed out")):
            with pytest.raises(LocalLLMUnavailableError, match="呼叫本地 LLM 逾時（超過 10 秒）"):
                local_llm_call("測試提示詞", timeout=10)
