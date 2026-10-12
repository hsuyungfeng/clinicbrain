"""
Taiwan Clinic Medical PageIndex RAG System - Web App 臨床決策推理樹簽核介面測試
Phase 21 Plan 21-02: 驗證 index.html、style.css 與 app.js 中推理樹頁籤、四段卡片、醫師醫囑與編輯 Modal
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


def test_html_has_trees_tab_and_components(client):
    """驗證 HTML 包含 tab-trees 頁籤、統計卡片、篩選控制項、上傳目標切換與編輯 Modal。"""
    html = client.get("/admin/").text

    # 頁籤與容器
    assert 'data-tab="tab-trees"' in html
    assert 'id="tab-trees"' in html
    assert 'id="treesContainer"' in html

    # 儀表板卡片
    assert 'id="statTreesPendingTotal"' in html
    assert 'id="statTreesApprovedTotal"' in html

    # 篩選控制項
    assert 'id="treesFilterStatus"' in html
    assert 'id="treesFilterCategory"' in html
    assert 'id="btnRefreshTrees"' in html

    # 上傳目標切換
    assert 'name="uploadTarget"' in html
    assert 'value="tree"' in html
    assert 'id="uploadTreeTitle"' in html

    # 編輯 Modal 與四段醫師指令
    assert 'id="treeEditModal"' in html
    assert 'id="treeEditPreOpNotes"' in html
    assert 'id="treeEditProcedureNotes"' in html
    assert 'id="treeEditPostOpNotes"' in html
    assert 'id="treeEditMaintenanceNotes"' in html


def test_css_has_tree_card_and_physician_styling(client):
    """驗證 CSS 包含 .tree-card、四段網格與醫師特約指令專業邊框樣式。"""
    css = client.get("/admin/style.css").text
    for token in (
        ".tree-card",
        ".tree-sections-grid",
        ".tree-section-box",
        ".tree-physician-note",
        ".tree-physician-badge",
        ".tree-summary-box",
    ):
        assert token in css, f"Missing {token} in style.css"


def test_js_wires_trees_endpoints_and_safe_dom(client):
    """驗證 JavaScript 正確連接 /api/v1/admin/trees API，且所有操作無 innerHTML 注入風險。"""
    js = client.get("/admin/app.js").text

    assert "/api/v1/admin/trees" in js
    assert "initTreesSection" in js
    assert "loadTrees" in js
    assert "createTreeCard" in js
    assert "openTreeEditModal" in js

    # 驗證推理樹區塊內無 innerHTML 拼接
    start = js.index("// Phase 21: 臨床決策推理樹簽核與管理前端邏輯")
    trees_section = js[start:]
    assert not re.search(r"innerHTML|insertAdjacentHTML|document\.write|outerHTML|eval\(", trees_section)
