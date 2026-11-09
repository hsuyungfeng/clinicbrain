"""
Phase 40 Wave 3: 201-400 規模化編譯器與自癒批次生成測試 (test_nhi400_batch_generator.py)。

測試目標：
1. 驗證 build_nhi400_manifest 產出剛好 200 筆合法任務清單，index 介於 201..400。
2. 驗證所有任務之 topic_key、title、keywords、archetype 映射合法無缺。
3. 驗證自癒重試迴圈（Self-Healing Retry Loop）：
   - 模擬模型回傳包含阿拉伯數字（如 "3 個月"）時，自動自癒轉換為中文數字並通過 validate_ir。
   - 模擬模型回傳保證療效禁詞（如 "保證有效"）時，自動攔截替換並自癒通過。
   - 模擬缺少場景或免責聲明時，自動補全免責聲明並自癒通過。
4. 驗證端到端批次生成（run_batch）在 mock 模式下 100% 成功。
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from scripts.build_nhi400_manifest import build_manifest, OUTPUT_PATH as MANIFEST_PATH
from scripts.generate_nhi400_visual_batch import (
    generate_single_item_with_self_healing,
    mock_generate_ir,
    post_process_self_heal,
    run_batch,
    sanitize_text_digits,
)
from src.visual.ir import validate_ir


def test_build_manifest_200_items():
    """驗證 Manifest 編譯產出恰好 200 筆，index 為 201 至 400。"""
    manifest = build_manifest()
    assert len(manifest) == 200
    indices = [m["index"] for m in manifest]
    assert indices == list(range(201, 401))

    # 檢查每一筆的必要欄位
    for m in manifest:
        assert "topic_key" in m and len(m["topic_key"]) >= 3
        assert "title" in m and len(m["title"]) > 0
        assert "disease_name" in m
        assert "archetype" in m
        archetype = m["archetype"]
        assert "s1_organ" in archetype
        assert "s2_left_mode" in archetype
        assert "s2_right_mode" in archetype
        assert "s3_connector" in archetype


def test_sanitize_text_digits():
    """驗證文字中阿拉伯數字與百分比符號轉換為繁體中文。"""
    raw = "經過 3 個月觀察，有 95% 機率改善，需於 10 天內回診"
    cleaned = sanitize_text_digits(raw)
    assert "3" not in cleaned
    assert "95" not in cleaned
    assert "%" not in cleaned
    assert "10" not in cleaned
    assert "三" in cleaned
    assert "十" in cleaned


def test_self_healing_dosage_or_percent_injection():
    """驗證注入處方劑量或百分比時，自癒迴圈能成功清洗並通過 validate_ir。"""
    manifest = build_manifest()
    item = manifest[0]  # W201 哮吼

    # 手工構建含處方劑量/百分比違規的原始 IR
    bad_ir = mock_generate_ir(item, inject_error="dosage_or_percent")
    # 原始 bad_ir 包含違規，檢驗應失敗
    ok_before, code_before = validate_ir(bad_ir)
    assert ok_before is False
    assert code_before in ("forbidden_phrase", "dosage_prescription", "param_error")

    # 執行自癒後處理
    healed = post_process_self_heal(bad_ir, item)
    ok_after, code_after = validate_ir(healed)
    assert ok_after is True, f"自癒後依然失敗: {code_after}"


def test_self_healing_forbidden_phrase_injection():
    """驗證注入保證療效禁詞時，自癒迴圈能成功替換並通過 validate_ir。"""
    manifest = build_manifest()
    item = manifest[10]  # W211 高血壓

    bad_ir = mock_generate_ir(item, inject_error="forbidden_phrase")
    ok_before, code_before = validate_ir(bad_ir)
    assert ok_before is False
    assert code_before == "forbidden_phrase"

    healed = post_process_self_heal(bad_ir, item)
    ok_after, code_after = validate_ir(healed)
    assert ok_after is True, f"自癒後依然失敗: {code_after}"


def test_generate_single_item_with_self_healing():
    """驗證單筆生成函式在 Mock 模式下順利回傳合格 IR。"""
    manifest = build_manifest()
    item = manifest[50]  # 隨機挑選一筆

    ok, ir_dict, code = generate_single_item_with_self_healing(item, mock_mode=True)
    assert ok is True
    assert ir_dict is not None
    assert code in ("ok", "ok_fallback")

    # 雙重驗證 IR
    val_ok, val_code = validate_ir(ir_dict)
    assert val_ok is True
    assert val_code == "ok"


def test_run_batch_mock_dry_run():
    """驗證小批量（5 筆）乾跑生成 100% 成功率。"""
    summary = run_batch(limit=5, mock_mode=True, dry_run=True, write_db=False)
    assert summary["total"] == 5
    assert summary["success"] == 5
    assert summary["failed"] == 0
    assert summary["success_rate"] == "100.0%"
