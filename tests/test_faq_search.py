"""
Taiwan Clinic Medical PageIndex RAG System - FAQ 查詢與路由整合測試
涵蓋 Phase 04 TASK-03:
- search_faq_cache() 之 FTS5 trigram MATCH 檢索 (3+ 字)
- search_faq_cache() 之 LIKE fallback 檢索 (<3 字)
- search_faq_cache() 診所識別隔離過濾
- handle_query() special 路由整合 faq_hits
- handle_query() general 路由嚴格隔離診所專屬 FAQ
- handle_query() faq_hits 價格遮蔽保護
"""

import sqlite3
import pytest
from src.query.search import search_faq_cache
from src.query.router import handle_query


def test_search_faq_cache_fts_match(conn: sqlite3.Connection):
    """驗證 3 字以上關鍵字能透過 FTS5 MATCH 正確檢索到 FAQ。"""
    hits = search_faq_cache(conn, "瘦瘦筆", clinic_id="3503190424")
    assert len(hits) >= 1
    questions = [h.fields["question"] for h in hits]
    assert any("瘦瘦筆" in q for q in questions)


def test_search_faq_cache_like_fallback(conn: sqlite3.Connection):
    """驗證少於 3 字之關鍵字（如 2 字「粉瘤」）能透過 LIKE fallback 命中。"""
    hits = search_faq_cache(conn, "粉瘤", clinic_id="3503190424")
    assert len(hits) >= 1
    questions = [h.fields["question"] for h in hits]
    assert any("粉瘤" in q for q in questions)


def test_search_faq_cache_clinic_isolation(isolated_conn: sqlite3.Connection):
    """驗證查詢時絕不會跨診所洩漏其他診所的私有 FAQ。"""
    cursor = isolated_conn.cursor()
    cursor.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type)
        VALUES ('other-clinic-999', 'isolation-test', '其他診所的機密問答？', '這是其他診所專屬資料', 'special', 'manual')
        """
    )
    isolated_conn.commit()

    # 以緻妍診所代碼查詢，不應命中 other-clinic-999
    hits_zhiyan = search_faq_cache(isolated_conn, "機密問答", clinic_id="3503190424")
    assert len(hits_zhiyan) == 0

    # 以 other-clinic-999 查詢，應正常命中
    hits_other = search_faq_cache(isolated_conn, "機密問答", clinic_id="other-clinic-999")
    assert len(hits_other) == 1
    assert hits_other[0].fields["clinic_id"] == "other-clinic-999"


def test_handle_query_special_faq_integration(conn: sqlite3.Connection):
    """測試 handle_query 在 special 路由下正確整合 faq_hits。"""
    resp = handle_query(conn, "瘦瘦筆可以用多久？", clinic_id="3503190424")
    assert resp.route == "special"
    assert len(resp.faq_hits) >= 1
    questions = [h.fields["question"] for h in resp.faq_hits]
    assert any("瘦瘦筆" in q for q in questions)


def test_handle_query_general_faq_isolation(isolated_conn: sqlite3.Connection):
    """驗證 general 路由絕對不會洩漏帶有 clinic_id 或 category='special' 的私有 FAQ。"""
    cursor = isolated_conn.cursor()
    # 插入一筆 general 類且 clinic_id 為 NULL 的通用衛教 FAQ
    cursor.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type)
        VALUES (NULL, 'general-health', '感冒多喝水有用嗎？', '多喝水能促進新陳代謝緩解症狀', 'general', 'manual')
        """
    )
    # 插入一筆 special 類且帶有 clinic_id 的私有 FAQ
    cursor.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type)
        VALUES ('3503190424', 'private-faq', '感冒看診掛號費用多少？', '掛號費200元請至櫃檯辦理', 'special', 'manual')
        """
    )
    isolated_conn.commit()

    resp = handle_query(isolated_conn, "感冒多喝水有用嗎？")
    assert resp.route == "general"
    # 應命中通用 FAQ
    questions = [h.fields["question"] for h in resp.faq_hits]
    assert "感冒多喝水有用嗎？" in questions
    # 絕不可命中私有 FAQ
    assert "感冒看診掛號費用多少？" not in questions
    for hit in resp.faq_hits:
        assert hit.fields.get("clinic_id") is None
        assert hit.fields.get("category") == "general"


def test_handle_query_faq_price_masked(isolated_conn: sqlite3.Connection):
    """驗證 faq_hits 中任何可能含有價格字樣的欄位均被替換為 [請致電診所確認]。"""
    cursor = isolated_conn.cursor()
    cursor.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type)
        VALUES ('3503190424', 'price-leak-test', '皮秒雷射療程價格是多少？', '特惠方案只要 3000元，雙部位 5000塊', 'special', 'manual')
        """
    )
    isolated_conn.commit()

    resp = handle_query(isolated_conn, "皮秒雷射療程價格是多少？", clinic_id="3503190424")
    matching_faqs = [h for h in resp.faq_hits if h.fields["topic_key"] == "price-leak-test"]
    assert len(matching_faqs) == 1
    ans = matching_faqs[0].fields["answer"]
    assert "3000元" not in ans
    assert "5000塊" not in ans
    assert "[請致電診所確認]" in ans
