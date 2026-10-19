"""
Phase 29 Plan 04: 病人諮詢頁視覺解說卡前端渲染與事件回報測試 (test_consult_visual_ui.py)。

驗證目標：
1. 靜態安全掃描：
   - 不含 innerHTML、insertAdjacentHTML、document.write、eval、localStorage、sessionStorage、document.cookie、setInterval。
   - 不含外部 <script src= 或 <img src=http。
   - 視覺解說卡容器內不含任何 <input、<form、電話或 LINE 輸入欄位。
2. 功能與結構檢驗：
   - 包含 renderVisual 函式，並在 renderResult 結尾呼叫。
   - 顯示條件明確限定 status 為 answered 或 llm_general，且 scenes 長度介於 3～5。
   - 支援三種場景模板（process_diagram、contrast、timeline），並使用 createElementNS 建立 SVG。
   - 包含固定前端免責常數文字「一般醫學知識說明，非個人化診斷；實際狀況須由醫師當面評估」。
   - 包含上一步／下一步按鈕與 @media (prefers-reduced-motion: reduce) 樣式。
   - 包含 /api/v1/general/visual/event 匿名事件回報（shown 與 completed）與 keepalive: true。
"""

from __future__ import annotations

import re
from pathlib import Path


CONSULT_HTML_PATH = Path("src/web/static/consult.html")
CONSULT_JS_PATH = Path("src/web/static/consult.js")
ENGINE_JS_PATH = Path("src/web/static/visual_engine.js")


def _read_consult_html() -> str:
    # 2026-10-19：/admin 的 CSP 為 script-src 'self'，內嵌腳本會被瀏覽器阻擋，
    # 前端邏輯在 consult.js 與 visual_engine.js；靜態掃描須同時涵蓋 HTML 與所有同源 JS。
    engine_js = ENGINE_JS_PATH.read_text(encoding="utf-8") if ENGINE_JS_PATH.exists() else ""
    return (
        CONSULT_HTML_PATH.read_text(encoding="utf-8")
        + "\n"
        + CONSULT_JS_PATH.read_text(encoding="utf-8")
        + "\n"
        + engine_js
    )


def test_consult_visual_security_no_dangerous_apis_or_external_assets():
    """確認 consult.html 不含危險 DOM 操作、儲存 API、計時輪播與外部腳本/圖片。"""
    html = _read_consult_html()

    forbidden_substrings = [
        "innerHTML",
        "insertAdjacentHTML",
        "document.write",
        "outerHTML",
        "eval",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "setInterval",
    ]
    for sub in forbidden_substrings:
        assert sub not in html, f"consult.html 不得包含禁用子字串: {sub}"

    # 禁止外部 script 或外部 img
    # 2026-10-19 最小更新：同源引入 visual_engine.js 與 consult.js（順序：引擎在前），
    # 任何其他 src（含 http(s)、// 協定相對、其他路徑）一律禁止。
    script_srcs = re.findall(r"<script\b[^>]*\bsrc\s*=\s*['\"]([^'\"]*)['\"]", html, re.IGNORECASE)
    assert script_srcs == ["/admin/visual_engine.js", "/admin/consult.js"], f"只允許同源 visual_engine.js 與 consult.js，實際: {script_srcs}"
    assert not re.search(r"<img\b[^>]*\bsrc\s*=\s*['\"]?https?:", html, re.IGNORECASE)


def test_consult_html_script_order_and_no_inline():
    """回歸驗證：HTML 無內嵌 <script>，且 visual_engine.js 在 consult.js 之前。"""
    raw_html = CONSULT_HTML_PATH.read_text(encoding="utf-8")
    inline_scripts = [m for m in re.findall(r"<script\b([^>]*)>", raw_html, re.IGNORECASE) if "src=" not in m]
    assert inline_scripts == [], "consult.html 不得含內嵌 <script>"

    srcs = re.findall(r"<script\b[^>]*\bsrc\s*=\s*['\"]([^'\"]*)['\"]", raw_html, re.IGNORECASE)
    assert srcs == ["/admin/visual_engine.js", "/admin/consult.js"], f"腳本順序必須為引擎在前，實際: {srcs}"


def test_consult_visual_card_has_no_input_or_form_elements():
    """確認解說卡區塊不含任何表單、input、電話或 LINE 收集欄位。"""
    html = _read_consult_html()
    assert 'id="visualCard"' in html

    # 整個頁面除了原本的 consultInput textarea 外，不應有任何 <input 或 <form
    assert "<input" not in html.lower()
    assert "<form" not in html.lower()


def test_consult_visual_features_blueprints_and_disclaimer():
    """確認 renderVisual、三種 blueprint、createElementNS、固定免責常數與無障礙降級皆到位。"""
    html = _read_consult_html()

    # 1. 函式與呼叫
    assert "function renderVisual(" in html
    assert "renderVisual(data);" in html

    # 2. 狀態與場景數量守門
    assert "answered" in html and "llm_general" in html
    assert "scenes.length < 3" in html or "scenes.length >= 3" in html

    # 3. 三種 blueprint 與 SVG createElementNS
    for bp in ("process_diagram", "contrast", "timeline"):
        assert bp in html, f"必須支援場景模板: {bp}"
    assert "http://www.w3.org/2000/svg" in html
    assert "createElementNS" in html

    # 4. 三種 tone 標籤樣式
    for tone in ("neutral", "warning", "optimal"):
        assert tone in html, f"必須支援標籤 tone: {tone}"

    # 5. 固定免責常數文字
    fixed_disclaimer = "一般醫學知識說明，非個人化診斷；實際狀況須由醫師當面評估"
    assert fixed_disclaimer in html

    # 6. 上一步／下一步控制與 prefers-reduced-motion
    assert "上一步" in html
    assert "下一步" in html
    assert "prefers-reduced-motion: reduce" in html


def test_consult_visual_event_reporting():
    """確認 shown 與 completed 匿名事件回報使用 fetch POST 與 keepalive。"""
    html = _read_consult_html()

    assert "/api/v1/general/visual/event" in html
    assert '"shown"' in html or "'shown'" in html
    assert '"completed"' in html or "'completed'" in html
    assert "keepalive" in html
