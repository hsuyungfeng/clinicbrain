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
                    # 傳統處置／病理風險對照（Phase 33）：體雕、眼整、鼻整、隆乳、微整五大專科
                    "mode": {"type": "enum", "values": (
                        "mass", "scattered", "wide_incision", "thermal_spread",
                        "tissue_trauma_torn_vessel", "scar_contracture_ectropion", "silicone_extrusion_erythema",
                        "capsular_contracture_ball", "nodule_clumping",
                    )},
                    "core_effect": {"type": "enum", "values": ("dim", "none")},
                    "core_label": {"type": "text", "max_len": 8},
                    "footnote": {"type": "text", "max_len": 16},
                    "unit_fill": {"type": "palette"},
                },
            },
            "right": {
                "type": "object",
                "fields": {
                    "title": {"type": "text", "max_len": 8},
                    "note": {"type": "text", "max_len": 14},
                    # 微創優勢／精準處置（Phase 33）
                    "mode": {"type": "enum", "values": (
                        "layered", "mass", "minimal_incision", "targeted_energy",
                        "ultrasonic_emulsification", "transconjunctival_fat_reposition", "cartilage_triangular_strut",
                        "dual_plane_natural_teardrop", "micro_droplet_diffusion",
                    )},
                    "rows": {"type": "int", "min": 1, "max": 4},
                    "per_row": {"type": "int", "min": 3, "max": 8},
                    "footnote": {"type": "text", "max_len": 16},
                    "unit_fill": {"type": "palette"},
                },
            },
        },
        "defaults": {
            "left": {
                "title": "單處過量",
                "note": "較易出現硬塊",
                "mode": "mass",
                "core_effect": "dim",
                "core_label": "中心缺血",
                "footnote": "單處集中：不易獲取充足養分",
                "unit_fill": "fat",
            },
            "right": {
                "title": "分層少量",
                "note": "接觸周圍組織",
                "mode": "layered",
                "rows": 3,
                "per_row": 5,
                "footnote": "多層分散：接觸周圍健康組織",
                "unit_fill": "fat",
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
            "unit_effect": {"type": "enum", "values": ("mature", "fade", "steady", "glow_restored")},
            # 生理修復歷程（Phase 33）：骨骼、退瘀、疤痕、感覺神經、皮膚緊緻回縮
            "connectors": {"type": "enum", "values": (
                "vessels", "none", "wound_healing", "collagen_remodeling",
                "bone_healing", "bruise_metabolism", "scar_maturation", "nerve_regeneration", "skin_retraction",
            )},
            "units": {"type": "int", "min": 2, "max": 5},
            "unit_fill": {"type": "palette"},
        },
        "defaults": {
            "milestones": ["術後初期", "微血管長入", "狀態穩定"],
            "unit_effect": "mature",
            "connectors": "vessels",
            "units": 3,
            "unit_fill": "fat",
        },
    },
    "skin_energy": {
        "params": {
            "mode": {"type": "enum", "values": ("focused", "volumetric")},
            "probe_label": {"type": "text", "max_len": 8},
            "layer_labels": {
                "type": "list",
                "min": 3,
                "max": 3,
                "item": {"type": "text", "max_len": 8},
            },
            "focal_points": {"type": "int", "min": 3, "max": 7},
            "energy_fill": {"type": "palette"},
            "step_labels": {
                "type": "list",
                "min": 3,
                "max": 3,
                "item": {"type": "text", "max_len": 10},
            },
        },
        "defaults": {
            "mode": "focused",
            "probe_label": "聚焦探頭",
            "layer_labels": ["表皮層", "真皮膠原層", "筋膜層"],
            "focal_points": 5,
            "energy_fill": "accent",
            "step_labels": ["能量精準傳遞", "深層熱凝結點", "膠原緊縮拉提"],
        },
    },
    "laser_action": {
        "params": {
            "mode": {"type": "enum", "values": ("shatter", "fractional")},
            "beam_label": {"type": "text", "max_len": 8},
            "target_label": {"type": "text", "max_len": 8},
            "layer_labels": {
                "type": "list",
                "min": 2,
                "max": 2,
                "item": {"type": "text", "max_len": 8},
            },
            "beam_fill": {"type": "palette"},
            "step_labels": {
                "type": "list",
                "min": 3,
                "max": 3,
                "item": {"type": "text", "max_len": 10},
            },
        },
        "defaults": {
            "mode": "shatter",
            "beam_label": "皮秒光束",
            "target_label": "色素團塊",
            "layer_labels": ["表皮角質層", "真皮基底層"],
            "beam_fill": "accent",
            "step_labels": ["短脈衝光束照射", "光震波擊碎色素", "微細粉塵代謝"],
        },
    },
    "neuromuscular": {
        "params": {
            "nerve_label": {"type": "text", "max_len": 8},
            "muscle_label": {"type": "text", "max_len": 8},
            "surface_label": {"type": "text", "max_len": 8},
            "blocker_fill": {"type": "palette"},
            "step_labels": {
                "type": "list",
                "min": 3,
                "max": 3,
                "item": {"type": "text", "max_len": 10},
            },
        },
        "defaults": {
            "nerve_label": "運動神經末梢",
            "muscle_label": "過度收縮肌肉",
            "surface_label": "動態表情皺紋",
            "blocker_fill": "ok",
            "step_labels": ["精準微量注射", "調節神經訊號", "肌肉放鬆撫平"],
        },
    },
    "dermal_support": {
        "params": {
            "filler_label": {"type": "text", "max_len": 8},
            "layer_labels": {
                "type": "list",
                "min": 2,
                "max": 2,
                "item": {"type": "text", "max_len": 8},
            },
            "droplets": {"type": "int", "min": 4, "max": 8},
            "filler_fill": {"type": "palette"},
            "step_labels": {
                "type": "list",
                "min": 3,
                "max": 3,
                "item": {"type": "text", "max_len": 10},
            },
        },
        "defaults": {
            "filler_label": "親水凝膠",
            "layer_labels": ["表皮輪廓層", "真皮皮下層"],
            "droplets": 6,
            "filler_fill": "gel",
            "step_labels": ["評估凹陷部位", "深淺分層注入", "立體支撐平順"],
        },
    },
    "cyst_excision": {
        "params": {
            "cyst_label": {"type": "text", "max_len": 8},
            "sac_label": {"type": "text", "max_len": 8},
            "core_label": {"type": "text", "max_len": 8},
            "layer_labels": {
                "type": "list",
                "min": 2,
                "max": 2,
                "item": {"type": "text", "max_len": 8},
            },
            "sac_fill": {"type": "palette"},
            "step_labels": {
                "type": "list",
                "min": 3,
                "max": 3,
                "item": {"type": "text", "max_len": 10},
            },
        },
        "defaults": {
            "cyst_label": "粉瘤囊腫",
            "sac_label": "完整包膜",
            "core_label": "角質分泌物",
            "layer_labels": ["表皮層", "皮下真皮層"],
            "sac_fill": "accent",
            "step_labels": ["微創切口定位", "減壓排空引流", "完整囊袋剝離"],
        },
    },
    "nail_matrix": {
        "params": {
            "nail_label": {"type": "text", "max_len": 8},
            "fold_label": {"type": "text", "max_len": 8},
            "spicule_label": {"type": "text", "max_len": 8},
            "matrix_label": {"type": "text", "max_len": 8},
            "matrix_fill": {"type": "palette"},
            "step_labels": {
                "type": "list",
                "min": 3,
                "max": 3,
                "item": {"type": "text", "max_len": 10},
            },
        },
        "defaults": {
            "nail_label": "趾甲板",
            "fold_label": "側甲襞",
            "spicule_label": "嵌甲尖刺",
            "matrix_label": "甲基質生長板",
            "matrix_fill": "warn",
            "step_labels": ["嵌甲邊緣游離", "縱向側切移除", "甲床基質重整"],
        },
    },
    "subdermal_curettage": {
        "params": {
            "target_label": {"type": "text", "max_len": 8},
            "shaver_label": {"type": "text", "max_len": 8},
            "layer_labels": {
                "type": "list",
                "min": 2,
                "max": 2,
                "item": {"type": "text", "max_len": 8},
            },
            "tool_fill": {"type": "palette"},
            "step_labels": {
                "type": "list",
                "min": 3,
                "max": 3,
                "item": {"type": "text", "max_len": 10},
            },
        },
        "defaults": {
            "target_label": "頂漿腺組織",
            "shaver_label": "微創旋轉刀",
            "layer_labels": ["真皮深層", "皮下脂肪層"],
            "tool_fill": "accent",
            "step_labels": ["微創切口入路", "旋轉刮除分離", "負壓即時抽吸"],
        },
    },
    "deep_plane_facelift": {
        "params": {
            "layer_labels": {
                "type": "list",
                "min": 3,
                "max": 3,
                "item": {"type": "text", "max_len": 8},
            },
            "smas_label": {"type": "text", "max_len": 8},
            "anchor_label": {"type": "text", "max_len": 8},
            "ligament_label": {"type": "text", "max_len": 8},
            "suture_fill": {"type": "palette"},
            "step_labels": {
                "type": "list",
                "min": 3,
                "max": 3,
                "item": {"type": "text", "max_len": 10},
            },
        },
        "defaults": {
            "layer_labels": ["表皮輪廓層", "SMAS筋膜層", "堅韌骨膜基底"],
            "smas_label": "SMAS筋膜瓣",
            "anchor_label": "骨膜錨定點",
            "ligament_label": "維持韌帶",
            "suture_fill": "accent",
            "step_labels": ["微創切口解離韌帶", "45度提拉骨膜錨定", "表皮零張力無壓縫合"],
        },
    },
    "corset_platysmaplasty": {
        "params": {
            "layer_labels": {
                "type": "list",
                "min": 3,
                "max": 3,
                "item": {"type": "text", "max_len": 8},
            },
            "muscle_label": {"type": "text", "max_len": 8},
            "fat_label": {"type": "text", "max_len": 8},
            "suture_label": {"type": "text", "max_len": 8},
            "suture_fill": {"type": "palette"},
            "step_labels": {
                "type": "list",
                "min": 3,
                "max": 3,
                "item": {"type": "text", "max_len": 10},
            },
        },
        "defaults": {
            "layer_labels": ["表皮與皮下層", "闊頸肌與深層墊", "頸前筋膜深層"],
            "muscle_label": "兩側闊頸肌",
            "fat_label": "深層脂肪墊",
            "suture_label": "馬甲式對縫",
            "suture_fill": "accent",
            "step_labels": ["微創入路修整脂肪", "闊頸肌馬甲式對縫", "緊緻吊帶俐落頸角"],
        },
    },
    "surgical_action": {
        "params": {
            "anatomy_target": {
                "type": "enum",
                "values": (
                    "mandible",
                    "smas_face",
                    "platysma_neck",
                    "malar_bone",
                    "submental",
                    "general_surgery",
                ),
            },
            "bone_label": {"type": "text", "max_len": 8},
            "nerve_label": {"type": "text", "max_len": 8},
            "nerve_status": {"type": "enum", "values": ("protected", "normal", "decompressed")},
            "incision_label": {"type": "text", "max_len": 8},
            "fixation_label": {"type": "text", "max_len": 8},
            "bone_shift_mm": {"type": "int", "min": 0, "max": 15},
            "protect_nerve": {"type": "bool"},
            "step_labels": {
                "type": "list",
                "min": 3,
                "max": 3,
                "item": {"type": "text", "max_len": 10},
            },
        },
        "defaults": {
            "anatomy_target": "mandible",
            "bone_label": "下顎骨端",
            "nerve_label": "頦神經",
            "nerve_status": "protected",
            "incision_label": "口內隱痕",
            "fixation_label": "純鈦板釘",
            "bone_shift_mm": 6,
            "protect_nerve": True,
            "step_labels": ["口內隱痕切開", "保護神經截骨", "純鈦板釘固定"],
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


def enum_values(blueprint: str, field: str, side: str | None = None) -> tuple[str, ...]:
    """回傳藍圖某列舉欄位的合法值（單一來源，供自癒整形器與測試共用）。

    side 為 'left' 或 'right' 時讀取 object 子欄位（如 contrast.left.mode）；否則讀取頂層欄位。
    """
    spec = BLUEPRINTS[blueprint]["params"]
    if side is not None:
        spec = spec[side]["fields"]
    values = spec[field]["values"]
    return tuple(values)
