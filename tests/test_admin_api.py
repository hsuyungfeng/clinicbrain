"""
Taiwan Clinic Medical PageIndex RAG System - Web 管理 API 單元與整合測試 (test_admin_api)
Phase 18 Plan 18-01: Admin API 認證、文件上傳解析、待審 FAQ 列表與核准/駁回操作
"""

import io
import sqlite3
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config
from src.pageindex.faq_review import get_faq
from src.pageindex.faq_writer import upsert_faqs

CLINIC_ID = "3503190424"


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    """建立 TestClient，預設開啟 allow_no_auth 放行開發模式。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "admin_api_key", "")
    with TestClient(app) as test_client:
        yield test_client


def test_admin_api_auth_fail_closed(isolated_db_path, monkeypatch):
    """測試 Fail-Closed 認證防禦：未授權請求阻斷 401。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", False)
    monkeypatch.setattr(config, "admin_api_key", "valid-admin-key")

    with TestClient(app) as test_client:
        # 未帶金鑰 ➔ 401
        res_no_key = test_client.get("/api/v1/admin/review/summary")
        assert res_no_key.status_code == 401

        # 錯誤金鑰 ➔ 401
        res_bad_key = test_client.get("/api/v1/admin/review/summary", headers={"X-API-Key": "wrong-key"})
        assert res_bad_key.status_code == 401

        # 正確金鑰 ➔ 200
        res_good_key = test_client.get("/api/v1/admin/review/summary", headers={"X-API-Key": "valid-admin-key"})
        assert res_good_key.status_code == 200


def test_admin_review_summary(client, isolated_db_path):
    """測試 /api/v1/admin/review/summary 儀表板指標查詢。"""
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        # 寫入幾筆測試用 FAQ
        upsert_faqs(conn, [
            {
                "question": "測試審核摘要問答 A？",
                "answer": "說明內容 A",
                "category": "special",
                "clinic_id": CLINIC_ID,
                "topic_key": "test-summary-a",
            },
        ], source_type="llm_generated")
    finally:
        conn.close()

    res = client.get("/api/v1/admin/review/summary")
    assert res.status_code == 200
    data = res.json()
    assert "pending_total" in data
    assert "approved_total" in data
    assert "rejected_total" in data
    assert data["pending_total"] >= 1


def test_admin_get_review_faqs_and_approve_reject(client, isolated_db_path):
    """測試 FAQ 待審列表查詢、核准與駁回操作。"""
    conn = sqlite3.connect(str(isolated_db_path))
    pending_id = None
    try:
        upsert_faqs(conn, [
            {
                "question": "測試待審問答條目？",
                "answer": "這是一般衛教說明內容。若出現高燒持續加重、呼吸困難或急性腹痛發作，請儘速就醫。",
                "category": "general",
                "clinic_id": None,
                "topic_key": "test-item-review",
            },
        ], source_type="llm_generated")

        cur = conn.cursor()
        cur.execute("SELECT id FROM faq_cache WHERE topic_key = 'test-item-review'")
        pending_id = cur.fetchone()[0]
    finally:
        conn.close()

    # 1. 檢索 pending 列表
    res_list = client.get("/api/v1/admin/review/faqs?status=pending")
    assert res_list.status_code == 200
    data_list = res_list.json()
    assert data_list["total"] >= 1
    faq_ids = [f["id"] for f in data_list["faqs"]]
    assert pending_id in faq_ids

    # 2. 測試核准 /api/v1/admin/review/faqs/{id}/approve
    res_app = client.post(f"/api/v1/admin/review/faqs/{pending_id}/approve")
    assert res_app.status_code == 200
    assert res_app.json()["status"] == "ok"

    conn = sqlite3.connect(str(isolated_db_path))
    try:
        faq_item = get_faq(conn, pending_id)
        assert faq_item["review_status"] == "approved"
    finally:
        conn.close()

    # 3. 測試駁回 /api/v1/admin/review/faqs/{id}/reject
    res_rej = client.post(f"/api/v1/admin/review/faqs/{pending_id}/reject")
    assert res_rej.status_code == 200
    assert res_rej.json()["status"] == "ok"

    conn = sqlite3.connect(str(isolated_db_path))
    try:
        faq_item = get_faq(conn, pending_id)
        assert faq_item["review_status"] == "rejected"
    finally:
        conn.close()


def test_admin_file_upload_validation_and_preview(client):
    """測試文件上傳邊界條件：非預期副檔名、檔案過大阻斷與預覽模式。"""
    # 1. 不支援副檔名 (.exe)
    res_bad_ext = client.post(
        "/api/v1/admin/upload",
        data={"clinic_id": CLINIC_ID},
        files={"file": ("malicious.exe", b"binary content", "application/octet-stream")},
    )
    assert res_bad_ext.status_code == 400
    assert "不支援的檔案格式" in res_bad_ext.json()["detail"]

    # 2. 超過 15MB 限制
    large_dummy_content = b"0" * (15 * 1024 * 1024 + 1)
    res_too_large = client.post(
        "/api/v1/admin/upload",
        data={"clinic_id": CLINIC_ID},
        files={"file": ("oversized.docx", large_dummy_content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert res_too_large.status_code == 400
    assert "超過上限 15MB" in res_too_large.json()["detail"]


def test_admin_docx_upload_ingestion(client, isolated_db_path):
    """測試合格 docx 文件上傳解析、去識別化、價格遮蔽與 pending 入庫。"""
    import docx
    temp_buffer = io.BytesIO()
    doc = docx.Document()
    doc.add_paragraph("問：皮秒雷射術後要如何保養？")
    doc.add_paragraph("答：請務必加強保濕與防曬，療程費用為 5000 元。聯絡電話 0912-345-678。")
    doc.save(temp_buffer)
    temp_buffer.seek(0)

    res_upload = client.post(
        "/api/v1/admin/upload",
        data={"clinic_id": CLINIC_ID, "preview_only": "false"},
        files={"file": ("pico_care.docx", temp_buffer.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert res_upload.status_code == 200
    data = res_upload.json()
    assert data["status"] == "ok"
    assert data["inserted"] >= 1

    # 驗證資料庫寫入內容已過濾敏感資料且狀態為 pending
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT question, answer, review_status FROM faq_cache WHERE topic_key = 'doc-pico_care'")
        row = cur.fetchone()
        assert row is not None
        q, a, status = row
        assert status == "pending"
        assert "皮秒雷射" in q or "皮秒雷射" in a
        assert "5000" not in a  # 價格已遮蔽
        assert "0912-345-678" not in a  # 個資電話已去識別化
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Phase 18 複審加固回歸測試
# ---------------------------------------------------------------------------
def _docx_bytes(text: str) -> bytes:
    import io
    import docx

    buf = io.BytesIO()
    d = docx.Document()
    for para in text.split("\n\n"):
        d.add_paragraph(para)
    d.save(buf)
    return buf.getvalue()


def _upload(client, name, content, clinic="3503190424", **data):
    return client.post(
        "/api/v1/admin/upload",
        data={"clinic_id": clinic, **data},
        files={"file": (name, content, "application/octet-stream")},
    )


def test_review_upload_is_web_upload_pending_and_hidden(client, isolated_db_path):
    """上傳草稿必為 source_type='web_upload'＋pending，且 visible_faq_sql 核准前一律查不到。"""
    import sqlite3
    from src.pageindex.faq_review import visible_faq_sql

    r = _upload(client, "hide_me.docx", _docx_bytes("問：複審隱蔽測試問題的保養方式？\n答：請加強保濕。若出現高燒超過3天或呼吸困難，請儘速就醫。"))
    assert r.status_code == 200 and r.json()["review_status"] == "pending"
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        rows = conn.execute("SELECT source_type, review_status FROM faq_cache WHERE topic_key='doc-hide_me'").fetchall()
        assert rows and all(x == ("web_upload", "pending") for x in rows)
        n = conn.execute(f"SELECT COUNT(*) FROM faq_cache WHERE topic_key='doc-hide_me' AND {visible_faq_sql(conn)}").fetchone()[0]
        assert n == 0
    finally:
        conn.close()


def test_review_upload_unknown_clinic_404(client):
    r = _upload(client, "x.docx", _docx_bytes("問：測試？\n答：測試。"), clinic="9999999999")
    assert r.status_code == 404


def test_review_upload_magic_mismatch_400(client):
    assert _upload(client, "fake.docx", b"not a zip file at all").status_code == 400
    assert _upload(client, "fake.pdf", b"PK\x03\x04junk").status_code == 400


def test_review_upload_too_many_paragraphs_400(client):
    text = "\n\n".join(f"第{i}段衛教內容。" for i in range(250))
    assert _upload(client, "big.docx", _docx_bytes(text)).status_code == 400


def test_review_upload_filters_guarantee_wording(client):
    """含保證療效字樣的段落單筆剔除，不影響其他段落。"""
    text = "問：術後如何保養？\n答：請加強保濕與防曬。\n\n問：效果如何？\n答：本療程保證有效，百分之百有效。"
    r = _upload(client, "mix.docx", _docx_bytes(text), preview_only="true")
    assert r.status_code == 200
    body = r.json()
    assert body["rejected_paragraphs"] >= 1
    assert all("保證有效" not in f["answer"] for f in body["faqs_preview"])


def test_review_list_filters_validated(client):
    assert client.get("/api/v1/admin/review/faqs?status=bogus").status_code == 422
    assert client.get("/api/v1/admin/review/faqs?category=bogus").status_code == 422


def test_review_filename_traversal_neutralised(client):
    r = _upload(client, "../../etc/evil.docx", _docx_bytes("問：路徑測試？\n答：測試內容。"), preview_only="true")
    assert r.status_code == 200 and "/" not in r.json()["filename"]
