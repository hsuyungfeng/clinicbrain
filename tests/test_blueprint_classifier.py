"""
Unit tests for Phase 57 LLM Blueprint Classifier (tests/test_blueprint_classifier.py).

覆蓋驗收指標：
1. 合法輸出 (ok)
2. enum 外未知類別 (unknown_blueprint)
3. 證據不在原文 (invalid_evidence)
4. 低信心度 (needs_review)
5. other 選項 (needs_review)
6. D1 規範：全形逗號、全形頓號、空白差異之正規化子字串容錯
"""

import json
import pytest

from src.visual.blueprint_classifier import (
    classify_scene1_blueprint,
    is_evidence_in_source,
    normalize_text_for_comparison,
    CLASSIFIER_ALLOWED_BLUEPRINTS,
)

SAMPLE_SOURCE_TEXT = """
【急性扁桃腺炎臨床指引】
病理機轉主要為外來細菌或病毒侵襲口咽部黏膜，引發局部組織劇烈充血、腫脹與發炎反應。
患者常伴隨高燒、吞嚥劇痛與淋巴結腫大。病理檢查可見扁桃腺表面滲出物與隱窩化膿。
若未妥善照護，可能引發扁桃腺周圍膿瘍等嚴重併發症。
"""


def test_classifier_case_1_valid():
    """1. 合法分類輸出：合法藍圖、高信心、證據吻合 -> status: ok"""
    fake_llm = lambda prompt: json.dumps(
        {
            "blueprint": "pathology_mechanism",
            "confidence": 0.92,
            "evidence_span": "外來細菌或病毒侵襲口咽部黏膜，引發局部組織劇烈充血",
            "reason": "典型病理機轉描述",
        }
    )

    res = classify_scene1_blueprint(SAMPLE_SOURCE_TEXT, fake_llm, title="扁桃腺炎")
    assert res["status"] == "ok"
    assert res["blueprint"] == "pathology_mechanism"
    assert res["confidence"] == 0.92
    assert res["is_valid_evidence"] is True
    assert res["needs_review"] is False


def test_classifier_case_2_unknown_enum():
    """2. enum 外值：模型給出不存在的藍圖 -> status: unknown_blueprint"""
    fake_llm = lambda prompt: json.dumps(
        {
            "blueprint": "magical_cure_blueprint",
            "confidence": 0.99,
            "evidence_span": "外來細菌或病毒侵襲口咽部黏膜",
            "reason": "胡亂分類",
        }
    )

    res = classify_scene1_blueprint(SAMPLE_SOURCE_TEXT, fake_llm, title="扁桃腺炎")
    assert res["status"] == "unknown_blueprint"
    assert res["is_valid_evidence"] is False
    assert res["needs_review"] is True


def test_classifier_case_3_invalid_evidence():
    """3. 證據不在原文：模型產生幻覺證據 -> status: invalid_evidence"""
    fake_llm = lambda prompt: json.dumps(
        {
            "blueprint": "pathology_mechanism",
            "confidence": 0.88,
            "evidence_span": "這是根本沒有出現在原文中的憑空捏造字串",
            "reason": "幻覺證據",
        }
    )

    res = classify_scene1_blueprint(SAMPLE_SOURCE_TEXT, fake_llm, title="扁桃腺炎")
    assert res["status"] == "invalid_evidence"
    assert res["is_valid_evidence"] is False
    assert res["needs_review"] is True


def test_classifier_case_4_low_confidence():
    """4. 低信心度：confidence < 0.6 -> status: needs_review"""
    fake_llm = lambda prompt: json.dumps(
        {
            "blueprint": "skin_energy",
            "confidence": 0.45,
            "evidence_span": "引發局部組織劇烈充血",
            "reason": "無法確定能量是否適用",
        }
    )

    res = classify_scene1_blueprint(
        SAMPLE_SOURCE_TEXT, fake_llm, title="扁桃腺炎", confidence_threshold=0.6
    )
    assert res["status"] == "needs_review"
    assert res["is_valid_evidence"] is True
    assert res["needs_review"] is True
    assert "低於門檻" in res["reason"]


def test_classifier_case_5_other_option():
    """5. other 選項：無合適模板主動選 other -> status: needs_review"""
    fake_llm = lambda prompt: json.dumps(
        {
            "blueprint": "other",
            "confidence": 0.90,
            "evidence_span": "患者常伴隨高燒、吞嚥劇痛與淋巴結腫大",
            "reason": "純症狀敘述無對應視覺圖元",
        }
    )

    res = classify_scene1_blueprint(SAMPLE_SOURCE_TEXT, fake_llm, title="扁桃腺炎")
    assert res["status"] == "needs_review"
    assert res["blueprint"] == "other"
    assert res["is_valid_evidence"] is True
    assert res["needs_review"] is True


def test_classifier_case_6_normalization_punctuation_tolerance():
    """6. D1 規範：全形逗號、全形頓號、空格差異的容錯比對"""
    # 原文為：引發局部組織劇烈充血、腫脹與發炎反應。
    # 模型輸出微小差異（全形改半形標點、中間含換行或空格）
    evidence_variant = "引發局部組織劇烈充血, 腫脹與發炎反應"
    assert is_evidence_in_source(SAMPLE_SOURCE_TEXT, evidence_variant) is True

    evidence_with_fullwidth_punct = "高燒，吞嚥劇痛，與淋巴結腫大"
    assert is_evidence_in_source(SAMPLE_SOURCE_TEXT, evidence_with_fullwidth_punct) is True


def test_classifier_markdown_json_parsing():
    """測試 LLM 包在 Markdown ```json ... ``` 程式碼區塊時能順利解析"""
    raw_markdown = """
    好的，這是我為您評估的結果：
    ```json
    {
      "blueprint": "surgical_action",
      "confidence": 0.82,
      "evidence_span": "扁桃腺周圍膿瘍",
      "reason": "需要切開引流"
    }
    ```
    希望對您有幫助！
    """
    fake_llm = lambda prompt: raw_markdown
    res = classify_scene1_blueprint(SAMPLE_SOURCE_TEXT, fake_llm, title="扁桃腺炎")
    assert res["status"] == "ok"
    assert res["blueprint"] == "surgical_action"
    assert res["confidence"] == 0.82


def test_prompt_lists_every_allowed_blueprint():
    """提示詞的藍圖清單與規則須涵蓋全部可選藍圖（含 other），避免新增藍圖後漏列。"""
    from src.visual.blueprint_classifier import build_classification_prompt

    prompt = build_classification_prompt(SAMPLE_SOURCE_TEXT, title="扁桃腺炎")
    for bp in CLASSIFIER_ALLOWED_BLUEPRINTS:
        assert bp in prompt, f"提示詞缺少藍圖：{bp}"


def test_prompt_rules_do_not_map_surgery_to_cyst_or_nail():
    """回歸測試：截骨／固定不得被對應到 cyst_excision 或 nail_matrix（舊規則錯誤）。"""
    from src.visual.blueprint_classifier import build_classification_prompt

    prompt = build_classification_prompt(SAMPLE_SOURCE_TEXT)
    assert "截骨、固定或特定解剖構造切除，請選 surgical_action、cyst_excision 或 nail_matrix" not in prompt
