"""
tests/test_visual_motion_vocab.py
驗證 clinic-visual-batch 之 motion-prompt 動態規格字典規格完整性與法規合規性
"""

import json
from pathlib import Path
import pytest


VOCAB_PATH = Path(__file__).resolve().parent.parent / ".agents" / "skills" / "clinic-visual-batch" / "resources" / "motion_vocab.json"


def test_motion_vocab_file_exists():
    assert VOCAB_PATH.exists(), f"找不到動態字典檔案: {VOCAB_PATH}"


def test_motion_vocab_schema_and_keys():
    with open(VOCAB_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    expected_top_keys = {"metadata", "easings", "motions", "camera_actions", "guardrails"}
    assert expected_top_keys.issubset(set(data.keys())), f"頂層鍵缺失: {expected_top_keys - set(data.keys())}"

    # Metadata checks
    meta = data["metadata"]
    assert meta.get("duration_cycle_seconds") == 24.0
    assert meta.get("scenes_count") == 3
    assert meta.get("scene_duration_seconds") == 8.0
    assert meta.get("compliance", {}).get("traditional_chinese_only") is True
    assert meta.get("compliance", {}).get("zero_price_leakage") is True


def test_easings_specification():
    with open(VOCAB_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    easings = data.get("easings", {})
    assert len(easings) >= 5, "至少需包含 5 種核心緩動曲線"

    for key, spec in easings.items():
        assert "name" in spec, f"緩動 {key} 缺少 name"
        assert "bezier" in spec, f"緩動 {key} 缺少 bezier"
        bezier = spec["bezier"]
        assert isinstance(bezier, list) and len(bezier) == 4, f"{key} bezier 必須為 4 元素陣列"
        for val in bezier:
            assert isinstance(val, (int, float)), f"{key} bezier 元素必須為數值"


def test_motions_specification():
    with open(VOCAB_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    easings = data.get("easings", {})
    motions = data.get("motions", {})
    assert len(motions) >= 8, "至少需包含 8 種醫療專科解剖/病理動效"

    for key, spec in motions.items():
        assert "name" in spec, f"動態 {key} 缺少 name"
        assert "category" in spec, f"動態 {key} 缺少 category"
        assert "default_easing" in spec, f"動態 {key} 缺少 default_easing"
        assert spec["default_easing"] in easings, f"動態 {key} 參考了不存在的緩動 {spec['default_easing']}"
        assert "duration_range" in spec, f"動態 {key} 缺少 duration_range"
        dur_range = spec["duration_range"]
        assert isinstance(dur_range, list) and len(dur_range) == 2, f"{key} duration_range 必須為 [min, max]"
        min_d, max_d = dur_range
        assert 0.1 <= min_d <= max_d <= 8.0, f"{key} duration_range 範圍不合法 (需在 0.1s ~ 8.0s 之間)"


def test_camera_actions_specification():
    with open(VOCAB_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    easings = data.get("easings", {})
    cameras = data.get("camera_actions", {})
    assert len(cameras) >= 3, "至少需包含 3 種運鏡方式"

    for key, spec in cameras.items():
        assert "name" in spec, f"相機動作 {key} 缺少 name"
        assert "default_easing" in spec, f"相機動作 {key} 缺少 default_easing"
        assert spec["default_easing"] in easings, f"相機動作 {key} 參考了不存在的緩動"


def test_compliance_and_terminology():
    with open(VOCAB_PATH, "r", encoding="utf-8") as f:
        raw_text = f.read()

    # 價格檢查
    price_markers = ["元", "NT$", "塊錢", "特價", "優惠"]
    for pm in price_markers:
        assert pm not in raw_text, f"動態字典內嚴禁出現價格敏感詞彙: {pm}"

    # 保證療效禁詞檢查
    forbidden_terms = ["保證有效", "保證根除", "百分之百", "零風險", "完全不復發"]
    for ft in forbidden_terms:
        assert ft not in raw_text, f"動態字典內嚴禁出現保證療效詞彙: {ft}"
