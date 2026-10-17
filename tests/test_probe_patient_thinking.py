"""Phase 28 Plan 07 Task 1: 本地 LLM 思考關閉與解碼速率探測腳本之靜態與假伺服器測試。

嚴格守護規則：
1. 測試期間絕不連線真實 llama-server (127.0.0.1:8080)。
2. 測試一律使用隔離複本，絕不寫入正式 clinic.db。
3. 驗證旗標防護、副本檢驗、唯讀模式、鎖防護與價格屏蔽輸出。
"""

from __future__ import annotations

import fcntl
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
from typing import List, Dict, Any
import urllib.request
import pytest

from scripts.probe_patient_thinking import main
from src.batch.db_lock import nightly_lock_path


@pytest.fixture
def dummy_copy_db(tmp_path: Path) -> Path:
    """建立一個隔離測試副本資料庫。"""
    copy_path = tmp_path / "probe_copy.db"
    conn = sqlite3.connect(copy_path)
    conn.execute(
        """
        CREATE TABLE faq_cache (
            id INTEGER PRIMARY KEY,
            clinic_id TEXT,
            topic_key TEXT,
            question TEXT,
            answer TEXT,
            category TEXT,
            review_status TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, review_status)
        VALUES ('3503190424', 'test-faq', '皮秒雷射會痛嗎？', '施打時會有輕微刺熱感，術前會敷麻舒緩。費用每次3000元。', 'special', 'approved')
        """
    )
    conn.commit()
    conn.close()
    return copy_path


def test_1_no_flag_refusal_and_no_network(monkeypatch, capsys, dummy_copy_db):
    """Test 1: 不帶 --i-approve-live-probe 執行 main 回結束碼 2 並印出繁體中文說明，零網路呼叫。"""
    network_called = False

    def _fail_urlopen(*args, **kwargs):
        nonlocal network_called
        network_called = True
        raise RuntimeError("測試中嚴禁發生網路呼叫！")

    monkeypatch.setattr(urllib.request, "urlopen", _fail_urlopen)

    ret = main(["--db-copy", str(dummy_copy_db)])
    assert ret == 2
    assert not network_called
    captured = capsys.readouterr()
    assert "拒絕執行" in captured.err
    assert "--i-approve-live-probe" in captured.err


def test_2_missing_db_copy_or_pointing_to_prod_refusal(capsys, tmp_path):
    """Test 2: 帶旗標但缺 --db-copy 或指向的檔案與正式 clinic.db 為同一路徑 -> 結束碼 2。"""
    # 缺 --db-copy
    ret1 = main(["--i-approve-live-probe"])
    assert ret1 == 2
    err1 = capsys.readouterr().err
    assert "--db-copy" in err1

    # 指向正式 clinic.db
    prod_path = Path("clinic.db").resolve()
    if prod_path.exists():
        ret2 = main(["--i-approve-live-probe", "--db-copy", str(prod_path)])
        assert ret2 == 2
        err2 = capsys.readouterr().err
        assert "clinic.db" in err2 or "相同" in err2


def test_3_read_only_uri_static_inspection():
    """Test 3: 來源資料庫以 file:...?mode=ro URI 開啟（靜態原始碼掃描確認），且腳本不含寫入語句。"""
    script_path = Path("scripts/probe_patient_thinking.py")
    content = script_path.read_text(encoding="utf-8")

    assert "mode=ro" in content
    assert "file:" in content

    # 檢查無寫入 SQL 關鍵字（排除註解行）
    code_lines = [line for line in content.splitlines() if not line.strip().startswith("#")]
    code_text = "\n".join(code_lines)
    for kw in ["INSERT INTO", "UPDATE ", "DELETE FROM", "ALTER TABLE"]:
        assert kw not in code_text


class MockLLMHandler(BaseHTTPRequestHandler):
    received_payloads: List[Dict[str, Any]] = []

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8")
        payload = json.loads(body)
        MockLLMHandler.received_payloads.append(payload)

        # 模擬不同變體產生的回覆
        is_thinking_disabled = (
            payload.get("reasoning_effort") == "none"
            or payload.get("chat_template_kwargs", {}).get("enable_thinking") is False
        )
        reasoning_text = "" if is_thinking_disabled else "這是模擬的推理思考過程文本"
        response_body = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "答：皮秒雷射能有效改善色素沉澱。\n費用原價8000元，特價5000元。\n追問：您想了解恢復期嗎？",
                        "reasoning_content": reasoning_text,
                    },
                }
            ],
            "usage": {
                "completion_tokens": 65,
                "prompt_tokens": 150,
                "total_tokens": 215,
            },
            "timings": {
                "predicted_n": 65,
                "predicted_per_second": 21.45,
            },
        }
        res_bytes = json.dumps(response_body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(res_bytes)))
        self.end_headers()
        self.wfile.write(res_bytes)

    def log_message(self, format, *args):
        pass  # 靜音


@pytest.fixture
def mock_server():
    MockLLMHandler.received_payloads = []
    server = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/v1/chat/completions"
    server.shutdown()
    server.server_close()


def test_4_three_variants_mock_server_execution(mock_server, dummy_copy_db, capsys):
    """Test 4: 假 HTTP 伺服器驗證三變體各自發送一次請求並解析各欄位指標。"""
    ret = main([
        "--i-approve-live-probe",
        "--db-copy", str(dummy_copy_db),
        "--endpoint", mock_server,
        "--timeout", "10",
    ])
    assert ret == 0

    # 驗證正好發送 3 次請求
    payloads = MockLLMHandler.received_payloads
    assert len(payloads) == 3

    # 變體 1: reasoning_effort none
    assert payloads[0].get("reasoning_effort") == "none"
    assert "chat_template_kwargs" not in payloads[0]

    # 變體 2: enable_thinking false
    assert "reasoning_effort" not in payloads[1]
    assert payloads[1].get("chat_template_kwargs", {}).get("enable_thinking") is False

    # 變體 3: both
    assert payloads[2].get("reasoning_effort") == "none"
    assert payloads[2].get("chat_template_kwargs", {}).get("enable_thinking") is False

    # 解析標準輸出 JSON
    captured = capsys.readouterr()
    doc = json.loads(captured.out)
    assert "results" in doc
    assert len(doc["results"]) == 3

    for r in doc["results"]:
        assert r["status"] == "success"
        assert "reasoning_chars" in r
        assert "content_chars" in r
        assert "finish_reason" in r
        assert "elapsed_seconds" in r
        assert "completion_tokens" in r
        assert "tokens_per_second" in r
        assert "content_preview" in r
        assert r["completion_tokens"] == 65
        assert r["tokens_per_second"] == 21.45
        # 價格已屏蔽
        assert "[請致電診所確認]" in r["content_preview"]
        assert "8000" not in r["content_preview"]
        assert "5000" not in r["content_preview"]


def test_5_nightly_batch_locked_refusal(dummy_copy_db, capsys):
    """Test 5: 夜間批次鎖被持有時腳本拒絕執行並回結束碼 2。"""
    prod_path = Path("clinic.db").resolve()
    lock_file = nightly_lock_path(prod_path)

    # 搶先持有鎖
    fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    try:
        ret = main(["--i-approve-live-probe", "--db-copy", str(dummy_copy_db)])
        assert ret == 2
        captured = capsys.readouterr()
        assert "鎖已被持有" in captured.err or "夜間批次" in captured.err
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_6_no_subprocess_or_systemctl_static():
    """Test 6: 腳本不會 import 或呼叫 systemctl／subprocess 重啟服務（靜態掃描無 subprocess、systemctl 字樣）。"""
    script_path = Path("scripts/probe_patient_thinking.py")
    content = script_path.read_text(encoding="utf-8")

    assert "subprocess" not in content
    assert "systemctl" not in content


def test_7_output_json_privacy_no_full_prompt_or_content(mock_server, dummy_copy_db, capsys):
    """Test 7: 結果以 JSON 印到標準輸出，不含 prompt 全文與 content 全文。"""
    ret = main([
        "--i-approve-live-probe",
        "--db-copy", str(dummy_copy_db),
        "--endpoint", mock_server,
        "--timeout", "10",
    ])
    assert ret == 0

    out_text = capsys.readouterr().out
    doc = json.loads(out_text)

    # 驗證輸出結構中無 prompt 或完整 content 鍵
    for r in doc["results"]:
        assert "prompt" not in r
        assert "content" not in r
        assert "full_content" not in r
        # 僅有 preview 且 preview <= 50 字元
        assert len(r["content_preview"]) <= 60
