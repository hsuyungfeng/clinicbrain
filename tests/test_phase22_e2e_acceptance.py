#!/usr/bin/env python3
"""
tests/test_phase22_e2e_acceptance.py
Phase 22 Plan 22-03: 端到端實機驗收、對抗性邊界加固與資料庫完整性驗證
"""

import hashlib
import re
import sqlite3
from pathlib import Path
import pytest

from src.pageindex.rag_ask import (
    MAX_FAQ,
    retrieve_evidence,
    build_ask_prompt,
    ask_with_data,
)
from src.query.search import (
    search_text,
    search_faq_cache,
    search_drugs,
    search_service_items,
    search_page_index_trees,
)
from src.query.router import (
    extract_search_terms,
    _search_terms_merged,
    handle_query,
)
from src.ingestion.generate_faq import validate_single_faq

PROD_DB_PATH = Path(__file__).resolve().parent.parent / "clinic.db"
CLINIC_ID = "3503190424"
EXPECTED_DB_SHA256 = "0089ca28795fd0f0f2a41e9fa6b16f840ae794bfaf4e5597576410e9f0cf23db"


def test_paronychia_retrieval_contains_home_care():
    """驗證真實資料庫查詢「甲溝炎要怎麼照護？」：
    BM25 與多詞交集加權生效，Top 8 必包含居家護理（ID 497），且整體來源兼具門診與生活照護。
    """
    if not PROD_DB_PATH.exists():
        pytest.skip("clinic.db 不存在")

    conn = sqlite3.connect(f"file:{PROD_DB_PATH}?mode=ro", uri=True)
    try:
        context, sources = retrieve_evidence(conn, "甲溝炎要怎麼照護？", CLINIC_ID)
        assert len(sources) == MAX_FAQ
        assert MAX_FAQ == 8

        source_ids = [s["id"] for s in sources if s["type"] == "faq"]
        # ID 497 (甲溝炎在家能做哪些自我護理與家庭治療？) 必須在召回清單中
        assert 497 in source_ids, f"預期 ID 497 在召回清單中，實際來源 ID 為：{source_ids}"

        # 驗證 Context 內文包含溫水浸泡與指甲修剪衛教
        assert "溫水浸泡" in context
        assert "直邊修剪" in context
    finally:
        conn.close()


def test_paronychia_structured_response_passes_all_safety_gates():
    """驗證結構化衛教生成輸出（包含門診處置、日常照護、就醫提醒）通過全套醫療法規審查。"""
    # 模擬 LLM 依據檢索 Context 產出之高品質繁體衛教解答
    simulated_llm_output = (
        "【門診處置】\n"
        "甲溝炎急性發作時，建議由醫師門診評估指甲與甲床發炎程度 [F1]。若發炎嚴重、反覆發作或有肉芽組織增生，醫師可能評估安排微創清創或部分指甲切除處置，以減輕周圍軟組織壓迫並降低復發機會 [F1][F4]。\n\n"
        "【日常照護】\n"
        "居家照護重點在於減少局部刺激與感染風險 [F2]。日常可用溫水浸泡患處約15分鐘以軟化角質，浸泡後請輕輕拍乾並保持通風乾燥 [F2]。修剪指甲時應採水平直邊修剪，切勿剪得過短、過彎或挖剔兩側甲溝，以防指甲向內長入皮膚 [F2][F3]。平時建議穿著寬鬆透氣之鞋襪，避免雙腳受壓迫摩擦 [F2]。\n\n"
        "【就醫提醒】\n"
        "若患部出現明顯紅腫發熱、劇烈跳痛、化膿液滲出或持續擴大等感染警訊，切勿自行挑刺擠壓，應儘速就醫回診請醫師評估處置 [F1][F2]。"
    )

    # 驗證字數約 250~400 字
    char_len = len(simulated_llm_output)
    assert 250 <= char_len <= 450, f"實際字數 {char_len} 不符合預期區間"

    # 驗證通過嚴格醫療法規檢核（含劑量、價格、保證療效）
    ok, reason = validate_single_faq(
        {"question": "甲溝炎要怎麼照護？", "answer": simulated_llm_output},
        check_dosage=True,
    )
    assert ok is True, f"合規檢核未通過：{reason}"


def test_adversarial_queries_and_sql_injection_defense():
    """對抗性測試：特殊符號、未閉合引號、FTS 語法關鍵字與 SQL 注入字串均被安全防禦。"""
    if not PROD_DB_PATH.exists():
        pytest.skip("clinic.db 不存在")

    conn = sqlite3.connect(f"file:{PROD_DB_PATH}?mode=ro", uri=True)
    try:
        adversarial_inputs = [
            '"',                        # 未閉合雙引號
            '"""',                      # 多重雙引號
            "甲溝炎' OR 1=1 --",         # SQL 注入特徵
            "AND OR NOT NEAR",          # FTS5 保留運算子
            "col:val",                  # FTS5 欄位過濾語法
            "(*^%$#@!)",                # 特殊標點
            "   ",                      # 純空白
            "a" * 300,                  # 長字串
        ]

        for q in adversarial_inputs:
            # 1. 檢索單一資料表不崩潰
            hits = search_faq_cache(conn, q, limit=5, clinic_id=CLINIC_ID)
            assert isinstance(hits, list)

            # 2. 多詞合併檢索不崩潰
            merged = _search_terms_merged(search_faq_cache, conn, [q], limit=5, clinic_id=CLINIC_ID)
            assert isinstance(merged, list)

            # 3. 統一 handle_query 不崩潰
            resp = handle_query(conn, q, clinic_id=CLINIC_ID, limit=5)
            assert resp is not None
    finally:
        conn.close()


def test_search_text_extra_where_with_rowid_no_ambiguity():
    """驗證 extra_where 中引用 rowid 時，JOIN _fts 子查詢無歧義解析。"""
    if not PROD_DB_PATH.exists():
        pytest.skip("clinic.db 不存在")

    conn = sqlite3.connect(f"file:{PROD_DB_PATH}?mode=ro", uri=True)
    try:
        hits = search_text(
            conn,
            table="faq_cache",
            fts_table="faq_cache_fts",
            query="甲溝炎",
            select_columns=("id", "question", "answer"),
            like_columns=("question", "answer"),
            limit=5,
            extra_where="rowid > 0",
        )
        assert len(hits) >= 1
    finally:
        conn.close()


def test_web_ui_ask_rendering_and_xss_protection():
    """驗證前端靜態資源包含 Phase 22 結構化衛教排版樣式，且杜絕 XSS 注入風險。"""
    app_js_path = Path(__file__).resolve().parent.parent / "src" / "web" / "static" / "app.js"
    style_css_path = Path(__file__).resolve().parent.parent / "src" / "web" / "static" / "style.css"

    js_code = app_js_path.read_text(encoding="utf-8")
    css_code = style_css_path.read_text(encoding="utf-8")

    # 驗證 CSS 包含結構化標籤與網格樣式
    assert ".ask-answer-structured" in css_code
    assert ".ask-para" in css_code
    assert ".ask-section-tag" in css_code
    assert ".ask-src-grid" in css_code
    assert ".ask-src-item" in css_code

    # 驗證 JS 實作結構化段落處理
    assert "ask-answer-structured" in js_code
    assert "ask-section-tag" in js_code
    assert "ask-src-grid" in js_code

    # 驗證提問區塊嚴格零 HTML 注入
    ask_section = js_code[js_code.index("// 7. 向 LLM 提問"):]
    assert not re.search(r"innerHTML|insertAdjacentHTML|document\.write|outerHTML|eval\(", ask_section)


def test_db_sha256_unmodified():
    """驗證正式庫 clinic.db SHA-256 恆定未變，完全零資料污染。"""
    if not PROD_DB_PATH.exists():
        pytest.skip("clinic.db 不存在")

    h = hashlib.sha256()
    with open(PROD_DB_PATH, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    current_sha256 = h.hexdigest()

    assert current_sha256 == EXPECTED_DB_SHA256, (
        f"正式資料庫 SHA-256 遭改動！\n預期：{EXPECTED_DB_SHA256}\n實際：{current_sha256}"
    )
