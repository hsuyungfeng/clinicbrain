"""
Taiwan Clinic Medical PageIndex RAG System - S/O/A/P 切分與去識別化測試
涵蓋 Phase 14 Plan 02 (D-05, D-06, D-07):
- parse_soap_text 中英文標記切分與 fallback
- extract_general_medical_insights 一般醫學資料分析與標籤萃取
- deidentify_text 台灣個資與價格二次清洗
- generate_patient_token 代號衍生與跨診所隔離
"""

import pytest
from src.soap.section_parser import parse_soap_text, extract_general_medical_insights
from src.soap.deid import deidentify_text, generate_patient_token, validate_taiwan_id


def test_section_parser_standard_chinese_markers():
    """測試中文臨床常見標記正確切分 S/O/A/P 四段。"""
    raw_transcript = (
        "主訴：病患主訴發燒三天伴隨劇烈咳嗽與黃濃痰\n"
        "理學檢查：咽喉紅腫，聽診肺部有囉音\n"
        "診斷：急性支氣管炎\n"
        "處置：開立化痰藥物與抗生素，衛教多飲水注意保暖"
    )

    parsed = parse_soap_text(raw_transcript)
    assert "發燒三天" in parsed["subjective"]
    assert "咽喉紅腫" in parsed["objective"]
    assert parsed["assessment"] == "急性支氣管炎"
    assert "化痰藥物" in parsed["plan"]
    assert parsed["raw_text"] == raw_transcript


def test_section_parser_english_abbreviations_and_multiline():
    """測試英文縮寫與多行內容切分。"""
    raw = (
        "S: Sore throat for 2 days\n"
        "fever noted yesterday\n"
        "O: Tonsil enlargement\n"
        "A: Acute tonsillitis\n"
        "P: Amoxicillin prescribed\n"
        "Follow up in 3 days"
    )

    parsed = parse_soap_text(raw)
    assert "Sore throat" in parsed["subjective"]
    assert "fever noted" in parsed["subjective"]
    assert "Tonsil enlargement" in parsed["objective"]
    assert "Acute tonsillitis" in parsed["assessment"]
    assert "Follow up in 3 days" in parsed["plan"]


def test_section_parser_no_markers_fallback():
    """測試純文字無段落標記時全數 fallback 歸入 subjective。"""
    raw = "病患昨晚開始頭暈眼花，胃部脹痛想吐，沒有腹瀉。"
    parsed = parse_soap_text(raw)
    assert parsed["subjective"] == raw
    assert parsed["objective"] == ""
    assert parsed["assessment"] == ""
    assert parsed["plan"] == ""
    assert parsed["raw_text"] == raw


def test_extract_general_medical_insights():
    """測試從 SOAP 文字中擷取一般醫學疾病、症狀、照護要點與建議標籤。"""
    soap = {
        "subjective": "患者出現畏寒、高燒38.8度與嚴重喉嚨痛。",
        "objective": "咽喉黏膜紅斑，體溫高。",
        "assessment": "流感合併急性咽喉炎",
        "plan": "開立退燒藥。衛教事項：請多喝水、充分休息，避免油膩辛辣飲食。",
    }

    insights = extract_general_medical_insights(soap)
    assert insights["is_general_relevant"] is True
    assert "流感" in insights["conditions"]
    assert "急性咽喉炎" in insights["conditions"]
    assert "發燒" in insights["symptoms"] or "喉嚨痛" in insights["symptoms"]
    assert any("多喝水" in pt for pt in insights["home_care"])
    assert "流感" in insights["suggested_tags"]


def test_taiwan_id_validation():
    """測試台灣身分證字號演算法檢驗。"""
    assert validate_taiwan_id("A123456789") is True  # 台北市男性的標準合法示範號
    assert validate_taiwan_id("A123456788") is False  # 錯誤檢查碼
    assert validate_taiwan_id("invalid") is False


def test_deidentify_taiwan_personal_info():
    """測試台灣身分證、手機、市話與姓名標籤遮蔽。"""
    text = (
        "病患姓名：陳大明，身分證字號 A123456789，"
        "聯絡電話 0912-345-678，市話 02-23456789。"
        "就診主訴持續發燒。"
    )

    cleaned = deidentify_text(text)
    assert "A123456789" not in cleaned
    assert "[身分證已遮蔽]" in cleaned
    assert "0912-345-678" not in cleaned
    assert "[電話已遮蔽]" in cleaned
    assert "02-23456789" not in cleaned
    assert "陳大明" not in cleaned
    assert "[姓名已遮蔽]" in cleaned
    assert "就診主訴持續發燒。" in cleaned


def test_deidentify_price_masking():
    """測試個資去識別化同時整合價格清洗。"""
    text = "病患自費注射營養針劑，費用 3500元 整，NT$ 1,200 診察費。"
    cleaned = deidentify_text(text)
    assert "3500元" not in cleaned
    assert "1,200" not in cleaned
    assert "[請致電診所確認]" in cleaned


def test_generate_patient_token_deterministic_and_isolated(monkeypatch):
    """測試 patient_token 同診所確定性與跨診所隔離。"""
    monkeypatch.setenv("CLINICBRAIN_DEID_KEY", "test-deid-key")
    t1 = generate_patient_token("PID-999", "3503190424")
    t2 = generate_patient_token("PID-999", "3503190424")
    t3 = generate_patient_token("PID-999", "OTHER-CLINIC")

    assert t1.startswith("PTK-")
    assert t1 == t2  # 相同診所相同病患代號 -> 相同 token
    assert t1 != t3  # 跨診所隔離 -> 不同 token


# ==============================================================================
# Category A: Regression Guard Tests (守門測試 1~5)
# ==============================================================================

def test_guard_chinese_negation_in_narrative_stays_subjective():
    """守門測試 1：敘述句內包含否定詞時仍整句保留於 subjective。"""
    raw = "病患主訴未做過任何身體檢查與評估，僅覺頭痛"
    parsed = parse_soap_text(raw)
    assert parsed["subjective"] == raw
    assert parsed["objective"] == ""
    assert parsed["assessment"] == ""
    assert parsed["plan"] == ""


def test_guard_pure_audio_transcript_fallback():
    """守門測試 2：無標記逐字稿乾淨退化歸入 subjective。"""
    raw = "病患昨晚開始頭暈眼花，胃部脹痛想吐，沒有腹瀉。"
    parsed = parse_soap_text(raw)
    assert parsed["subjective"] == raw
    assert parsed["objective"] == ""
    assert parsed["assessment"] == ""
    assert parsed["plan"] == ""


def test_guard_non_negated_adverbs_preserved():
    """守門測試 3：副詞（非常、未見好轉）不誤殺症狀。"""
    soap = {"subjective": "非常頭痛，未見好轉的咳嗽", "assessment": ""}
    insights = extract_general_medical_insights(soap)
    assert set(insights["symptoms"]) == {"頭痛", "咳嗽"}


def test_guard_parse_soap_sublabel_in_plan_preserved():
    """守門測試 4：處置段落內之子標籤（衛教事項：）保留於 Plan 段落中。"""
    raw = "處置：開立退燒藥。衛教事項：多喝水休息"
    parsed = parse_soap_text(raw)
    assert "開立退燒藥" in parsed["plan"]
    assert "多喝水休息" in parsed["plan"]
    assert parsed["subjective"] == ""
    assert parsed["objective"] == ""
    assert parsed["assessment"] == ""


def test_guard_parse_soap_inline_vitals_not_split():
    """守門測試 5：行內單字母與生命徵象（如 P: 80）不作為切分點。"""
    raw = "客觀：T: 37.2 P: 80 R: 18 BP: 120/80"
    parsed = parse_soap_text(raw)
    assert "T: 37.2 P: 80 R: 18 BP: 120/80" in parsed["objective"]
    assert parsed["plan"] == ""


# ==============================================================================
# Category B: Red TDD Tests for parse_soap_text (測試 3~9)
# ==============================================================================

def test_red_parse_soap_inline_chinese_markers():
    """測試 3：行內中文標記切分。"""
    raw = "主訴：喉嚨痛 理學檢查：喉嚨紅 診斷：咽喉炎 處置：多喝水"
    parsed = parse_soap_text(raw)
    assert parsed["subjective"] == "喉嚨痛"
    assert parsed["objective"] == "喉嚨紅"
    assert parsed["assessment"] == "咽喉炎"
    assert parsed["plan"] == "多喝水"


def test_red_parse_soap_bracketed_headers():
    """測試 4：成對括號標頭切分。"""
    raw = "【主訴】發燒三天 【客觀】體溫38度 【診斷】流感 【處置】給予克流感"
    parsed = parse_soap_text(raw)
    assert parsed["subjective"] == "發燒三天"
    assert parsed["objective"] == "體溫38度"
    assert parsed["assessment"] == "流感"
    assert parsed["plan"] == "給予克流感"


def test_red_parse_soap_english_article_a_not_confused():
    """測試 5：英文冠詞 A 不被誤判為 Assessment 切分標記。"""
    raw = "A 35-year-old male presents with headache"
    parsed = parse_soap_text(raw)
    assert parsed["subjective"] == raw
    assert parsed["assessment"] == ""


def test_red_parse_soap_plan_word_not_confused():
    """測試 6：英文敘述句起點 Plan 不被誤判為 Plan 切分標記。"""
    raw = "Plan to evaluate next Monday"
    parsed = parse_soap_text(raw)
    assert parsed["subjective"] == raw
    assert parsed["plan"] == ""


def test_red_parse_soap_single_letter_space_delimiter_rejected():
    """測試 7：單字母標記拒絕純空白分隔。"""
    raw = "S cough\nO clear\nA flu\nP rest"
    parsed = parse_soap_text(raw)
    assert parsed["subjective"] == raw
    assert parsed["objective"] == ""
    assert parsed["assessment"] == ""
    assert parsed["plan"] == ""


def test_red_parse_soap_fullwidth_space_colon_clean():
    """測試 8：全形空白與前導冒號乾淨移除。"""
    raw = "主訴　：喉嚨痛"
    parsed = parse_soap_text(raw)
    assert parsed["subjective"] == "喉嚨痛"


def test_red_parse_soap_duplicate_marker_merge():
    """測試 9：重複標記自動累加合併至同段落。"""
    raw = "主訴：頭痛 主訴：發燒三天"
    parsed = parse_soap_text(raw)
    assert "頭痛" in parsed["subjective"]
    assert "發燒三天" in parsed["subjective"]


# ==============================================================================
# Category B: Red TDD Tests for extract_general_medical_insights (測試 10~18)
# ==============================================================================

def test_red_insights_negation_conditions():
    """測試 10：Assessment 內排除語境不採計為確診條件。"""
    soap = {"assessment": "排除流感，確診普通感冒"}
    insights = extract_general_medical_insights(soap)
    assert "感冒" in insights["conditions"]
    assert "流感" not in insights["conditions"]


def test_red_insights_negation_symptoms():
    """測試 11：Subjective 內前置與後置否定語境排除症狀。"""
    soap = {"subjective": "無發燒、無咳嗽，否認腹瀉"}
    insights = extract_general_medical_insights(soap)
    assert insights["symptoms"] == []


def test_red_insights_enumeration_negation():
    """測試 12：頓號列舉延續否定語境。"""
    soap = {"subjective": "無發燒、咳嗽"}
    insights = extract_general_medical_insights(soap)
    assert insights["symptoms"] == []


def test_red_insights_conjunction_scope_breaker():
    """測試 13：獨立轉折詞中斷否定作用域。"""
    soap = {"subjective": "無發燒，但有咳嗽"}
    insights = extract_general_medical_insights(soap)
    assert "咳嗽" in insights["symptoms"]
    assert "發燒" not in insights["symptoms"]


def test_red_insights_negation_precedence_weichuxian():
    """測試 14：最長前置否定片語優先於轉折詞。"""
    soap = {"subjective": "未出現發燒"}
    insights = extract_general_medical_insights(soap)
    assert "發燒" not in insights["symptoms"]


def test_red_insights_symptoms_exclude_plan():
    """測試 15：Symptoms 僅掃描 S/O，嚴格排除 Plan 段落。"""
    soap = {"plan": "衛教：避免發燒時服用阿斯匹靈，多喝水休息"}
    insights = extract_general_medical_insights(soap)
    assert insights["symptoms"] == []


def test_red_insights_rule_out_and_suspected_excluded():
    """測試 16：R/O 與疑似語意不計入確診條件。"""
    soap = {"assessment": "R/O 流感，疑似急性支氣管炎，確診普通感冒"}
    insights = extract_general_medical_insights(soap)
    assert "感冒" in insights["conditions"]
    assert "流感" not in insights["conditions"]
    assert "急性支氣管炎" not in insights["conditions"]


def test_red_insights_empty_assessment_conditions_empty():
    """測試 17：Assessment 為空時 Conditions 保持為空清單。"""
    soap = {"subjective": "自述同事罹患流感，非常擔心", "assessment": ""}
    insights = extract_general_medical_insights(soap)
    assert insights["conditions"] == []


def test_red_insights_subsumption_dedup():
    """測試 18：最長匹配去重（急性咽喉炎覆蓋咽喉炎）。"""
    soap = {"assessment": "急性咽喉炎"}
    insights = extract_general_medical_insights(soap)
    assert insights["conditions"] == ["急性咽喉炎"]



def test_review_suffix_negation_with_qualifier():
    """複審：『流感快篩陰性』（後置否定前有修飾詞）不得擷取為 conditions。"""
    from src.soap.section_parser import extract_general_medical_insights

    r = extract_general_medical_insights(
        {"assessment": "流感快篩陰性", "subjective": "", "objective": "", "plan": ""}
    )
    assert r["conditions"] == []


def test_review_inline_lenticular_bracket_marker():
    """複審：【主訴】咳嗽【診斷】感冒 —— 全形粗括號標記緊鄰前文仍應切分。"""
    from src.soap.section_parser import parse_soap_text

    r = parse_soap_text("【主訴】咳嗽【診斷】感冒")
    assert r["subjective"] == "咳嗽"
    assert r["assessment"] == "感冒"
