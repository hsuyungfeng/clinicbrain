"""
Taiwan Clinic Medical PageIndex RAG System - Web App 前端介面靜態檔案測試 (test_web_ui)
Phase 18 Plan 18-02: 靜態 HTML5/CSS/JS 開放與路由掛載驗證
"""

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    """建立指向 isolated_db_path 測試複本之 TestClient。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    with TestClient(app) as test_client:
        yield test_client


def test_admin_web_ui_routes(client):
    """測試 /admin 靜態網頁與資源檔案正常服務。"""
    # 1. 測試 HTML 首頁
    res_index = client.get("/admin/")
    assert res_index.status_code == 200
    assert "clinicbrain 診所管理 Web App" in res_index.text
    assert "<title>clinicbrain 診所衛教與管理系統</title>" in res_index.text

    # 2. 測試 style.css
    res_css = client.get("/admin/style.css")
    assert res_css.status_code == 200
    assert ".nav-tab.active" in res_css.text

    # 3. 測試 app.js
    res_js = client.get("/admin/app.js")
    assert res_js.status_code == 200
    assert "initAuth()" in res_js.text
    assert "loadReviewFaqs" in res_js.text


def test_admin_ui_security_headers(client):
    """複審：/admin 靜態頁面須帶 CSP 與防嵌入標頭，且前端 SOAP 檢索走 POST＋金鑰。"""
    res = client.get("/admin/")
    csp = res.headers.get("content-security-policy", "")
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert res.headers.get("x-frame-options") == "DENY"
    js = client.get("/admin/app.js").text
    assert "/api/v1/soap/search" in js and 'method: "POST"' in js
