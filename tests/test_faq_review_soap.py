"""
Taiwan Clinic Medical PageIndex RAG System - FAQ 審核工具擴充測試 (test_faq_review_soap)
Phase 15 Plan 15-02: 測試依 source_type 篩選、病歷溯源呈現與審核核准/駁回
"""

import json
import sqlite3
import pytest

import scripts.review_faq as review_script
from src.pageindex.faq_review import get_faq, list_faqs, set_review_status
from src.pageindex.faq_writer import upsert_faqs

CLINIC = "3503190424"


def _seed_distilled_faq(conn: sqlite3.Connection) -> int:
    """插入一筆 soap_distilled FAQ 於測試資料庫中。"""
    meta = json.dumps({
        "source": "soap_distilled",
        "record_count": 3,
        "condition": "急性咽喉炎",
        "clinic_id": CLINIC,
    }, ensure_ascii=False)

    faqs = [
        {
            "clinic_id": CLINIC,
            "topic_key": "care-急性咽喉炎",
            "question": "【照護指引】罹患急性咽喉炎應注意哪些居家照護事項？",
            "answer": "以下為罹患急性咽喉炎之常見居家照護重點：\n1. 請多喝溫水與充分休息。\n\n【就醫警訊】若出現高燒超過3天或呼吸困難，請儘速就醫。\n【免責聲明】本資訊僅供衛教參考。",
            "category": "special",
            "metadata": meta,
        }
    ]
    upsert_faqs(conn, faqs, source_type="soap_distilled")

    cur = conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE topic_key = 'care-急性咽喉炎'")
    return cur.fetchone()[0]


def test_list_faqs_filter_by_source_type(isolated_conn):
    """測試 list_faqs 支援依 source_type='soap_distilled' 篩選。"""
    conn = isolated_conn
    faq_id = _seed_distilled_faq(conn)

    # 1. 不帶 source_type -> 包含 soap_distilled 與 llm_generated
    faqs_all = list_faqs(conn, status="pending")
    assert len(faqs_all) >= 1

    # 2. 帶 source_type="soap_distilled"
    faqs_soap = list_faqs(conn, status="pending", source_type="soap_distilled")
    assert len(faqs_soap) == 1
    assert faqs_soap[0]["id"] == faq_id
    assert faqs_soap[0]["source_type"] == "soap_distilled"

    # 3. 帶 source_type="llm_generated"
    faqs_llm = list_faqs(conn, status="pending", source_type="llm_generated")
    assert len(faqs_llm) == 0


def test_review_faq_cli_show_provenance(isolated_db_path, capsys):
    """測試 CLI show 命令正確印出 [臨床病歷溯源] 區塊。"""
    db_path = isolated_db_path
    conn = sqlite3.connect(str(db_path))
    try:
        faq_id = _seed_distilled_faq(conn)
    finally:
        conn.close()

    ret = review_script.main(["--db", str(db_path), "show", str(faq_id)])
    assert ret == 0

    captured = capsys.readouterr()
    assert "【臨床病歷溯源】" in captured.out
    assert "SOAP 臨床照護摘要提煉" in captured.out
    assert "參考病歷筆數：3 筆" in captured.out
    assert "標的疾病：急性咽喉炎" in captured.out


def test_review_faq_approve_soap_distilled(isolated_conn):
    """測試核准 soap_distilled 項目，將 review_status 轉為 approved。"""
    conn = isolated_conn
    faq_id = _seed_distilled_faq(conn)

    # 執行核准
    res = set_review_status(conn, [faq_id], "approved")
    assert res.changed == [faq_id]

    faq = get_faq(conn, faq_id)
    assert faq["review_status"] == "approved"


def test_review_writer_never_alters_unmigrated_db(tmp_path):
    """複審：寫入路徑不得自動 ALTER；未遷移 metadata 欄位時寫入 soap_distilled 須 Fail-Closed。"""
    import shutil
    from tests.conftest import PROD_DB_PATH
    from src.pageindex.faq_writer import upsert_faqs, has_metadata_column

    db = tmp_path / "unmigrated.db"
    shutil.copy2(PROD_DB_PATH, db)
    from tests.conftest import _ensure_faq_cache
    _ensure_faq_cache(db)
    conn = sqlite3.connect(str(db))
    try:
        if has_metadata_column(conn):
            conn.execute("ALTER TABLE faq_cache DROP COLUMN metadata")
            conn.commit()
        assert not has_metadata_column(conn)
        faq = {"clinic_id": "3503190424", "topic_key": "care-x", "question": "Q?", "answer": "A", "category": "special", "metadata": "{}"}
        with pytest.raises(RuntimeError):
            upsert_faqs(conn, [faq], source_type="soap_distilled")
        # 一般來源（如同步匯入）寫入也不會順手加欄位
        upsert_faqs(conn, [{k: v for k, v in faq.items() if k != "metadata"}], source_type="clinic_upload")
        assert not has_metadata_column(conn)
    finally:
        conn.close()


def test_review_rerun_does_not_reset_approved(isolated_conn):
    """複審：內容未變的重跑不得把已核准草稿打回 pending 或遞增版號。"""
    from src.pageindex.faq_writer import upsert_faqs
    from src.pageindex.faq_review import set_review_status

    faq = {"clinic_id": "3503190424", "topic_key": "care-rerun", "question": "【照護指引】罹患感冒應注意哪些居家照護事項？",
           "answer": "1. 多休息\n\n【就醫警訊】若出現高燒超過3天或呼吸困難，請儘速就醫。\n【免責聲明】僅供衛教參考，無法取代醫師親自診察。",
           "category": "special", "metadata": json.dumps({"record_count": 2})}
    upsert_faqs(isolated_conn, [faq], source_type="soap_distilled")
    fid = isolated_conn.execute("SELECT id FROM faq_cache WHERE topic_key='care-rerun'").fetchone()[0]
    res = set_review_status(isolated_conn, [fid], "approved")
    assert fid in res.changed
    ver = isolated_conn.execute("SELECT content_version FROM faq_cache WHERE id=?", (fid,)).fetchone()[0]

    upsert_faqs(isolated_conn, [dict(faq, metadata=json.dumps({"record_count": 3}))], source_type="soap_distilled")
    st, ver2, meta = isolated_conn.execute("SELECT review_status, content_version, metadata FROM faq_cache WHERE id=?", (fid,)).fetchone()
    assert st == "approved" and ver2 == ver
    assert json.loads(meta)["record_count"] == 3
