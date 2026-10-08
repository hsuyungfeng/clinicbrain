"""Phase 19 前端結構與 XSS 防護靜態檢查。"""

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


def test_html_has_batch_controls(client):
    html = client.get("/admin/").text
    for ident in ("btnSelectAll", "btnInvertSelect", "btnClearSelect", "selectionCounter",
                  "actionBar", "btnBatchApprove", "btnBatchReject", "toast"):
        assert f'id="{ident}"' in html
    assert 'value="web_upload"' in html  # 來源篩選含網頁上傳


def test_js_wires_new_endpoints(client):
    js = client.get("/admin/app.js").text
    assert "/api/v1/admin/review/batch" in js
    assert "/generate-answer" in js
    assert 'method: "PATCH"' in js
    assert "本地 LLM 生成解答" in js and "✏️ 編輯" in js


def test_js_never_injects_server_data_via_html(client):
    """審核區塊不得以 innerHTML／insertAdjacentHTML／document.write 置入動態資料。"""
    js = client.get("/admin/app.js").text
    start = js.index("// 4. 待審草稿簽核")
    end = js.index("// 5. 文件拖曳上傳")
    review = js[start:end]
    assert not re.search(r"innerHTML|insertAdjacentHTML|document\.write|outerHTML|eval\(", review)


def test_css_has_clinical_theme(client):
    css = client.get("/admin/style.css").text
    for token in (".action-bar", ".spinner", ".skeleton", ".badge-warn", ".faq-card"):
        assert token in css
