"""
Taiwan Clinic Medical PageIndex RAG System - 路由模組測試
涵蓋 TASK-008 測試範疇：
- 類別 1：extract_search_terms() 固定回歸案例
- 類別 2：價格遮罩 mask_prices() 格式與防禦測試
- 類別 3：special / general 路由隔離與合規防漏測試
"""

import pytest
from src.query.router import (
    extract_search_terms,
    mask_prices,
    classify,
    handle_query,
    _PRICE_MASK,
)

# ---------------------------------------------------------------------------
# 類別 1：extract_search_terms() 固定回歸案例
# 跨 TASK-005, TASK-006, TASK-007 三次驗證，順序與詞彙完全鎖定
# ---------------------------------------------------------------------------

KNOWN_GOOD_EXTRACT_TERMS = {
    "診所幾點開門？": ["診所幾點開門", "開門", "幾點"],
    "音波拉提會痛嗎？": ["音波拉提", "拉提", "音波"],
    "乙醯胺酚是什麼藥？": ["乙醯胺酚"],
    "感冒吃什麼好？": ["感冒吃"],
    "雷射拆線": ["雷射拆線", "雷射", "拆線"],
    "請問玻尿酸填充可以維持多久？": ["玻尿酸填充", "玻尿酸", "填充", "維持"],
    # 通用詞（術後/回診）降到具體詞之後
    "術後回診要注意什麼": ["術後回診", "術後", "回診"],
}


def test_generic_terms_ranked_after_specific_terms():
    """低資訊通用詞（維持/回診/術後…）必須排在具體詞之後，但仍保留在結果中。"""
    terms = extract_search_terms("肉毒術後回診")
    assert terms.index("肉毒") < terms.index("術後")
    assert terms.index("肉毒") < terms.index("回診")
    assert extract_search_terms("維持多久？") == ["維持"]


@pytest.mark.parametrize("query,expected_terms", KNOWN_GOOD_EXTRACT_TERMS.items())
def test_extract_search_terms_known_good_regression(query: str, expected_terms: list[str]):
    """驗證已知正確的搜尋關鍵詞擷取結果，順序與內容必須逐字一致。"""
    actual_terms = extract_search_terms(query)
    assert actual_terms == expected_terms, f"查詢 '{query}' 擷取詞不符：預期 {expected_terms}，實際 {actual_terms}"


def test_extract_search_terms_empty_or_punctuation():
    """邊界測試：純標點符號或無法分詞的輸入，應安全 fallback 為原始輸入。"""
    assert extract_search_terms("？？？") == ["？？？"]
    assert extract_search_terms("") == [""]


# ---------------------------------------------------------------------------
# 類別 2：價格遮罩 mask_prices()
# 驗證所有法定價格格式被遮罩為 [請致電診所確認]，非價格文字完整保留
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "price_text,expected_masked",
    [
        ("1500元", _PRICE_MASK),
        ("療程費用3000塊", f"療程費用{_PRICE_MASK}"),
        ("費用NT$500", f"費用{_PRICE_MASK}"),
        ("費用NT$ 500", f"費用{_PRICE_MASK}"),
        ("掛號費$800", f"掛號費{_PRICE_MASK}"),
        (
            "原價1500元，特價NT$800，加購價$300或200塊",
            f"原價{_PRICE_MASK}，特價{_PRICE_MASK}，加購價{_PRICE_MASK}或{_PRICE_MASK}",
        ),
    ],
)
def test_mask_prices_formats(price_text: str, expected_masked: str):
    """驗證中英文各種價格寫法均能被正確遮罩。"""
    assert mask_prices(price_text) == expected_masked


def test_mask_prices_normal_text_unchanged():
    """驗證一般不含價格的醫療衛教與數字描述不被誤殺。"""
    normal_text = "音波拉提療程術後需注意保濕與防曬，術後7天內避免高溫，每日服用2次。"
    assert mask_prices(normal_text) == normal_text


def test_mask_prices_none_and_empty():
    """邊界測試：None 與空字串輸入不拋出例外，安全回傳原值。"""
    assert mask_prices("") == ""
    assert mask_prices(None) is None


# ---------------------------------------------------------------------------
# 類別 3：special / general 路由隔離
# 驗證診所營運/療程問題走 special，一般健康常識走 general，
# 且 general 查詢絕不滲漏任何診所專屬資訊（合規防漏）
# ---------------------------------------------------------------------------

SPECIAL_QUERIES = [
    ("音波拉提會痛嗎？", ["音波", "拉提"]),
    ("請問玻尿酸填充可以維持多久？", ["玻尿酸", "填充"]),
    ("診所幾點開門？", ["開門", "幾點"]),
    ("請問診所有什麼術前注意事項？", ["術前"]),
]

GENERAL_QUERIES = [
    "高血壓可以吃什麼水果？",
    "感冒要多喝水嗎？",
    "頭痛想吐該看哪一科？",
]


@pytest.mark.parametrize("query,expected_keywords", SPECIAL_QUERIES)
def test_classify_special_queries(query: str, expected_keywords: list[str]):
    """驗證醫美特定療程與診所營運問題正確分類為 special。"""
    result = classify(query)
    assert result.route == "special"
    for kw in expected_keywords:
        assert kw in result.matched_keywords


@pytest.mark.parametrize("query", GENERAL_QUERIES)
def test_classify_general_queries(query: str):
    """驗證一般醫學衛教常識問題正確分類為 general，無匹配關鍵字。"""
    result = classify(query)
    assert result.route == "general"
    assert result.matched_keywords == []


def test_handle_query_special_clinic_ops(conn):
    """驗證 special 診所營運查詢（如開門時間）會完整帶出診所資訊與門診時段。"""
    res = handle_query(conn, "診所幾點開門？", clinic_id="3503190424")
    assert res.route == "special"
    assert res.clinic_info is not None
    assert res.clinic_info["clinic_id"] == "3503190424"
    assert "緻妍" in res.clinic_info["name"]
    assert len(res.clinic_hours) == 7


def test_handle_query_special_procedure_and_custom_notes(conn):
    """驗證 special 療程查詢命中 PageIndex 樹時，會帶出療程資訊與診所通用段落備註。"""
    res = handle_query(conn, "音波拉提會痛嗎？", clinic_id="3503190424")
    assert res.route == "special"
    assert len(res.page_index_hits) > 0
    # 命中音波拉提推理樹
    doc_ids = [hit.fields.get("doc_id") for hit in res.page_index_hits]
    assert "hifu-lifting" in doc_ids
    # 帶出診所層級通用備註
    assert isinstance(res.clinic_custom_notes, dict)
    assert len(res.clinic_custom_notes) > 0
    assert "pre_op" in res.clinic_custom_notes


@pytest.mark.parametrize("query", GENERAL_QUERIES)
def test_handle_query_general_strict_isolation(conn, query: str):
    """核心合規測試：任何 general 查詢結果，絕不包含診所專屬資訊。
    clinic_info 必須為 None、clinic_hours 必須為空串列、clinic_custom_notes 必須為空字典。
    """
    res = handle_query(conn, query)
    assert res.route == "general", f"查詢 '{query}' 應為 general 路由"
    assert res.clinic_info is None, f"合規違規：general 查詢 '{query}' 洩漏了 clinic_info"
    assert res.clinic_hours == [], f"合規違規：general 查詢 '{query}' 洩漏了 clinic_hours"
    assert res.clinic_custom_notes == {}, f"合規違規：general 查詢 '{query}' 洩漏了 clinic_custom_notes"


def test_handle_query_special_missing_clinic_id_raises_value_error(conn):
    """TASK-02: 驗證 special 路由查詢若涉及診所專屬資訊但未傳入 clinic_id 時，拋出明確之 ValueError。"""
    # 診所營運查詢（需 clinic_info / clinic_hours）
    with pytest.raises(ValueError, match="special 路由查詢診所營運資訊需要提供 clinic_id"):
        handle_query(conn, "診所幾點開門？")

    # 療程與備註查詢（需 clinic_custom_notes）
    with pytest.raises(ValueError, match="special 路由查詢診所通用備註需要提供 clinic_id"):
        handle_query(conn, "音波拉提會痛嗎？")
