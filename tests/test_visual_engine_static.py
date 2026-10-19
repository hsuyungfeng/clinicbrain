"""
Phase 30 Plan 02 Task 1: 視覺場景引擎靜態安全掃描與介面測試 (test_visual_engine_static.py)。

驗證目標：
1. 外部檔案存在於 src/web/static/visual_engine.js。
2. 原始碼與註解嚴格不含任何禁用子字串：
   - innerHTML, insertAdjacentHTML, document.write, outerHTML
   - eval（包含任何大小寫與複合單字如 retrieval、evaluation 等）
   - localStorage, sessionStorage, document.cookie
   - setInterval, setTimeout
   - Date.now, Math.random, new Date, performance.now
   - fetch(, XMLHttpRequest, import(, <script
3. 具備全域 ClinicVisual IIFE 與必要公開介面：
   - blueprints, PALETTE, resolveParams, sceneDuration, mount
4. 命名空間安全：除了 SVG 命名空間 http://www.w3.org/2000/svg 外，不含任何外部 http(s) 網址。
"""

from __future__ import annotations

from pathlib import Path
import re
import pytest

ENGINE_JS_PATH = Path("src/web/static/visual_engine.js")


def _read_engine_source() -> str:
    assert ENGINE_JS_PATH.exists(), f"引擎檔案不存在：{ENGINE_JS_PATH}"
    return ENGINE_JS_PATH.read_text(encoding="utf-8")


def test_visual_engine_file_exists():
    """驗證 visual_engine.js 檔案存在且為非空一般檔案。"""
    assert ENGINE_JS_PATH.exists(), "src/web/static/visual_engine.js 必須存在"
    assert ENGINE_JS_PATH.is_file()
    content = _read_engine_source()
    assert len(content.strip()) > 0


def test_visual_engine_no_forbidden_substrings():
    """驗證 visual_engine.js 絕不含危險 DOM 操作、計時器、非確定性時間與儲存 API（含註解）。"""
    content = _read_engine_source()

    forbidden_list = [
        "innerHTML",
        "insertAdjacentHTML",
        "document.write",
        "outerHTML",
        "eval",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "setInterval",
        "setTimeout",
        "Date.now",
        "Math.random",
        "new Date",
        "performance.now",
        "fetch(",
        "XMLHttpRequest",
        "import(",
        "<script",
    ]

    for forbidden in forbidden_list:
        assert forbidden not in content, f"visual_engine.js 不得包含禁用子字串: {forbidden}"

    # 特別嚴格檢查：任何大小寫的 eval（連 retrieval、evaluation 都不可出現）
    lower_content = content.lower()
    assert "eval" not in lower_content, "visual_engine.js 不得包含任何含有 eval 的單字（含註解）"


def test_visual_engine_exports_and_interfaces():
    """驗證 visual_engine.js 定義全域 ClinicVisual 及其必要介面。"""
    content = _read_engine_source()

    assert "ClinicVisual" in content, "必須導出全域物件 ClinicVisual"
    assert "blueprints" in content, "必須包含 blueprints 註冊表"
    assert "PALETTE" in content, "必須包含 PALETTE 調色盤"
    assert "resolveParams" in content, "必須包含 resolveParams 函式"
    assert "sceneDuration" in content, "必須包含 sceneDuration 函式"
    assert "mount" in content, "必須包含 mount 函式"

    for bp in ("process_diagram", "contrast", "timeline"):
        assert bp in content, f"必須包含 blueprint 定義: {bp}"


def test_visual_engine_no_external_urls():
    """驗證除了 SVG 規範命名空間外，不含任何外部 http/https 網路請求連結。"""
    content = _read_engine_source()
    urls = re.findall(r"https?://[^\s'\"]+", content)
    # 只允許 http://www.w3.org/2000/svg
    allowed_urls = {"http://www.w3.org/2000/svg"}
    for url in urls:
        assert url in allowed_urls, f"不允許的外部 URL: {url}"
