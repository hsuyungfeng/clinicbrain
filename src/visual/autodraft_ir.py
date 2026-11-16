"""
Scene 1 / Scene 2 / Scene 3 視覺 IR 純函式驗證與塑形器（由 autodraft.py 拆出）。
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from src.visual.blueprints import PALETTE_TOKENS, enum_values

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<think>.*", re.DOTALL)
_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

VALID_SCENE1_BLUEPRINTS = (
    "process_diagram",
    "skin_energy",
    "laser_action",
    "neuromuscular",
    "dermal_support",
    "cyst_excision",
    "nail_matrix",
    "subdermal_curettage",
    "deep_plane_facelift",
    "corset_platysmaplasty",
    "surgical_action",
    "pathology_mechanism",
)


def clean_3d_recursive(val: Any) -> Any:
    """醫學專用 3D/4D 縮寫轉換為正體中文「三維」「四維」，避免誤觸零數字硬限制。"""
    if isinstance(val, str):
        val = re.sub(r"\b3[dD]\b|3[dD]", "三維", val)
        val = re.sub(r"\b4[dD]\b|4[dD]", "四維", val)
        return val
    if isinstance(val, dict):
        return {k: clean_3d_recursive(v) for k, v in val.items()}
    if isinstance(val, list):
        return [clean_3d_recursive(item) for item in val]
    return val


def parse_int_val(v: Any, default: int, min_v: int, max_v: int) -> int:
    if isinstance(v, str):
        _cn = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        v = _cn.get(v.strip(), default)
    if not isinstance(v, int) or isinstance(v, bool):
        return default
    return max(min_v, min(max_v, v))


def extract_ir_json(raw: str) -> tuple[Optional[dict[str, Any]], str]:
    """自模型原始輸出萃取並解析 JSON dict。"""
    if not raw or not isinstance(raw, str):
        return None, "empty_output"

    cleaned = _THINK_BLOCK_RE.sub("", raw)
    cleaned = _THINK_OPEN_RE.sub("", cleaned).strip()

    json_str = None
    m = _CODE_BLOCK_RE.search(cleaned)
    if m:
        json_str = m.group(1).strip()
    else:
        s_idx = cleaned.find("{")
        e_idx = cleaned.rfind("}")
        if s_idx != -1 and e_idx != -1 and e_idx > s_idx:
            json_str = cleaned[s_idx : e_idx + 1].strip()

    if not json_str:
        return None, "schema_error"

    try:
        data = json.loads(json_str)
    except Exception:
        return None, "schema_error"

    if not isinstance(data, dict):
        return None, "schema_error"
    return clean_3d_recursive(data), "ok"


def _valid_str_list(val: Any, length: int) -> bool:
    return isinstance(val, list) and len(val) == length and all(isinstance(x, str) and x.strip() for x in val)


def _shape_process_diagram(raw_params: dict[str, Any]) -> Optional[dict[str, Any]]:
    src = raw_params.get("source")
    if not isinstance(src, dict) or not isinstance(src.get("label"), str) or not src["label"].strip():
        return None
    layers = raw_params.get("container_layers")
    if not isinstance(layers, list) or not (2 <= len(layers) <= 4):
        return None
    for layer in layers:
        if not isinstance(layer, dict) or not isinstance(layer.get("label"), str) or not layer["label"].strip():
            return None
    step_lbls = raw_params.get("step_labels")
    if not _valid_str_list(step_lbls, 3):
        return None
    particles = raw_params.get("particles", 6)
    if not isinstance(particles, int) or isinstance(particles, bool) or not (4 <= particles <= 12):
        particles = 6
    s_fill = src.get("fill", "skin")
    if s_fill not in PALETTE_TOKENS:
        s_fill = "skin"
    return {
        "source": {"label": src["label"].strip()[:8], "fill": s_fill},
        "particles": particles,
        "container_layers": [
            {
                "label": l["label"].strip()[:6],
                "fill": l.get("fill", "accent") if l.get("fill") in PALETTE_TOKENS else "accent",
                "weight": int(l.get("weight", 2))
                if isinstance(l.get("weight"), (int, float)) and 1 <= int(l.get("weight", 2)) <= 5
                else 2,
                "keep": bool(l.get("keep", False)),
            }
            for l in layers
        ],
        "step_labels": [s.strip()[:10] for s in step_lbls],
    }


def _shape_skin_energy(raw_params: dict[str, Any]) -> Optional[dict[str, Any]]:
    mode = raw_params.get("mode", "focused")
    if mode not in ("focused", "volumetric"):
        mode = "focused"
    probe = raw_params.get("probe_label")
    if not isinstance(probe, str) or not probe.strip():
        return None
    layers = raw_params.get("layer_labels")
    if isinstance(layers, list) and len(layers) > 3:
        layers = layers[:3]
    if not _valid_str_list(layers, 3):
        return None
    step_lbls = raw_params.get("step_labels")
    if not _valid_str_list(step_lbls, 3):
        return None
    return {
        "mode": mode,
        "probe_label": probe.strip()[:8],
        "layer_labels": [ly.strip()[:8] for ly in layers],
        "focal_points": parse_int_val(raw_params.get("focal_points"), default=5, min_v=3, max_v=7),
        "energy_fill": raw_params.get("energy_fill", "accent"),
        "step_labels": [sl.strip()[:10] for sl in step_lbls],
    }


def _shape_cyst_excision(raw_params: dict[str, Any]) -> Optional[dict[str, Any]]:
    c_label = raw_params.get("cyst_label")
    s_label = raw_params.get("sac_label")
    core_lbl = raw_params.get("core_label")
    layers = raw_params.get("layer_labels")
    step_lbls = raw_params.get("step_labels")
    if not all(isinstance(x, str) and x.strip() for x in (c_label, s_label, core_lbl)):
        return None
    if isinstance(layers, list) and len(layers) > 2:
        layers = layers[:2]
    if not isinstance(layers, list) or len(layers) != 2:
        return None
    if not isinstance(step_lbls, list) or len(step_lbls) != 3:
        return None
    return {
        "cyst_label": c_label.strip()[:8],
        "sac_label": s_label.strip()[:8],
        "core_label": core_lbl.strip()[:8],
        "layer_labels": [ly.strip()[:8] for ly in layers],
        "sac_fill": raw_params.get("sac_fill", "accent"),
        "step_labels": [sl.strip()[:10] for sl in step_lbls],
    }


def _shape_nail_matrix(raw_params: dict[str, Any]) -> Optional[dict[str, Any]]:
    n_label = raw_params.get("nail_label", "趾甲板")
    f_label = raw_params.get("fold_label", "側甲襞")
    s_label = raw_params.get("spicule_label", "嵌甲尖刺")
    m_label = raw_params.get("matrix_label", "甲基質生長板")
    step_lbls = raw_params.get("step_labels")
    if not all(isinstance(x, str) and x.strip() for x in (n_label, f_label, s_label, m_label)):
        return None
    if not isinstance(step_lbls, list) or len(step_lbls) != 3:
        return None
    return {
        "nail_label": n_label.strip()[:8],
        "fold_label": f_label.strip()[:8],
        "spicule_label": s_label.strip()[:8],
        "matrix_label": m_label.strip()[:8],
        "matrix_fill": raw_params.get("matrix_fill", "warn"),
        "step_labels": [sl.strip()[:10] for sl in step_lbls],
    }


def _shape_subdermal_curettage(raw_params: dict[str, Any]) -> Optional[dict[str, Any]]:
    t_label = raw_params.get("target_label")
    s_label = raw_params.get("shaver_label")
    layers = raw_params.get("layer_labels")
    step_lbls = raw_params.get("step_labels")
    if not all(isinstance(x, str) and x.strip() for x in (t_label, s_label)):
        return None
    if isinstance(layers, list) and len(layers) > 2:
        layers = layers[:2]
    if not isinstance(layers, list) or len(layers) != 2:
        return None
    if not isinstance(step_lbls, list) or len(step_lbls) != 3:
        return None
    return {
        "target_label": t_label.strip()[:8],
        "shaver_label": s_label.strip()[:8],
        "layer_labels": [ly.strip()[:8] for ly in layers],
        "tool_fill": raw_params.get("tool_fill", "accent"),
        "step_labels": [sl.strip()[:10] for sl in step_lbls],
    }


def _shape_deep_plane_facelift(raw_params: dict[str, Any]) -> Optional[dict[str, Any]]:
    smas_lbl = raw_params.get("smas_label", "SMAS筋膜瓣")
    anchor_lbl = raw_params.get("anchor_label", "骨膜錨定點")
    lig_lbl = raw_params.get("ligament_label", "維持韌帶")
    layers = raw_params.get("layer_labels")
    step_lbls = raw_params.get("step_labels")
    if not all(isinstance(x, str) and x.strip() for x in (smas_lbl, anchor_lbl, lig_lbl)):
        return None
    if isinstance(layers, list) and len(layers) > 3:
        layers = layers[:3]
    if not isinstance(layers, list) or len(layers) != 3:
        return None
    if not isinstance(step_lbls, list) or len(step_lbls) != 3:
        return None
    return {
        "smas_label": smas_lbl.strip()[:8],
        "anchor_label": anchor_lbl.strip()[:8],
        "ligament_label": lig_lbl.strip()[:8],
        "layer_labels": [ly.strip()[:8] for ly in layers],
        "suture_fill": raw_params.get("suture_fill", "accent"),
        "step_labels": [sl.strip()[:10] for sl in step_lbls],
    }


def _shape_corset_platysmaplasty(raw_params: dict[str, Any]) -> Optional[dict[str, Any]]:
    m_lbl = raw_params.get("muscle_label", "兩側闊頸肌")
    f_lbl = raw_params.get("fat_label", "深層脂肪墊")
    sut_lbl = raw_params.get("suture_label", "馬甲式對縫")
    layers = raw_params.get("layer_labels")
    step_lbls = raw_params.get("step_labels")
    if not all(isinstance(x, str) and x.strip() for x in (m_lbl, f_lbl, sut_lbl)):
        return None
    if isinstance(layers, list) and len(layers) > 3:
        layers = layers[:3]
    if not isinstance(layers, list) or len(layers) != 3:
        return None
    if not isinstance(step_lbls, list) or len(step_lbls) != 3:
        return None
    return {
        "muscle_label": m_lbl.strip()[:8],
        "fat_label": f_lbl.strip()[:8],
        "suture_label": sut_lbl.strip()[:8],
        "layer_labels": [ly.strip()[:8] for ly in layers],
        "suture_fill": raw_params.get("suture_fill", "accent"),
        "step_labels": [sl.strip()[:10] for sl in step_lbls],
    }


def _shape_surgical_action(raw_params: dict[str, Any]) -> dict[str, Any]:
    anat = raw_params.get("anatomy_target", "mandible")
    if anat not in enum_values("surgical_action", "anatomy_target"):
        anat = "mandible"
    bone_lbl = raw_params.get("bone_label", "下顎骨端")
    nerve_lbl = raw_params.get("nerve_label", "頦神經")
    n_status = raw_params.get("nerve_status", "protected")
    if n_status not in enum_values("surgical_action", "nerve_status"):
        n_status = "protected"
    inc_lbl = raw_params.get("incision_label", "口內隱痕")
    fix_lbl = raw_params.get("fixation_label", "純鈦板釘")
    shift_mm = parse_int_val(raw_params.get("bone_shift_mm"), default=6, min_v=0, max_v=15)
    prot_nerve = bool(raw_params.get("protect_nerve", True))
    step_lbls = raw_params.get("step_labels")
    if _valid_str_list(step_lbls, 3):
        clean_steps = [x.strip()[:10] for x in step_lbls]
    else:
        clean_steps = ["切口進入", "神經保護處置", "穩定固定完成"]

    return {
        "anatomy_target": anat,
        "bone_label": str(bone_lbl).strip()[:8] if bone_lbl else "骨端結構",
        "nerve_label": str(nerve_lbl).strip()[:8] if nerve_lbl else "周邊神經",
        "nerve_status": n_status,
        "incision_label": str(inc_lbl).strip()[:8] if inc_lbl else "微創切口",
        "fixation_label": str(fix_lbl).strip()[:8] if fix_lbl else "剛性固定",
        "bone_shift_mm": shift_mm,
        "protect_nerve": prot_nerve,
        "step_labels": clean_steps,
    }


def _shape_laser_action(raw_params: dict[str, Any]) -> Optional[dict[str, Any]]:
    mode = raw_params.get("mode", "shatter")
    if mode not in ("shatter", "fractional"):
        mode = "shatter"
    beam = raw_params.get("beam_label")
    target = raw_params.get("target_label")
    if not isinstance(beam, str) or not beam.strip() or not isinstance(target, str) or not target.strip():
        return None
    layers = raw_params.get("layer_labels")
    step_lbls = raw_params.get("step_labels")
    if not _valid_str_list(layers, 2) or not _valid_str_list(step_lbls, 3):
        return None
    return {
        "mode": mode,
        "beam_label": beam.strip()[:8],
        "target_label": target.strip()[:8],
        "layer_labels": [ly.strip()[:8] for ly in layers],
        "beam_fill": raw_params.get("beam_fill", "accent"),
        "step_labels": [sl.strip()[:10] for sl in step_lbls],
    }


def _shape_neuromuscular(raw_params: dict[str, Any]) -> Optional[dict[str, Any]]:
    nerve = raw_params.get("nerve_label")
    muscle = raw_params.get("muscle_label")
    surface = raw_params.get("surface_label")
    if not all(isinstance(x, str) and x.strip() for x in (nerve, muscle, surface)):
        return None
    step_lbls = raw_params.get("step_labels")
    if not _valid_str_list(step_lbls, 3):
        return None
    return {
        "nerve_label": nerve.strip()[:8],
        "muscle_label": muscle.strip()[:8],
        "surface_label": surface.strip()[:8],
        "blocker_fill": raw_params.get("blocker_fill", "ok"),
        "step_labels": [sl.strip()[:10] for sl in step_lbls],
    }


def _shape_dermal_support(raw_params: dict[str, Any]) -> Optional[dict[str, Any]]:
    filler = raw_params.get("filler_label")
    if not isinstance(filler, str) or not filler.strip():
        return None
    layers = raw_params.get("layer_labels")
    step_lbls = raw_params.get("step_labels")
    if not _valid_str_list(layers, 2) or not _valid_str_list(step_lbls, 3):
        return None
    droplets = raw_params.get("droplets", 6)
    if not isinstance(droplets, int) or isinstance(droplets, bool) or not (4 <= droplets <= 8):
        droplets = 6
    return {
        "filler_label": filler.strip()[:8],
        "layer_labels": [ly.strip()[:8] for ly in layers],
        "droplets": droplets,
        "filler_fill": raw_params.get("filler_fill", "gel"),
        "step_labels": [sl.strip()[:10] for sl in step_lbls],
    }


_SCENE1_SHAPERS: dict[str, Callable[[dict[str, Any]], Optional[dict[str, Any]]]] = {
    "process_diagram": _shape_process_diagram,
    "skin_energy": _shape_skin_energy,
    "cyst_excision": _shape_cyst_excision,
    "nail_matrix": _shape_nail_matrix,
    "subdermal_curettage": _shape_subdermal_curettage,
    "deep_plane_facelift": _shape_deep_plane_facelift,
    "corset_platysmaplasty": _shape_corset_platysmaplasty,
    "surgical_action": _shape_surgical_action,
    "laser_action": _shape_laser_action,
    "neuromuscular": _shape_neuromuscular,
    "dermal_support": _shape_dermal_support,
}


def shape_scene1_params(
    bp: str,
    raw_params: dict[str, Any],
    pathology_shaper: Callable[[dict[str, Any]], dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Scene 1 參數驗證與塑形。"""
    if bp == "pathology_mechanism":
        return pathology_shaper(raw_params)
    shaper = _SCENE1_SHAPERS.get(bp)
    return shaper(raw_params) if shaper else None


def shape_scene2_contrast_params(raw_params: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Scene 2 (contrast) 參數驗證與塑形。"""
    left = raw_params.get("left")
    right = raw_params.get("right")
    if not isinstance(left, dict) or not isinstance(right, dict):
        return None
    for req_k in ("title", "note", "core_label", "footnote"):
        if not isinstance(left.get(req_k), str) or not left[req_k].strip():
            return None
    for req_k in ("title", "note", "footnote"):
        if not isinstance(right.get(req_k), str) or not right[req_k].strip():
            return None

    rows = right.get("rows", raw_params.get("rows", 3))
    per_row = right.get("per_row", raw_params.get("per_row", 5))
    left_mode = left.get("mode", "mass")
    if left_mode not in enum_values("contrast", "mode", "left"):
        left_mode = "mass"
    left_effect = left.get("core_effect", "dim")
    if left_effect not in ("dim", "none"):
        left_effect = "dim"
    left_fill = left.get("unit_fill", "warn")
    if left_fill not in PALETTE_TOKENS:
        left_fill = "warn"

    right_mode = right.get("mode", "layered")
    if right_mode not in enum_values("contrast", "mode", "right"):
        right_mode = "layered"
    right_fill = right.get("unit_fill", "accent")
    if right_fill not in PALETTE_TOKENS:
        right_fill = "accent"

    return {
        "left": {
            "title": left["title"].strip()[:8],
            "note": left["note"].strip()[:14],
            "mode": left_mode,
            "core_effect": left_effect,
            "core_label": left["core_label"].strip()[:8],
            "footnote": left["footnote"].strip()[:16],
            "unit_fill": left_fill,
        },
        "right": {
            "title": right["title"].strip()[:8],
            "note": right["note"].strip()[:14],
            "mode": right_mode,
            "rows": int(rows) if isinstance(rows, int) and not isinstance(rows, bool) and 1 <= rows <= 4 else 3,
            "per_row": int(per_row) if isinstance(per_row, int) and not isinstance(per_row, bool) and 3 <= per_row <= 8 else 5,
            "footnote": right["footnote"].strip()[:16],
            "unit_fill": right_fill,
        },
    }


def shape_scene3_timeline_params(
    raw_params: dict[str, Any],
    topic_key: str,
    fallback_title: str,
) -> Optional[dict[str, Any]]:
    """Scene 3 (timeline) 參數驗證與塑形。"""
    milestones = raw_params.get("milestones")
    if not _valid_str_list(milestones, 3):
        return None
    units = parse_int_val(raw_params.get("units"), default=3, min_v=2, max_v=5)
    is_fat_topic = ("脂肪" in fallback_title) or ("fat" in topic_key)
    connectors = raw_params.get("connectors", "vessels" if is_fat_topic else "none")
    if not is_fat_topic and connectors == "vessels":
        connectors = "none"
    if connectors not in enum_values("timeline", "connectors"):
        connectors = "none"
    unit_effect = raw_params.get("unit_effect", "mature")
    if unit_effect not in enum_values("timeline", "unit_effect"):
        unit_effect = "mature"
    unit_fill = raw_params.get("unit_fill", "accent")
    if unit_fill not in PALETTE_TOKENS:
        unit_fill = "accent"
    return {
        "milestones": [m_item.strip()[:8] for m_item in milestones],
        "unit_effect": unit_effect,
        "connectors": connectors,
        "units": int(units) if isinstance(units, int) and not isinstance(units, bool) and 2 <= units <= 5 else 3,
        "unit_fill": unit_fill,
    }
