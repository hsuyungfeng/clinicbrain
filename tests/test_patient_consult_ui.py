"""病人簡易諮詢頁前端靜態與離線行為測試 (Phase 27 T2)。

驗證項目：
1. 靜態檔案存在且掛載於 /admin/consult.html 可回應 200。
2. 前端原始碼嚴格遵守安全與隱私規範：
   - 不含 innerHTML、insertAdjacentHTML、document.write、eval。
   - 不含 localStorage、sessionStorage、document.cookie。
3. 前端原始碼包含 /api/v1/general/consult 呼叫與 textContent 安全寫入。
4. 離線行為測試：後端端點格式符合前端需求（不呼叫真實 LLM）。
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config
from src.api.routes import general as general_route
from src.general import patient_consult as pc


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    """建立指向 isolated_db_path 測試複本之 TestClient。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    with TestClient(app) as test_client:
        yield test_client


def test_consult_file_exists():
    """驗證 consult.html 檔案存在於靜態資源目錄。"""
    file_path = Path("src/web/static/consult.html")
    assert file_path.exists(), "src/web/static/consult.html 必須存在"
    assert file_path.is_file()


def test_consult_route_served(client):
    """驗證掛載於 /admin/consult.html 可正常服務並回應 200。"""
    res = client.get("/admin/consult.html")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert "醫療衛教諮詢" in res.text


def test_consult_source_code_safety_and_privacy():
    """驗證前端原始碼嚴格不含禁止的 DOM 操作與客戶端儲存 API。"""
    content = _read_consult_sources()

    forbidden_tokens = [
        "innerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval",
        "localStorage",
        "sessionStorage",
        "document.cookie",
    ]
    for token in forbidden_tokens:
        assert token not in content, f"consult.html 原始碼不得包含 {token}"


def test_consult_source_code_features():
    """驗證前端原始碼包含必要之後端端點呼叫、安全賦值與關鍵文字。"""
    content = _read_consult_sources()

    assert "/api/v1/general/consult/jobs" in content, "必須包含 /api/v1/general/consult/jobs 呼叫路徑"
    assert "/api/v1/general/consult" in content, "必須包含 /api/v1/general/consult 呼叫路徑"
    assert "textContent" in content, "所有回傳內容必須使用 textContent 寫入"
    assert "整理中，通常需 20 秒至 2 分鐘，請稍候" in content, "送出狀態必須包含指定等待提示文字"
    assert "預約諮詢" in content, "必須包含預約諮詢按鈕文字"
    assert 'maxlength="300"' in content, "輸入框必須限制最多 300 字"
    assert "POLL_MAX_MS" in content, "必須包含輪詢逾時常數"
    assert "POLL_INTERVAL_MS" in content, "必須包含輪詢間隔常數"
    assert "setInterval" not in content, "不得使用 setInterval"


def test_offline_backend_consult_red_flag_structure(client):
    """離線驗證：後端紅旗回應結構符合前端渲染需求（不呼叫真實 LLM）。"""
    res = client.post(
        "/api/v1/general/consult",
        json={"query": "我現在胸痛呼吸困難很嚴重"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "red_flag"
    assert "message" in data and len(data["message"]) > 0
    assert "disclaimer" in data and len(data["disclaimer"]) > 0
    assert data["booking_url"] == "https://doctor-toolbox.com/"
    assert data["label"] is None


def test_offline_backend_consult_mock_general_structure(client, monkeypatch):
    """離線驗證：後端一般醫學說明結構符合前端渲染需求（使用假 LLM）。"""
    import json
    from src.general import patient_consult as pc

    mock_warning = "若出現胸痛、呼吸困難或高燒超過38.5度持續3天，請立即前往急診或儘速就醫。"
    mock_body = "這是一段用於測試的一般醫學說明文字，內容為常識性的簡要介紹。" + mock_warning

    def _mock_llm(prompt):
        return json.dumps([{"question": "測試用罕見症狀問題甲", "answer": mock_body}], ensure_ascii=False)

    monkeypatch.setattr(general_route, "default_patient_llm", _mock_llm)
    monkeypatch.setattr(pc, "default_patient_llm", _mock_llm)

    res = client.post(
        "/api/v1/general/consult",
        json={"query": "測試用罕見症狀問題甲"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "llm_general"
    from src.general.answer_compose import CTA_TEXT

    assert mock_body in data["message"]
    assert data["message"].endswith(CTA_TEXT)
    assert data["message"].count("？") == 1
    assert data["label"] == pc.LLM_LABEL
    assert data["disclaimer"] == pc.LLM_DISCLAIMER
    assert data["booking_url"] == "https://doctor-toolbox.com/"


def _read_consult_sources() -> str:
    """HTML、consult.js 與 visual_engine.js 合併內容（CSP script-src 'self' 禁止內嵌腳本，邏輯在外部 JS；掃描須全數涵蓋）。"""
    html = Path("src/web/static/consult.html").read_text(encoding="utf-8")
    js = Path("src/web/static/consult.js").read_text(encoding="utf-8")
    engine_js_path = Path("src/web/static/visual_engine.js")
    engine_js = engine_js_path.read_text(encoding="utf-8") if engine_js_path.exists() else ""
    return html + "\n" + js + "\n" + engine_js


def test_consult_has_no_inline_script_and_loads_external_js(client):
    """回歸（2026-10-19）：/admin 帶 CSP script-src 'self'，consult.html 不得有內嵌 <script>，
    且必須依序載入 visual_engine.js 與 consult.js。"""
    import re

    html = Path("src/web/static/consult.html").read_text(encoding="utf-8")
    inline = [m for m in re.findall(r"<script\b([^>]*)>", html, re.I) if "src=" not in m]
    assert inline == [], "consult.html 不得含內嵌 <script>（會被 CSP 阻擋）"
    assert '<script src="/admin/visual_engine.js"></script>' in html
    assert '<script src="/admin/consult.js"></script>' in html

    res_engine = client.get("/admin/visual_engine.js")
    assert res_engine.status_code == 200
    assert "javascript" in res_engine.headers.get("content-type", "")

    res = client.get("/admin/consult.js")
    assert res.status_code == 200
    assert "javascript" in res.headers.get("content-type", "")
    csp = client.get("/admin/consult.html").headers.get("content-security-policy", "")
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp.split("style-src")[0]

