"""
Phase 40 Wave 2: 201-400 專科圖元與藍圖語意擴充測試 (test_nhi400_blueprints.py)。

測試目標：
1. 驗證 BLUEPRINTS 註冊表中包含眼科、耳鼻喉、泌尿、牙周再生與中醫特種療法之新增列舉值：
   - pathology_mechanism: organ_system (ophthalmic_retina, ent_airway, uro_genital, dental_periodontal, tcm_special_acup)
   - contrast: left.mode, right.mode 次專科對比列舉
   - timeline: connectors 次專科時序連接樣式
2. 驗證擴充參數與 default_params 合法性。
3. 驗證包含次專科圖元之 3 幕 Intermediate Representation (IR) 經 validate_ir 嚴格驗證通過：
   - 3 幕 × 8 秒 = 24 秒（無 duration_sec 時預設 8 秒）
   - 零阿拉伯數字、無價格洩漏、無保證療效禁詞
   - 第三幕具備衛教免責聲明。
4. 驗證 visual_engine.js 中具備對應專科繪圖常數與繪製函式。
"""

from __future__ import annotations

from pathlib import Path
import pytest

from src.visual.blueprints import (
    BLUEPRINTS,
    PATHOLOGY_ORGAN_SYSTEMS,
    CONTRAST_LEFT_SPECIALTY,
    CONTRAST_RIGHT_SPECIALTY,
    TIMELINE_SPECIALTY,
    default_params,
    validate_params,
)
from src.visual.ir import validate_ir


def test_blueprints_contain_nhi400_specialty_organ_systems():
    """驗證 pathology_mechanism 藍圖包含 5 大次專科 organ_system。"""
    organ_values = BLUEPRINTS["pathology_mechanism"]["params"]["organ_system"]["values"]
    expected_systems = [
        "ophthalmic_retina",
        "ent_airway",
        "uro_genital",
        "dental_periodontal",
        "tcm_special_acup",
    ]
    for sys in expected_systems:
        assert sys in organ_values, f"pathology_mechanism 缺少 organ_system: {sys}"
        assert sys in PATHOLOGY_ORGAN_SYSTEMS


def test_blueprints_contain_nhi400_contrast_modes():
    """驗證 contrast 藍圖包含次專科對比模式列舉。"""
    left_modes = BLUEPRINTS["contrast"]["params"]["left"]["fields"]["mode"]["values"]
    right_modes = BLUEPRINTS["contrast"]["params"]["right"]["fields"]["mode"]["values"]

    expected_left = [
        "vitreous_drusen_degeneration",
        "airway_laryngeal_edema",
        "venous_plexus_reflux",
        "periodontal_bone_defect",
        "tcm_deep_adhesion",
    ]
    expected_right = [
        "optical_barrier_shield",
        "airway_patency_restore",
        "venous_ligation_clear",
        "gtr_guided_regeneration",
        "acupotomy_micro_release",
    ]

    for mode in expected_left:
        assert mode in left_modes, f"contrast left.mode 缺少: {mode}"
        assert mode in CONTRAST_LEFT_SPECIALTY

    for mode in expected_right:
        assert mode in right_modes, f"contrast right.mode 缺少: {mode}"
        assert mode in CONTRAST_RIGHT_SPECIALTY


def test_blueprints_contain_nhi400_timeline_connectors():
    """驗證 timeline 藍圖包含次專科時序連接符號。"""
    connectors = BLUEPRINTS["timeline"]["params"]["connectors"]["values"]
    expected_connectors = [
        "retinal_epithelium_repair",
        "airway_mucosa_calm",
        "pelvic_microflow_restore",
        "bone_graft_integration",
        "meridian_unblock_healing",
    ]
    for conn in expected_connectors:
        assert conn in connectors, f"timeline connectors 缺少: {conn}"
        assert conn in TIMELINE_SPECIALTY


def test_specialty_params_validation_pass():
    """驗證代入次專科參數時，validate_params 判定為合格。"""
    # 1. pathology_mechanism (ophthalmic_retina)
    params_patho = default_params("pathology_mechanism")
    params_patho["organ_system"] = "ophthalmic_retina"
    params_patho["organ_label"] = "視網膜底"
    params_patho["lesion_label"] = "黃斑變性"
    ok, code = validate_params("pathology_mechanism", params_patho)
    assert ok is True, f"pathology_mechanism 參數驗證失敗: {code}"

    # 2. contrast (airway)
    params_contrast = default_params("contrast")
    params_contrast["left"]["mode"] = "airway_laryngeal_edema"
    params_contrast["left"]["title"] = "氣道狹窄"
    params_contrast["right"]["mode"] = "airway_patency_restore"
    params_contrast["right"]["title"] = "通暢復原"
    ok, code = validate_params("contrast", params_contrast)
    assert ok is True, f"contrast 參數驗證失敗: {code}"

    # 3. timeline (meridian_unblock_healing)
    params_timeline = default_params("timeline")
    params_timeline["connectors"] = "meridian_unblock_healing"
    params_timeline["milestones"] = ["初期引導", "疏通經絡", "氣血調和"]
    ok, code = validate_params("timeline", params_timeline)
    assert ok is True, f"timeline 參數驗證失敗: {code}"


def test_specialty_ir_validation_strict_pass():
    """驗證包含專科圖元的完整 3 幕 IR 通過 validate_ir 嚴格檢驗。"""
    valid_specialty_ir = {
        "topic_key": "vitreous-floaters",
        "title": "飛蚊症成因與視網膜檢查",
        "keywords": ["飛蚊症", "視網膜", "玻璃體", "眼底檢查"],
        "scenes": [
            {
                "blueprint": "pathology_mechanism",
                "title": "玻璃體與視網膜病理構造",
                "caption": "正常玻璃體為透明膠狀基質，隨年齡增長產生微細沉積陰影投射至感光層。",
                "labels": [
                    {"text": "感光視網膜", "tone": "neutral"},
                    {"text": "退化沉積", "tone": "warning"},
                ],
                "duration_sec": 8.0,
                "params": {
                    "organ_system": "ophthalmic_retina",
                    "organ_label": "視網膜底",
                    "lesion_label": "玻璃體暗影",
                    "trigger_label": "膠原凝縮",
                    "defense_label": "感光維持",
                    "severity_level": 2,
                    "accent_fill": "warn",
                    "step_labels": ["膠狀體凝縮", "微細沉積物", "投影視網膜"],
                },
            },
            {
                "blueprint": "contrast",
                "title": "清澈與混濁視覺成像對照",
                "caption": "左側光線順利聚焦視網膜，右側混濁懸浮物阻擋部分投影形成飛蚊陰影。",
                "labels": [
                    {"text": "正常視野", "tone": "optimal"},
                    {"text": "懸浮暗影", "tone": "warning"},
                ],
                "duration_sec": 8.0,
                "params": {
                    "left": {
                        "title": "退化暗影",
                        "note": "感光投影遮蔽",
                        "mode": "vitreous_drusen_degeneration",
                        "core_effect": "dim",
                        "core_label": "暗影點狀",
                        "footnote": "玻璃體微細凝結沉澱",
                        "unit_fill": "pale",
                    },
                    "right": {
                        "title": "光學防護",
                        "note": "定期眼底追蹤",
                        "mode": "optical_barrier_shield",
                        "rows": 3,
                        "per_row": 5,
                        "footnote": "維持良好用眼作息",
                        "unit_fill": "ok",
                    },
                },
            },
            {
                "blueprint": "timeline",
                "title": "臨床定期追蹤與散瞳檢查流程",
                "caption": "突發大量黑點或閃光感應立即就醫散瞳檢查，本說明僅供衛教參考請諮詢專科醫師。",
                "labels": [
                    {"text": "門診檢查", "tone": "neutral"},
                    {"text": "定期追蹤", "tone": "optimal"},
                ],
                "duration_sec": 8.0,
                "params": {
                    "milestones": ["門診散瞳", "眼底檢查", "定期追蹤"],
                    "unit_effect": "glow_restored",
                    "connectors": "retinal_epithelium_repair",
                    "units": 3,
                    "unit_fill": "accent",
                },
            },
        ],
    }

    ok, code = validate_ir(valid_specialty_ir)
    assert ok is True, f"IR 驗證失敗: {code}"


def test_visual_engine_js_contains_specialty_drawers():
    """驗證 visual_engine.js 中包含次專科圖元繪製函式與常數定義。"""
    engine_path = Path("src/web/static/visual_engine.js")
    assert engine_path.exists()
    content = engine_path.read_text(encoding="utf-8")

    expected_identifiers = [
        "pmOphthalmicRetina",
        "pmENTAirway",
        "pmUroGenital",
        "pmDentalPeriodontal",
        "pmTCMSpecialAcup",
        "drawContrastLeftSpecialty",
        "drawContrastRightSpecialty",
        "drawTimelineSpecialty",
        "vitreous_drusen_degeneration",
        "airway_laryngeal_edema",
        "venous_plexus_reflux",
        "periodontal_bone_defect",
        "tcm_deep_adhesion",
        "optical_barrier_shield",
        "airway_patency_restore",
        "venous_ligation_clear",
        "gtr_guided_regeneration",
        "acupotomy_micro_release",
        "retinal_epithelium_repair",
        "airway_mucosa_calm",
        "pelvic_microflow_restore",
        "bone_graft_integration",
        "meridian_unblock_healing",
    ]

    for ident in expected_identifiers:
        assert ident in content, f"visual_engine.js 缺少專科標識符: {ident}"
