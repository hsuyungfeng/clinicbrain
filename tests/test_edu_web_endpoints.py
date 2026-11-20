"""Phase 53-03: 雙軌衛教 API (`/api/v1/visual/edu/{topic_key}`) 與獨立分享頁 (`/edu/{topic_key}`) 測試。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from src.api.app import create_app
from src.api.dependencies import get_read_db

ROOT_DIR = Path(__file__).resolve().parent.parent
EDU_HTML_PATH = ROOT_DIR / "src" / "web" / "static" / "edu.html"
EDU_JS_PATH = ROOT_DIR / "src" / "web" / "static" / "edu.js"
VISUAL_ENGINE_PATH = ROOT_DIR / "src" / "web" / "static" / "visual_engine.js"


def test_edu_api_and_html_endpoints() -> None:
    app = create_app()

    def _override_read_db():
        conn = sqlite3.connect(str(ROOT_DIR / "clinic.db"), check_same_thread=False)
        conn.execute("PRAGMA query_only = ON;")
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_read_db] = _override_read_db
    client = TestClient(app)

    # 1. 已核准且已生成之大腸結腸憩室病
    resp = client.get("/api/v1/visual/edu/nhi-w225-k57-30")
    assert resp.status_code == 200
    data = resp.json()
    assert data["topic_key"] == "nhi-w225-k57-30"
    assert data["share_url"] == "/edu/nhi-w225-k57-30"
    assert data["edu"] is not None
    for key in (
        "definition",
        "comparison",
        "causes_risks",
        "symptoms_complications",
        "diagnosis",
        "prevention_myth",
        "red_flags_takeaway",
    ):
        assert key in data["edu"]
    assert data["ir"]["scenes"][2]["blueprint"] == "care_redflag"

    # 2. 不存在之主題應回 404
    assert client.get("/api/v1/visual/edu/nonexistent-topic-xyz").status_code == 404

    # 3. 獨立衛教頁面 /edu/{topic_key}
    page_resp = client.get("/edu/nhi-w225-k57-30")
    assert page_resp.status_code == 200
    assert "visual_engine.js" in page_resp.text
    assert "edu.js" in page_resp.text


def test_edu_page_playwright_renders_7_sections_and_svg() -> None:
    conn = sqlite3.connect(str(ROOT_DIR / "clinic.db"))
    row = conn.execute(
        "SELECT title, ir_json, edu_json FROM visual_assets WHERE topic_key = 'nhi-w225-k57-30'"
    ).fetchone()
    conn.close()
    assert row is not None and row[2] is not None
    payload = {
        "title": row[0],
        "ir": json.loads(row[1]),
        "edu": json.loads(row[2]),
    }

    html = EDU_HTML_PATH.read_text(encoding="utf-8")
    js_engine = VISUAL_ENGINE_PATH.read_text(encoding="utf-8")
    js_edu = EDU_JS_PATH.read_text(encoding="utf-8")

    # 內聯靜態資源以便無網路獨立測試
    html_inline = (
        html.replace('<link rel="stylesheet" href="/static/tailwind.min.css" />', "")
        .replace('<script src="/static/visual_engine.js"></script>', f"<script>{js_engine}</script>")
        .replace('<script src="/static/edu.js"></script>', f"<script>{js_edu}</script>")
    )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1024, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.set_content(html_inline)
        page.evaluate(
            """(p) => {
                document.getElementById('edu-title').textContent = p.title;
                const svg = document.getElementById('edu-svg-stage');
                const m = window.ClinicVisual.mount(svg, p.ir.scenes);
                m.renderAt(m.totalDuration * 0.85);
                window.ClinicEduRenderer.renderEduSections(document.getElementById('edu-sections'), p.edu);
            }""",
            payload,
        )
        text = page.locator("#edu-sections").inner_text()
        assert "一、認識這個狀況" in text
        assert "七、何時必須立即就醫" in text
        assert "一句話記牢：" in text
        svg_html = page.locator("#edu-svg-stage").evaluate("el => el.outerHTML")
        assert "日常衛教重點與急診紅旗警訊" in svg_html
        browser.close()
    assert not errors, f"Playwright 出現 JS 錯誤: {errors}"
