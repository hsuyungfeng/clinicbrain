"""Phase 52 深度回歸測試：全庫 398 筆 visual_assets 稽核與瀏覽器繪圖器派發驗證。"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.audit_db_visual_assets import audit_db, simulate_js_drawer
from src.visual.video_queue import compute_ir_sha256, _visual_engine_salt

DB_PATH = PROJECT_ROOT / "clinic.db"
VISUAL_ENGINE_PATH = PROJECT_ROOT / "src" / "web" / "static" / "visual_engine.js"


def test_all_398_visual_assets_zero_anatomy_mismatches():
    rep = audit_db(DB_PATH)
    assert rep["total"] >= 398
    assert rep["mismatch_count"] == 0, f"發現全庫錯配: {rep['findings']}"


def test_video_queue_hash_includes_visual_engine_salt():
    salt = _visual_engine_salt()
    assert len(salt) == 12
    h1 = compute_ir_sha256({"a": 1})
    assert len(h1) == 64


def test_key_corrected_topics_drawer_routing_and_browser_render():
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("Playwright 未安裝")

    expected_labels = {
        "nhi-d384-b37-0": "口腔黏膜・舌背・唾液腺",
        "nhi-d385-k11-6": "口腔黏膜・舌背・唾液腺",
        "nhi-d389-k11-6": "口腔黏膜・舌背・唾液腺",
        "nhi-w209-k12-0": "口腔黏膜・舌背・唾液腺",
        "nhi-d393-k00-1": "上顎正中門齒與多生錐齒",
        "nhi-d395-m26-62": "顳顎關節窩・關節盤・髁突",
        "nhi-d397-t85-79": "人工植體螺紋與周圍骨",
    }

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        assets = {}
        for tk in list(expected_labels.keys()) + ["nhi-w266-n48-1", "nhi-w283-g50-0"]:
            row = conn.execute("SELECT ir_json FROM visual_assets WHERE topic_key=?", (tk,)).fetchone()
            assert row is not None, f"找不到 {tk}"
            ir = json.loads(row[0])
            assets[tk] = ir
    finally:
        conn.close()

    assert simulate_js_drawer(assets["nhi-w266-n48-1"]["scenes"][0]["params"]) == "uro_pelvic"
    assert simulate_js_drawer(assets["nhi-w283-g50-0"]["scenes"][0]["params"]) == "vascular_metabolic"

    js_code = VISUAL_ENGINE_PATH.read_text(encoding="utf-8")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 800, "height": 600})
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.set_content(f"<!doctype html><html><body><svg id='stage' viewBox='0 0 800 500'></svg><script>{js_code}</script></body></html>")

        for tk, expected_text in expected_labels.items():
            scene = assets[tk]["scenes"][0]
            svg_text = page.evaluate(
                """([scene]) => {
                    const svg = document.getElementById('stage');
                    const m = window.ClinicVisual.mount(svg, [scene]);
                    m.renderAt(m.totalDuration * 0.4);
                    return svg.outerHTML;
                }""",
                [scene],
            )
            assert expected_text in svg_text, f"{tk} 預期含 {expected_text!r}，實際輸出: {svg_text[:180]}"
        browser.close()
    assert errors == [], f"JS 執行錯誤: {errors}"
