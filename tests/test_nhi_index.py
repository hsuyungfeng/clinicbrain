"""單元測試：健保 1-400 大疾病目錄檢索與 LLM 選取模組。"""

import sqlite3
import pytest
from src.query.nhi_index import search_nhi_catalog, get_nhi_entry, format_nhi_context_for_llm


@pytest.fixture
def db_conn():
    conn = sqlite3.connect("clinic.db")
    yield conn
    conn.close()


def test_search_nhi_catalog_fts(db_conn):
    """測試 FTS5 3 字以上關鍵字檢索。"""
    hits = search_nhi_catalog(db_conn, "三叉神經痛", limit=5)
    assert len(hits) > 0
    names = [h["name"] for h in hits]
    assert any("三叉神經痛" in name for name in names)


def test_search_nhi_catalog_short_query(db_conn):
    """測試小於 3 字之 LIKE 備援檢索。"""
    hits = search_nhi_catalog(db_conn, "感冒", limit=5)
    assert len(hits) > 0
    assert any("感冒" in h["name"] or any("感冒" in k for k in h["keywords"]) for h in hits)


def test_get_nhi_entry(db_conn):
    """測試編號與 ID 查詢。"""
    entry_by_num = get_nhi_entry(db_conn, 201)
    assert entry_by_num is not None
    assert "哮吼" in entry_by_num["name"]

    entry_by_id = get_nhi_entry(db_conn, "W201")
    assert entry_by_id is not None
    assert entry_by_id["index_no"] == 201


def test_format_nhi_context_for_llm(db_conn):
    """測試 LLM 上下文組裝格式。"""
    hits = search_nhi_catalog(db_conn, "牙隱裂", limit=2)
    assert len(hits) > 0
    ctx = format_nhi_context_for_llm(hits)
    assert "【健保基層門診 1-400 疾病參考索引】:" in ctx
    assert "牙齒隱裂症候群" in ctx
