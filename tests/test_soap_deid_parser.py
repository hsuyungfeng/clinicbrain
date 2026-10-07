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
