"""
FastAPI 自然語言查詢端點與二次價格遮蔽防禦測試。
依據專案規範：所有測試透過 isolated_db_path 進行，保證正式 clinic.db 0 污染。
"""

import re
from fastapi.testclient import TestClient
import pytest
from src.api.app import create_app
from src.api.config import config
from src.api.routes.query import deep_mask_prices


@pytest.fixture
def api_client(isolated_db_path, monkeypatch):
    """建立連線至獨立資料庫複本的 TestClient。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    app = create_app()

    with TestClient(app) as client:
        yield client


def test_post_query_special_with_body_clinic_id(api_client):
    """測試 special 療程查詢透過 Request Body 提供 clinic_id。"""
    payload = {
        "query": "音波拉提術後要怎麼照顧？",
        "clinic_id": "3503190424",
        "limit": 5,
    }
    response = api_client.post("/api/v1/query", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["route"] == "special"
    assert "音波" in data["matched_keywords"] or "拉提" in data["matched_keywords"]
    assert len(data["page_index_hits"]) > 0 or len(data["faq_hits"]) > 0
    # 斷言撈出診所自訂術後備註
    assert "post_op_short" in data["clinic_custom_notes"]


def test_post_query_special_with_header_clinic_id(api_client):
    """測試 special 營運查詢透過 Header X-Clinic-ID 提供 clinic_id。"""
    payload = {
        "query": "請問診所營業時間與地址？",
    }
    headers = {"X-Clinic-ID": "3503190424"}
    response = api_client.post("/api/v1/query", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()

    assert data["route"] == "special"
    assert data["clinic_info"] is not None
    assert data["clinic_info"]["clinic_id"] == "3503190424"
    assert data["clinic_info"]["name"] == "緻妍外科診所"
    assert len(data["clinic_hours"]) >= 7


def test_post_query_special_missing_clinic_id_returns_400(api_client):
    """測試 special 營運查詢在未提供 clinic_id 時回傳 HTTP 400 結構化錯誤。"""
    payload = {
        "query": "請問診所門診營業時間？",
    }
    response = api_client.post("/api/v1/query", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert "clinic_id" in data["detail"]


def test_post_query_general_route_no_clinic_id_needed(api_client):
    """測試 general 健保藥品查詢不需 clinic_id 即可正常查詢且無診所資料滲漏。"""
    payload = {
        "query": "乙醯胺酚",
    }
    response = api_client.post("/api/v1/query", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["route"] == "general"
    assert len(data["drug_hits"]) > 0
    # 嚴格斷言 general 路由絕不滲漏診所專屬資料
    assert data["clinic_info"] is None
    assert data["clinic_hours"] == []
    assert data["clinic_custom_notes"] == {}


def test_post_clinic_scoped_query_endpoint(api_client):
    """測試 URL 路徑綁定診所之專用入口 /api/v1/clinics/{clinic_id}/query。"""
    payload = {
        "query": "音波拉提效果可以維持多久？",
    }
    response = api_client.post("/api/v1/clinics/3503190424/query", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["route"] == "special"
    assert len(data["page_index_hits"]) > 0 or len(data["faq_hits"]) > 0


def test_get_query_shortcut(api_client):
    """測試 GET /api/v1/query 捷徑端點。"""
    response = api_client.get("/api/v1/query?q=乙醯胺酚&limit=3")
    assert response.status_code == 200
    data = response.json()
    assert data["route"] == "general"
    assert len(data["drug_hits"]) > 0


def test_deep_mask_prices_sanitizer():
    """單元測試 deep_mask_prices 遞迴遮蔽能力。"""
    raw = {
        "title": "促銷療程特價1500元",
        "nested": {
            "fee": "只要 NT$2000 即可享有",
            "items": ["單堂 500 元", "原價12000元優惠中"],
        },
        "safe_int": 42,
        "safe_bool": True,
    }
    masked = deep_mask_prices(raw)
    assert masked["title"] == "促銷療程特價[請致電診所確認]"
    assert masked["nested"]["items"] == ["單堂 [請致電診所確認]", "原價[請致電診所確認]優惠中"]
    assert masked["safe_int"] == 42
    assert masked["safe_bool"] is True


def test_api_response_zero_price_leakage(api_client):
    """測試查詢 API 回應全文字段無任何具體價格數字洩漏（正規表達式掃描）。"""
    price_regex = re.compile(r"(?:\$|NT\$|NT\s*|新台幣)?\s*\d+(?:,\d+)*(?:\.\d+)?\s*(?:元|點|塊)")

    # 針對可能涉及費用的問句進行檢驗
    queries = [
        {"query": "音波拉提多少錢？費用多少？", "clinic_id": "3503190424"},
        {"query": "粉瘤切除手術有健保嗎？自費要多少元？", "clinic_id": "3503190424"},
        {"query": "普拿疼一顆多少錢？", "clinic_id": None},
    ]

    for p in queries:
        resp = api_client.post("/api/v1/query", json=p)
        assert resp.status_code == 200
        text = resp.text

        # 排除合法醫學與劑量數值（如 200mg, 500 毫克）
        # 尋找所有金額模式
        matches = price_regex.findall(text)
        # 允許被替換後的 "[請致電診所確認]"，但不能有具體數字價格
        assert len(matches) == 0, f"問句 '{p['query']}' 的 API 回應中發現價格洩漏：{matches}"
