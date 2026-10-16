"""病人先答後導（Phase 26 階段一）路由測試：假 LLM，不呼叫真實模型。"""

import json

from src.general import patient_consult as pc
from src.pageindex.llm_client import LocalLLMUnavailableError

Q = "測試用罕見問題甲乙丙丁"
WARNING = "若出現胸痛、呼吸困難或高燒超過38.5度持續3天，請立即前往急診或儘速就醫。"


def _llm_ok(prompt):
    body = "這是一段用於測試的一般醫學說明文字，內容為常識性的簡要介紹。" + WARNING
    return json.dumps([{"question": Q, "answer": body}], ensure_ascii=False)


def _pending_general(conn):
    return conn.execute(
        "SELECT review_status FROM faq_cache WHERE category='general' AND question=?", (Q,)
    ).fetchall()


def test_red_flag_short_circuits_without_llm(isolated_conn):
    def boom(prompt):
        raise AssertionError("紅旗不得呼叫模型")
    r = pc.patient_consult(isolated_conn, "我現在胸痛很嚴重還呼吸困難", boom)
    assert r.status == "red_flag"
    assert r.booking_url == pc.BOOKING_URL


def test_no_data_generates_labeled_answer_and_queues_pending(isolated_conn):
    r = pc.patient_consult(isolated_conn, Q, _llm_ok)
    assert r.status == "llm_general"
    assert r.label == pc.LLM_LABEL
    assert r.booking_url == "https://doctor-toolbox.com/"
    assert _pending_general(isolated_conn) == [("pending",)]


def test_llm_unavailable_returns_fixed_text_and_writes_nothing(isolated_conn):
    def down(prompt):
        raise LocalLLMUnavailableError("down")
    r = pc.patient_consult(isolated_conn, Q, down)
    assert r.status == "no_match"
    assert r.message == pc.NO_DATA_TEXT
    assert _pending_general(isolated_conn) == []


def test_busy_returns_busy_without_llm(isolated_conn):
    def boom(prompt):
        raise AssertionError("忙碌時不得呼叫模型")
    assert pc._PATIENT_LLM_LOCK.acquire(blocking=False)
    try:
        r = pc.patient_consult(isolated_conn, Q, boom)
    finally:
        pc._PATIENT_LLM_LOCK.release()
    assert r.status == "busy"


def test_same_question_reuses_pending_draft_without_llm(isolated_conn):
    first = pc.patient_consult(isolated_conn, Q, _llm_ok)
    assert first.status == "llm_general"

    def boom(prompt):
        raise AssertionError("同題已有草稿，不得再呼叫模型")
    second = pc.patient_consult(isolated_conn, Q, boom)
    assert second.status == "llm_general"
    assert second.message == first.message
    assert _pending_general(isolated_conn) == [("pending",)]


def test_rejected_draft_is_not_regenerated(isolated_conn):
    pc.patient_consult(isolated_conn, Q, _llm_ok)
    isolated_conn.execute(
        "UPDATE faq_cache SET review_status='rejected' WHERE category='general' AND question=?", (Q,)
    )
    isolated_conn.commit()

    def boom(prompt):
        raise AssertionError("已駁回的題目不得再生成")
    r = pc.patient_consult(isolated_conn, Q, boom)
    assert r.status == "no_match"
