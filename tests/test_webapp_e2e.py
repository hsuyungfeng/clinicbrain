"""
Taiwan Clinic Medical PageIndex RAG System - Web App 業務全流程閉環測試 (test_webapp_e2e)
Phase 18 Plan 18-03: 上傳 -> pending 草稿 -> 公開端點隱蔽 -> 醫師核准 -> 快取短路命中端到端驗證
"""

import io
import sqlite3
import docx
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config
from src.pageindex.faq_review import get_faq

CLINIC_ID = "3503190424"


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    """建立指向 isolated_db_path 測試複本之 TestClient。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "admin_api_key", "test-admin-key")
    with TestClient(app) as test_client:
        yield test_client


def test_webapp_e2e_full_lifecycle(client, isolated_db_path):
    """測試端到端閉環生命週期：文件上傳 -> pending 草稿 -> 公開端點隱蔽 -> 醫師核准 -> 查詢命中。"""
    # 1. 建立測試 DOCX 文件（包含價格與去識別化內容）
    temp_buffer = io.BytesIO()
    doc = docx.Document()
    doc.add_paragraph("問：海芙音波拉提術後要如何保養與照顧？\n答：請加強保濕與防曬，治療費用 30000 元。聯絡護理師王小明 0987-654-321。若出現高燒持續加重、呼吸困難或急性腹痛發作，請儘速就醫。")
    doc.save(temp_buffer)
    temp_buffer.seek(0)

    admin_headers = {"X-API-Key": "test-admin-key"}

    # 2. 行政人員透過 Admin API 上傳檔案 (POST /api/v1/admin/upload)
    up_resp = client.post(
        "/api/v1/admin/upload",
        data={"clinic_id": CLINIC_ID, "preview_only": "false"},
        files={"file": ("hifu_care_e2e.docx", temp_buffer.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        headers=admin_headers,
    )
    assert up_resp.status_code == 200
    up_data = up_resp.json()
    assert up_data["status"] == "ok"
    assert up_data["review_status"] == "pending"

    # 確認資料庫有 pending 狀態之草稿
    conn = sqlite3.connect(str(isolated_db_path))
    pending_id = None
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, question, answer, review_status FROM faq_cache WHERE topic_key = 'doc-hifu_care_e2e'"
        )
        row = cur.fetchone()
        assert row is not None
        pending_id, q_text, a_text, status = row
        assert status == "pending"
        assert "30000" not in a_text  # 價格已遮蔽
        assert "0987-654-321" not in a_text  # 個資電話已去識別化
    finally:
        conn.close()

    # 3. 驗證公開自然語言查詢端點 (/api/v1/query)，確認 pending 草稿 Fail-Closed 防禦（不可見）
    q_resp_before = client.post(
        "/api/v1/query",
        json={"query": "海芙音波拉提術後要如何保養與照顧？", "clinic_id": CLINIC_ID},
    )
    assert q_resp_before.status_code == 200
    data_before = q_resp_before.json()
    assert data_before.get("source") != "cache"  # 絕不可短路命中未簽核草稿

    # 4. 醫師查詢待審摘要與列表，並執行核准 (POST /api/v1/admin/review/faqs/{id}/approve)
    sum_resp = client.get("/api/v1/admin/review/summary", headers=admin_headers)
    assert sum_resp.status_code == 200
    assert sum_resp.json()["pending_total"] >= 1

    app_resp = client.post(f"/api/v1/admin/review/faqs/{pending_id}/approve", headers=admin_headers)
    assert app_resp.status_code == 200
    assert app_resp.json()["status"] == "ok"

    conn = sqlite3.connect(str(isolated_db_path))
    try:
        faq_item = get_faq(conn, pending_id)
        assert faq_item["review_status"] == "approved"
    finally:
        conn.close()

    # 5. 再次呼叫公開查詢端點，驗證核准後即刻快取短路精準命中
    q_resp_after = client.post(
        "/api/v1/query",
        json={"query": "海芙音波拉提術後要如何保養與照顧？", "clinic_id": CLINIC_ID},
    )
    assert q_resp_after.status_code == 200
    data_after = q_resp_after.json()
    assert data_after["source"] == "cache"
    assert "加強保濕與防曬" in data_after["cache_answer"]
