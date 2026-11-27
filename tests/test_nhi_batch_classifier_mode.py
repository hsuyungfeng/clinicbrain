import json
import pytest
from unittest.mock import patch
from src.visual.blueprints import BLUEPRINTS
from scripts.generate_nhi200_visual_batch import (
    compile_visual_ir_local,
    generate_single_nhi_ir,
)
from scripts.generate_nhi400_visual_batch import (
    generate_single_item_with_self_healing as nhi400_generate_single_item,
    mock_generate_ir as nhi400_mock_generate_ir,
)

def test_nhi200_fixed_mode_defaults_to_pathology_mechanism():
    """驗證 nhi200 在 fixed 模式下第一幕固定為 pathology_mechanism"""
    item = {
        "id": "nhi-001",
        "name": "高血壓",
        "clean_name": "高血壓",
        "category": "循環系統",
        "keywords": ["高血壓", "血管", "血壓計"],
    }
    archetype = {
        "s1_organ": "vascular_metabolic",
        "s2_left_mode": "延誤處置",
        "s2_right_mode": "規律追蹤",
        "s3_connector": "循序漸進",
    }
    fact_sheet = {
        "organ_label": "血管組織",
        "lesion_label": "動脈硬化",
        "trigger_label": "高壓血流",
        "defense_label": "內皮修復",
        "step_labels": ["血壓上升", "管壁受壓", "組織修復"],
        "pathology_notes": "病理機轉備註",
        "contrast_notes": "對照備註",
        "timeline_notes": "時間軸備註",
    }
    prompt_captured = []
    def fake_call(p):
        prompt_captured.append(p)
        payload = {
            "topic_key": "nhi-001-hypertension",
            "title": "高血壓衛教圖解",
            "keywords": ["高血壓", "血管"],
            "scenes": [
                {
                    "blueprint": "pathology_mechanism",
                    "title": "病理機轉解說",
                    "caption": "血管組織在高壓血流衝擊下，管壁承受極大張力，須持續由專業醫師當面評估。",
                    "labels": [{"text": "高壓血流", "tone": "warning"}, {"text": "血管組織", "tone": "neutral"}],
                    "duration_sec": 8,
                    "params": BLUEPRINTS["pathology_mechanism"]["defaults"],
                },
                {
                    "blueprint": "contrast",
                    "title": "照護處置對照",
                    "caption": "延誤處置易加重負擔，規律照護有助穩定結構防禦，詳細照護建議由專業醫師當面評估。",
                    "labels": [{"text": "延誤處置", "tone": "warning"}, {"text": "規律追蹤", "tone": "optimal"}],
                    "duration_sec": 8,
                    "params": BLUEPRINTS["contrast"]["defaults"],
                },
                {
                    "blueprint": "timeline",
                    "title": "長期復原進程",
                    "caption": "血管結構逐步穩定，配合專業醫事人員指導維持健康，個人化處置因人而異。",
                    "labels": [{"text": "初起穩定", "tone": "neutral"}, {"text": "長期維護", "tone": "optimal"}],
                    "duration_sec": 8,
                    "params": BLUEPRINTS["timeline"]["defaults"],
                },
            ],
        }
        return json.dumps(payload, ensure_ascii=False)

    ir = compile_visual_ir_local(item, archetype, fact_sheet, call_local_fn=fake_call, blueprint_mode="fixed")
    assert ir is not None
    assert ir["scenes"][0]["blueprint"] == "pathology_mechanism"
    assert '"blueprint": "pathology_mechanism"' in prompt_captured[0]

def test_nhi200_classifier_mode_uses_classifier():
    """驗證 nhi200 在 classifier 模式下正確使用分類器結果"""
    item = {
        "id": "nhi-001",
        "name": "高血壓",
        "clean_name": "高血壓",
        "category": "循環系統",
        "keywords": ["高血壓", "血管", "血壓計"],
    }
    mock_clf_result = {
        "blueprint": "surgical_action",
        "confidence": 0.95,
        "reason": "手術動作步驟",
        "evidence": "手術",
        "status": "ok",
        "needs_review": False,
    }
    with patch("src.visual.blueprint_classifier.classify_scene1_blueprint", return_value=mock_clf_result):
        with patch("scripts.generate_nhi200_visual_batch.extract_anatomy_fact_sheet_deepseek", return_value={
            "organ_label": "血管組織",
            "lesion_label": "動脈硬化",
            "trigger_label": "高壓血流",
            "defense_label": "內皮修復",
            "step_labels": ["血壓上升", "管壁受壓", "組織修復"],
            "pathology_notes": "病理機轉備註",
            "contrast_notes": "對照備註",
            "timeline_notes": "時間軸備註",
        }):
            def fake_llm(p):
                payload = {
                    "topic_key": "nhi-001-hypertension",
                    "title": "高血壓衛教圖解",
                    "keywords": ["高血壓", "血管"],
                    "scenes": [
                        {
                            "blueprint": "surgical_action",
                            "title": "臨床藍圖解說",
                            "caption": "手術動作解剖構造包含骨骼與神經保護，須由專業醫師當面評估。",
                            "labels": [{"text": "骨骼結構", "tone": "neutral"}, {"text": "神經保護", "tone": "neutral"}],
                            "duration_sec": 8,
                            "params": BLUEPRINTS["surgical_action"]["defaults"],
                        },
                        {
                            "blueprint": "contrast",
                            "title": "照護處置對照",
                            "caption": "延誤處置易加重負擔，規律照護有助穩定結構防禦，詳細照護建議由專業醫師當面評估。",
                            "labels": [{"text": "延誤處置", "tone": "warning"}, {"text": "規律追蹤", "tone": "optimal"}],
                            "duration_sec": 8,
                            "params": BLUEPRINTS["contrast"]["defaults"],
                        },
                        {
                            "blueprint": "timeline",
                            "title": "長期復原進程",
                            "caption": "血管結構逐步穩定，配合專業醫事人員指導維持健康，個人化處置因人而異。",
                            "labels": [{"text": "初起穩定", "tone": "neutral"}, {"text": "長期維護", "tone": "optimal"}],
                            "duration_sec": 8,
                            "params": BLUEPRINTS["timeline"]["defaults"],
                        },
                    ],
                }
                return json.dumps(payload, ensure_ascii=False)
            ok, ir, err = generate_single_nhi_ir(item, llm_call=fake_llm, blueprint_mode="classifier")
            assert ok is True
            assert ir["scenes"][0]["blueprint"] == "surgical_action"
            assert ir.get("needs_review") is not True

def test_nhi400_fixed_mode_defaults_to_pathology_mechanism():
    """驗證 nhi400 在 fixed 模式下第一幕固定為 pathology_mechanism"""
    item = {
        "index": 201,
        "topic_key": "nhi-201-glaucoma",
        "disease_name": "青光眼",
        "category": "眼部疾患",
        "keywords": ["青光眼", "視神經", "眼壓"],
    }
    raw_ir = nhi400_mock_generate_ir(item, blueprint_mode="fixed")
    assert raw_ir["scenes"][0]["blueprint"] == "pathology_mechanism"

    ok, healed_ir, code = nhi400_generate_single_item(item, mock_mode=True, blueprint_mode="fixed")
    assert ok is True
    assert healed_ir["scenes"][0]["blueprint"] == "pathology_mechanism"
    assert healed_ir.get("needs_review") is not True

def test_nhi400_classifier_mode_success_uses_classifier():
    """驗證 nhi400 在 classifier 模式下信心充足時使用分類器結果"""
    item = {
        "index": 201,
        "topic_key": "nhi-201-glaucoma",
        "disease_name": "青光眼",
        "category": "眼部疾患",
        "keywords": ["青光眼", "視神經", "眼壓"],
    }
    mock_clf_result = {
        "blueprint": "laser_action",
        "confidence": 0.88,
        "reason": "雷射作用模式",
        "evidence": "青光眼",
        "status": "ok",
        "needs_review": False,
    }
    with patch("src.visual.blueprint_classifier.classify_scene1_blueprint", return_value=mock_clf_result):
        ok, healed_ir, code = nhi400_generate_single_item(
            item,
            mock_mode=True,
            blueprint_mode="classifier",
        )
        assert ok is True
        assert healed_ir["scenes"][0]["blueprint"] == "laser_action"
        assert healed_ir.get("needs_review") is not True

def test_nhi400_classifier_mode_low_confidence_marks_review():
    """驗證 nhi400 在 classifier 模式下低信心時標記 needs_review 並 fallback"""
    item = {
        "index": 201,
        "topic_key": "nhi-201-glaucoma",
        "disease_name": "青光眼",
        "category": "眼部疾患",
        "keywords": ["青光眼", "視神經", "眼壓"],
    }
    mock_clf_result = {
        "blueprint": "laser_action",
        "confidence": 0.55,
        "reason": "雷射作用模式 (低信心)",
        "evidence": "青光眼",
        "status": "low_confidence",
        "needs_review": True,
    }
    with patch("src.visual.blueprint_classifier.classify_scene1_blueprint", return_value=mock_clf_result):
        ok, healed_ir, code = nhi400_generate_single_item(
            item,
            mock_mode=True,
            blueprint_mode="classifier",
        )
        assert ok is True
        assert healed_ir.get("needs_review") is True
        assert healed_ir["scenes"][0]["blueprint"] == "pathology_mechanism"
