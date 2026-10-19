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


def test_approved_data_composes_with_cta_and_single_question(isolated_conn, monkeypatch):
    """Test 1: 已核准資料命中時 status 為 answered，含 CTA_TEXT 且恰一個「？」；compose 回 None 時退回既有 found.message。"""
    from src.pageindex.faq_writer import upsert_faqs
    from src.general.answer_compose import CTA_TEXT

    app_q = "測試專用已核准一般衛教問題甲乙丙？"
    app_ans = f"這是已核准的日常照護說明，請依指示清潔患部保持通風乾燥。{WARNING}"
    upsert_faqs(
        isolated_conn,
        [{
            "clinic_id": None,
            "topic_key": "p28-app-cons",
            "category": "general",
            "question": app_q,
            "answer": app_ans,
        }],
        source_type="manual",
    )

    r = pc.patient_consult(isolated_conn, app_q)
    assert r.status == "answered"
    assert CTA_TEXT in r.message
    assert r.message.count("？") == 1
    assert r.label is None

    # 當 compose 回 None 時，退回 found.message
    monkeypatch.setattr(pc, "compose_from_approved", lambda *args, **kwargs: None)
    r2 = pc.patient_consult(isolated_conn, app_q)
    assert r2.status == "answered"
    assert "資料庫中與您問題相關" in r2.message


def test_pending_draft_decorated_message_does_not_mutate_db_record(isolated_conn):
    """Test 3: message 含草稿答案與追問與 CTA，而 faq_cache 該草稿列的 answer 不含 CTA。"""
    from src.general.answer_compose import CTA_TEXT

    q_draft = "測試一般新題目草稿分離檢驗"
    r = pc.patient_consult(isolated_conn, q_draft, _llm_ok)
    assert r.status == "llm_general"
    assert CTA_TEXT in r.message
    assert r.label == pc.LLM_LABEL

    # 檢查資料庫列中存的 answer 不含 CTA_TEXT
    cur = isolated_conn.execute(
        "SELECT answer FROM faq_cache WHERE category='general' AND question=?", (q_draft,)
    )
    db_answer = cur.fetchone()[0]
    assert CTA_TEXT not in db_answer
    assert WARNING in db_answer


def test_max_llm_calls_is_at_most_one(isolated_conn):
    """Test 6: 整個流程呼叫 llm_call 的總次數對任何路徑皆小於等於 1。"""
    calls = []
    def counting_llm(prompt):
        calls.append(prompt)
        return _llm_ok(prompt)

    # 1. 新草稿生成路徑
    q_new = "測試呼叫次數限制題目甲"
    pc.patient_consult(isolated_conn, q_new, counting_llm)
    assert len(calls) == 1

    # 2. 同題重用路徑
    calls.clear()
    pc.patient_consult(isolated_conn, q_new, counting_llm)
    assert len(calls) == 0

    # 3. 紅旗路徑
    calls.clear()
    pc.patient_consult(isolated_conn, "胸痛無法呼吸", counting_llm)
    assert len(calls) == 0


def test_irrelevant_evidence_filtered_to_general_draft(isolated_conn):
    """Phase 28 Plan 10: 問感冒居家照顧但資料庫僅有甲溝炎 FAQ 時，過濾後無相關證據，直接進入 2.24，不呼叫組稿模型。"""
    from src.pageindex.faq_writer import upsert_faqs

    # 植入已核准之甲溝炎 FAQ（一般類）
    upsert_faqs(
        isolated_conn,
        [{
            "clinic_id": None,
            "topic_key": "paronychia-care",
            "category": "general",
            "question": "甲溝炎門診處理與日常照顧方法",
            "answer": f"甲溝炎主要是指甲邊緣軟組織發炎化膿，門診需評估是否修剪甲片。{WARNING}",
        }],
        source_type="manual",
    )
    isolated_conn.execute("UPDATE faq_cache SET review_status='approved' WHERE topic_key='paronychia-care'")
    isolated_conn.commit()

    compose_calls = []
    def _tracking_compose_llm(p):
        compose_calls.append(p)
        return "不應被呼叫"

    general_calls = []
    def _fake_general_llm(p):
        general_calls.append(p)
        return json.dumps([{
            "question": "感冒的時候可以怎麼在家照顧自己？",
            "answer": f"感冒期間應多休息、適當補充水分並維持清淡飲食。{WARNING}",
        }], ensure_ascii=False)

    q = "感冒的時候可以怎麼在家照顧自己？"
    res = pc.patient_consult(
        isolated_conn,
        q,
        llm_call=_fake_general_llm,
        compose_llm_call=_tracking_compose_llm,
    )

    # 1. 組稿模型完全不被呼叫
    assert len(compose_calls) == 0
    # 2. 進入 2.24 未審一般說明路徑
    assert res.status == "llm_general"
    assert "甲溝炎" not in res.message
    assert "發炎化膿" not in res.message
    assert "感冒期間應多休息" in res.message


def test_insufficient_output_bypasses_general_evidence_to_2_24(isolated_conn, monkeypatch):
    """Phase 28 Plan 10: 組稿模型輸出自述參考資料不足時，拋出 InsufficientEvidenceError，跳過組稿與 found.message，進入 2.24。"""
    from src.general.patient_compose import InsufficientEvidenceError

    app_q = "測試資料不足退回二點二四"
    from src.pageindex.faq_writer import upsert_faqs
    upsert_faqs(
        isolated_conn,
        [{
            "clinic_id": None,
            "topic_key": "insufficient-test-key",
            "category": "general",
            "question": app_q,
            "answer": f"這是一段一般測試回答說明。{WARNING}",
        }],
        source_type="manual",
    )
    isolated_conn.execute("UPDATE faq_cache SET review_status='approved' WHERE topic_key='insufficient-test-key'")
    isolated_conn.commit()

    # 模擬 compose_from_approved 拋出 InsufficientEvidenceError
    def _mock_compose_insufficient(*args, **kwargs):
        raise InsufficientEvidenceError("模型輸出自述資料不足")

    monkeypatch.setattr(pc, "compose_from_approved", _mock_compose_insufficient)

    general_calls = []
    def _fake_general_llm(p):
        general_calls.append(p)
        return json.dumps([{
            "question": app_q,
            "answer": f"由未審模型生成的完整一般衛教說明。{WARNING}",
        }], ensure_ascii=False)

    res = pc.patient_consult(
        isolated_conn,
        app_q,
        llm_call=_fake_general_llm,
    )

    # 必須跳過 found.message（不回傳 answered），進入 2.24 回傳 llm_general
    assert res.status == "llm_general"
    assert "由未審模型生成的完整一般衛教說明" in res.message


def test_patient_consult_followup_no_procedure_terms_when_general_only(isolated_conn):
    """驗證 2.24 未審說明與通用資料直答時，追問一律為中性，不含療程/術後詞彙。"""
    from src.general.answer_compose import PROCEDURE_ONLY_TERMS

    q = "平日如何預防感冒與維持抵抗力？"
    res = pc.patient_consult(isolated_conn, q, _llm_ok)
    assert res.status == "llm_general"
    lines = res.message.split("\n")
    assert len(lines) == 3
    fol_line = lines[1]
    assert fol_line.endswith("？")
    for term in PROCEDURE_ONLY_TERMS:
        assert term not in fol_line, f"通用說明追問不得出現療程專用詞 '{term}': {fol_line}"



