"""測試 src/general/consult.py 業務層模組。"""

import json
import sqlite3
import pytest

from src.general.consult import GeneralConsultResult, consult_general
from src.general.disclaimer import (
    ANSWERED_MESSAGE,
    DISCLAIMER_TEXT,
    EMERGENCY_MESSAGE,
    FILLER_OCCLUSION_ADDENDUM,
    NO_MATCH_MESSAGE,
    RED_FLAG_DISCLAIMER_TEXT,
    URGENT_MESSAGE,
)
from src.pageindex.faq_writer import upsert_faqs


def test_red_flag_shortcut_does_not_call_search(monkeypatch, isolated_conn):
    """紅旗短路測試：確保不呼叫任何檢索或分詞函式，直接回傳就醫指引。"""
    def fail_search(*args, **kwargs):
        raise AssertionError("不得呼叫檢索函式！")

    def fail_terms(*args, **kwargs):
        raise AssertionError("不得呼叫 extract_search_terms！")

    monkeypatch.setattr("src.general.consult.search_faq_cache", fail_search)
    monkeypatch.setattr("src.general.consult.search_text", fail_search)
    monkeypatch.setattr("src.general.consult.extract_search_terms", fail_terms)

    # Emergency: 胸痛
    res1 = consult_general(isolated_conn, "我胸口好痛")
    assert res1.status == "red_flag"
    assert res1.red_flag_level == "emergency"
    assert res1.message == EMERGENCY_MESSAGE
    assert res1.faq_hits == []
    assert res1.guide_hits == []
    assert res1.disclaimer == RED_FLAG_DISCLAIMER_TEXT

    # Urgent: 發燒三天都不退
    res2 = consult_general(isolated_conn, "發燒三天都不退")
    assert res2.status == "red_flag"
    assert res2.red_flag_level == "urgent"
    assert res2.message == URGENT_MESSAGE
    assert res2.faq_hits == []
    assert res2.guide_hits == []
    assert res2.disclaimer == RED_FLAG_DISCLAIMER_TEXT

    # E08: 填充劑血管阻塞徵兆附加句
    res3 = consult_general(isolated_conn, "打完玻尿酸鼻頭發黑")
    assert res3.status == "red_flag"
    assert res3.red_flag_level == "emergency"
    assert res3.message.startswith(EMERGENCY_MESSAGE)
    assert FILLER_OCCLUSION_ADDENDUM in res3.message


def test_red_flag_does_not_touch_connection():
    """紅旗短路測試：即使傳入已關閉的連線，仍能正常回傳（證明完全不存取 DB）。"""
    closed_conn = sqlite3.connect(":memory:")
    closed_conn.close()

    res = consult_general(closed_conn, "我胸口好痛")
    assert res.status == "red_flag"
    assert res.red_flag_level == "emergency"


def test_answered_general_faq_and_tree(isolated_conn):
    """一般問句命中測試：檢索到 general 類 FAQ 與指引樹。"""
    # 寫入 general FAQ
    faq = {
        "question": "感冒時要多喝水嗎",
        "answer": "感冒期間應補充足夠水分與充分休息，有助於身體新陳代謝。",
        "category": "general",
        "clinic_id": None,
        "topic_key": "common-cold",
    }
    upsert_faqs(isolated_conn, [faq], source_type="manual")

    # 寫入 general 樹（僅限測試複本 raw INSERT）
    cur = isolated_conn.cursor()
    cur.execute(
        """
        INSERT INTO page_index_trees (
            doc_id, category, clinic_id, version, content_version,
            summary_text, pre_op, procedure, post_op_short, maintenance,
            source_type, needs_regeneration
        ) VALUES (
            'general-cold-care', 'general', NULL, '1.0', 1,
            '感冒居家照護指引：充分休息、多喝溫水。',
            '留意體溫與精神狀態', '依症狀適度休養', '觀察發燒是否退去', '維持規律作息',
            'manual', 0
        )
        """
    )
    isolated_conn.commit()

    # 測試 FAQ 命中
    res1 = consult_general(isolated_conn, "感冒時要多喝水嗎")
    assert res1.status == "answered"
    assert res1.message == ANSWERED_MESSAGE
    assert res1.disclaimer == DISCLAIMER_TEXT
    assert len(res1.faq_hits) >= 1
    hit = res1.faq_hits[0]
    assert set(hit.keys()) == {"topic_key", "question", "answer"}
    assert hit["topic_key"] == "common-cold"
    assert "多喝水" in hit["question"]

    # 測試 Tree 命中
    res2 = consult_general(isolated_conn, "感冒居家照護")
    assert res2.status == "answered"
    assert len(res2.guide_hits) >= 1
    guide = res2.guide_hits[0]
    assert set(guide.keys()) == {
        "doc_id",
        "summary_text",
        "pre_op",
        "procedure",
        "post_op_short",
        "maintenance",
    }
    assert guide["doc_id"] == "general-cold-care"


def test_no_match_honest_response(isolated_conn):
    """無命中測試：誠實回覆 NO_MATCH_MESSAGE 與法定免責聲明。"""
    res = consult_general(isolated_conn, "完全不存在的主題哨兵詞語")
    assert res.status == "no_match"
    assert res.message == NO_MATCH_MESSAGE
    assert res.disclaimer == DISCLAIMER_TEXT
    assert res.faq_hits == []
    assert res.guide_hits == []


def test_clinic_isolation_strict(isolated_conn):
    """診所隔離測試（GENERAL-04）：確認絕不外洩診所特定資訊與藥品項目。"""
    # 寫入 special 專屬 FAQ
    special_faq = {
        "question": "感冒後能做雷射嗎",
        "answer": "感冒期間不建議雷射。診所專屬標記甲。",
        "category": "special",
        "clinic_id": "3503190424",
        "topic_key": "laser-cold",
    }
    upsert_faqs(isolated_conn, [special_faq], source_type="manual")

    queries_to_test = [
        "感冒後能做雷射嗎",
        "音波拉提",
        "營業時間",
        "乙醯胺酚",
    ]

    for q in queries_to_test:
        res = consult_general(isolated_conn, q)
        as_json = json.dumps(
            {
                "faq_hits": res.faq_hits,
                "guide_hits": res.guide_hits,
                "message": res.message,
            },
            ensure_ascii=False,
        )
        assert "診所專屬標記甲" not in as_json
        assert "3503190424" not in as_json
        assert "緻妍" not in as_json
        assert "clinic_hours" not in as_json

    # 乙醯胺酚在 drugs 表中有，但一般諮詢不查 drugs，應為 no_match
    res_drug = consult_general(isolated_conn, "乙醯胺酚")
    assert res_drug.status == "no_match"
    assert res_drug.faq_hits == []
    assert res_drug.guide_hits == []


def test_price_masking_applied_to_hits(isolated_conn):
    """價格防禦測試：即使一般問答資料庫含價格數字，回傳亦會自動遮蔽。"""
    faq_with_price = {
        "question": "感冒自費噴劑多少錢",
        "answer": "自費喉嚨噴劑費用約 1500 元，請遵照醫囑使用。",
        "category": "general",
        "clinic_id": None,
        "topic_key": "spray-price",
    }
    upsert_faqs(isolated_conn, [faq_with_price], source_type="manual")

    res = consult_general(isolated_conn, "感冒自費噴劑多少錢")
    assert res.status == "answered"
    assert len(res.faq_hits) >= 1
    answer = res.faq_hits[0]["answer"]
    assert "1500 元" not in answer
    assert "1500元" not in answer
    assert "[請致電診所確認]" in answer


def test_fts_syntax_error_handled_gracefully(isolated_conn):
    """FTS 語法錯誤容錯測試：特殊符號不導致程式崩潰。"""
    res1 = consult_general(isolated_conn, '感冒" OR *')
    assert res1.status in ("answered", "no_match")

    res2 = consult_general(isolated_conn, "AND OR NOT ( )")
    assert res2.status in ("answered", "no_match")


def test_limit_parameter_effective(isolated_conn):
    """數量限制測試：limit 參數有效截斷回傳數量。"""
    faqs = [
        {
            "question": f"一般流感照護問答{i}",
            "answer": f"流感照護重點第{i}條說明。",
            "category": "general",
            "clinic_id": None,
            "topic_key": "flu-care",
        }
        for i in range(1, 4)
    ]
    upsert_faqs(isolated_conn, faqs, source_type="manual")

    res = consult_general(isolated_conn, "一般流感照護問答", limit=2)
    assert len(res.faq_hits) <= 2


def test_consult_general_read_only_pragma(isolated_conn):
    """唯讀測試：在 PRAGMA query_only = ON 連線上執行無任何寫入錯誤。"""
    isolated_conn.execute("PRAGMA query_only = ON;")
    res = consult_general(isolated_conn, "發燒可以洗澡嗎")
    assert res.status in ("answered", "no_match")
