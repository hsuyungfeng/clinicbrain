"""
Taiwan Clinic Medical PageIndex RAG System - 全文檢索與分流模組測試
涵蓋 TASK-008 測試範疇：
- 類別 6：FTS5 trigram / LIKE 分流正確性（_use_fts 邊界測試與真實表檢索）
"""

import pytest
from src.query.search import (
    _use_fts,
    search_drugs,
    search_service_items,
    search_page_index_trees,
    FTS_MIN_CHARS,
)


# ---------------------------------------------------------------------------
# _use_fts 邊界測試
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "query,expected",
    [
        ("雷射拆線", True),       # 4 字 -> FTS5
        ("音波拉提", True),       # 4 字 -> FTS5
        ("玻尿酸", True),         # 3 字 -> FTS5
        ("123", True),           # 3 字元 -> FTS5
        ("ABC", True),           # 3 字元 -> FTS5
        ("  普拿疼  ", True),     # strip 後 3 字 -> FTS5
        ("雷射", False),         # 2 字 -> LIKE fallback
        ("拆線", False),         # 2 字 -> LIKE fallback
        ("肉毒", False),         # 2 字 -> LIKE fallback
        ("藥", False),           # 1 字 -> LIKE fallback
        ("", False),             # 0 字 -> False
        ("   ", False),          # 純空白 -> False
    ],
)
def test_use_fts_boundary(query: str, expected: bool):
    """驗證 3 字以上走 FTS5 trigram，少於 3 字走 LIKE fallback。"""
    assert _use_fts(query) == expected


# ---------------------------------------------------------------------------
# 三表真實查詢測試（涵蓋 FTS 路徑與 LIKE fallback 路徑）
# ---------------------------------------------------------------------------

def test_search_drugs_fts_path(conn):
    """測試 drugs 表走 FTS5 路徑（3+字，例如 '普拿疼'）。"""
    hits = search_drugs(conn, "普拿疼", limit=5)
    assert len(hits) > 0
    # 驗證欄位完整性
    first = hits[0]
    assert first.table == "drugs"
    assert "code" in first.fields
    assert "chinese_name" in first.fields
    assert "otc_name_chinese" in first.fields
    assert "display_name" in first.fields
    # 應命中含有「普拿疼」的 OTC 俗名藥品
    assert any("普拿疼" in (h.fields.get("otc_name_chinese") or "") for h in hits)


def test_search_drugs_like_path(conn):
    """測試 drugs 表走 LIKE fallback 路徑（2字，例如 '消炎'）。"""
    hits = search_drugs(conn, "消炎", limit=5)
    assert len(hits) > 0
    # 應在中文名或 otc 俗名中包含「消炎」
    for hit in hits:
        cname = hit.fields.get("chinese_name") or ""
        otc = hit.fields.get("otc_name_chinese") or ""
        assert "消炎" in cname or "消炎" in otc


def test_search_service_items_fts_path(conn):
    """測試 service_items 表走 FTS5 路徑（4字，例如 '雷射拆線'）。"""
    hits = search_service_items(conn, "雷射拆線", limit=5)
    assert len(hits) > 0
    first = hits[0]
    assert first.table == "service_items"
    assert "code" in first.fields
    assert "chinese_name" in first.fields
    assert "points" in first.fields
    assert "雷射" in first.fields["chinese_name"]


def test_search_service_items_like_path(conn):
    """測試 service_items 表走 LIKE fallback 路徑（2字，例如 '拆線'、'換藥'）。"""
    hits_remove_stitch = search_service_items(conn, "拆線", limit=5)
    assert len(hits_remove_stitch) > 0
    for hit in hits_remove_stitch:
        assert "拆線" in hit.fields["chinese_name"]

    hits_dressing = search_service_items(conn, "換藥", limit=5)
    assert len(hits_dressing) > 0
    for hit in hits_dressing:
        assert "換藥" in hit.fields["chinese_name"]


def test_search_page_index_trees_fts_path(conn):
    """測試 page_index_trees 表走 FTS5 路徑（例如 '音波拉提'、'玻尿酸'）。"""
    hits_hifu = search_page_index_trees(conn, "音波拉提", limit=5)
    assert len(hits_hifu) > 0
    doc_ids = [h.fields["doc_id"] for h in hits_hifu]
    assert "zhiyan-clinic-hifu-lifting" in doc_ids

    hits_filler = search_page_index_trees(conn, "玻尿酸", limit=5)
    assert len(hits_filler) > 0
    doc_ids_filler = [h.fields["doc_id"] for h in hits_filler]
    assert "zhiyan-clinic-hyaluronic-acid-filler" in doc_ids_filler


def test_search_page_index_trees_like_path(conn):
    """測試 page_index_trees 表走 LIKE fallback 路徑（2字，例如 '肉毒'）。"""
    hits_botox = search_page_index_trees(conn, "肉毒", limit=5)
    assert len(hits_botox) > 0
    doc_ids = [h.fields["doc_id"] for h in hits_botox]
    assert "zhiyan-clinic-botox-injection" in doc_ids


# ---------------------------------------------------------------------------
# 邊界與參數測試
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("empty_query", ["", "   ", "\t\n"])
def test_search_empty_queries_return_empty_list(conn, empty_query: str):
    """驗證任何空字串或純空白查詢均安全回傳空串列，不拋出 SQL 異常。"""
    assert search_drugs(conn, empty_query) == []
    assert search_service_items(conn, empty_query) == []
    assert search_page_index_trees(conn, empty_query) == []


def test_search_limit_parameter(conn):
    """驗證 limit 參數嚴格控制回傳筆數。"""
    hits = search_drugs(conn, "消炎", limit=2)
    assert len(hits) <= 2
