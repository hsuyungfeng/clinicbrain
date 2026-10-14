"""Phase 24 Plan 24-01 單元與整合測試：上傳中心「名稱」欄位、共用管線與批量行為回歸。"""

from __future__ import annotations

import io
import json
from pathlib import Path
import sqlite3
import docx
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from src.api.app import app
from src.api.config import config
from src.api.routes.admin import (
    _NAME_VALIDATION_ERROR_MSG,
    _text_to_faq_drafts,
    validate_display_name,
)

CLINIC_ID = "3503190424"
GOLDEN_PATH = Path(__file__).parent / "fixtures" / "upload_pipeline_golden.json"


def _docx_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    d = docx.Document()
    for para in text.split("\n\n"):
        d.add_paragraph(para)
    d.save(buf)
    return buf.getvalue()


def _upload(client: TestClient, filename: str, content: bytes, clinic: str = CLINIC_ID, name: str | None = None, **data):
    form_data = {"clinic_id": clinic, **data}
    if name is not None:
        form_data["name"] = name
    return client.post(
        "/api/v1/admin/upload",
        data=form_data,
        files={"file": (filename, content, "application/octet-stream")},
    )


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    """建立 TestClient，明確確保與正式 clinic.db 隔離。"""
    assert isolated_db_path != config.db_path
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "admin_api_key", "")
    with TestClient(app) as test_client:
        yield test_client


# =========================================================================
# Task 1 測試：golden 基準與 _text_to_faq_drafts 管線
# =========================================================================

def test_pipeline_golden_matches_legacy(client):
    """Task 1: 重構後，對同一 golden 輸入文件，faqs_preview 與改動前 golden 基準逐項相同。"""
    p1 = "問：什麼是微創手術？\n答：微創手術是以小切口進行的治療方式，恢復期通常較短，術後請依醫師指示回診。"
    p2 = "術後照護非常重要，請依照醫師指示清潔傷口並保持乾燥，避免感染並定期回診追蹤復原進度。"
    p3 = "本微創手術療程單次費用為 NT3000 元整，費用包含術後傷口護理材料與首次回診檢查。"
    p4 = "这是简体字的说明文字，请依照医嘱执行。"
    p5 = "短"
    full_text = "\n\n".join([p1, p2, p3, p4, p5])
    content = _docx_bytes(full_text)

    resp = _upload(client, "golden.docx", content, clinic=CLINIC_ID, preview_only="true")
    assert resp.status_code == 200
    actual = resp.json()

    golden_data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert actual == golden_data


def test_text_to_faq_drafts_direct():
    """Task 1: 直接驗證 _text_to_faq_drafts 函式之 topic_key、佔位題與過長防護。"""
    raw_text = (
        "問：皮秒雷射作用機制？\n答：透過光震波擊碎色素斑塊，術後請加強保濕與防曬避免反黑。\n\n"
        "日常照護指示說明內容，請依循醫師門診處置指導原則執行傷口照護處置。"
    )
    drafts, extracted_cnt, rej_cnt = _text_to_faq_drafts(raw_text, topic="custom-topic", clinic_id=CLINIC_ID)
    assert extracted_cnt == 2
    assert rej_cnt == 0
    assert len(drafts) == 2

    # 第一題為問答配對
    assert drafts[0]["question"] == "皮秒雷射作用機制？"
    assert "光震波擊碎色素" in drafts[0]["answer"]
    assert drafts[0]["topic_key"] == "doc-custom-topic"
    assert drafts[0]["category"] == "special"
    assert drafts[0]["clinic_id"] == CLINIC_ID

    # 第二題為無前綴段落的佔位題
    assert drafts[1]["question"] == "【診所文件】custom-topic - 指示 2"
    assert drafts[1]["topic_key"] == "doc-custom-topic"

    # 超過 200 段落時拋出 400
    too_many = "\n\n".join([f"段落 {i}" for i in range(201)])
    with pytest.raises(HTTPException) as exc:
        _text_to_faq_drafts(too_many, topic="x", clinic_id=CLINIC_ID)
    assert exc.value.status_code == 400
    assert "文件段落過多（201 > 200）" in exc.value.detail


# =========================================================================
# Task 2 測試：validate_display_name 單元驗證
# =========================================================================

def test_validate_display_name_basic_and_nfkc():
    """Task 2: 空白修剪、空值返回 None 與 NFKC 正規化。"""
    assert validate_display_name("  微創手術衛教 ") == "微創手術衛教"
    assert validate_display_name("") is None
    assert validate_display_name("   ") is None
    assert validate_display_name(None) is None
    assert validate_display_name("ＡＢＣ衛教") == "ABC衛教"
    assert validate_display_name("隆鼻手術（初診）·注意事項-2026") == "隆鼻手術(初診)·注意事項-2026"


def test_validate_display_name_length_limit():
    """Task 2: 長度超過 80 字元拋出 400，錯誤訊息不包含輸入原文。"""
    long_name = "微" * 81
    with pytest.raises(HTTPException) as exc:
        validate_display_name(long_name)
    assert exc.value.status_code == 400
    assert exc.value.detail == _NAME_VALIDATION_ERROR_MSG
    assert long_name not in exc.value.detail


def test_validate_display_name_privacy_and_price_tamper():
    """Task 2: 含電話個資或價格金額字樣拋出 400。"""
    name_phone = "王小明電話0912-345-678"
    with pytest.raises(HTTPException) as exc:
        validate_display_name(name_phone)
    assert exc.value.status_code == 400
    assert exc.value.detail == _NAME_VALIDATION_ERROR_MSG
    assert "0912" not in exc.value.detail

    name_price = "療程3000元"
    with pytest.raises(HTTPException) as exc2:
        validate_display_name(name_price)
    assert exc2.value.status_code == 400
    assert exc2.value.detail == _NAME_VALIDATION_ERROR_MSG
    assert "3000" not in exc2.value.detail


def test_validate_display_name_path_and_control_chars():
    """Task 2: 含路徑字元（/ \）或控制字元（\n）拋出 400。"""
    for bad in ("a/../b", "a\\b", "x\ny", "test<script>", "name; DROP TABLE"):
        with pytest.raises(HTTPException) as exc:
            validate_display_name(bad)
        assert exc.value.status_code == 400
        assert exc.value.detail == _NAME_VALIDATION_ERROR_MSG


# =========================================================================
# Task 3 測試：名稱欄位端到端、同名覆寫與批量上傳行為回歸
# =========================================================================

def test_name_default_preserves_legacy_topic(client, isolated_db_path):
    """Task 3: 不傳 name 上傳 衛教A.docx，topic_key 維持 doc-衛教A。"""
    text = "問：術後照護重點？\n答：保持傷口乾燥，避免劇烈運動，若有異常紅腫請立即就醫。"
    content = _docx_bytes(text)

    resp = _upload(client, "衛教A.docx", content)
    assert resp.status_code == 200

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM faq_cache WHERE clinic_id = ? AND topic_key = ?", (CLINIC_ID, "doc-衛教A"))
    assert cur.fetchone()[0] == 1
    conn.close()


def test_same_filename_no_name_overwrites_legacy(client, isolated_db_path):
    """Task 3 (R4 回歸): 未填名稱，同診所連續兩次上傳同檔名 x.docx，同一問句答案更新，topic_key 僅 1 列。"""
    content1 = _docx_bytes("問：什麼是微創？\n答：版本一說明文字，提供基礎處置指引。")
    content2 = _docx_bytes("問：什麼是微創？\n答：版本二修改說明，提供更新後之門診衛教方針。")

    # 第一次上傳
    r1 = _upload(client, "x.docx", content1)
    assert r1.status_code == 200
    assert r1.json()["inserted"] == 1

    # 第二次上傳相同檔名
    r2 = _upload(client, "x.docx", content2)
    assert r2.status_code == 200
    assert r2.json()["updated"] == 1
    assert r2.json()["inserted"] == 0

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT answer, content_version FROM faq_cache WHERE clinic_id = ? AND topic_key = ? AND question = ?",
        (CLINIC_ID, "doc-x", "什麼是微創？"),
    ).fetchall()
    assert len(rows) == 1
    assert "版本二修改說明" in rows[0][0]
    assert rows[0][1] == 2  # content_version 遞增
    conn.close()


def test_name_overrides_topic(client, isolated_db_path):
    """Task 3: 傳入 name='微創手術衛教' 上傳 衛教A.docx，topic_key 為 doc-微創手術衛教。"""
    text = "一般日常衛教文字說明，請患者保持清潔與按時服藥。"
    content = _docx_bytes(text)

    resp = _upload(client, "衛教A.docx", content, name="微創手術衛教")
    assert resp.status_code == 200

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    row = cur.execute(
        "SELECT question, topic_key FROM faq_cache WHERE clinic_id = ? AND topic_key = ?",
        (CLINIC_ID, "doc-微創手術衛教"),
    ).fetchone()
    assert row is not None
    assert row[0] == "【診所文件】微創手術衛教 - 指示 1"
    assert row[1] == "doc-微創手術衛教"
    conn.close()


def test_same_filename_different_names_do_not_overwrite(client, isolated_db_path):
    """Task 3: 同診所，兩次上傳同檔名 x.docx 但 name 分別為 '甲' 與 '乙'，兩者互不覆寫。"""
    content = _docx_bytes("問：常見問題？\n答：詳細解答說明內容，遵守醫囑方針。")

    r1 = _upload(client, "x.docx", content, name="甲")
    assert r1.status_code == 200

    r2 = _upload(client, "x.docx", content, name="乙")
    assert r2.status_code == 200

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    cnt_jia = cur.execute("SELECT COUNT(*) FROM faq_cache WHERE clinic_id = ? AND topic_key = ?", (CLINIC_ID, "doc-甲")).fetchone()[0]
    cnt_yi = cur.execute("SELECT COUNT(*) FROM faq_cache WHERE clinic_id = ? AND topic_key = ?", (CLINIC_ID, "doc-乙")).fetchone()[0]
    assert cnt_jia == 1
    assert cnt_yi == 1
    conn.close()


def test_same_name_reupload_overwrites_as_before(client, isolated_db_path):
    """Task 3: 同 name 重傳相同內容 → unchanged 計數 > 0，不新增重複列。"""
    content = _docx_bytes("問：術後復原？\n答：復原期約需一週，保持傷口乾淨。")

    r1 = _upload(client, "doc1.docx", content, name="專題A")
    assert r1.status_code == 200
    assert r1.json()["inserted"] == 1

    r2 = _upload(client, "doc2.docx", content, name="專題A")
    assert r2.status_code == 200
    assert r2.json()["unchanged"] == 1
    assert r2.json()["inserted"] == 0


def test_invalid_name_rejected_400_no_db_write(client, isolated_db_path):
    """Task 3: name 含個資/電話時回 400，且 faq_cache 列數不變。"""
    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    cnt_before = cur.execute("SELECT COUNT(*) FROM faq_cache WHERE clinic_id = ?", (CLINIC_ID,)).fetchone()[0]

    content = _docx_bytes("問：問題？\n答：回答內容。")
    resp = _upload(client, "doc.docx", content, name="王小明0912-345-678")
    assert resp.status_code == 400
    assert resp.json()["detail"] == _NAME_VALIDATION_ERROR_MSG
    assert "0912" not in resp.json()["detail"]

    cnt_after = cur.execute("SELECT COUNT(*) FROM faq_cache WHERE clinic_id = ?", (CLINIC_ID,)).fetchone()[0]
    assert cnt_before == cnt_after
    conn.close()


def test_preview_with_name_writes_nothing(client, isolated_db_path):
    """Task 3: preview_only=true 帶 name 時不寫入資料庫，faqs_preview 正確使用 name。"""
    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    cnt_before = cur.execute("SELECT COUNT(*) FROM faq_cache WHERE clinic_id = ?", (CLINIC_ID,)).fetchone()[0]

    content = _docx_bytes("問：預覽問題？\n答：預覽回答說明內容文字。")
    resp = _upload(client, "test.docx", content, name="自訂專案", preview_only="true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["preview_only"] is True
    assert data["faqs_preview"][0]["topic_key"] == "doc-自訂專案"

    cnt_after = cur.execute("SELECT COUNT(*) FROM faq_cache WHERE clinic_id = ?", (CLINIC_ID,)).fetchone()[0]
    assert cnt_before == cnt_after
    conn.close()


def test_write_path_still_pending_web_upload(client, isolated_db_path):
    """Task 3: 帶 name 實質寫入後，review_status='pending', source_type='web_upload'。"""
    content = _docx_bytes("問：審核狀態測試？\n答：測試答案內容。")
    resp = _upload(client, "status_test.docx", content, name="狀態測試")
    assert resp.status_code == 200
    assert resp.json()["review_status"] == "pending"

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    row = cur.execute(
        "SELECT source_type, review_status FROM faq_cache WHERE clinic_id = ? AND topic_key = ?",
        (CLINIC_ID, "doc-狀態測試"),
    ).fetchone()
    assert row[0] == "web_upload"
    assert row[1] == "pending"
    conn.close()


def test_batch_upload_each_file_independent(client, isolated_db_path):
    """Task 3 (批量行為): 前端逐檔送出，單檔損毀（狀態碼 400）不影響其他檔案正常入庫 (200/400/200)。"""
    good1 = _docx_bytes("問：良好一？\n答：內容一說明。")
    broken = b"This is plain text pretending to be docx, magic header fails"
    good2 = _docx_bytes("問：良好二？\n答：內容二說明。")

    r1 = _upload(client, "good1.docx", good1)
    assert r1.status_code == 200

    r2 = _upload(client, "broken.docx", broken)
    assert r2.status_code == 400

    r3 = _upload(client, "good2.docx", good2)
    assert r3.status_code == 200

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    assert cur.execute("SELECT COUNT(*) FROM faq_cache WHERE clinic_id = ? AND topic_key = 'doc-good1'", (CLINIC_ID,)).fetchone()[0] == 1
    assert cur.execute("SELECT COUNT(*) FROM faq_cache WHERE clinic_id = ? AND topic_key = 'doc-broken'", (CLINIC_ID,)).fetchone()[0] == 0
    assert cur.execute("SELECT COUNT(*) FROM faq_cache WHERE clinic_id = ? AND topic_key = 'doc-good2'", (CLINIC_ID,)).fetchone()[0] == 1
    conn.close()


def test_batch_same_filename_in_batch_overwrites(client, isolated_db_path):
    """Task 3 (批量已知限制): 批量中兩次送出同檔名 x.docx（未附 name），後者覆寫前者。"""
    c1 = _docx_bytes("問：同檔名題目？\n答：第一次上傳內容。")
    c2 = _docx_bytes("問：同檔名題目？\n答：第二次覆寫內容。")

    r1 = _upload(client, "same.docx", c1)
    assert r1.status_code == 200

    r2 = _upload(client, "same.docx", c2)
    assert r2.status_code == 200
    assert r2.json()["updated"] == 1

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    rows = cur.execute("SELECT answer FROM faq_cache WHERE clinic_id = ? AND topic_key = 'doc-same'", (CLINIC_ID,)).fetchall()
    assert len(rows) == 1
    assert "第二次覆寫內容" in rows[0][0]
    conn.close()
