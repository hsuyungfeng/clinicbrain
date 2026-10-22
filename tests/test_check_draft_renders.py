"""Phase 34 Plan 02：草稿渲染驗收腳本的單元測試（不需瀏覽器、不查正式庫）。"""

from __future__ import annotations

import ast
import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_draft_renders.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_draft_renders", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


def test_summarize_scene_flags_violation_and_nondeterminism():
    ok = mod.summarize_scene(0, "contrast", [], True, None)
    assert ok["ok"] is True
    bad_bounds = mod.summarize_scene(1, "contrast", [{"tag": "rect", "type": "out_of_bounds"}], True, None)
    assert bad_bounds["ok"] is False
    drift = mod.summarize_scene(2, "timeline", [], False, None)
    assert drift["ok"] is False
    err = mod.summarize_scene(0, "timeline", [], True, "TimeoutError")
    assert err["ok"] is False


def test_build_report_counts_and_lists_failures():
    results = [
        {"topic_key": "tree-a", "ok": True, "scenes": [], "clinic_id": "1", "id": 1, "review_status": "pending"},
        {"topic_key": "tree-b", "ok": False, "scenes": [], "clinic_id": "1", "id": 2, "review_status": "pending"},
    ]
    report = mod.build_report(results, "2026-10-22T00:00:00+00:00")
    assert report["draft_count"] == 2
    assert report["ok_count"] == 1
    assert report["failed_topic_keys"] == ["tree-b"]


def test_write_outputs_overwrites_stale_report(tmp_path):
    stale = tmp_path / "REPORT.md"
    stale.write_text("舊的過時報告", encoding="utf-8")
    report = mod.build_report([], "2026-10-22T00:00:00+00:00")
    mod.write_outputs(tmp_path, report)
    text = stale.read_text(encoding="utf-8")
    assert "舊的過時報告" not in text
    assert "草稿數：0" in text
    assert (tmp_path / "report.json").exists()


def test_readonly_connection_rejects_writes(tmp_path):
    db = tmp_path / "t.db"
    setup = sqlite3.connect(str(db))
    setup.execute("CREATE TABLE visual_assets (id INTEGER PRIMARY KEY, topic_key TEXT)")
    setup.commit()
    setup.close()
    conn = mod.open_readonly(db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO visual_assets (topic_key) VALUES ('x')")
    finally:
        conn.close()


def test_script_never_opens_writable_connection():
    """AST 守門：所有 sqlite3.connect 呼叫都必須使用 mode=ro 的 URI。"""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "connect":
            src = ast.get_source_segment(SCRIPT.read_text(encoding="utf-8"), node) or ""
            assert "mode=ro" in src, src


def test_script_does_not_call_llm_or_write_db():
    text = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("local_llm_call", "upsert_assets", "set_review_status", "INSERT INTO", "UPDATE visual_assets"):
        assert forbidden not in text, forbidden
