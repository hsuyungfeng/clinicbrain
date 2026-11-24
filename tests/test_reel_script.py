"""Phase 56-03: reel_script.py 單元測試（合規攔截、重試與離線確定性降級）。"""

from __future__ import annotations

import json
import sqlite3

import pytest

from src.visual.reel_script import (
    DEFAULT_REEL_DISCLAIMER,
    ReelScript,
    generate_reel_script,
    validate_reel_script,
)


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE visual_assets (id INTEGER PRIMARY KEY, topic_key TEXT, title TEXT, ir_json TEXT, edu_json TEXT, clinic_id TEXT)"
    )
    ir = {
        "scenes": [
            {"title": "胃酸侵蝕", "caption": "當胃酸侵蝕超過黏膜保護能力，胃壁會受損。"},
            {"title": "病症對照", "caption": "輕度發炎與明顯潰瘍需要不同照護方式。"},
            {"title": "日常預防", "caption": "規律作息與飲食，出現警訊請盡速就醫。"},
        ]
    }
    edu = {
        "red_flags_takeaway": {
            "takeaway": "胃痛別硬撐，警訊出現快就醫，配合醫師評估與追蹤。",
        }
    }
    conn.execute(
        "INSERT INTO visual_assets (topic_key, title, ir_json, edu_json) VALUES (?, ?, ?, ?)",
        ("icd-k279-peptic-ulcer", "消化性潰瘍", json.dumps(ir), json.dumps(edu)),
    )
    return conn


def test_validate_reel_script_blocks_violations() -> None:
    base = ReelScript(
        topic_key="icd-k279-peptic-ulcer",
        hook_title="消化性潰瘍衛教",
        badge="ICD-10: K279",
        summary_points=["胃酸侵蝕黏膜", "及早就醫評估"],
        narration_lines=["當胃酸侵蝕黏膜時請及早由醫師評估。"],
        disclaimer=DEFAULT_REEL_DISCLAIMER,
    )
    ok, errs = validate_reel_script(base)
    assert ok and errs == []

    # 百分比符號與中文分數百分比
    for bad_text in ["成功率達95%", "百分之九十有效", "優惠費用1500元", "保證根治不復發", "胃溃疡治疗"]:
        bad = base.model_copy(update={"hook_title": bad_text})
        ok_bad, errs_bad = validate_reel_script(bad)
        assert not ok_bad, f"應攔截違規文案: {bad_text}"
        assert errs_bad


def test_generate_reel_script_retries_once_on_violation() -> None:
    conn = _make_db()
    calls = {"n": 0}

    def fake_llm(prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({
                "hook_title": "療程100%根治胃潰瘍",
                "badge": "ICD-10: K27.9",
                "summary_points": ["保證有效", "只要500元"],
                "narration_lines": ["一次療程即可永久根治。"],
            }, ensure_ascii=False)
        assert "修正要求" in prompt
        return json.dumps({
            "hook_title": "認識消化性潰瘍成因",
            "badge": "ICD-10: K27.9",
            "summary_points": ["胃酸與黏膜失衡", "戒菸限酒助修復"],
            "narration_lines": ["當胃酸侵蝕黏膜時，請配合醫師評估與生活調整。"],
        }, ensure_ascii=False)

    res = generate_reel_script(conn, "icd-k279-peptic-ulcer", use_llm=True, llm_caller=fake_llm)
    assert calls["n"] == 2
    assert res.source == "ornith"
    assert res.hook_title == "認識消化性潰瘍成因"
    conn.close()


def test_generate_reel_script_fallback_on_error_or_offline() -> None:
    conn = _make_db()
    fb = generate_reel_script(conn, "icd-k279-peptic-ulcer", use_llm=False)
    assert fb.source == "fallback"
    ok, _ = validate_reel_script(fb)
    assert ok

    def boom(_prompt: str) -> str:
        raise RuntimeError("LLM offline")

    fb2 = generate_reel_script(conn, "icd-k279-peptic-ulcer", use_llm=True, llm_caller=boom)
    assert fb2.source == "fallback"
    ok2, _ = validate_reel_script(fb2)
    assert ok2
    conn.close()
