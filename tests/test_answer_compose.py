"""純函式組稿與截斷防護模組單元測試 (Phase 28 Plan 02 Task 1)。"""

import pytest

from src.general import answer_compose as ac
from src.ingestion.medical_safety import has_doctor_warning


WARNING_SENT = "若出現胸痛、呼吸困難或高燒超過38.5度持續3天，請立即前往急診就醫。"


def test_split_sentences():
    """驗證 split_sentences 能依句末標點切分並保留標點，空字串回空清單。"""
    assert ac.split_sentences("") == []
    assert ac.split_sentences("   ") == []

    text = "第一句說明。第二句說明！第三句說明？第四句說明；第五句換行\n"
    sents = ac.split_sentences(text)
    assert len(sents) == 5
    assert sents[0] == "第一句說明。"
    assert sents[1] == "第二句說明！"
    assert sents[2] == "第三句說明？"
    assert sents[3] == "第四句說明；"
    assert sents[4].strip() == "第五句換行"


def test_is_complete_ending():
    """驗證 is_complete_ending 判定完整句尾與半句截斷。"""
    assert ac.is_complete_ending("") is False
    assert ac.is_complete_ending("   ") is False
    assert ac.is_complete_ending("若出現胸") is False
    assert ac.is_complete_ending("術後請注意休息，") is False
    assert ac.is_complete_ending("正常說明文字。") is True
    assert ac.is_complete_ending("請儘速就醫！") is True
    assert ac.is_complete_ending("需要進一步評估嗎？") is True
    assert ac.is_complete_ending("（請遵照醫囑指示）") is True
    assert ac.is_complete_ending("「請洽專業醫師」") is True


def test_clip_at_sentence_within_limit():
    """長度內原文不變。"""
    text = "短句子說明。第二句。"
    assert ac.clip_at_sentence(text, 100) == text


def test_clip_at_sentence_never_outputs_half_sentence():
    """超出長度時只輸出完整句，永不輸出半句或省略號。"""
    text = "第一句內容很完整。" + "第二句內容也很完整。" + "第三句內容同樣很完整。"
    clipped = ac.clip_at_sentence(text, 25)
    assert clipped.endswith("。")
    assert "…" not in clipped
    assert "..." not in clipped
    assert len(clipped) <= 25


def test_clip_at_sentence_preserves_doctor_warning_at_end():
    """600 字超長答案最後一句為警訊句時，警訊句優先保留且不輸出半句。"""
    padding = "這是用於填充長度的說明句子，請病患安心靜養。" * 15  # 約 330 字
    full_text = padding + WARNING_SENT
    assert len(full_text) > 300
    assert has_doctor_warning(WARNING_SENT)

    clipped = ac.clip_at_sentence(full_text, 150)
    assert len(clipped) <= 150
    assert WARNING_SENT in clipped, "警訊句必須優先被保留在截斷結果中"
    assert clipped.endswith("。")
    assert "…" not in clipped


def test_clip_at_sentence_oversized_single_sentence_returns_empty():
    """單一句子超過 limit 時回傳空字串。"""
    long_single = "這是一句完全沒有任何標點符號的超級長句子超級長句子超級長句子"
    assert ac.clip_at_sentence(long_single, 10) == ""


def test_classify_intent():
    """驗證意圖分類。"""
    assert ac.classify_intent("隆乳手術後需要多久恢復期？") == "recovery"
    assert ac.classify_intent("這個療程有什麼風險或併發症嗎？") == "risk"
    assert ac.classify_intent("我有高血壓體質適合做這個嗎？") == "suitable"
    assert ac.classify_intent("出現什麼症狀要不要就醫？") == "when_to_see_doctor"
    assert ac.classify_intent("水飛梭是什麼原理介紹一下？") == "what"
    assert ac.classify_intent("今天天氣真好") == "other"


def test_default_followups_validity():
    """驗證預設追問常數表六類皆合法：恰一個「？」、無網址、無數字。"""
    intents = ["what", "recovery", "risk", "suitable", "when_to_see_doctor", "other"]
    for it in intents:
        f = ac.DEFAULT_FOLLOWUPS.get(it)
        assert f is not None, f"缺少 {it} 的預設追問"
        assert f.count("？") == 1, f"{it} 預設追問必須恰一個問號"
        assert f.endswith("？")
        assert "http" not in f
        ok, reason = ac.validate_composed("價值回答測試句一。" + WARNING_SENT, f)
        assert ok, f"預設追問未通過驗證: {reason}"


def test_cta_text_has_no_url_and_no_numbers():
    """驗證 CTA_TEXT 不含網址與數字。"""
    assert "http" not in ac.CTA_TEXT
    assert "www" not in ac.CTA_TEXT
    import re
    assert not re.search(r"\d", ac.CTA_TEXT), "CTA_TEXT 不得包含阿拉伯數字"


def test_parse_model_output():
    """驗證模型輸出解析與 think 標籤清理。"""
    raw = "<think>思考過程123</think>答：這是第一句回答。這是第二句警訊。\n追問：您比較在意哪一點呢？"
    val, fol = ac.parse_model_output(raw)
    assert val == "這是第一句回答。這是第二句警訊。"
    assert fol == "您比較在意哪一點呢？"

    # 無標記時整段為 value
    raw_no_tag = "這是整段說明文字直接輸出。"
    v2, f2 = ac.parse_model_output(raw_no_tag)
    assert v2 == raw_no_tag
    assert f2 is None


def test_assemble_answer_structure_and_single_question_mark():
    """組裝結果恆為：2～4 句價值句、恰一個追問、預約邀請。多追問只留第一個。"""
    val = "第一句說明。" + "第二句說明。" + "第三句說明。" + "第四句說明。" + WARNING_SENT
    fol = "您想要了解費用嗎？還是想要看案例？"  # 兩個問號

    assembled = ac.assemble_answer(val, fol, "what")
    assert assembled is not None

    # 必須恰好一個問號（多追問只留第一個）
    assert assembled.count("？") == 1
    assert "您想要了解費用嗎？" in assembled
    assert "還是想要看案例？" not in assembled

    # 包含警訊句與 CTA
    assert WARNING_SENT in assembled
    assert ac.CTA_TEXT in assembled

    # 檢查價值句上限（4 句）
    # 組裝前價值段有 5 句，組裝後必須截為最多 4 句且包含警訊句
    val_part = assembled.split("您想要了解費用嗎？")[0]
    val_sents = ac.split_sentences(val_part)
    assert 2 <= len(val_sents) <= 4
    assert any(has_doctor_warning(s) for s in val_sents)


def test_assemble_answer_too_short_returns_none():
    """價值句少於 2 句時回傳 None，不硬湊。"""
    val = "只有一句話。"
    assert ac.assemble_answer(val, "追問一句？", "what") is None


def test_validate_composed():
    """驗證 validate_composed 檢核價值段與追問段。追問含時間數字不被誤攔。"""
    good_val = "傷口保持清潔乾燥。" + WARNING_SENT
    good_fol_with_num = "您目前的不適症狀已經持續超過3天了嗎？"

    ok, reason = ac.validate_composed(good_val, good_fol_with_num)
    assert ok, f"合法的追問含數字不應被誤攔: {reason}"

    # 價值段缺警訊句 -> 失敗
    bad_val_no_warn = "傷口保持清潔乾燥即可，請多休息。"
    ok2, reason2 = ac.validate_composed(bad_val_no_warn, good_fol_with_num)
    assert not ok2
    assert "警訊" in reason2

    # 追問段含價格 -> 失敗
    bad_fol_price = "這項療程大約只要1500元您能接受嗎？"
    ok3, reason3 = ac.validate_composed(good_val, bad_fol_price)
    assert not ok3
    assert "金額" in reason3 or "價格" in reason3


def test_build_compose_prompt():
    """驗證提示組裝格式與關鍵規則要求。"""
    evidence = ["[F1] 術後衛教說明", "[T1] 處置前評估說明"]
    prompt = ac.build_compose_prompt("隆乳術後保養", evidence, "recovery")
    assert "思考過程請保持簡潔" in prompt
    assert "繁體中文" in prompt
    assert "答：" in prompt
    assert "追問：" in prompt
    assert "[F1]" in prompt
    assert "[T1]" in prompt
    assert "不要輸出 JSON" in prompt


def test_default_followup_other_neutral():
    """驗證 other 類別預設追問為中性用語，不假設為療程，且通過合規檢驗。"""
    other_fol = ac.DEFAULT_FOLLOWUPS["other"]
    assert "療程" not in other_fol
    assert other_fol == "您目前是否有特定的困擾部位，或想先了解哪方面的照護方式？"
    ok, err = ac._validate_followup_text(other_fol)
    assert ok, f"預設追問檢驗失敗: {err}"


def test_build_compose_prompt_warning_rule():
    """驗證 build_compose_prompt 無錯字且提供通過 has_doctor_warning 檢驗之示範警訊句。"""
    prompt = ac.build_compose_prompt("測試題目", [], "other")
    assert "一工具體" not in prompt, "prompt 內不得包含錯字『一工具體』"
    assert "一句具體" in prompt
    # 驗證 prompt 內提示詞含有示範警訊句且通過 has_doctor_warning 檢查
    demo_sentence = "若傷口出現持續紅腫或化膿，請盡速回診尋求醫師評估。"
    assert demo_sentence in prompt
    assert has_doctor_warning(demo_sentence)


def test_general_followups_keys_and_validity():
    """驗證 GENERAL_FOLLOWUPS 鍵與 DEFAULT_FOLLOWUPS 一致，且每句皆無療程術語。"""
    assert hasattr(ac, "GENERAL_FOLLOWUPS"), "必須定義 GENERAL_FOLLOWUPS"
    assert hasattr(ac, "PROCEDURE_ONLY_TERMS"), "必須定義 PROCEDURE_ONLY_TERMS"
    assert set(ac.GENERAL_FOLLOWUPS.keys()) == set(ac.DEFAULT_FOLLOWUPS.keys())

    for k, text in ac.GENERAL_FOLLOWUPS.items():
        assert text.count("？") == 1, f"GENERAL_FOLLOWUPS[{k}] 必須恰一個問號"
        assert ac.is_complete_ending(text), f"GENERAL_FOLLOWUPS[{k}] 必須為完整句結尾"
        ok, reason = ac._validate_followup_text(text)
        assert ok, f"GENERAL_FOLLOWUPS[{k}] 合規失敗: {reason}"
        for term in ac.PROCEDURE_ONLY_TERMS:
            assert term not in text, f"GENERAL_FOLLOWUPS[{k}] 不得包含療程術語 '{term}': {text}"


def test_assemble_answer_scope_behavior():
    """驗證 assemble_answer 依 scope 選用追問表，預設維持 procedure。"""
    val = "傷口保持清潔乾燥。" + WARNING_SENT

    # 1. scope='general' 取 GENERAL_FOLLOWUPS
    ans_general = ac.assemble_answer(val, None, "recovery", scope="general")
    assert ans_general is not None
    assert ac.GENERAL_FOLLOWUPS["recovery"] in ans_general
    assert "術後" not in ans_general.split("\n")[1]

    # 2. scope 省略時（預設）維持 procedure 行為（DEFAULT_FOLLOWUPS）
    ans_default = ac.assemble_answer(val, None, "recovery")
    ans_proc = ac.assemble_answer(val, None, "recovery", scope="procedure")
    assert ans_default == ans_proc
    assert ac.DEFAULT_FOLLOWUPS["recovery"] in ans_default
    assert "術後" in ans_default

    # 3. 未知 scope 視同 procedure
    ans_unknown = ac.assemble_answer(val, None, "recovery", scope="unrecognized_scope")
    assert ans_unknown == ans_proc


def test_assemble_answer_model_followup_procedure_terms_blocked_in_general():
    """驗證 scope='general' 時模型自帶追問若含療程詞彙則退回中性追問；scope='procedure' 則保留。"""
    val = "傷口保持清潔乾燥。" + WARNING_SENT
    model_fol_procedure = "您想了解術後照護的哪個部分？"

    # scope='general' 時模型自帶療程追問被攔截，退回 GENERAL_FOLLOWUPS
    ans_gen = ac.assemble_answer(val, model_fol_procedure, "recovery", scope="general")
    assert ans_gen is not None
    assert model_fol_procedure not in ans_gen
    assert ac.GENERAL_FOLLOWUPS["recovery"] in ans_gen

    # scope='procedure' 時模型自帶療程追問被保留
    ans_proc = ac.assemble_answer(val, model_fol_procedure, "recovery", scope="procedure")
    assert ans_proc is not None
    assert model_fol_procedure in ans_proc

    # scope='general' 時完全中性的模型追問正常保留
    model_fol_neutral = "您比較在意哪方面的生活調整呢？"
    ans_gen_neutral = ac.assemble_answer(val, model_fol_neutral, "recovery", scope="general")
    assert ans_gen_neutral is not None
    assert model_fol_neutral in ans_gen_neutral

    assert ans_gen.count("？") == 1
    assert ans_gen.endswith(ac.CTA_TEXT)


def test_suggest_followup_chips_complementary_and_compliant():
    """驗證 suggest_followup_chips 回傳 2 個互補意圖追問且皆符合合規規範。"""
    chips_proc = ac.suggest_followup_chips("what", scope="procedure")
    assert len(chips_proc) == 2
    assert ac.DEFAULT_FOLLOWUPS["what"] not in chips_proc
    assert chips_proc[0] == ac.DEFAULT_FOLLOWUPS["recovery"]
    assert chips_proc[1] == ac.DEFAULT_FOLLOWUPS["suitable"]

    chips_gen = ac.suggest_followup_chips("recovery", scope="general")
    assert len(chips_gen) == 2
    assert ac.GENERAL_FOLLOWUPS["recovery"] not in chips_gen
    for chip in chips_gen:
        ok, err = ac._validate_followup_text(chip)
        assert ok, err
        for term in ac.PROCEDURE_ONLY_TERMS:
            assert term not in chip





# ---- 2.5 互動追問膠囊：suggest_followup_chips ----

ALL_INTENTS = ["what", "recovery", "risk", "suitable", "when_to_see_doctor", "other"]


@pytest.mark.parametrize("intent", ALL_INTENTS)
@pytest.mark.parametrize("scope", ["procedure", "general"])
def test_suggest_followup_chips_returns_two_compliant_questions(intent, scope):
    """每個意圖與範圍皆回傳 2 句，且取自合規追問表，不含當前意圖的追問句。"""
    chips = ac.suggest_followup_chips(intent, scope=scope)
    table = ac.GENERAL_FOLLOWUPS if scope == "general" else ac.DEFAULT_FOLLOWUPS
    assert len(chips) == 2
    assert all(c in table.values() for c in chips)
    assert table.get(intent) not in chips or intent == "other"


def test_suggest_followup_chips_excludes_current_intent_question():
    chips = ac.suggest_followup_chips("recovery", scope="procedure")
    assert ac.DEFAULT_FOLLOWUPS["recovery"] not in chips


def test_suggest_followup_chips_unknown_intent_falls_back_to_other():
    assert ac.suggest_followup_chips("不存在的意圖") == ac.suggest_followup_chips("other")
    assert ac.suggest_followup_chips("") == ac.suggest_followup_chips("other")


def test_suggest_followup_chips_is_pure_and_deterministic():
    assert ac.suggest_followup_chips("risk") == ac.suggest_followup_chips("risk")
