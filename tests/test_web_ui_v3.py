"""
Taiwan Clinic Medical PageIndex RAG System - Web App 前端 V3 (Phase 20 Auto-Filler) 測試
驗證 index.html, style.css, app.js 包含背景自動補齊與選取補齊相關元件及邏輯。
"""

import re
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    with TestClient(app) as c:
        yield c


def test_html_has_autofill_and_batch_selected_elements(client):
    """驗證 HTML 包含 Phase 20 Auto-Filler 按鈕、進度橫幅、取消按鈕與浮動列選取補齊按鈕。"""
    html = client.get("/admin/").text
    for ident in (
        "btnAutoFillAll",
        "autofillProgressBanner",
        "autofillStatusText",
        "autofillCountText",
        "btnCancelAutoFill",
        "autofillProgressBar",
        "autofillDetailText",
        "btnBatchGenerateSelected",
    ):
        assert f'id="{ident}"' in html, f"Missing #{ident} in index.html"


def test_css_has_autofill_progress_banner_styles(client):
    """驗證 CSS 包含 .progress-banner 等樣式定義。"""
    css = client.get("/admin/style.css").text
    for token in (
        ".progress-banner",
        ".progress-banner-head",
        ".progress-banner-text",
        ".progress-banner-count",
    ):
        assert token in css, f"Missing {token} in style.css"


def test_js_wires_autofill_endpoints_and_polling(client):
    """驗證 JavaScript 正確連接 /autofill/all、3000ms 輪詢與對應事件處理函式。"""
    js = client.get("/admin/app.js").text
    assert "/api/v1/admin/review/autofill/all" in js
    assert "startAutoFillAll" in js
    assert "startBatchGenerateSelected" in js
    assert "btnAutoFillAll" in js
    assert "btnBatchGenerateSelected" in js
    assert "btnCancelAutoFill" in js
    # 驗證輪詢週期包含 3000ms
    assert "3000" in js

    # 驗證審核區塊無 innerHTML 注入安全漏洞
    start = js.index("// 4. 待審草稿簽核")
    end = js.index("// 5. 文件拖曳上傳")
    review = js[start:end]
    assert not re.search(r"innerHTML|insertAdjacentHTML|document\.write|outerHTML|eval\(", review)
