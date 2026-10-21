"""
Phase 30 Task 1: 視覺解說卡 Blueprint 參數規格單一來源與驗證測試。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import pytest

from src.visual.blueprints import (
    BLUEPRINTS,
    PALETTE_TOKENS,
    default_params,
    merge_defaults,
    validate_params,
)


def test_palette_tokens_list():
    """驗證調色盤代號清單包含所有指定基礎代號。"""
    required_tokens = {
        "fat",
        "oil",
        "blood",
        "skin",
        "neutral",
        "accent",
        "warn",
        "ok",
        "gel",
        "pale",
    }
    assert required_tokens.issubset(set(PALETTE_TOKENS))


def test_blueprints_registry_completeness():
    """驗證註冊表包含三種基礎模板。"""
    assert "process_diagram" in BLUEPRINTS
    assert "contrast" in BLUEPRINTS
    assert "timeline" in BLUEPRINTS


def test_default_params_self_validation():
    """驗證各 blueprint 的預設參數自身皆完全通過驗證。"""
    for bp in BLUEPRINTS:
        dp = default_params(bp)
        ok, code = validate_params(bp, dp)
        assert ok is True, f"Blueprint {bp} default params 驗證失敗: {code}"
        assert code == "ok"


def test_default_params_returns_deep_copy():
    """驗證 default_params 回傳獨立深複本，修改回傳值不污染註冊表或後續呼叫。"""
    dp1 = default_params("timeline")
    dp1["units"] = 999
    dp1["milestones"].append("污染項")

    dp2 = default_params("timeline")
    assert dp2["units"] != 999
    assert len(dp2["milestones"]) == 3
    assert "污染項" not in dp2["milestones"]


def test_merge_defaults_with_test_vectors():
    """驗證 merge_defaults 完全符合 visual_merge_vectors.json 規範。"""
    vectors_path = Path("tests/fixtures/visual_merge_vectors.json")
    assert vectors_path.exists(), "tests/fixtures/visual_merge_vectors.json 必須存在"

    vectors = json.loads(vectors_path.read_text(encoding="utf-8"))
    assert len(vectors) >= 8, "測試向量至少需有 8 組"

    for idx, vec in enumerate(vectors):
        bp = vec["blueprint"]
        inp = copy.deepcopy(vec["input_params"])
        expected = vec["expected"]

        merged = merge_defaults(bp, inp)
        assert merged == expected, f"Vector #{idx} ({vec.get('description')}) 合併結果與預期不符！\nGot: {merged}\nExpected: {expected}"

        # 驗證輸入參數未被破壞 (immutability)
        assert inp == vec["input_params"], f"Vector #{idx} 輸入參數遭原地修改！"


def test_validate_params_none_and_non_dict():
    """驗證 None 視為合格（預設），非 dict 視為 param_error。"""
    assert validate_params("timeline", None) == (True, "ok")
    assert validate_params("timeline", "not a dict") == (False, "param_error")
    assert validate_params("timeline", [1, 2, 3]) == (False, "param_error")


def test_validate_params_unknown_blueprint():
    """驗證未知 blueprint 回傳 unknown_blueprint。"""
    assert validate_params("non_existent_bp", {}) == (False, "unknown_blueprint")
    assert validate_params("unknown", None) == (False, "unknown_blueprint")


def test_validate_params_unknown_key_rejected():
    """驗證頂層或巢狀未知鍵一律拒絕（param_error）。"""
    # 頂層未知鍵
    assert validate_params("timeline", {"unknown_key": 123}) == (False, "param_error")

    # 巢狀未知鍵 (contrast.left)
    assert validate_params("contrast", {"left": {"title": "標題", "extra_bad": True}}) == (False, "param_error")

    # 巢狀未知鍵 (process_diagram.source)
    assert validate_params("process_diagram", {"source": {"label": "正常", "color": "red"}}) == (False, "param_error")


def test_validate_params_arbitrary_color_rejected():
    """驗證非 PALETTE_TOKENS 的任意色碼（#hex 或 css 顏色）被拒絕。"""
    # hex color
    assert validate_params("process_diagram", {"source": {"fill": "#ff0000"}}) == (False, "param_error")
    assert validate_params("process_diagram", {"source": {"fill": "#fff"}}) == (False, "param_error")

    # css color name
    assert validate_params("process_diagram", {"source": {"fill": "red"}}) == (False, "param_error")
    assert validate_params("process_diagram", {"source": {"fill": "rgb(0,0,0)"}}) == (False, "param_error")


def test_validate_params_process_diagram_bounds():
    """驗證 process_diagram 各欄位邊界與型別。"""
    # particles 4..12
    assert validate_params("process_diagram", {"particles": 4}) == (True, "ok")
    assert validate_params("process_diagram", {"particles": 12}) == (True, "ok")
    assert validate_params("process_diagram", {"particles": 3}) == (False, "param_error")
    assert validate_params("process_diagram", {"particles": 13}) == (False, "param_error")
    assert validate_params("process_diagram", {"particles": "5"}) == (False, "param_error")

    # source.label text <= 8
    assert validate_params("process_diagram", {"source": {"label": "八個中文字剛好滿"}}) == (True, "ok")
    assert validate_params("process_diagram", {"source": {"label": "九個中文字超出長度"}}) == (False, "param_error")
    assert validate_params("process_diagram", {"source": {"label": ""}}) == (False, "schema_error")

    # container_layers list 2..4
    layer = {"label": "層", "fill": "fat", "weight": 2, "keep": True}
    assert validate_params("process_diagram", {"container_layers": [layer, layer]}) == (True, "ok")
    assert validate_params("process_diagram", {"container_layers": [layer, layer, layer, layer]}) == (True, "ok")
    assert validate_params("process_diagram", {"container_layers": [layer]}) == (False, "param_error")
    assert validate_params("process_diagram", {"container_layers": [layer] * 5}) == (False, "param_error")

    # layer.weight 1..5
    bad_weight_low = {"label": "層", "fill": "fat", "weight": 0, "keep": True}
    bad_weight_high = {"label": "層", "fill": "fat", "weight": 6, "keep": True}
    assert validate_params("process_diagram", {"container_layers": [bad_weight_low, layer]}) == (False, "param_error")
    assert validate_params("process_diagram", {"container_layers": [bad_weight_high, layer]}) == (False, "param_error")

    # layer.keep must be bool
    bad_keep = {"label": "層", "fill": "fat", "weight": 2, "keep": "yes"}
    assert validate_params("process_diagram", {"container_layers": [bad_keep, layer]}) == (False, "param_error")

    # step_labels exactly 3
    assert validate_params("process_diagram", {"step_labels": ["一", "二", "三"]}) == (True, "ok")
    assert validate_params("process_diagram", {"step_labels": ["一", "二"]}) == (False, "param_error")
    assert validate_params("process_diagram", {"step_labels": ["一", "二", "三", "四"]}) == (False, "param_error")
    assert validate_params("process_diagram", {"step_labels": ["超過十個字元的步驟名稱測試", "二", "三"]}) == (False, "param_error")


def test_validate_params_contrast_bounds():
    """驗證 contrast 各欄位邊界、列舉與型別。"""
    # left.mode: enum[mass, scattered, wide_incision, thermal_spread]
    assert validate_params("contrast", {"left": {"mode": "mass"}}) == (True, "ok")
    assert validate_params("contrast", {"left": {"mode": "scattered"}}) == (True, "ok")
    assert validate_params("contrast", {"left": {"mode": "wide_incision"}}) == (True, "ok")
    assert validate_params("contrast", {"left": {"mode": "thermal_spread"}}) == (True, "ok")
    assert validate_params("contrast", {"left": {"mode": "layered"}}) == (False, "param_error")

    # right.mode: enum[layered, mass, minimal_incision, targeted_energy]
    assert validate_params("contrast", {"right": {"mode": "layered"}}) == (True, "ok")
    assert validate_params("contrast", {"right": {"mode": "mass"}}) == (True, "ok")
    assert validate_params("contrast", {"right": {"mode": "minimal_incision"}}) == (True, "ok")
    assert validate_params("contrast", {"right": {"mode": "targeted_energy"}}) == (True, "ok")
    assert validate_params("contrast", {"right": {"mode": "scattered"}}) == (False, "param_error")

    # right.rows 1..4
    assert validate_params("contrast", {"right": {"rows": 1}}) == (True, "ok")
    assert validate_params("contrast", {"right": {"rows": 4}}) == (True, "ok")
    assert validate_params("contrast", {"right": {"rows": 0}}) == (False, "param_error")
    assert validate_params("contrast", {"right": {"rows": 5}}) == (False, "param_error")

    # right.per_row 3..8
    assert validate_params("contrast", {"right": {"per_row": 3}}) == (True, "ok")
    assert validate_params("contrast", {"right": {"per_row": 8}}) == (True, "ok")
    assert validate_params("contrast", {"right": {"per_row": 2}}) == (False, "param_error")
    assert validate_params("contrast", {"right": {"per_row": 9}}) == (False, "param_error")

    # left.title <= 8, left.note <= 14
    assert validate_params("contrast", {"left": {"title": "八個字剛剛好滿"}}) == (True, "ok")
    assert validate_params("contrast", {"left": {"title": "九個字超過標題上限"}}) == (False, "param_error")
    assert validate_params("contrast", {"left": {"note": "剛好十四個中文字的正常說明句"}}) == (True, "ok")
    assert validate_params("contrast", {"left": {"note": "十五個中文字說明超過備註規定長度"}}) == (False, "param_error")


def test_validate_params_timeline_bounds():
    """驗證 timeline 各欄位邊界與列舉。"""
    # milestones 3..3, text <= 8
    assert validate_params("timeline", {"milestones": ["一", "二", "三"]}) == (True, "ok")
    assert validate_params("timeline", {"milestones": ["一", "二"]}) == (False, "param_error")
    assert validate_params("timeline", {"milestones": ["一", "二", "三", "四"]}) == (False, "param_error")
    assert validate_params("timeline", {"milestones": ["九個中文字超過長度", "二", "三"]}) == (False, "param_error")

    # unit_effect enum[mature, fade, steady]
    assert validate_params("timeline", {"unit_effect": "mature"}) == (True, "ok")
    assert validate_params("timeline", {"unit_effect": "fade"}) == (True, "ok")
    assert validate_params("timeline", {"unit_effect": "steady"}) == (True, "ok")
    assert validate_params("timeline", {"unit_effect": "glow"}) == (False, "param_error")

    # connectors enum[vessels, none, wound_healing, collagen_remodeling]
    assert validate_params("timeline", {"connectors": "vessels"}) == (True, "ok")
    assert validate_params("timeline", {"connectors": "none"}) == (True, "ok")
    assert validate_params("timeline", {"connectors": "wound_healing"}) == (True, "ok")
    assert validate_params("timeline", {"connectors": "collagen_remodeling"}) == (True, "ok")
    assert validate_params("timeline", {"connectors": "lines"}) == (False, "param_error")

    # units 2..5
    assert validate_params("timeline", {"units": 2}) == (True, "ok")
    assert validate_params("timeline", {"units": 5}) == (True, "ok")
    assert validate_params("timeline", {"units": 1}) == (False, "param_error")
    assert validate_params("timeline", {"units": 6}) == (False, "param_error")


def test_validate_params_text_security_and_compliance():
    """驗證文字欄位重用 validate_visual_text 檢驗安全、禁詞、簡體與價格。"""
    # 1. HTML 標籤
    assert validate_params("timeline", {"milestones": ["<b>第一</b>", "第二", "第三"]}) == (False, "text_unsafe")

    # 2. 網址
    assert validate_params("contrast", {"left": {"title": "http://x"}}) == (False, "text_unsafe")

    # 3. 視覺卡專屬禁詞「永久」
    assert validate_params("contrast", {"left": {"note": "效果永久維持"}}) == (False, "forbidden_phrase")

    # 4. 價格洩漏
    assert validate_params("process_diagram", {"source": {"label": "一次5000元"}}) == (False, "price_leak")

    # 5. 簡體中文
    assert validate_params("timeline", {"milestones": ["第1天", "第7天", "简体字"]}) == (False, "simplified_chinese")


def test_error_code_never_contains_raw_text():
    """驗證 validate_params 任何回傳代碼皆為固定英文代碼，絕不洩漏原文。"""
    raw_sensitive = "http://bad-url.com/hacked?q=secret12345"
    ok, code = validate_params("contrast", {"left": {"title": raw_sensitive}})
    assert ok is False
    assert raw_sensitive not in code
    assert code == "text_unsafe"


# ---------------------------------------------------------------------------
# 2026-10-19 補充：對照場景與時間軸的主題專屬內容必須是參數（玻尿酸驗證主題暴露）
# ---------------------------------------------------------------------------

def test_contrast_and_timeline_topic_specific_text_and_color_are_params():
    """core_effect／core_label／footnote／unit_fill 皆為受驗證的參數，預設值保留脂肪移植畫面。"""
    d = default_params("contrast")
    assert d["left"]["core_effect"] == "dim" and d["left"]["core_label"] == "中心缺血"
    assert d["left"]["footnote"] and d["right"]["footnote"]
    assert d["left"]["unit_fill"] == "fat" and d["right"]["unit_fill"] == "fat"
    assert default_params("timeline")["unit_fill"] == "fat"

    ok, code = validate_params("contrast", {"left": {"core_effect": "none", "footnote": "集中放置：易顯得不自然", "unit_fill": "gel"},
                                            "right": {"footnote": "分散放置：貼近自然", "unit_fill": "gel"}})
    assert ok is True, code
    assert validate_params("timeline", {"unit_fill": "gel"})[0] is True


@pytest.mark.parametrize(
    "bp,params",
    [
        ("contrast", {"left": {"core_effect": "blink"}}),            # 列舉外
        ("contrast", {"left": {"unit_fill": "#ff0000"}}),            # 任意色碼
        ("contrast", {"right": {"unit_fill": "red"}}),               # 非調色盤代號
        ("contrast", {"left": {"footnote": "字" * 17}}),             # 超過長度
        ("contrast", {"right": {"footnote": "永久有效"}}),            # 禁詞
        ("contrast", {"left": {"core_label": "<b>缺血</b>"}}),        # HTML
        ("timeline", {"unit_fill": "#fff"}),
    ],
)
def test_new_topic_params_reject_unsafe_values(bp, params):
    ok, code = validate_params(bp, params)
    assert ok is False
    assert code in {"param_error", "text_unsafe", "forbidden_phrase", "schema_error"}


def test_surgical_facelift_and_platysmaplasty_blueprints():
    """驗證 SMAS 深層拉皮與天鵝頸闊頸肌馬甲縫合專屬外科藍圖。"""
    assert "deep_plane_facelift" in BLUEPRINTS
    assert "corset_platysmaplasty" in BLUEPRINTS

    dp_face = default_params("deep_plane_facelift")
    assert dp_face["smas_label"] == "SMAS筋膜瓣"
    assert dp_face["anchor_label"] == "骨膜錨定點"
    assert len(dp_face["layer_labels"]) == 3
    ok1, code1 = validate_params("deep_plane_facelift", dp_face)
    assert ok1 is True, code1

    dp_plat = default_params("corset_platysmaplasty")
    assert dp_plat["muscle_label"] == "兩側闊頸肌"
    assert dp_plat["suture_label"] == "馬甲式對縫"
    assert len(dp_plat["layer_labels"]) == 3
    ok2, code2 = validate_params("corset_platysmaplasty", dp_plat)
    assert ok2 is True, code2
