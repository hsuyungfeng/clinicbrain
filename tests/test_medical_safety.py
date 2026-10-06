"""
tests/test_medical_safety.py - GC-02 與 GC-03 醫療安全驗證器測試

涵蓋：
1. 劑量與處方建議攔截（DX-1 ~ DX-6 正例 47 則、負例 50 則、全形/NFKC、保守攔截）
2. 就醫警訊段落檢核（正例 15 則、負例 17 則）
3. 雙層整合測試（同時滿足無劑量且含警訊）
4. answer-only 檢驗與預設關閉相容性
5. 正式庫 40 筆診所上傳 FAQ 回掃 0 誤拒
6. classify_reject_reason 安全代碼映射 (test_classify_*)
7. build_seed_faq_prompt 提示詞規則 (test_prompt_*)
8. generate_topic_faqs 批次接線與隱私防護 (test_wiring_*)
"""

import pytest


DOSAGE_POS = [
    "醫師會開止痛藥給您，疼痛時服用即可。", "退燒時吃退燒藥即可。", "抗生素要吃七天，不可中斷。", "可吃抗組織胺緩解鼻水。",
    "可服用制酸劑緩解胃部不適。", "可塗抹類固醇藥膏於患處。", "可使用抗生素藥膏。", "疼痛時可吃止痛藥。",
    "可自行購買消炎藥服用。", "可吃些抗病毒藥物。", "每次吃500mg，每天三次。", "服用 500 ＭＧ 後休息。",
    "一次吃５００ｍｇ即可。", "每次服用五百毫克。", "每8小時服用一次退燒藥。", "退燒藥可依q8h使用。",
    "每天bid服用。", "睡前服用兩片。", "每次吃兩顆感冒藥。", "成人每次服用一顆即可。",
    "抗生素每天吃三次，飯後服用。", "可先吃一顆普拿疼。", "乙醯胺酚成人每次500毫克。", "兒童退燒藥依體重每公斤10毫克。",
    "布洛芬每六小時可吃一次。", "咳嗽時可服用止咳藥。", "腹瀉時可吃止瀉藥。", "鼻塞時使用鼻噴劑，每邊兩下。",
    "嘔吐時可吃止吐藥。", "發燒時可以吃布洛芬。", "吃克流感五天可縮短病程。", "症狀嚴重時可吞服胃藥。",
    "眼睛癢可點抗組織胺眼藥水。", "服藥後多休息。", "感冒了就吃藥休息。", "可口服藥物緩解症狀。",
    "自行服用類固醇。", "先吃一些感冒藥觀察。", "每天吃三次抗生素。", "發燒超過38度可吃退燒藥。",
    "塗抹藥膏時每次約一公克。", "q6h服用止痛藥。", "每天服用兩次維持。", "一次吃1錠。", "吃藥後即可上班。",
    "疼痛時吃兩片止痛藥。", "每日三次，每次一顆，飯後服用抗生素。",
]

DOSAGE_NEG = [
    "每天睡7～8小時。", "每天應攝取足夠水分。", "每天量血壓並記錄。", "每餐少量多餐。", "每次洗手至少20秒。",
    "每天刷牙兩次。", "每週運動三次，每次30分鐘。", "攝取2000毫升水分。", "可使用冷敷。", "可使用加濕器。",
    "可以使用溫毛巾熱敷。", "可以吃清粥小菜。", "請使用口罩。", "休息時可以使用枕頭墊高頭部。",
    "一天內若嘔吐超過三次應就醫。", "體溫38.5度以上請就醫。", "症狀持續3天未改善請就醫。", "血壓180mmHg以上請就醫。",
    "多喝溫開水補充水分。", "若一天內腹瀉超過三次或嘔吐不止，應儘速就醫。", "若每天腹瀉超過6次或有血便，請立即就醫。",
    "請勿自行服用抗生素，需由醫師評估。", "避免自行購買止痛藥服用。", "若正在服用抗凝血藥物，請告知醫師。",
    "請依醫囑服用醫師開立的藥物。", "可使用生理食鹽水沖洗鼻腔。", "補充口服電解質液以預防脫水。", "請保持室內空氣流通，使用空氣清淨機。",
    "就醫時請攜帶目前使用的藥物清單。", "流感病毒可透過飛沫傳播。", "感冒通常由病毒引起，抗生素對病毒無效。", "可吃稀飯、白吐司等清淡食物。",
    "每天吃三餐，維持均衡飲食。", "睡前避免使用手機，維持充足睡眠。", "休息時可使用兩個枕頭墊高頭部。", "每次嘔吐後可喝一小口溫水。",
    "每4小時測量一次體溫。", "過敏性鼻炎的人應避免接觸塵蟎與花粉。", "可用溫水洗臉保持清潔。", "出現呼吸急促或胸痛，請立即撥打119。",
    "嬰幼兒發燒超過38度請盡速就醫。", "洗手時使用肥皂搓洗至少20秒。", "每天使用加濕器保持適當濕度。", "清淡飲食，每次進食量不宜過多。",
    "可用溫毛巾敷在鼻樑，每次約十分鐘。", "可喝500毫升溫開水補充水分。", "切勿自行吃退燒藥超過規定天數。", "醫師會依病情評估是否需要用藥。",
    "發燒時可穿著輕薄衣物並多休息。", "可吃一片吐司搭配白開水。",
]

DOSAGE_KNOWN_CONSERVATIVE = ["若醫師開立藥物，請依指示服用。"]

WARN_POS = [
    "若出現胸痛、呼吸急促，請撥打119或至急診就診。", "若孩童反覆嘔吐，請儘早帶往醫院。", "體溫超過38.5度且持續3天，請盡速就醫。",
    "若一天內嘔吐超過三次，應就醫評估。", "若每天腹瀉超過6次或有血便，請立即就醫。", "若一天內腹瀉超過三次或嘔吐不止，應儘速就醫。",
    "出現呼吸困難或嘴唇發紫時，請立即前往急診。", "症狀持續超過7天仍未改善，建議回診。", "若出現意識不清或抽搐，請立刻送醫。",
    "高燒不退或頸部僵硬，應儘速至醫院檢查。", "出現脫水徵象如尿量明顯減少、口乾，請就醫。", "若發燒持續超過72小時，請至門診診療。",
    "嬰兒出現發燒且精神萎靡，請立即就醫。", "如有黑便或嘔血，請儘速至急診處理。", "咳嗽超過兩週仍未緩解，建議就診。",
]

WARN_NEG = [
    "出現不適請就醫。", "當然可以多喝水，不嚴重不用就醫。", "本文不構成就醫建議。", "如果持續發燒，建議至醫院看診。",
    "若症狀加重，請回診。", "嚴重時請至醫院。", "請多休息並補充水分。", "有任何問題請諮詢專業人員。",
    "胸痛、呼吸急促是常見的症狀。", "體溫超過38.5度是發燒的定義。", "沒有胸痛的話不需就醫。", "若不舒服可以考慮看看醫生。",
    "體溫超過38度，不需要就醫，在家休息即可。", "症狀持續請留意。", "流感病程通常約一週，請放心。", "注意休息，必要時就醫。", "如有需要請就醫。",
]

INTEGRATION = [
    "若一天內腹瀉超過三次或嘔吐不止，應儘速就醫。", "若每天腹瀉超過6次或有血便，請立即就醫。",
    "體溫超過38.5度且持續3天，請盡速就醫。", "一天內嘔吐超過三次，請就醫。",
]


@pytest.mark.parametrize("text", DOSAGE_POS)
def test_dosage_prescription_positive_cases(text):
    """47 則劑量處方正例皆必須被成功攔截（check_dosage_prescription 非 None）。"""
    from src.ingestion.medical_safety import check_dosage_prescription
    result = check_dosage_prescription(text)
    assert result is not None, f"正例未被攔截: '{text}'"


@pytest.mark.parametrize("text", DOSAGE_NEG)
def test_dosage_prescription_negative_cases(text):
    """50 則安全衛教負例皆必須被放行（check_dosage_prescription 為 None）。"""
    from src.ingestion.medical_safety import check_dosage_prescription
    result = check_dosage_prescription(text)
    assert result is None, f"負例被誤攔: '{text}' (規則: {result})"


def test_dosage_prescription_nfkc_and_variations():
    """全形、大寫、中文數字與拉丁簡寫皆必須被攔截。"""
    from src.ingestion.medical_safety import check_dosage_prescription
    assert check_dosage_prescription("服用 500 ＭＧ 後休息。") is not None
    assert check_dosage_prescription("吃５００ｍｇ即可。") is not None
    assert check_dosage_prescription("每次服用五百毫克。") is not None
    assert check_dosage_prescription("退燒藥可依q8h使用。") is not None
    assert check_dosage_prescription("每天bid服用。") is not None


def test_dosage_prescription_conservative_baseline():
    """已知保守案例：『若醫師開立藥物，請依指示服用。』回傳 DX-5。"""
    from src.ingestion.medical_safety import check_dosage_prescription
    assert check_dosage_prescription(DOSAGE_KNOWN_CONSERVATIVE[0]) == "DX-5"


@pytest.mark.parametrize("text", WARN_POS)
def test_doctor_warning_positive_cases(text):
    """15 則具體就醫警訊正例皆判定為 True。"""
    from src.ingestion.medical_safety import has_doctor_warning
    assert has_doctor_warning(text) is True, f"警訊正例未被識別: '{text}'"


@pytest.mark.parametrize("text", WARN_NEG)
def test_doctor_warning_negative_cases(text):
    """17 則空泛、無具體條件或否定警訊負例皆判定為 False。"""
    from src.ingestion.medical_safety import has_doctor_warning
    assert has_doctor_warning(text) is False, f"警訊負例被誤放行: '{text}'"


@pytest.mark.parametrize("text", INTEGRATION)
def test_medical_safety_integration_cases(text):
    """雙層整合測試：4 句合規衛教同時通過無劑量處方與含具體警訊。"""
    from src.ingestion.medical_safety import check_dosage_prescription, has_doctor_warning
    from src.ingestion.generate_faq import validate_single_faq

    assert check_dosage_prescription(text) is None
    assert has_doctor_warning(text) is True

    is_valid, reason = validate_single_faq(
        {"question": "何時該就醫？", "answer": text},
        check_dosage=True,
        require_doctor_warning=True,
    )
    assert is_valid is True
    assert reason is None


def test_validate_single_faq_answer_only_guard():
    """第五層僅檢查 answer，不檢查 question。"""
    from src.ingestion.generate_faq import validate_single_faq

    # question 含時間或疑慮詞，answer 為標準診所回覆
    is_valid, reason = validate_single_faq(
        {"question": "音波拉提大約多久需要再做一次？", "answer": "請致電診所確認"},
        check_dosage=True,
    )
    assert is_valid is True
    assert reason is None

    # answer 出現具體處方建議則被攔截
    is_valid, reason = validate_single_faq(
        {"question": "音波拉提術後不舒服怎麼辦？", "answer": "建議吃止痛藥。"},
        check_dosage=True,
    )
    assert is_valid is False
    assert reason is not None
    assert "用藥劑量或處方建議" in reason


def test_validate_single_faq_default_disabled():
    """validate_single_faq 預設關閉新檢查層，維持 100% 向後相容。"""
    from src.ingestion.generate_faq import validate_single_faq

    is_valid, reason = validate_single_faq(
        {"question": "感冒怎麼辦？", "answer": "請吃止痛藥每天三次。"}
    )
    assert is_valid is True
    assert reason is None


def test_backscan_clinic_upload_faqs(isolated_conn):
    """正式庫中 40 筆 clinic_upload FAQ 回掃，劑量處方層 0 誤拒。"""
    from src.ingestion.medical_safety import check_dosage_prescription
    from src.ingestion.generate_faq import validate_single_faq

    cur = isolated_conn.cursor()
    cur.execute(
        "SELECT id, question, answer FROM faq_cache WHERE source_type = 'clinic_upload'"
    )
    rows = cur.fetchall()
    assert len(rows) >= 40, f"clinic_upload 筆數不足: {len(rows)}"

    for row_id, q, a in rows:
        hit = check_dosage_prescription(a)
        assert hit is None, f"FAQ id={row_id} 被誤判為劑量處方 (規則: {hit}):\n{a}"

        is_valid, reason = validate_single_faq(
            {"question": q, "answer": a},
            check_dosage=True,
        )
        assert is_valid is True, f"FAQ id={row_id} 驗證失敗: {reason}"


# ---- classify 相關測試 (test_classify_*) ----

def test_classify_dosage_prescription_code():
    """classify_reject_reason 正確將劑量處方詳細訊息映射為 dosage_prescription 代碼。"""
    from src.batch.faq_generator import REJECT_CODES, classify_reject_reason

    assert "dosage_prescription" in REJECT_CODES
    code = classify_reject_reason("檢出用藥劑量或處方建議 (規則: DX-4)")
    assert code == "dosage_prescription"


def test_classify_missing_doctor_warning_code():
    """classify_reject_reason 正確將就醫警訊缺漏映射為 missing_doctor_warning，不被 malformed_item 攔截。"""
    from src.batch.faq_generator import REJECT_CODES, classify_reject_reason

    assert "missing_doctor_warning" in REJECT_CODES
    code = classify_reject_reason("缺少「何時該就醫」警訊（需具體症狀或數值條件加就醫動作）")
    assert code == "missing_doctor_warning"

    # 既有「缺少必要欄位」仍應正確歸類為 malformed_item
    assert classify_reject_reason("缺少必要欄位 'answer'") == "malformed_item"


# ---- prompt 相關測試 (test_prompt_*) ----

def test_prompt_build_seed_faq_prompt_rules():
    """build_seed_faq_prompt 恆包含用藥劑量禁令，且依 require_doctor_warning 決定是否要求警訊收尾。"""
    from src.batch.faq_generator import build_seed_faq_prompt

    prompt_default = build_seed_faq_prompt(
        title="音波拉提常見問題",
        questions=["音波拉提大約多久需要再做一次？"],
        reference_context=None,
    )
    assert "用藥劑量" in prompt_default or "禁止輸出具體用藥劑量" in prompt_default
    assert "何時該就醫" not in prompt_default

    prompt_warning = build_seed_faq_prompt(
        title="感冒居家照護",
        questions=["感冒通常會出現哪些常見症狀？"],
        reference_context=None,
        require_doctor_warning=True,
    )
    assert "禁止輸出具體用藥劑量" in prompt_warning or "用藥劑量" in prompt_warning
    assert "何時該就醫" in prompt_warning or "具體症狀或數值條件" in prompt_warning


# ---- wiring 相關測試 (test_wiring_*) ----

def test_wiring_general_topic_requires_warning(isolated_conn):
    """generate_topic_faqs 對 category='general' 主題要求就醫警訊，缺少者被拒絕，合格者放行。"""
    import json
    from src.batch.faq_generator import generate_topic_faqs
    from src.batch.topic_sources import SeedTopic

    topic = SeedTopic(
        topic_key="test-general-cold",
        title="感冒居家照護測試",
        category="general",
        clinic_id=None,
        keywords=[],
        always=True,
        tree_doc_id=None,
        questions=["感冒時要如何休息？"],
    )

    # 模擬 LLM 產出不含警訊的答案
    def mock_llm_no_warning(_):
        return json.dumps([
            {"question": "感冒時要如何休息？", "answer": "請多休息並補充水分即可逐漸恢復健康。"}
        ])

    conn = isolated_conn
    res = generate_topic_faqs(conn, topic, mock_llm_no_warning)
    assert len(res.valid) == 0
    assert len(res.rejected) == 1
    assert res.rejected[0]["code"] == "missing_doctor_warning"
    assert "多休息並補充水分" not in repr(res)  # 隱私防護

    # 模擬 LLM 產出含具體警訊之合法答案
    def mock_llm_with_warning(_):
        return json.dumps([
            {"question": "感冒時要如何休息？", "answer": "多喝溫開水充分休息。若體溫超過38.5度且持續3天，請盡速就醫。"}
        ])

    res2 = generate_topic_faqs(conn, topic, mock_llm_with_warning)
    assert len(res2.valid) == 1
    assert len(res2.rejected) == 0


def test_wiring_special_topic_dosage_interception(isolated_conn):
    """generate_topic_faqs 對 category='special' 主題阻斷劑量處方，但不強制要求警訊。"""
    import json
    from src.batch.faq_generator import generate_topic_faqs
    from src.batch.topic_sources import SeedTopic

    topic = SeedTopic(
        topic_key="test-special-laser",
        title="皮秒雷射測試",
        category="special",
        clinic_id="3503190424",
        keywords=[],
        always=False,
        tree_doc_id=None,
        questions=["皮秒雷射術後疼痛怎麼辦？"],
    )

    # 模擬 LLM 產出含劑量處方之答案
    def mock_llm_dosage(_):
        return json.dumps([
            {"question": "皮秒雷射術後疼痛怎麼辦？", "answer": "可服用止痛藥每天三次來緩解疼痛。"}
        ])

    conn = isolated_conn
    res = generate_topic_faqs(conn, topic, mock_llm_dosage)
    assert len(res.valid) == 0
    assert len(res.rejected) == 1
    assert res.rejected[0]["code"] == "dosage_prescription"

    # 模擬 LLM 產出無劑量但無警訊之答案（special 不要求警訊）
    def mock_llm_safe_no_warning(_):
        return json.dumps([
            {"question": "皮秒雷射術後疼痛怎麼辦？", "answer": "術後局部冰敷可減緩紅腫與不適感，請保持患部清潔乾燥。"}
        ])

    res2 = generate_topic_faqs(conn, topic, mock_llm_safe_no_warning)
    assert len(res2.valid) == 1
    assert len(res2.rejected) == 0


# ---------------------------------------------------------
# 複審補強（2026-10-06）：獨立語料，非封閉語料之外的新正負例
# ---------------------------------------------------------
DOSAGE_POS_EXTRA = [
    # 只有數量、無藥名的劑量句（原 DX-2 漏攔）
    "每次吃２顆，每天３次", "小孩一次吃半顆", "吃3片就夠了", "每日兩次，每次一顆", "一次吃兩粒，一天吃三次",
    # 否定詞不緊鄰動詞，不得整句豁免
    "請勿擔心可吃止痛藥", "別擔心可以吃退燒藥", "避免疼痛可吃止痛藥",
    # 未列名劑型與英文學名
    "可喝感冒糖漿緩解", "咳嗽時可服用止咳糖漿", "可使用栓劑退燒", "建議吃acetaminophen", "可吃Tylenol",
]

DOSAGE_NEG_EXTRA = [
    "請勿自行服用抗生素，需由醫師評估。", "不要隨便亂吃藥。", "避免擅自服用止痛藥。", "切勿自行購買消炎藥。",
    "每天吃三餐，定時定量。", "每次洗手至少二十秒。",
]

WARN_NEG_EXTRA = [
    "高燒超過3天也無需前往醫院", "呼吸困難時無需到急診", "胸痛時不要去醫院", "胸痛時大多不必急著就醫",
    "症狀持續或惡化時請盡速就醫",
]

WARN_POS_EXTRA = [
    "若出現以下情形請儘速就醫：\n1. 高燒超過3天\n2. 呼吸困難",
    "出現下列症狀時應就醫：\n- 持續高燒\n- 呼吸急促",
    "胸痛或呼吸困難時，請不要拖延，立即就醫。",
]


@pytest.mark.parametrize("s", DOSAGE_POS_EXTRA)
def test_dosage_extra_positive(s):
    from src.ingestion.medical_safety import check_dosage_prescription
    assert check_dosage_prescription(s) is not None, s


@pytest.mark.parametrize("s", DOSAGE_NEG_EXTRA)
def test_dosage_extra_negative(s):
    from src.ingestion.medical_safety import check_dosage_prescription
    assert check_dosage_prescription(s) is None, s


@pytest.mark.parametrize("s", WARN_NEG_EXTRA)
def test_warning_extra_negative(s):
    from src.ingestion.medical_safety import has_doctor_warning
    assert has_doctor_warning(s) is False, s


@pytest.mark.parametrize("s", WARN_POS_EXTRA)
def test_warning_extra_positive(s):
    from src.ingestion.medical_safety import has_doctor_warning
    assert has_doctor_warning(s) is True, s
