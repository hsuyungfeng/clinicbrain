"""
視覺解說卡 Blueprint 參數規格單一來源與驗證模組 (Phase 30 P30-PARAMS)。

設計原則：
1. 單一來源：所有 blueprint 名稱、參數規格、預設值、調色盤代號皆定義於此。
2. 參數型別受限：僅支援 enum、int(有界)、text(長度有界)、palette、list(有界)、object、bool。
   嚴禁任意顏色字串、HTML、SVG、網址、程式碼。
3. 確定性合併：merge_defaults 語意為物件欄位遞迴合併、list 欄位整批取代、None 為全預設。
4. 零原始文字洩漏：驗證失敗一律回傳結構化英文代碼，丟棄任何含原文的錯誤訊息。
"""

from __future__ import annotations

import copy
from typing import Any, Tuple

# 固定調色盤代號清單（實際 hex 色碼定義於前端 CSS / JS 引擎）
PALETTE_TOKENS: tuple[str, ...] = (
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
)

# Blueprint 規格定義與預設值註冊表
BLUEPRINTS: dict[str, dict[str, Any]] = {
    "process_diagram": {
        "params": {
            "source": {
                "type": "object",
                "fields": {
                    "label": {"type": "text", "max_len": 8},
                    "fill": {"type": "palette"},
                },
            },
            "particles": {"type": "int", "min": 4, "max": 12},
            "container_layers": {
                "type": "list",
                "min": 2,
                "max": 4,
                "item": {
                    "type": "object",
                    "fields": {
                        "label": {"type": "text", "max_len": 6},
                        "fill": {"type": "palette"},
                        "weight": {"type": "int", "min": 1, "max": 5},
                        "keep": {"type": "bool"},
                    },
                },
            },
            "step_labels": {
                "type": "list",
                "min": 3,
                "max": 3,
                "item": {"type": "text", "max_len": 10},
            },
        },
        "defaults": {
            "source": {"label": "皮下脂肪", "fill": "skin"},
            "particles": 5,
            "container_layers": [
                {"label": "油滴", "fill": "oil", "weight": 2, "keep": False},
                {"label": "純化脂肪", "fill": "fat", "weight": 3, "keep": True},
                {"label": "血水", "fill": "blood", "weight": 2, "keep": False},
            ],
            "step_labels": ["微創抽取", "離心分層", "保留純化脂肪"],
        },
    },
    "contrast": {
        "params": {
            "left": {
                "type": "object",
                "fields": {
                    "title": {"type": "text", "max_len": 8},
                    "note": {"type": "text", "max_len": 14},
                    "mode": {"type": "enum", "values": ("mass", "scattered")},
                },
            },
            "right": {
                "type": "object",
                "fields": {
                    "title": {"type": "text", "max_len": 8},
                    "note": {"type": "text", "max_len": 14},
                    "mode": {"type": "enum", "values": ("layered", "mass")},
                    "rows": {"type": "int", "min": 1, "max": 4},
                    "per_row": {"type": "int", "min": 3, "max": 8},
                },
            },
        },
        "defaults": {
            "left": {
                "title": "單處過量",
                "note": "較易出現硬塊",
                "mode": "mass",
            },
            "right": {
                "title": "分層少量",
                "note": "接觸周圍組織",
                "mode": "layered",
                "rows": 3,
                "per_row": 5,
            },
        },
    },
    "timeline": {
        "params": {
            "milestones": {
                "type": "list",
                "min": 3,
                "max": 3,
                "item": {"type": "text", "max_len": 8},
            },
            "unit_effect": {"type": "enum", "values": ("mature", "fade", "steady")},
            "connectors": {"type": "enum", "values": ("vessels", "none")},
            "units": {"type": "int", "min": 2, "max": 5},
        },
        "defaults": {
            "milestones": ["術後初期", "微血管長入", "狀態穩定"],
            "unit_effect": "mature",
            "connectors": "vessels",
            "units": 3,
        },
    },
}


def default_params(blueprint: str) -> dict[str, Any]:
    """取得指定 blueprint 的預設參數深複本。"""
    if blueprint not in BLUEPRINTS:
        raise KeyError(f"Unknown blueprint: {blueprint}")
    return copy.deepcopy(BLUEPRINTS[blueprint]["defaults"])


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """遞迴合併物件欄位；list 與純量由 override 整批取代。"""
    res = copy.deepcopy(base)
    for k, v in override.items():
        if k in res and isinstance(res[k], dict) and isinstance(v, dict):
            res[k] = _merge_dicts(res[k], v)
        else:
            res[k] = copy.deepcopy(v)
    return res


def merge_defaults(blueprint: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """將使用端提供的部分 params 與該 blueprint 的預設值合併。

    語意規範：
    1. None 或空字典 -> 回傳完整預設值。
    2. 物件欄位（dict）遞迴逐欄合併。
    3. list 欄位整批取代（若提供則取代整份預設 list）。
    4. 回傳為獨立新物件，絕不改動輸入或註冊表。
    """
    defaults = default_params(blueprint)
    if not params:
        return defaults
    return _merge_dicts(defaults, params)


def _validate_value(spec: dict[str, Any], value: Any, is_merged_check: bool = False) -> Tuple[bool, str]:
    """依據型別規格檢驗單一值或結構。"""
    stype = spec.get("type")

    if stype == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            return False, "param_error"
        if not (spec["min"] <= value <= spec["max"]):
            return False, "param_error"
        return True, "ok"

    elif stype == "bool":
        if not isinstance(value, bool):
            return False, "param_error"
        return True, "ok"

    elif stype == "enum":
        if not isinstance(value, str) or value not in spec.get("values", ()):
            return False, "param_error"
        return True, "ok"

    elif stype == "palette":
        if not isinstance(value, str) or value not in PALETTE_TOKENS:
            return False, "param_error"
        return True, "ok"

    elif stype == "text":
        if not isinstance(value, str):
            return False, "schema_error"
        t = value.strip()
        if not t:
            return False, "schema_error"

        # 優先檢核文字安全、禁詞與價格合規性
        from src.visual.ir import validate_visual_text

        ok, code = validate_visual_text(value)
        if not ok:
            return False, code

        if not (1 <= len(value) <= spec.get("max_len", 100)):
            return False, "param_error"

        return True, "ok"

    elif stype == "object":
        if not isinstance(value, dict):
            return False, "param_error"

        fields = spec.get("fields", {})
        # 未知鍵一律拒絕
        for k in value.keys():
            if k not in fields:
                return False, "param_error"

        # 若是合併後的檢查，所有 required 欄位必須到齊
        if is_merged_check:
            for fk in fields.keys():
                if fk not in value:
                    return False, "param_error"

        for k, v in value.items():
            ok, code = _validate_value(fields[k], v, is_merged_check=is_merged_check)
            if not ok:
                return False, code
        return True, "ok"

    elif stype == "list":
        if not isinstance(value, list) or isinstance(value, (str, bytes)):
            return False, "param_error"
        if not (spec["min"] <= len(value) <= spec["max"]):
            return False, "param_error"

        item_spec = spec.get("item", {})
        for item in value:
            ok, code = _validate_value(item_spec, item, is_merged_check=is_merged_check)
            if not ok:
                return False, code
        return True, "ok"

    return False, "param_error"


def validate_params(blueprint: str, params: Any) -> Tuple[bool, str]:
    """檢驗指定 blueprint 之 params 的規格合法性與文字合規性。

    驗證流程：
    1. blueprint 必須存在於 BLUEPRINTS 註冊表。
    2. params 為 None 視為全預設，直接回傳 (True, "ok")。
    3. params 必須為 dict。
    4. 頂層鍵不能包含未知鍵。
    5. 逐一檢驗 params 中已提供的欄位（邊界、列舉、調色盤代號、validate_visual_text）。
    6. 執行 merge_defaults 後再次完整檢驗全量參數結構。
    """
    if blueprint not in BLUEPRINTS:
        return False, "unknown_blueprint"

    if params is None:
        return True, "ok"

    if not isinstance(params, dict):
        return False, "param_error"

    schema = BLUEPRINTS[blueprint]["params"]

    # 1. 檢查頂層未知鍵
    for k in params.keys():
        if k not in schema:
            return False, "param_error"

    # 2. 檢驗已提供之欄位
    for k, v in params.items():
        ok, code = _validate_value(schema[k], v, is_merged_check=False)
        if not ok:
            return False, code

    # 3. 合併預設值並確保合併後結果具備所有必要欄位且皆完全合法
    try:
        merged = merge_defaults(blueprint, params)
    except Exception:
        return False, "param_error"

    for k, spec in schema.items():
        if k not in merged:
            return False, "param_error"
        ok, code = _validate_value(spec, merged[k], is_merged_check=True)
        if not ok:
            return False, code

    return True, "ok"
