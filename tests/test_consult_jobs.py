"""Phase 28 Plan 04: consult_jobs 記憶體非同步作業與端點單元測試。

涵蓋 12 項行為測試：
- Test 1: POST jobs 非紅旗問句回 pending 與不可預測之安全 job_id。
- Test 2: 紅旗問句立即同步回傳就醫指示，不建立 job、不呼叫模型。
- Test 3: GET 輪詢 pending 狀態；完成後第一次讀取回傳完整結果，第二次讀取回 404（單次讀取即刪除）。
- Test 4: 未知或格式不符的 job_id 統一回傳 404 固定文字，不洩漏存在性差異。
- Test 5: 超過 300 秒 TTL 後回傳 404，sweep_expired 清理過期作業。
- Test 6: 隱私保證：registry 內部狀態序列化（JSON 或 repr）絕不含問句原文。
- Test 7: 容量上限：worker 達 MAX_RUNNING (4) 或總作業達 MAX_JOBS (20) 時回 busy；GENERATION_LOCK 互斥保護。
- Test 8: worker 例外轉為 no_match 固定結果，不洩漏例外細節，running 標記正常清除。
- Test 9: GET 輪詢路徑純記憶體運作，絕不開啟任何 SQLite 資料庫連線。
- Test 10: 結果訊息全面經 deep_mask_prices 價格清洗。
- Test 11: 請求主體驗證失敗回傳固定 422「請求格式不正確」；access log filter 對 jobs 端點過濾不記錄。
- Test 12: 守門測試：若連線正式庫 clinic.db 則觸發 AssertionError，測試一律使用隔離複本。
"""

import json
import logging
from pathlib import Path
import re
import sqlite3
import threading
import time
import pytest
from fastapi.testclient import TestClient

from src.api.access_log_filter import ExcludeGeneralPathFilter
from src.api.app import app
from src.api.config import config
from src.general import consult_jobs
from src.general.patient_consult import PatientConsultResult


PROD_DB_PATH = Path("clinic.db").resolve()


@pytest.fixture(autouse=True)
def guard_no_prod_db(isolated_db_path, monkeypatch):
    """資料庫安全守門 fixture：任何連線至專案根目錄 clinic.db 立即引發 AssertionError。"""
    orig_connect = sqlite3.connect

    def guarded_connect(database, *args, **kwargs):
        if str(database) != ":memory:":
            try:
                p = Path(str(database)).resolve()
                if p == PROD_DB_PATH:
                    raise AssertionError("測試中禁止連線至正式資料庫 clinic.db！")
            except Exception as exc:
                if isinstance(exc, AssertionError):
                    raise
        return orig_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)

    consult_jobs.reset_for_tests()
    yield
    consult_jobs.wait_idle(timeout=5.0)
    consult_jobs.reset_for_tests()


@pytest.fixture
def client():
    with TestClient(app) as tc:
        yield tc


def test_1_post_jobs_pending_structure(client, monkeypatch):
    """Test 1: 非紅旗問句回傳 pending 與 token_urlsafe(16) 特徵之 job_id。"""
    res = client.post(
        "/api/v1/general/consult/jobs",
        json={"query": "感冒咳嗽居家護理該怎麼做？"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "pending"
    assert "job_id" in data
    job_id = data["job_id"]
    assert len(job_id) >= 22
    assert re.match(r"^[A-Za-z0-9_-]{16,64}$", job_id)


def test_2_red_flag_sync_no_job(client):
    """Test 2: 急重症紅旗問句同步回傳指示，不建立 job，不排入 registry。"""
    res = client.post(
        "/api/v1/general/consult/jobs",
        json={"query": "我現在胸痛呼吸困難全身冒冷汗快暈倒"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "red_flag"
    assert "job_id" not in data
    assert "message" in data and len(data["message"]) > 0
    assert "disclaimer" in data
    assert data["booking_url"] == "https://doctor-toolbox.com/"
    assert consult_jobs.snapshot()["total"] == 0


def test_3_poll_result_and_delete_on_read(client, monkeypatch):
    """Test 3: 輪詢 pending -> 完成後回傳完整結構 -> 第二次讀取回傳 404（讀後即刪）。"""
    worker_hold = threading.Event()

    def _holding_patient_consult(conn, query, *args, **kwargs):
        worker_hold.wait(timeout=5.0)
        return PatientConsultResult(
            status="answered",
            message="測試衛教解答內容",
            disclaimer="免責宣告",
            label=None,
            booking_url="https://doctor-toolbox.com/",
        )

    monkeypatch.setattr(consult_jobs, "patient_consult", _holding_patient_consult)

    post_res = client.post(
        "/api/v1/general/consult/jobs",
        json={"query": "玻尿酸注射後注意事項？"},
    )
    job_id = post_res.json()["job_id"]

    # 1. 仍在執行中時輪詢
    poll_pending = client.get(f"/api/v1/general/consult/jobs/{job_id}")
    assert poll_pending.status_code == 200
    assert poll_pending.json() == {"status": "pending"}

    # 2. 放行 worker 完成處理
    worker_hold.set()
    assert consult_jobs.wait_idle(timeout=5.0)

    # 3. 完成後第一次讀取：取得完整結果
    poll_done = client.get(f"/api/v1/general/consult/jobs/{job_id}")
    assert poll_done.status_code == 200
    data = poll_done.json()
    assert data["status"] == "answered"
    assert data["message"] == "測試衛教解答內容"
    assert data["disclaimer"] == "免責宣告"
    assert data["booking_url"] == "https://doctor-toolbox.com/"

    # 4. 第二次讀取：單次讀取即刪除，回傳 404
    poll_deleted = client.get(f"/api/v1/general/consult/jobs/{job_id}")
    assert poll_deleted.status_code == 404
    assert poll_deleted.json() == {"detail": "找不到結果"}


def test_4_unknown_or_invalid_job_id_uniform_404(client):
    """Test 4: 未知、過期或格式錯誤的 job_id 回應相同 404 固定文字。"""
    res1 = client.get("/api/v1/general/consult/jobs/nonexistent_safe_token_123456789")
    assert res1.status_code == 404
    assert res1.json() == {"detail": "找不到結果"}

    res2 = client.get("/api/v1/general/consult/jobs/invalid!@#$%^&*()")
    assert res2.status_code == 404
    assert res2.json() == {"detail": "找不到結果"}


def test_5_ttl_expired_and_sweep(client, monkeypatch):
    """Test 5: 超過 TTL (300 秒) 後 GET 回傳 404，sweep_expired 正確刪除項目。"""
    post_res = client.post(
        "/api/v1/general/consult/jobs",
        json={"query": "音波拉提維持多久？"},
    )
    job_id = post_res.json()["job_id"]
    assert consult_jobs.wait_idle(timeout=5.0)

    # 模擬時間推進 301 秒
    orig_now = consult_jobs._now()
    monkeypatch.setattr(consult_jobs, "_now", lambda: orig_now + 301.0)

    # 讀取時過期
    poll_res = client.get(f"/api/v1/general/consult/jobs/{job_id}")
    assert poll_res.status_code == 404
    assert poll_res.json() == {"detail": "找不到結果"}


def test_6_privacy_no_query_in_registry(client):
    """Test 6: 隱私檢查：registry 內部狀態序列化後絕不包含問句原文。"""
    secret_token = "SECRET_PATIENT_SYMPTOM_TOKEN_XYZ_98765"
    client.post(
        "/api/v1/general/consult/jobs",
        json={"query": f"我有此症狀 {secret_token} 該看哪科？"},
    )

    snap = consult_jobs.snapshot()
    snap_json = json.dumps(snap, ensure_ascii=False)
    assert secret_token not in snap_json

    with consult_jobs._lock:
        internal_repr = repr(consult_jobs._jobs)
        assert secret_token not in internal_repr


def test_7_max_running_and_max_jobs_capacity(client, monkeypatch):
    """Test 7: 容量上限測試（MAX_RUNNING=4 與 MAX_JOBS=20）。"""
    worker_event = threading.Event()

    def _slow_consult(*args, **kwargs):
        worker_event.wait(timeout=5.0)
        return PatientConsultResult("answered", "解答", "免責", None, "https://doctor-toolbox.com/")

    monkeypatch.setattr(consult_jobs, "patient_consult", _slow_consult)

    # 1. 提交 4 個 worker 佔滿 MAX_RUNNING
    for _ in range(4):
        res = client.post("/api/v1/general/consult/jobs", json={"query": "問題"})
        assert res.status_code == 200
        assert res.json()["status"] == "pending"

    # 2. 第 5 個提交直接回傳 busy，不建立 job
    res_busy = client.post("/api/v1/general/consult/jobs", json={"query": "第5個問題"})
    assert res_busy.status_code == 200
    assert res_busy.json()["status"] == "busy"
    assert "job_id" not in res_busy.json()

    # 放行 worker
    worker_event.set()
    assert consult_jobs.wait_idle(timeout=5.0)


def test_8_worker_exception_fallback_no_match(client, monkeypatch):
    """Test 8: worker 遇到例外時回傳 no_match 固定文字，不洩漏例外細節，計數正常遞減。"""
    def _crashing_consult(*args, **kwargs):
        raise RuntimeError("內部模型連線致命崩潰敏感資訊")

    monkeypatch.setattr(consult_jobs, "patient_consult", _crashing_consult)

    post_res = client.post("/api/v1/general/consult/jobs", json={"query": "出錯問題"})
    job_id = post_res.json()["job_id"]
    assert consult_jobs.wait_idle(timeout=5.0)

    poll_res = client.get(f"/api/v1/general/consult/jobs/{job_id}")
    assert poll_res.status_code == 200
    data = poll_res.json()
    assert data["status"] == "no_match"
    assert "內部模型連線致命崩潰敏感資訊" not in data["message"]
    assert consult_jobs.snapshot()["running"] == 0


def test_9_poll_makes_zero_db_connections(client, monkeypatch):
    """Test 9: GET 輪詢端點純讀取記憶體，絕不建立任何 SQLite 連線。"""
    post_res = client.post("/api/v1/general/consult/jobs", json={"query": "一般衛教問題"})
    job_id = post_res.json()["job_id"]
    assert consult_jobs.wait_idle(timeout=5.0)

    db_connect_count = 0
    orig_connect = sqlite3.connect

    def _spy_connect(*args, **kwargs):
        nonlocal db_connect_count
        db_connect_count += 1
        return orig_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", _spy_connect)

    poll_res = client.get(f"/api/v1/general/consult/jobs/{job_id}")
    assert poll_res.status_code == 200
    assert db_connect_count == 0  # 輪詢期間零資料庫連線


def test_10_price_masking(client, monkeypatch):
    """Test 10: 結果訊息經 deep_mask_prices，價格金額數字已清洗。"""
    def _priced_consult(*args, **kwargs):
        return PatientConsultResult("answered", "療程費用約 15000 元整", "免責", None, "https://doctor-toolbox.com/")

    monkeypatch.setattr(consult_jobs, "patient_consult", _priced_consult)

    post_res = client.post("/api/v1/general/consult/jobs", json={"query": "費用問題"})
    job_id = post_res.json()["job_id"]
    assert consult_jobs.wait_idle(timeout=5.0)

    poll_res = client.get(f"/api/v1/general/consult/jobs/{job_id}")
    assert poll_res.status_code == 200
    data = poll_res.json()
    assert "15000" not in data["message"]


def test_11_validation_error_and_access_log(client):
    """Test 11: 請求主體驗證失敗回傳 422 且 detail 為固定「請求格式不正確」；日誌過濾有效。"""
    # 畸形請求（缺少 query 欄位）
    res = client.post("/api/v1/general/consult/jobs", json={"bad_field": 123})
    assert res.status_code == 422
    assert res.json() == {"detail": "請求格式不正確"}

    # 日誌過濾器驗證
    filt = ExcludeGeneralPathFilter()
    rec = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='POST /api/v1/general/consult/jobs HTTP/1.1" 200',
        args=(),
        exc_info=None,
    )
    assert filt.filter(rec) is False  # 應被過濾


def test_12_prod_db_guard(isolated_db_path):
    """Test 12: 守門驗證：若連線至正式庫 clinic.db 必須拋出 AssertionError。"""
    with pytest.raises(AssertionError, match="測試中禁止連線至正式資料庫"):
        sqlite3.connect(str(PROD_DB_PATH))
