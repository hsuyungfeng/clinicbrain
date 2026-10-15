"""機構代碼下拉選單與新增診所：後端端點（隔離複本）與前端靜態檢查。

禁止寫入正式 clinic.db；所有寫入都在 isolated_db_path 複本上進行。
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.config import config
from src.api.app import app

STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "web" / "static"


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    with TestClient(app) as c:
        yield c


def test_list_clinics_returns_registered_clinics(client):
    res = client.get("/api/v1/admin/clinics")
    assert res.status_code == 200
    ids = [c["clinic_id"] for c in res.json()["clinics"]]
    assert "3503190424" in ids


def test_create_clinic_success_then_listed(client):
    res = client.post(
        "/api/v1/admin/clinics",
        json={"clinic_id": "3503999001", "name": "測試診所", "clinic_type": "醫美診所",
              "phone": None, "address": "", "website": "https://example.com"},
    )
    assert res.status_code == 201
    assert res.json()["clinic_id"] == "3503999001"
    ids = [c["clinic_id"] for c in client.get("/api/v1/admin/clinics").json()["clinics"]]
    assert "3503999001" in ids


def test_create_duplicate_clinic_returns_409(client):
    res = client.post("/api/v1/admin/clinics", json={"clinic_id": "3503190424", "name": "重複"})
    assert res.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"clinic_id": "123", "name": "代碼太短"},
        {"clinic_id": "35031904AB", "name": "非數字"},
        {"clinic_id": "3503999002", "name": "   "},
        {"clinic_id": "3503999003", "name": "網址非 https", "website": "http://a.b"},
        {"clinic_id": "3503999004", "name": "多餘欄位", "unknown": 1},
    ],
)
def test_create_clinic_validation_rejects(client, payload):
    res = client.post("/api/v1/admin/clinics", json=payload)
    assert res.status_code == 422


def test_create_clinic_does_not_touch_existing_row(client):
    client.post("/api/v1/admin/clinics", json={"clinic_id": "3503999005", "name": "新診所"})
    rows = {c["clinic_id"]: c for c in client.get("/api/v1/admin/clinics").json()["clinics"]}
    assert rows["3503190424"]["name"] == "緻妍外科診所"


def test_static_selectors_wired_to_same_ids():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for sel_id in ("uploadClinicId", "soapClinicId", "askClinicId"):
        assert re.search(rf'<select[^>]*id="{sel_id}"', html), sel_id
    assert 'id="clinicCreateModal"' in html
    assert "3503190424" not in re.findall(r'value="(\d{10})"', html)


def test_static_clinic_section_has_no_innerhtml():
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    start = js.index("機構代碼下拉選單")
    section = js[start:]
    assert "innerHTML" not in section
    assert "insertAdjacentHTML" not in section
    assert "document.write" not in section


def test_review_and_trees_tabs_have_clinic_filter():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<select[^>]*id="reviewFilterClinic"', html)
    assert re.search(r'<select[^>]*id="treesFilterClinic"', html)
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "&clinic_id=" in js and "reviewFilterClinic" in js and "treesFilterClinic" in js
