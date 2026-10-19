"""
Phase 29 Task 2: 視覺解說卡 Typed IR 規格與驗證單元測試。
"""

import copy
import pytest

from src.visual.ir import (
    VALID_BLUEPRINTS,
    VALID_TONES,
    VISUAL_EXTRA_FORBIDDEN,
    validate_visual_text,
    validate_ir,
)

VALID_IR_SAMPLE = {
    "topic_key": "autologous-fat-grafting",
    "title": "自體脂肪移植手術簡介",
    "keywords": ["自體脂肪", "抽脂填補", "脂肪移植"],
    "scenes": [
        {
            "blueprint": "process_diagram",
            "title": "脂肪抽取與純化",
            "caption": "利用專業抽脂技術自腹部或大腿抽取多餘脂肪，經過離心純化技術篩選出健康完整的脂肪細胞以供後續填補。",
            "labels": [
                {"text": "抽取脂肪", "tone": "neutral"},
                {"text": "離心純化", "tone": "optimal"},
            ],
        },
        {
            "blueprint": "contrast",
            "title": "注射填補方式",
            "caption": "醫師採用多層次微量注射技術將脂肪分散注入目標部位，能使組織均勻吸收營養並減少局部硬塊發生的風險。",
            "labels": [
                {"text": "分層注射", "tone": "optimal"},
                {"text": "過量填補", "tone": "warning"},
            ],
        },
        {
            "blueprint": "timeline",
            "title": "術後照護週期",
            "caption": "術後初期需避免劇烈擠壓填補區域，保持規律作息與均衡營養，通常在數週後組織便會逐步達到一定程度的穩定。",
            "labels": [
                {"text": "避免按壓", "tone": "warning"},
                {"text": "穩定成形", "tone": "optimal"},
            ],
        },
    ],
}


def test_valid_ir_passes():
    """驗證標準自體脂肪移植 3 場景 IR 完全通過且回傳 ok。"""
    ok, code = validate_ir(VALID_IR_SAMPLE)
    assert ok is True
    assert code == "ok"


def test_schema_error_top_level_structure():
    """驗證頂層缺鍵、多鍵、型別錯誤皆回傳 schema_error。"""
    # 1. 非 dict
    ok, code = validate_ir("not a dict")
    assert ok is False
    assert code == "schema_error"

    # 2. 缺鍵
    ir_missing = copy.deepcopy(VALID_IR_SAMPLE)
    del ir_missing["scenes"]
    ok, code = validate_ir(ir_missing)
    assert ok is False
    assert code == "schema_error"

    # 3. 多鍵（多餘欄位拒絕）
    ir_extra = copy.deepcopy(VALID_IR_SAMPLE)
    ir_extra["clinic_id"] = "3503190424"
    ok, code = validate_ir(ir_extra)
    assert ok is False
    assert code == "schema_error"

    # 4. topic_key 格式不合
    ir_bad_key = copy.deepcopy(VALID_IR_SAMPLE)
    ir_bad_key["topic_key"] = "Invalid_Key!"
    ok, code = validate_ir(ir_bad_key)
    assert ok is False
    assert code == "schema_error"

    # 5. title 過長 (> 30)
    ir_long_title = copy.deepcopy(VALID_IR_SAMPLE)
    ir_long_title["title"] = "這是一個超過三十個字元長度的醫療解說卡標題測試字串請注意長度限制"
    ok, code = validate_ir(ir_long_title)
    assert ok is False
    assert code == "schema_error"

    # 6. keywords 數量不符 (0 或 > 8)
    ir_no_kw = copy.deepcopy(VALID_IR_SAMPLE)
    ir_no_kw["keywords"] = []
    ok, code = validate_ir(ir_no_kw)
    assert ok is False
    assert code == "schema_error"

    ir_many_kw = copy.deepcopy(VALID_IR_SAMPLE)
    ir_many_kw["keywords"] = [f"詞{i}" for i in range(9)]
    ok, code = validate_ir(ir_many_kw)
    assert ok is False
    assert code == "schema_error"


def test_schema_error_scenes_structure():
    """驗證場景數（少於 3 或多於 5）、場景缺鍵、多鍵、標籤結構不符回傳 schema_error。"""
    # 1. 場景數少於 3 (2 個)
    ir_two_scenes = copy.deepcopy(VALID_IR_SAMPLE)
    ir_two_scenes["scenes"] = ir_two_scenes["scenes"][:2]
    ok, code = validate_ir(ir_two_scenes)
    assert ok is False
    assert code == "schema_error"

    # 2. 場景數大於 5 (6 個)
    ir_six_scenes = copy.deepcopy(VALID_IR_SAMPLE)
    ir_six_scenes["scenes"] = ir_six_scenes["scenes"] * 2
    ok, code = validate_ir(ir_six_scenes)
    assert ok is False
    assert code == "schema_error"

    # 3. caption 過短 (< 20)
    ir_short_cap = copy.deepcopy(VALID_IR_SAMPLE)
    ir_short_cap["scenes"][0]["caption"] = "太短的說明文字。"
    ok, code = validate_ir(ir_short_cap)
    assert ok is False
    assert code == "schema_error"

    # 4. caption 過長 (> 120)
    ir_long_cap = copy.deepcopy(VALID_IR_SAMPLE)
    ir_long_cap["scenes"][0]["caption"] = "這是一段刻意超過一百二十個字元的超長解說文字測試。" * 6
    ok, code = validate_ir(ir_long_cap)
    assert ok is False
    assert code == "schema_error"

    # 5. scene 多餘鍵
    ir_extra_scene_key = copy.deepcopy(VALID_IR_SAMPLE)
    ir_extra_scene_key["scenes"][0]["extra"] = 123
    ok, code = validate_ir(ir_extra_scene_key)
    assert ok is False
    assert code == "schema_error"

    # 6. label tone 非法
    ir_bad_tone = copy.deepcopy(VALID_IR_SAMPLE)
    ir_bad_tone["scenes"][0]["labels"][0]["tone"] = "danger"
    ok, code = validate_ir(ir_bad_tone)
    assert ok is False
    assert code == "schema_error"


def test_unknown_blueprint_error():
    """驗證未知 blueprint 回傳 unknown_blueprint 代碼。"""
    ir_bad_bp = copy.deepcopy(VALID_IR_SAMPLE)
    ir_bad_bp["scenes"][0]["blueprint"] = "video_player"
    ok, code = validate_ir(ir_bad_bp)
    assert ok is False
    assert code == "unknown_blueprint"


def test_text_unsafe_html_url_script():
    """驗證 HTML 標籤、網址、javascript 等回傳 text_unsafe 代碼。"""
    # 1. 包含 HTML 標籤字元 <script>
    ir_html = copy.deepcopy(VALID_IR_SAMPLE)
    ir_html["scenes"][0]["caption"] = "利用抽脂技術<script>alert(1)</script>抽取多餘脂肪以供填補使用。"
    ok, code = validate_ir(ir_html)
    assert ok is False
    assert code == "text_unsafe"

    # 2. 包含 URL
    ir_url = copy.deepcopy(VALID_IR_SAMPLE)
    ir_url["scenes"][0]["caption"] = "利用抽脂技術抽取多餘脂肪，詳情請參考 http://example.com 說明。"
    ok, code = validate_ir(ir_url)
    assert ok is False
    assert code == "text_unsafe"

    # 3. 包含 javascript:
    ir_js = copy.deepcopy(VALID_IR_SAMPLE)
    ir_js["scenes"][0]["caption"] = "利用抽脂技術抽取多餘脂肪 javascript:void(0) 進行純化處理作業。"
    ok, code = validate_ir(ir_js)
    assert ok is False
    assert code == "text_unsafe"


def test_price_leak_error():
    """驗證價格數字洩漏回傳 price_leak 代碼。"""
    ir_price = copy.deepcopy(VALID_IR_SAMPLE)
    ir_price["scenes"][0]["caption"] = "利用專業抽脂技術抽取多餘脂肪，整體費用約 30000 元整並進行分層填補。"
    ok, code = validate_ir(ir_price)
    assert ok is False
    assert code == "price_leak"


    ir_num_price = copy.deepcopy(VALID_IR_SAMPLE)
    ir_num_price["scenes"][0]["caption"] = "利用專業抽脂技術抽取多餘脂肪，單一部位收費 50000 元整以供填補。"
    ok, code = validate_ir(ir_num_price)
    assert ok is False
    assert code == "price_leak"


def test_simplified_chinese_error():
    """驗證簡體中文回傳 simplified_chinese 代碼。"""
    ir_sim = copy.deepcopy(VALID_IR_SAMPLE)
    ir_sim["scenes"][0]["caption"] = "利用专业抽脂技术自腹部抽取多余脂肪，经过离心纯化技术筛选健康脂肪。"
    ok, code = validate_ir(ir_sim)
    assert ok is False
    assert code == "simplified_chinese"


def test_dosage_prescription_error():
    """驗證用藥劑量與處方回傳 dosage_prescription 代碼。"""
    ir_dose = copy.deepcopy(VALID_IR_SAMPLE)
    ir_dose["scenes"][0]["caption"] = "術後每日口服抗生素 500mg 兩次，並搭配止痛藥物按時服用以減輕不適。"
    ok, code = validate_ir(ir_dose)
    assert ok is False
    assert code == "dosage_prescription"


def test_forbidden_phrase_and_visual_extra_forbidden():
    """驗證政治立場、保證療效、視覺專屬禁詞與百分比回傳 forbidden_phrase。"""
    # 1. 永久 / 終身 / 存活率 / 保證
    for word in ["永久存留", "終身維持", "一輩子有效", "成為身體一部分", "存活率極佳", "保證無痕"]:
        ir_bad = copy.deepcopy(VALID_IR_SAMPLE)
        ir_bad["scenes"][0]["caption"] = f"利用專業抽脂技術抽取多餘脂肪，{word}並進行健康篩選以供填補。"
        ok, code = validate_ir(ir_bad)
        assert ok is False, f"未攔截禁詞: {word}"
        assert code == "forbidden_phrase"

    # 2. 百分比數字 (80%, 90％)
    for pct in ["90%", "85％", "百分之八十"]:
        ir_pct = copy.deepcopy(VALID_IR_SAMPLE)
        ir_pct["scenes"][0]["caption"] = f"利用專業抽脂技術抽取多餘脂肪，平均有 {pct} 可以穩定留存。"
        ok, code = validate_ir(ir_pct)
        assert ok is False, f"未攔截百分比: {pct}"
        assert code == "forbidden_phrase"


def test_natural_language_not_overkilled():
    """驗證含「一定程度」「不一定」「一定時間」之自然語言合法句子不被誤判。"""
    # 包含「一定程度」
    ok1, code1 = validate_visual_text("術後組織便會逐步達到一定程度的穩定狀態。")
    assert ok1 is True
    assert code1 == "ok"

    # 包含「不一定」
    ok2, code2 = validate_visual_text("個人體質不同，恢復進度不一定完全相同。")
    assert ok2 is True
    assert code2 == "ok"

    # 包含「一定時間」
    ok3, code3 = validate_visual_text("需等待一定時間讓微血管新生與組織相容。")
    assert ok3 is True
    assert code3 == "ok"


def test_code_never_leaks_original_text():
    """驗證回傳的 code 均為列舉字串，不包含任何原始文字或機密內容。"""
    valid_codes = {
        "ok",
        "schema_error",
        "text_unsafe",
        "forbidden_phrase",
        "price_leak",
        "simplified_chinese",
        "dosage_prescription",
        "unknown_blueprint",
        "param_error",
    }
    sample_fail_texts = [
        "<script>bad()</script>",
        "費用 30000 元",
        "专业离心技术",
        "口服 500mg 每日三次",
        "永久有效保證不變",
        "存活率達 90%",
    ]
    for text in sample_fail_texts:
        ok, code = validate_visual_text(text)
        assert ok is False
        assert code in valid_codes
        assert text not in code


def test_valid_ir_with_params_and_duration_sec():
    """Phase 30 Task 2: 驗證帶有合法 params 與 duration_sec 之 IR 完全通過。"""
    from src.visual.blueprints import default_params

    ir_with_params = copy.deepcopy(VALID_IR_SAMPLE)
    for scene in ir_with_params["scenes"]:
        scene["params"] = default_params(scene["blueprint"])
        scene["duration_sec"] = 6

    ok, code = validate_ir(ir_with_params)
    assert ok is True
    assert code == "ok"


def test_ir_scene_params_errors_rejected():
    """Phase 30 Task 2: 驗證 scene.params 各種規格或文字違規被拒絕並回傳對應代碼。"""
    # 1. 未知鍵 -> param_error
    ir_bad_key = copy.deepcopy(VALID_IR_SAMPLE)
    ir_bad_key["scenes"][0]["params"] = {"particles": 5, "unknown_field": True}
    ok, code = validate_ir(ir_bad_key)
    assert ok is False
    assert code == "param_error"

    # 2. 顏色填入 hex -> param_error
    ir_bad_color = copy.deepcopy(VALID_IR_SAMPLE)
    ir_bad_color["scenes"][0]["params"] = {"source": {"fill": "#fff"}}
    ok, code = validate_ir(ir_bad_color)
    assert ok is False
    assert code == "param_error"

    # 3. 超出數值範圍 -> param_error
    ir_bad_num = copy.deepcopy(VALID_IR_SAMPLE)
    ir_bad_num["scenes"][0]["params"] = {"particles": 99}
    ok, code = validate_ir(ir_bad_num)
    assert ok is False
    assert code == "param_error"

    # 4. blueprint 與 params 欄位不符
    ir_mismatch = copy.deepcopy(VALID_IR_SAMPLE)
    ir_mismatch["scenes"][0]["params"] = {"units": 3}  # timeline 欄位放在 process_diagram
    ok, code = validate_ir(ir_mismatch)
    assert ok is False
    assert code == "param_error"

    # 5. params 非 dict
    ir_non_dict = copy.deepcopy(VALID_IR_SAMPLE)
    ir_non_dict["scenes"][0]["params"] = "bad"
    ok, code = validate_ir(ir_non_dict)
    assert ok is False
    assert code == "param_error"


def test_ir_scene_duration_sec_bounds():
    """Phase 30 Task 2: 驗證 duration_sec 必須為 4..12 整數，超範圍或型別不符回 param_error。"""
    # 邊界 4 與 12 通過
    ir_ok4 = copy.deepcopy(VALID_IR_SAMPLE)
    ir_ok4["scenes"][0]["duration_sec"] = 4
    assert validate_ir(ir_ok4) == (True, "ok")

    ir_ok12 = copy.deepcopy(VALID_IR_SAMPLE)
    ir_ok12["scenes"][0]["duration_sec"] = 12
    assert validate_ir(ir_ok12) == (True, "ok")

    # 超界 3 與 13 拒絕
    ir_bad3 = copy.deepcopy(VALID_IR_SAMPLE)
    ir_bad3["scenes"][0]["duration_sec"] = 3
    assert validate_ir(ir_bad3) == (False, "param_error")

    ir_bad13 = copy.deepcopy(VALID_IR_SAMPLE)
    ir_bad13["scenes"][0]["duration_sec"] = 13
    assert validate_ir(ir_bad13) == (False, "param_error")

    # 型別錯誤（字串、布林）
    ir_bad_str = copy.deepcopy(VALID_IR_SAMPLE)
    ir_bad_str["scenes"][0]["duration_sec"] = "6"
    assert validate_ir(ir_bad_str) == (False, "param_error")

    ir_bad_bool = copy.deepcopy(VALID_IR_SAMPLE)
    ir_bad_bool["scenes"][0]["duration_sec"] = True
    assert validate_ir(ir_bad_bool) == (False, "param_error")


def test_ir_scene_extra_keys_rejected():
    """Phase 30 Task 2: 驗證 scene 包含 params / duration_sec 以外之未知鍵回 schema_error。"""
    ir_extra = copy.deepcopy(VALID_IR_SAMPLE)
    ir_extra["scenes"][0]["extra_unsupported"] = 123
    assert validate_ir(ir_extra) == (False, "schema_error")

