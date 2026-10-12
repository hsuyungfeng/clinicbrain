"""
Taiwan Clinic Medical PageIndex RAG System - 背景自動補齊答案後端測試
Phase 20 Plan 20-01: get_pending_unanswered_ids 與 POST /api/v1/admin/review/autofill/all
"""

import pathlib
import sqlite3
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config
from src.api.routes import admin as admin_mod
from src.pageindex import batch_answer_job
from src.pageindex.batch_answer_job import get_pending_unanswered_ids
from src.pageindex.faq_writer import upsert_faqs

CLINIC_ID = "3503190424"


PROD_PATH = (pathlib.Path(__file__).resolve().parent.parent / "clinic.db").resolve()


def _clear_pending_in_copy(path):
    """僅清除『隔離複本』中的待審草稿，讓斷言不受正式庫的即時資料影響。
    安全守門：拒絕對正式庫路徑操作。"""
    assert pathlib.Path(path).resolve() != PROD_PATH, "測試禁止清理正式庫"
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("DELETE FROM faq_cache WHERE review_status = 'pending'")
        conn.commit()
    finally:
        conn.close()


def _reset_batch_state():
    from src.batch import db_lock
    batch_answer_job._cancel.set()
    batch_answer_job.wait(10)
    if admin_mod._GENERATION_LOCK.locked():
        admin_mod._GENERATION_LOCK.release()
    db_lock.release(batch_answer_job._db_lock_fd)
    batch_answer_job._db_lock_fd = None
    batch_answer_job._thread = None
    batch_answer_job._state = None
    batch_answer_job._cancel.clear()


@pytest.fixture(autouse=True)
def _isolated_batch_state(monkeypatch):
    """每個測試前後重置背景作業狀態；測試一律禁止呼叫真實 LLM。"""
    def forbid(prompt):
        raise AssertionError("測試禁止呼叫真實 LLM")
    monkeypatch.setattr(admin_mod, "_local_llm_call", forbid)
    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", forbid)
    _reset_batch_state()
    yield
    _reset_batch_state()


@pytest.fixture
def test_client(isolated_db_path, monkeypatch):
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "admin_api_key", "")
    with TestClient(app) as tc:
        yield tc


def test_get_pending_unanswered_ids_filtering(isolated_db_path):
    """測試 get_pending_unanswered_ids 正確過濾待補齊草稿：
    - review_status='pending' 且 (answer IS NULL OR length(trim(answer)) < 15)
    - 忽略已核准 (approved) 或已駁回 (rejected)
    - 忽略 answer 長度 >= 15 的完整草稿
    - 支援 clinic_id 過濾與 id 升冪排序
    """
    _clear_pending_in_copy(isolated_db_path)   # 排除複本內既有的待審資料（如正式庫的即時上傳）
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        # 先清除或插入控制資料
        cur = conn.cursor()
        # 1. pending, answer="" (空字串，長度為 0 < 15)
        cur.execute(
            """INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (CLINIC_ID, "test-autofill", "問題1：答案為空？", "", "special", "web_upload", "pending")
        )
        id1 = cur.lastrowid

        # 2. pending, answer 長度 < 15
        cur.execute(
            """INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (CLINIC_ID, "test-autofill", "問題2：短答案？", "  簡短答案  ", "special", "web_upload", "pending")
        )
        id2 = cur.lastrowid

        # 3. pending, answer 長度 >= 15 (完整答案，不應被納入)
        cur.execute(
            """INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (CLINIC_ID, "test-autofill", "問題3：完整答案？", "這是一個超過三十個中文字的完整臨床照護說明解答內容，包含術後觀察重點與何時應儘速回診就醫的具體條件說明。", "special", "web_upload", "pending")
        )
        id3 = cur.lastrowid

        # 4. approved, answer 為空 (非 pending，不應納入)
        cur.execute(
            """INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (CLINIC_ID, "test-autofill", "問題4：已核准？", "", "special", "web_upload", "approved")
        )
        id4 = cur.lastrowid

        # 5. pending, answer 為空，但為其他診所或 general (clinic_id=None)
        cur.execute(
            """INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (None, "test-autofill", "問題5：通用無診所？", "", "general", "llm_generated", "pending")
        )
        id5 = cur.lastrowid
        conn.commit()

        # 測試不過濾 clinic_id
        all_unanswered = get_pending_unanswered_ids(conn, clinic_id=None, limit=100)
        assert id1 in all_unanswered
        assert id2 in all_unanswered
        assert id5 in all_unanswered
        assert id3 not in all_unanswered
        assert id4 not in all_unanswered

        # 測試指定 clinic_id
        clinic_unanswered = get_pending_unanswered_ids(conn, clinic_id=CLINIC_ID, limit=100)
        assert id1 in clinic_unanswered
        assert id2 in clinic_unanswered
        assert id5 not in clinic_unanswered
        assert id3 not in clinic_unanswered
        assert id4 not in clinic_unanswered

        # 驗證排序為升冪 (id1 < id2)
        idx1 = clinic_unanswered.index(id1)
        idx2 = clinic_unanswered.index(id2)
        assert idx1 < idx2

        # 測試 limit
        limited = get_pending_unanswered_ids(conn, clinic_id=CLINIC_ID, limit=1)
        assert len(limited) == 1
        assert limited[0] == id1

    finally:
        conn.close()


def test_autofill_all_endpoint_auth(isolated_db_path, monkeypatch):
    """測試 POST /api/v1/admin/review/autofill/all 的認證防禦。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", False)
    monkeypatch.setattr(config, "admin_api_key", "secret-test-key")

    with TestClient(app) as tc:
        # 未帶金鑰 401
        res = tc.post("/api/v1/admin/review/autofill/all", json={})
        assert res.status_code == 401

        # 錯誤金鑰 401
        res = tc.post("/api/v1/admin/review/autofill/all", headers={"X-API-Key": "bad-key"}, json={})
        assert res.status_code == 401

        # 正確金鑰 (無待補齊題目時回 noop 200)
        res = tc.post("/api/v1/admin/review/autofill/all", headers={"X-API-Key": "secret-test-key"}, json={})
        assert res.status_code == 200
        assert res.json().get("status") in ("noop", "started")


def test_autofill_all_endpoint_noop_and_started(test_client, isolated_db_path, monkeypatch):
    """測試 autofill/all 的 noop 與 started 行為，以及衝突 409。"""
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        cur = conn.cursor()
        # 清除現存所有 pending 項目，製造 noop 情境
        cur.execute("UPDATE faq_cache SET review_status = 'approved' WHERE review_status = 'pending'")
        conn.commit()

        # 1. 無待補草稿 ➔ noop
        res = test_client.post("/api/v1/admin/review/autofill/all", json={})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "noop"
        assert data["scheduled_count"] == 0

        # 2. 插入一筆待補草稿
        cur.execute(
            """INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (CLINIC_ID, "test-autofill", "問題A：需要補齊答案？", "", "special", "web_upload", "pending")
        )
        new_id = cur.lastrowid
        conn.commit()

        # Mock batch_answer_job.start 以免真的啟動 LLM 背景執行緒
        started_calls = []
        def mock_start(db_path, ids, llm_call, ask_call, lock):
            started_calls.append((db_path, ids))
            return {"status": "started", "total": len(ids)}

        monkeypatch.setattr(batch_answer_job, "start", mock_start)

        res = test_client.post("/api/v1/admin/review/autofill/all", json={})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "started"
        assert data["scheduled_count"] == 1
        assert new_id in data["faq_ids"]
        assert len(started_calls) == 1
        assert new_id in started_calls[0][1]

        # 3. 測試正在執行中時拋出 409 Conflict
        monkeypatch.setattr(batch_answer_job, "is_running", lambda: True)
        res_conflict = test_client.post("/api/v1/admin/review/autofill/all", json={})
        assert res_conflict.status_code == 409
        assert "進行中" in res_conflict.json()["detail"]

    finally:
        conn.close()
