"""Phase 28 Plan 03: patient_compose 組稿模組單元測試。

驗證：
1. 直答判定（雙門檻 >=0.9/0.7、風險特徵對稱、歧義邊界 >=0.1、最小長度 >=4）
2. LLM 組稿流程（提示詞組裝、草稿隔離、模型輸出驗證與重組）
3. 各類異常降級為確定性回答（離線、空輸出、截斷、鎖佔用、驗證失敗）
4. 確定性回答萃取與 decorate_general_answer 裝飾
5. 預生成已核准項目命中直答與待審隔離
"""

import json
import pytest

from src.general.answer_compose import CTA_TEXT
from src.general.consult import GeneralConsultResult, consult_general
from src.general.patient_compose import compose_from_approved, decorate_general_answer
from src.pageindex.faq_writer import upsert_faqs
from src.pageindex.llm_client import (
    LLMEmptyOutputError,
    LLMTruncatedError,
    LocalLLMUnavailableError,
)
from src.pageindex.llm_lock import GENERATION_LOCK

WARNING = "若出現胸痛、呼吸困難或高燒超過38.5度持續3天，請立即前往急診或儘速就醫。"
FAQ_ANS_STD = f"術後初期應保持傷口通風乾燥，避免劇烈運動與碰撞拉扯，每日輕柔清潔消毒患部。{WARNING}"


def _make_found(faq_hits=None, guide_hits=None) -> GeneralConsultResult:
    return GeneralConsultResult(
        status="answered",
        red_flag_level=None,
        message="這是一般衛教資訊說明。",
        disclaimer="本資訊僅供參考，無法取代醫師親自診察。",
        faq_hits=faq_hits or [],
        guide_hits=guide_hits or [],
    )


def test_1_shortcut_direct_hit_without_llm(isolated_conn):
    """Test 1（命中直答）: 通過雙門檻、風險對稱與歧義邊界時不呼叫 llm_call，回傳文字含該 FAQ 答案、恰一個「？」、含 CTA_TEXT。"""
    q = "果凍矽膠隆乳術後日常居家清潔如何進行？"
    ans = f"果凍矽膠隆乳術後應保持傷口通風乾燥，每日以生理食鹽水輕柔拍拭並換藥。{WARNING}"
    found = _make_found(
        faq_hits=[{
            "topic_key": "p28-t1-direct",
            "question": q,
            "answer": ans,
        }]
    )

    calls = []
    def boom(prompt):
        calls.append(prompt)
        return "不應被呼叫"

    result = compose_from_approved(isolated_conn, q, found, boom)
    assert len(calls) == 0
    assert result is not None
    assert CTA_TEXT in result
    assert result.count("？") == 1
    assert "果凍矽膠" in result


def test_1b_risk_mismatch_prevents_direct_hit(isolated_conn):
    """Test 1b（風險不對稱不直答）: 問句含「三天」對 FAQ「五天」，數字不一致不直答，進入 LLM 組稿。"""
    q_user = "果凍矽膠隆乳術後三天可以洗澡嗎？"
    q_faq = "果凍矽膠隆乳術後五天可以洗澡嗎？"
    found = _make_found(
        faq_hits=[{
            "topic_key": "p28-t1b",
            "question": q_faq,
            "answer": FAQ_ANS_STD,
        }]
    )

    calls = []
    def fake_llm(prompt):
        calls.append(prompt)
        return f"答：術後三天傷口尚未完全癒合，建議以擦澡為主並保持局部乾燥清潔。\n{WARNING}\n追問：目前傷口處是否有敷料覆蓋呢？"

    result = compose_from_approved(isolated_conn, q_user, found, fake_llm)
    assert len(calls) == 1
    assert result is not None
    assert result.count("？") == 1
    assert CTA_TEXT in result


def test_1c_ambiguity_prevents_direct_hit(isolated_conn):
    """Test 1c（歧義不直答）: 兩筆已核准 FAQ 覆蓋率差距小於 0.1 時不直答，改走組稿。"""
    q_user = "果凍矽膠隆乳切口選擇與術後修復"
    found = _make_found(
        faq_hits=[
            {
                "topic_key": "p28-t1c-1",
                "question": "果凍矽膠隆乳切口選擇方式有哪些？",
                "answer": FAQ_ANS_STD,
            },
            {
                "topic_key": "p28-t1c-2",
                "question": "果凍矽膠隆乳術後修復照護要點？",
                "answer": FAQ_ANS_STD,
            },
        ]
    )

    calls = []
    def fake_llm(prompt):
        calls.append(prompt)
        return f"答：切口選擇會影響初期修復時程與疤痕位置，建議依個人身型條件由醫師評估。\n{WARNING}\n追問：您比較在意的是恢復期長短，還是疤痕位置呢？"

    result = compose_from_approved(isolated_conn, q_user, found, fake_llm)
    assert len(calls) == 1
    assert result is not None


def test_1d_query_too_short_prevents_direct_hit(isolated_conn):
    """Test 1d（查詢過短不直答）: 標準化後少於 4 字不直答。"""
    q_user = "隆乳嗎"  # 去語助詞後少於 4 字
    found = _make_found(
        faq_hits=[{
            "topic_key": "p28-t1d",
            "question": "隆乳手術術後照護注意事項？",
            "answer": FAQ_ANS_STD,
        }]
    )

    calls = []
    def fake_llm(prompt):
        calls.append(prompt)
        return f"答：隆乳手術需依據個人身形條件評估適合的材質與手術方式。\n{WARNING}\n追問：您想了解的是手術方式還是術後照護呢？"

    result = compose_from_approved(isolated_conn, q_user, found, fake_llm)
    assert len(calls) == 1
    assert result is not None


def test_2_llm_compose_and_pending_draft_isolation(isolated_conn):
    """Test 2（LLM 組稿）: 覆蓋率不足時呼叫 llm_call 一次；prompt 含已核准 FAQ 且不含 pending 草稿。"""
    # 寫入一筆 pending 狀態的草稿
    upsert_faqs(
        isolated_conn,
        [{
            "clinic_id": None,
            "topic_key": "p28-secret-pending",
            "category": "general",
            "question": "極密一般草稿問題甲乙丙丁？",
            "answer": "這是一筆未核准的機密一般草稿內容絕對不得進入prompt。",
        }],
        source_type="llm_generated",
    )

    q_user = "隆乳材質與自體脂肪豐胸的優缺點差異與術後照護要點"
    found = _make_found(
        faq_hits=[{
            "topic_key": "p28-approved-visible",
            "question": "隆乳材質比較分析？",
            "answer": f"隆乳材質包含果凍矽膠與光滑面等選擇，應依組織厚度與預期效果評估。{WARNING}",
        }]
    )

    seen_prompts = []
    def fake_llm(prompt):
        seen_prompts.append(prompt)
        return f"答：假體隆乳與自體脂肪各有適合條件，假體適合希望明顯升級者，自體脂肪適合局部修飾。\n{WARNING}\n追問：您目前較偏向假體植入還是自體脂肪評估呢？"

    res = compose_from_approved(isolated_conn, q_user, found, fake_llm)
    assert len(seen_prompts) == 1
    prompt = seen_prompts[0]
    assert "隆乳材質比較分析" in prompt
    assert "未核准的機密一般草稿內容" not in prompt
    assert res is not None
    assert CTA_TEXT in res
    assert res.count("？") == 1


def test_3_fallback_on_llm_exceptions(isolated_conn):
    """Test 3（降級）: LocalLLMUnavailableError、LLMEmptyOutputError、LLMTruncatedError 均降級為確定性回答。"""
    q_user = "隆乳手術後恢復期要多久？"
    found = _make_found(
        faq_hits=[{
            "topic_key": "p28-t3",
            "question": "隆乳手術術後恢復時程說明？",
            "answer": FAQ_ANS_STD,
        }]
    )

    for err_cls in (LocalLLMUnavailableError, LLMEmptyOutputError, LLMTruncatedError):
        def raise_err(prompt):
            raise err_cls("模擬錯誤")

        res = compose_from_approved(isolated_conn, q_user, found, raise_err)
        assert res is not None, f"{err_cls} 降級失敗"
        assert CTA_TEXT in res
        assert res.count("？") == 1
        assert "保持傷口通風乾燥" in res


def test_4_fallback_when_generation_lock_busy(isolated_conn):
    """Test 4（降級）: GENERATION_LOCK 被佔用時 llm_call 呼叫 0 次，回確定性回答。"""
    q_user = "隆乳手術後恢復期要多久？"
    found = _make_found(
        faq_hits=[{
            "topic_key": "p28-t4",
            "question": "隆乳手術術後恢復時程說明？",
            "answer": FAQ_ANS_STD,
        }]
    )

    calls = []
    def boom(prompt):
        calls.append(prompt)
        return "不應被呼叫"

    assert GENERATION_LOCK.acquire(blocking=False)
    try:
        res = compose_from_approved(isolated_conn, q_user, found, boom)
    finally:
        GENERATION_LOCK.release()

    assert len(calls) == 0
    assert res is not None
    assert CTA_TEXT in res
    assert res.count("？") == 1


def test_5_fallback_on_validation_failure(isolated_conn):
    """Test 5（驗證失敗）: 模型輸出含價格、無警訊等合規違規時降級，最終訊息不含價格。"""
    q_user = "隆乳手術後恢復期要多久？"
    found = _make_found(
        faq_hits=[{
            "topic_key": "p28-t5",
            "question": "隆乳手術術後恢復時程說明？",
            "answer": FAQ_ANS_STD,
        }]
    )

    # 包含價格「150000元」
    def price_llm(prompt):
        return f"答：費用約 150000 元，術後需保持乾燥。\n{WARNING}\n追問：您想預約諮詢嗎？"

    res = compose_from_approved(isolated_conn, q_user, found, price_llm)
    assert res is not None
    assert "150000" not in res
    assert CTA_TEXT in res
    assert res.count("？") == 1


def test_6_fallback_on_truncated_incomplete_ending(isolated_conn):
    """Test 6（截斷輸出）: 假輸出結尾停在半句「若出現胸」，is_complete_ending 失敗後降級。"""
    q_user = "隆乳手術後恢復期要多久？"
    found = _make_found(
        faq_hits=[{
            "topic_key": "p28-t6",
            "question": "隆乳手術術後恢復時程說明？",
            "answer": FAQ_ANS_STD,
        }]
    )

    def trunc_llm(prompt):
        return "答：術後應保持局部清潔通風，若出現胸"

    res = compose_from_approved(isolated_conn, q_user, found, trunc_llm)
    assert res is not None
    assert "局部清潔通風" not in res
    assert not res.endswith("若出現胸")
    assert CTA_TEXT in res
    assert res.count("？") == 1


def test_7_fallback_extracts_sentences_with_warning():
    """Test 7: 確定性降級的價值段來自已核准 FAQ 原文，組裝 2～4 句且確保包含警訊句。"""
    # 建立一個多句且警訊在末尾的 FAQ
    sents = [
        "術後第一週應每日以生理食鹽水清潔傷口。",
        "日常活動應避免劇烈提重物以防拉扯患部。",
        "穿著透氣無鋼圈內衣可減緩壓迫不適感。",
        WARNING,
    ]
    long_ans = "".join(sents)
    found = _make_found(
        faq_hits=[{
            "topic_key": "p28-t7",
            "question": "隆乳術後日常照護細節說明？",
            "answer": long_ans,
        }]
    )

    def boom(prompt):
        raise LocalLLMUnavailableError("離線")

    import sqlite3
    dummy_conn = sqlite3.connect(":memory:")
    try:
        res = compose_from_approved(dummy_conn, "照護細節", found, boom)
        assert res is not None
        assert "清潔傷口" in res
        assert "救醫" in res or "就醫" in res
        assert CTA_TEXT in res
    finally:
        dummy_conn.close()


def test_8_decorate_general_answer():
    """Test 8: decorate_general_answer 對 2.24 草稿答案附單一追問與 CTA，不改動原答案句子內容。"""
    ans = f"皮秒雷射術後角質層暫時受損，應加強保濕與防曬避免反黑。{WARNING}"
    decorated = decorate_general_answer(ans, "皮秒雷射術後保養")
    assert ans in decorated
    assert CTA_TEXT in decorated
    assert decorated.count("？") == 1

    # 若少於 2 句則安全回傳原文
    single_sent = "單一句子。"
    assert decorate_general_answer(single_sent, "問題") == single_sent


def test_9_prefill_approved_direct_hit_and_pending_isolated(isolated_conn):
    """Test 9（預生成命中）: 寫入 metadata 含 origin='patient_prefill' 的 FAQ，核准時直答，待審時完全不命中。"""
    prefill_q = "超音波拉提療程術後如何居家照護？"
    prefill_ans = f"超音波拉提術後應加強肌膚保濕防曬，一週內避免高溫三溫暖。{WARNING}"

    # 1. pending 狀態：consult_general 查不到（visible 閘門隔離），compose_from_approved 不會收到它
    upsert_faqs(
        isolated_conn,
        [{
            "clinic_id": None,
            "topic_key": "p28-prefill-test",
            "category": "general",
            "question": prefill_q,
            "answer": prefill_ans,
            "metadata": json.dumps({"origin": "patient_prefill"}),
        }],
        source_type="llm_generated",
    )
    found_pending = consult_general(isolated_conn, prefill_q)
    assert all(h.get("topic_key") != "p28-prefill-test" for h in found_pending.faq_hits)

    # 2. approved 狀態：consult_general 查得到，compose_from_approved 高度吻合直答，不呼叫 llm
    from src.pageindex.faq_review import set_review_status
    cur = isolated_conn.execute("SELECT id FROM faq_cache WHERE topic_key='p28-prefill-test'")
    row_ids = [r[0] for r in cur.fetchall()]
    set_review_status(isolated_conn, row_ids, "approved")
    found_approved = consult_general(isolated_conn, prefill_q)
    assert any(h.get("topic_key") == "p28-prefill-test" for h in found_approved.faq_hits)

    calls = []
    def boom(prompt):
        calls.append(prompt)
        return "不應被呼叫"

    res = compose_from_approved(isolated_conn, prefill_q, found_approved, boom)
    assert len(calls) == 0
    assert res is not None
    assert "超音波拉提" in res
    assert CTA_TEXT in res
