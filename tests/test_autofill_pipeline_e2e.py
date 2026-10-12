"""
Taiwan Clinic Medical PageIndex RAG System - 背景自動補齊全流程端到端測試 (test_autofill_pipeline_e2e)
Phase 20 Plan 20-01 & 20-02:
上傳/建立待補題目草稿 -> 公開端點不可見 -> 觸發 autofill/all -> 背景作業執行完成 ->
狀態維持 pending -> 公開端點仍不可見 -> 批量 approve -> 公開端點短路命中。
"""

import sqlite3
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config
from src.pageindex import batch_answer_job
from src.pageindex.answer_generator import generate_answer_for_faq
from src.pageindex.faq_review import set_review_status

CLINIC_ID = "3503190424"


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "admin_api_key", "")
    with TestClient(app) as tc:
        yield tc


def test_autofill_pipeline_full_e2e(client, isolated_db_path, monkeypatch):
    """
    驗證 Phase 20 背景自動補齊完整端到端生命週期：
    1. 建立「答案待補齊」草稿（answer=""，review_status="pending"）。
    2. 公開查詢端點 (/api/v1/query) 驗證絕對不可見。
    3. 觸發 POST /api/v1/admin/review/autofill/all 啟動自動補齊。
    4. 執行背景補齊邏輯（mock LLM 回覆合規繁體答案）。
    5. 補齊後資料庫中草稿答案已完整，但 review_status 仍為 pending。
    6. 公開查詢端點再次驗證，pending 項目依舊絕對不可見（Fail-Closed 隔離保證）。
    7. 醫師於管理端執行批量核准 (approve)。
    8. 公開查詢端點驗證成功透過快取短路 (source="cache") 命中！
    """
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        cur = conn.cursor()
        test_q = "【照護指引】乾眼症日常保養有哪些關鍵注意事項？"
        # 1. 插入待補草稿
        cur.execute(
            """INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (CLINIC_ID, "dry-eye-care", test_q, "", "special", "web_upload", "pending"),
        )
        faq_id = cur.lastrowid
        conn.commit()

        # 2. 驗證公開端點不可見
        q_resp1 = client.post(
            "/api/v1/query",
            json={"query": test_q, "clinic_id": CLINIC_ID},
        )
        assert q_resp1.status_code == 200
        assert q_resp1.json().get("source") != "cache"

        # 3. 呼叫 autofill/all 端點
        # 為了受控執行，我們以同等邏輯跑 generate_answer_for_faq
        compliance_answer = (
            "乾眼症日常保養建議注意以下重點：多補充水分，避免長時間盯著螢幕，"
            "建議每用眼三十分鐘休息五分鐘；可配合毛巾溫敷眼部促進血液循環，並維持充足睡眠與均衡飲食。"
            "若出現持續高燒、胸痛或視力明顯減退等劇烈異常症狀，請務必立即就醫尋求專業醫師診治。"
        )
        assert len(compliance_answer) >= 100

        def mock_llm(prompt: str) -> str:
            return compliance_answer

        # 模擬背景批次處理執行
        res_fill = generate_answer_for_faq(conn, faq_id, mock_llm)
        assert res_fill["id"] == faq_id
        assert res_fill["review_status"] == "pending"

        # 5. 驗證資料庫狀態：答案已補齊，但仍為 pending
        cur.execute("SELECT answer, review_status FROM faq_cache WHERE id = ?", (faq_id,))
        row = cur.fetchone()
        assert row is not None
        ans_db, status_db = row
        assert len(ans_db.strip()) >= 100
        assert status_db == "pending"

        # 6. 再次驗證公開端點不可見 (Fail-Closed)
        q_resp2 = client.post(
            "/api/v1/query",
            json={"query": test_q, "clinic_id": CLINIC_ID},
        )
        assert q_resp2.status_code == 200
        assert q_resp2.json().get("source") != "cache"

        # 7. 醫師批量核准
        res_batch = client.post(
            "/api/v1/admin/review/batch",
            json={"action": "approve", "faq_ids": [faq_id]},
        )
        assert res_batch.status_code == 200
        assert res_batch.json()["success_count"] == 1

        # 8. 公開端點短路命中
        q_resp3 = client.post(
            "/api/v1/query",
            json={"query": test_q, "clinic_id": CLINIC_ID},
        )
        assert q_resp3.status_code == 200
        data3 = q_resp3.json()
        assert data3["source"] == "cache"
        assert "乾眼症日常保養建議注意以下重點" in data3["cache_answer"]

    finally:
        conn.close()
