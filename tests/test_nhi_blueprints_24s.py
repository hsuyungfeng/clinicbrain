# -*- coding: utf-8 -*-
"""Phase 39 Plan 02: 健保 200 大核心專科（牙科、中醫、代謝）圖元與 24 秒循環驗證。

驗證項目：
1. blueprints.py 參數規格擴充（dental_oral, tcm_meridian, endocrine_receptor 等）。
2. ir.py 規格檢驗（支援 duration_sec 8 秒，加總 24 秒，零阿拉伯數字）。
3. visual_engine.js 註冊與繪圖引擎一致性。
"""

from pathlib import Path
from src.visual.blueprints import BLUEPRINTS, validate_params
from src.visual.ir import validate_ir


def test_blueprints_spec_contains_nhi_specialties():
    """驗證 blueprints.py 已正確納入牙科、中醫、內分泌代謝圖元規格。"""
    # 1. pathology_mechanism organ_system
    patho_organs = BLUEPRINTS["pathology_mechanism"]["params"]["organ_system"]["values"]
    assert "dental_oral" in patho_organs
    assert "tcm_meridian" in patho_organs
    assert "endocrine_receptor" in patho_organs

    # 2. contrast modes
    contrast_left = BLUEPRINTS["contrast"]["params"]["left"]["fields"]["mode"]["values"]
    contrast_right = BLUEPRINTS["contrast"]["params"]["right"]["fields"]["mode"]["values"]

    assert "dental_caries_erosion" in contrast_left
    assert "tcm_qi_stagnation" in contrast_left
    assert "metabolic_insulin_resistance" in contrast_left

    assert "dental_sealing_restoration" in contrast_right
    assert "tcm_acupuncture_flow" in contrast_right
    assert "metabolic_glycemic_control" in contrast_right

    # 3. timeline connectors
    timeline_conn = BLUEPRINTS["timeline"]["params"]["connectors"]["values"]
    assert "dental_pulp_healing" in timeline_conn
    assert "tcm_meridian_harmony" in timeline_conn
    assert "metabolic_vessel_stabilization" in timeline_conn


def test_dental_3scene_ir_validation():
    """驗證牙科齲齒/根管 3 幕動畫 IR（3 幕 x 8 秒 = 24 秒）。"""
    dental_ir = {
        "topic_key": "dental-caries",
        "title": "齲齒酸蝕與階梯式樹脂充填",
        "keywords": ["齲齒", "蛀牙", "樹脂充填", "牙髓腔"],
        "scenes": [
            {
                "blueprint": "pathology_mechanism",
                "title": "牙釉質細菌酸蝕侵襲",
                "caption": "牙菌斑代謝產酸侵蝕牙釉質與牙本質小管，引發神經微血管充血",
                "labels": [
                    {"text": "牙菌斑", "tone": "warning"},
                    {"text": "牙髓神經", "tone": "neutral"},
                ],
                "duration_sec": 8,
                "params": {
                    "organ_system": "dental_oral",
                    "severity_level": 3,
                    "step_labels": ["牙菌斑滋生", "齒質酸蝕穿孔", "牙神經微血管充血"],
                },
            },
            {
                "blueprint": "contrast",
                "title": "傳統拖延與微創封填",
                "caption": "左側持續拖延引發牙髓深層發炎，右側以階梯式光固化樹脂密封保護",
                "labels": [
                    {"text": "持續深蝕", "tone": "warning"},
                    {"text": "光固化封填", "tone": "optimal"},
                ],
                "duration_sec": 8,
                "params": {
                    "left": {
                        "title": "未處理持續深蝕",
                        "mode": "dental_caries_erosion",
                        "unit_fill": "warn",
                    },
                    "right": {
                        "title": "光固化階梯封填",
                        "mode": "dental_sealing_restoration",
                        "unit_fill": "accent",
                    },
                },
            },
            {
                "blueprint": "timeline",
                "title": "牙髓腔清創與咬合重塑",
                "caption": "完成感染清除與根管緻密充填，重塑健全咬合與牙周屏障",
                "labels": [
                    {"text": "根管清創", "tone": "neutral"},
                    {"text": "全冠修復", "tone": "optimal"},
                ],
                "duration_sec": 8,
                "params": {
                    "connectors": "dental_pulp_healing",
                    "unit_fill": "accent",
                },
            },
        ],
    }

    ok, code = validate_ir(dental_ir)
    assert ok, f"Dental IR validation failed: {code}"

    total_sec = sum(s["duration_sec"] for s in dental_ir["scenes"])
    assert total_sec == 24


def test_tcm_3scene_ir_validation():
    """驗證中醫氣滯/針灸 3 幕動畫 IR（3 幕 x 8 秒 = 24 秒）。"""
    tcm_ir = {
        "topic_key": "tcm-cervical-stiff-neck",
        "title": "頸項落枕與經絡針灸疏通",
        "keywords": ["落枕", "經絡", "針灸", "氣滯血瘀"],
        "scenes": [
            {
                "blueprint": "pathology_mechanism",
                "title": "經脈拘急氣滯血瘀",
                "caption": "局部經絡受寒或姿態不良致使氣血瘀阻凝滯，引發頸項牽拉拘急",
                "labels": [
                    {"text": "寒濕阻絡", "tone": "warning"},
                    {"text": "經脈攣急", "tone": "neutral"},
                ],
                "duration_sec": 8,
                "params": {
                    "organ_system": "tcm_meridian",
                    "severity_level": 3,
                    "step_labels": ["寒濕阻絡", "經氣鬱閉凝滯", "局部痛點攣急"],
                },
            },
            {
                "blueprint": "contrast",
                "title": "局部僵凝與金針導引",
                "caption": "左側經脈凝滯阻閉，右側經由毫針入穴得氣導引，促進氣血流注",
                "labels": [
                    {"text": "凝滯結塊", "tone": "warning"},
                    {"text": "毫針得氣", "tone": "optimal"},
                ],
                "duration_sec": 8,
                "params": {
                    "left": {
                        "title": "氣血凝滯結塊",
                        "mode": "tcm_qi_stagnation",
                        "unit_fill": "warn",
                    },
                    "right": {
                        "title": "毫針得氣流注",
                        "mode": "tcm_acupuncture_flow",
                        "unit_fill": "ok",
                    },
                },
            },
            {
                "blueprint": "timeline",
                "title": "經絡通達與陰陽調和",
                "caption": "穴位針感擴散驅散局部鬱滯，臟腑氣血平秘安和恢復彈性",
                "labels": [
                    {"text": "氣血通暢", "tone": "optimal"},
                    {"text": "陰陽平衡", "tone": "optimal"},
                ],
                "duration_sec": 8,
                "params": {
                    "connectors": "tcm_meridian_harmony",
                    "unit_fill": "ok",
                },
            },
        ],
    }

    ok, code = validate_ir(tcm_ir)
    assert ok, f"TCM IR validation failed: {code}"

    total_sec = sum(s["duration_sec"] for s in tcm_ir["scenes"])
    assert total_sec == 24


def test_endocrine_3scene_ir_validation():
    """驗證內分泌代謝（第2型糖尿病）3 幕動畫 IR（3 幕 x 8 秒 = 24 秒）。"""
    endocrine_ir = {
        "topic_key": "metabolic-type2-diabetes",
        "title": "胰島素阻抗與受體敏感化調控",
        "keywords": ["糖尿病", "胰島素", "血糖控制", "代謝受體"],
        "scenes": [
            {
                "blueprint": "pathology_mechanism",
                "title": "受體鈍化與高糖微環境",
                "caption": "周邊組織受體敏感度降低形成阻抗屏障，游離葡萄糖蓄積增加負荷",
                "labels": [
                    {"text": "受體阻抗", "tone": "warning"},
                    {"text": "微血管損耗", "tone": "warning"},
                ],
                "duration_sec": 8,
                "params": {
                    "organ_system": "endocrine_receptor",
                    "severity_level": 4,
                    "step_labels": ["代謝負荷失調", "受體結合受阻", "微血管受壓損耗"],
                },
            },
            {
                "blueprint": "contrast",
                "title": "持續高糖與代謝調控",
                "caption": "左側受體關閉糖毒性蓄積，右側調控後轉運通道順利開放攝入",
                "labels": [
                    {"text": "轉運受阻", "tone": "warning"},
                    {"text": "敏感化攝入", "tone": "optimal"},
                ],
                "duration_sec": 8,
                "params": {
                    "left": {
                        "title": "胰島素轉運受阻",
                        "mode": "metabolic_insulin_resistance",
                        "unit_fill": "warn",
                    },
                    "right": {
                        "title": "受體敏感化攝入",
                        "mode": "metabolic_glycemic_control",
                        "unit_fill": "ok",
                    },
                },
            },
            {
                "blueprint": "timeline",
                "title": "血管內皮穩定與長期平衡",
                "caption": "長期規律介入使內皮細胞獲得保護修復，維持代謝指標平衡穩固",
                "labels": [
                    {"text": "血管減壓", "tone": "neutral"},
                    {"text": "長期平穩", "tone": "optimal"},
                ],
                "duration_sec": 8,
                "params": {
                    "connectors": "metabolic_vessel_stabilization",
                    "unit_fill": "accent",
                },
            },
        ],
    }

    ok, code = validate_ir(endocrine_ir)
    assert ok, f"Endocrine IR validation failed: {code}"

    total_sec = sum(s["duration_sec"] for s in endocrine_ir["scenes"])
    assert total_sec == 24


def test_visual_engine_js_nhi_registrations():
    """靜態檢查 visual_engine.js 是否包含新註冊的常數、詞表與繪圖分流。"""
    js_path = Path("src/web/static/visual_engine.js")
    assert js_path.exists()
    content = js_path.read_text(encoding="utf-8")

    # 1. PATHO_DRAWERS
    assert "dental_oral: pmDental" in content
    assert "tcm_meridian: pmTCM" in content
    assert "endocrine_receptor: pmEndocrine" in content

    # 2. CONTRAST SPECIALTY
    assert '"dental_caries_erosion"' in content
    assert '"tcm_qi_stagnation"' in content
    assert '"metabolic_insulin_resistance"' in content
    assert '"dental_sealing_restoration"' in content
    assert '"tcm_acupuncture_flow"' in content
    assert '"metabolic_glycemic_control"' in content

    # 3. TIMELINE SPECIALTY
    assert '"dental_pulp_healing"' in content
    assert '"tcm_meridian_harmony"' in content
    assert '"metabolic_vessel_stabilization"' in content

    # 4. TIMELINE_STAGE_DESC
    assert "dental_pulp_healing:" in content
    assert "tcm_meridian_harmony:" in content
    assert "metabolic_vessel_stabilization:" in content
