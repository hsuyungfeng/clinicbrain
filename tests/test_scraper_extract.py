"""Phase 23 Task 1 單元測試：HTML 結構化擷取與 schema_drift 偵測。"""

import json
from pathlib import Path
import pytest

from src.scraper.extract import SCHEMA_VERSION, ExtractedClinicPage, extract_clinic_page

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "scraper"


@pytest.fixture
def sample_a_html() -> str:
    return (FIXTURES_DIR / "clinic_sample_a.html").read_text(encoding="utf-8")


@pytest.fixture
def missing_fields_html() -> str:
    return (FIXTURES_DIR / "clinic_missing_fields.html").read_text(encoding="utf-8")


def test_extract_clinic_sample_a_basic_fields(sample_a_html):
    """Test 1: clinic_sample_a.html 解析後機構名稱、地址、電話、營業時間非空。"""
    page = extract_clinic_page(sample_a_html)
    assert page.institution_name == "範例醫美診所"
    assert "南京東路" in page.address
    assert page.phone == "02-2500-1234"
    assert "週一至週五" in page.business_hours
    assert page.schema_drift is False
    assert page.is_usable() is True


def test_extract_services(sample_a_html):
    """Test 2: services 至少 2 筆有效項目，每筆 name 與 description 皆非空。"""
    page = extract_clinic_page(sample_a_html)
    assert len(page.services) >= 2
    for svc in page.services:
        assert svc["name"]
        assert len(svc["description"]) >= 30


def test_doctor_private_contacts_stripped(sample_a_html):
    """Test 3: 醫師私人手機 09xx、信箱與 LINE ID 不出現在 ExtractedClinicPage 任何欄位。"""
    page = extract_clinic_page(sample_a_html)
    serialized = json.dumps(page.to_dict(), ensure_ascii=False)
    assert "0912" not in serialized
    assert "@example.com" not in serialized
    assert "LINE" not in serialized
    assert "abc123" not in serialized
    assert len(page.doctors) >= 1
    assert page.doctors[0]["name"] == "王小明"


def test_prices_stripped_from_services(sample_a_html):
    """Test 4: 服務價格 NT$、1,500、元等字樣不進入 services 或任何欄位。"""
    page = extract_clinic_page(sample_a_html)
    serialized = json.dumps(page.to_dict(), ensure_ascii=False)
    assert "1500" not in serialized
    assert "1,500" not in serialized
    assert "NT$" not in serialized
    assert "元非常划算" not in serialized


def test_missing_fields_drift(missing_fields_html):
    """Test 5: 缺少服務項目時 schema_drift 為 True，drift_fields 含 services，is_usable 為 False。"""
    page = extract_clinic_page(missing_fields_html)
    assert page.schema_drift is True
    assert "services" in page.drift_fields
    assert page.is_usable() is False


def test_blank_html_drift():
    """Test 6: 完全空白 HTML 不拋例外，回傳 schema_drift 為 True。"""
    page = extract_clinic_page("")
    assert page.schema_drift is True
    assert page.is_usable() is False


def test_schema_version(sample_a_html):
    """Test 7: 解析結果之 schema_version 必須為 '1'。"""
    page = extract_clinic_page(sample_a_html)
    assert page.schema_version == SCHEMA_VERSION == "1"


def test_ignore_scripts_and_styles(sample_a_html):
    """Test 8: 忽略 script 與 style 標籤內文，'注入' 字樣不出現。"""
    page = extract_clinic_page(sample_a_html)
    serialized = json.dumps(page.to_dict(), ensure_ascii=False)
    assert "注入" not in serialized
