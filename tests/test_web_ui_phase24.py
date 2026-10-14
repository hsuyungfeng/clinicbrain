"""
Web UI tests for Phase 24 Upload Center enhancements.
Plan 24-03:
- Static HTML & JS wiring checks for uploadSource, uploadName, and upload-url endpoint.
- XSS prevention (textContent rules, no innerHTML in slice).
- Behavioral tests executing pure functions from app.js upload slice via Node.js.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest
from starlette.testclient import TestClient

from src.api.app import app
from src.api.config import config


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    with TestClient(app) as c:
        yield c


def _get_upload_slice() -> str:
    js_text = Path("src/web/static/app.js").read_text(encoding="utf-8")
    start = js_text.index("// 上傳佇列")
    end = js_text.index("// 6. SOAP 瀏覽")
    return js_text[start:end]


def _run_node_expression(expression: str):
    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("node 不存在，略過行為測試")

    js_slice = _get_upload_slice()
    runner = f"""
const vm = require('vm');
const sandbox = {{
    document: {{
        getElementById: () => null,
        querySelectorAll: () => [],
        querySelector: () => null,
    }},
    window: {{}},
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    UPLOAD_EXTS: [".docx", ".xlsx", ".pdf"],
    UPLOAD_MAX_BYTES: 15 * 1024 * 1024,
    UPLOAD_MAX_FILES: 200,
    uploadState: {{ queue: [], busy: false }},
    showToast: () => {{}},
    getAuthHeaders: () => ({{}}),
    loadDashboardSummary: () => {{}},
}};
vm.createContext(sandbox);
const code = {json.dumps(js_slice)};
vm.runInContext(code, sandbox);
const res = vm.runInContext({json.dumps(expression)}, sandbox);
console.log(JSON.stringify(res));
"""
    proc = subprocess.run([node_bin, "-e", runner], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, f"Node script execution failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    return json.loads(proc.stdout.strip())


# =========================================================================
# 靜態結構與接線測試
# =========================================================================

def test_url_mode_controls_present(client: TestClient):
    html = client.get("/admin/").text
    assert 'name="uploadSource"' in html
    assert 'value="file"' in html
    assert 'value="url"' in html
    assert 'id="uploadUrl"' in html
    assert 'type="url"' in html
    assert 'id="uploadName"' in html
    assert 'id="uploadNameHint"' in html
    assert 'id="urlSourceField"' in html
    assert 'id="fileSourceArea"' in html


def test_url_mode_wired_to_upload_url(client: TestClient):
    js = client.get("/admin/app.js").text
    assert "/api/v1/admin/upload-url" in js
    assert "uploadUrl" in js
    assert "uploadName" in js
    assert 'target' in js


def test_legacy_upload_endpoint_still_wired(client: TestClient):
    js = client.get("/admin/app.js").text
    assert "/api/v1/admin/upload" in js
    assert '"preview_only"' in js


def test_upload_section_no_html_injection():
    sect = _get_upload_slice()
    assert not re.search(r"innerHTML|insertAdjacentHTML|document\.write|outerHTML|eval\(", sect)


def test_tree_target_disables_url_source():
    sect = _get_upload_slice()
    assert "uploadTarget" in sect
    assert "disabled" in sect
    assert "僅支援 FAQ 草稿" in sect


def test_missing_fields_not_echoed_as_text():
    sect = _get_upload_slice()
    # 斷言不得直接回顯 data.missing_fields
    assert not re.search(r"textContent\s*=\s*data\.missing_fields", sect)


def test_static_assets_served(client: TestClient):
    r_index = client.get("/admin/")
    assert r_index.status_code == 200
    assert "uploadSource" in r_index.text

    r_js = client.get("/admin/app.js")
    assert r_js.status_code == 200
    assert "upload-url" in r_js.text


# =========================================================================
# 行為測試（以 Node.js 執行切片純函式）
# =========================================================================

def test_batch_multi_file_never_sends_name():
    # queueLength > 1 時，絕不附加 name
    res2 = _run_node_expression('uploadNameForSubmit(2, "甲")')
    assert res2 is None
    res5 = _run_node_expression('uploadNameForSubmit(5, "甲")')
    assert res5 is None


def test_single_file_sends_trimmed_name():
    res1 = _run_node_expression('uploadNameForSubmit(1, "  甲  ")')
    assert res1 == "甲"
    res_blank = _run_node_expression('uploadNameForSubmit(1, "   ")')
    assert res_blank is None
    res0 = _run_node_expression('uploadNameForSubmit(0, "甲")')
    assert res0 is None


def test_multi_file_name_readonly_with_hint():
    st = _run_node_expression('uploadNameFieldState(2, "x")')
    assert st["readOnly"] is True
    assert st["hint"] == "多檔將自動以檔名命名"
    assert st["prefill"] is None


def test_single_file_prefills_stem():
    st = _run_node_expression('uploadNameFieldState(1, "衛教A")')
    assert st["readOnly"] is False
    assert st["prefill"] == "衛教A"
    assert st["hint"] == ""


def test_queue_cleared_keeps_editable():
    st = _run_node_expression('uploadNameFieldState(0, "x")')
    assert st["readOnly"] is False
    assert st["prefill"] is None
    assert st["hint"] == ""


def test_same_stem_batch_keeps_first_only():
    res = _run_node_expression('pickUniqueStemEntries(["x"], ["x", "y", "y", "z"])')
    assert res == ["y", "z"]


def test_missing_fields_labels_fixed_map_unknown_dropped():
    res = _run_node_expression('missingFieldsLabels(["address", "phone", "x<script>", "doctors"])')
    assert res == ["地址", "電話", "醫師"]


def test_detail_non_string_uses_fallback():
    r1 = _run_node_expression('uploadDetailText({ detail: { msg: "x" } }, "固定")')
    assert r1 == "固定"
    r2 = _run_node_expression('uploadDetailText({ detail: "網址不允許解析" }, "固定")')
    assert r2 == "網址不允許解析"
    r3 = _run_node_expression('uploadDetailText(null, "固定")')
    assert r3 == "固定"


def test_batch_sequence_via_pure_helpers():
    # 模擬批量選擇：多個同檔名與新檔名
    incoming = ["doc_a", "doc_b", "doc_b", "doc_c"]
    kept_stems = _run_node_expression(f'pickUniqueStemEntries([], {json.dumps(incoming)})')
    assert kept_stems == ["doc_a", "doc_b", "doc_c"]

    # 對多檔送出時，逐檔檢查附加名稱：長度為 3 時每檔皆不附加 name
    total_files = len(kept_stems)
    for _ in kept_stems:
        name_sub = _run_node_expression(f'uploadNameForSubmit({total_files}, "使用者輸入的主題")')
        assert name_sub is None

    # 單檔送出時，才可附加 name
    single_sub = _run_node_expression('uploadNameForSubmit(1, "使用者輸入的主題")')
    assert single_sub == "使用者輸入的主題"
