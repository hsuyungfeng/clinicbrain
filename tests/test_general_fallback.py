"""無診所資料時的一般醫學草稿生成測試（假 LLM，不呼叫真實模型）。"""

import json
import sqlite3

import pytest

from src.pageindex.general_fallback import GeneralDraftError, generate_general_draft

WARNING = "若出現胸痛、呼吸困難或高燒超過38.5度持續3天，請立即前往急診或儘速就醫。"


def _llm(question, answer):
    payload = [{"question": question, "answer": answer}]
    return lambda prompt: json.dumps(payload, ensure_ascii=False)


def _general_rows(conn, question):
    # 隔離複本來自正式庫，題目需唯一，避免與既有草稿混淆
    return conn.execute(
        "SELECT question, category, clinic_id, source_type, review_status FROM faq_cache "
        "WHERE category='general' AND question=?",
        (question,),
    ).fetchall()


def test_valid_draft_saved_as_pending_general(isolated_conn):
    q = "測試用一般醫學題目甲"
    answer = "這是一段用於測試的衛教說明文字，內容為一般醫學常識的簡要說明。" + WARNING
    result = generate_general_draft(isolated_conn, q, _llm(q, answer))
    assert result["review_status"] == "pending"
    rows = _general_rows(isolated_conn, q)
    assert rows == [(q, "general", None, "llm_generated", "pending")]


def test_price_in_answer_is_rejected_and_nothing_written(isolated_conn):
    q = "測試用一般醫學題目乙"
    answer = "這項療程費用約為1500元，術後請依醫師指示照護。" + WARNING
    with pytest.raises(GeneralDraftError):
        generate_general_draft(isolated_conn, q, _llm(q, answer))
    assert _general_rows(isolated_conn, q) == []


def test_missing_doctor_warning_is_rejected(isolated_conn):
    q = "測試用一般醫學題目丙"
    answer = "這是一段用於測試的衛教說明文字，術後恢復時間因人而異，請保持良好作息與規律生活。"
    with pytest.raises(GeneralDraftError):
        generate_general_draft(isolated_conn, q, _llm(q, answer))
    assert _general_rows(isolated_conn, q) == []


def test_model_rewritten_question_is_stored_under_original(isolated_conn):
    q = "測試用一般醫學題目丁"
    answer = "這是一段用於測試的衛教說明文字，內容為一般醫學常識的簡要說明。" + WARNING
    generate_general_draft(isolated_conn, q, _llm("模型改寫的題目", answer))
    assert _general_rows(isolated_conn, q) == [(q, "general", None, "llm_generated", "pending")]
    assert _general_rows(isolated_conn, "模型改寫的題目") == []


def test_empty_question_rejected(isolated_conn):
    with pytest.raises(GeneralDraftError):
        generate_general_draft(isolated_conn, "   ", _llm("x", "x"))


def test_empty_output_retries_once_with_no_think(isolated_conn):
    from src.pageindex.llm_client import LLMEmptyOutputError

    q = "測試用一般醫學題目戊"
    answer = "這是一段用於測試的衛教說明文字，內容為一般醫學常識的簡要說明。" + WARNING
    calls = []

    def flaky(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            raise LLMEmptyOutputError("empty")
        return _llm(q, answer)(prompt)

    result = generate_general_draft(isolated_conn, q, flaky)
    assert result["review_status"] == "pending"
    assert len(calls) == 2
    assert all("/no_think" in c for c in calls)  # 預設即關閉思考，空白時仍重試一次
