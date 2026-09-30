"""
FastAPI 服務健康檢查與根端點測試。
遵守專案原則：所有測試透過 isolated_conn 進行，保證正式 clinic.db 0 污染。
"""

import sqlite3
from fastapi.testclient import TestClient
import pytest
from src.api.app import create_app
from src.api.dependencies import get_read_db, get_write_db, verify_admin_key
from src.api.config import config


@pytest.fixture
def api_client(isolated_db_path, monkeypatch):
    """建立帶有獨立資料庫連線注入的 TestClient。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    app = create_app()

    with TestClient(app) as client:
        yield client


def test_api_root(api_client):
    """測試 API 根路徑回傳基本服務資訊。"""
    response = api_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "clinicbrain"
    assert data["status"] == "running"
    assert "version" in data


def test_api_health_endpoint(api_client):
    """測試 /health 端點能正常讀取資料庫狀態與各表統計。"""
    response = api_client.get("/health")
    assert response.status_code == 200
    data = response.json()

    assert data["database_connected"] is True
    assert data["status"] in ("ok", "degraded")
    assert "tables_count" in data

    counts = data["tables_count"]
    # 斷言核心資料表皆存在且筆數符合既有庫狀態
    assert counts.get("drugs", 0) > 7000
    assert counts.get("service_items", 0) > 2000
    assert counts.get("page_index_trees", 0) >= 6
    assert counts.get("faq_cache", 0) >= 40
    assert counts.get("clinic_info", 0) >= 1
    assert counts.get("clinic_hours", 0) >= 7
    assert counts.get("clinic_custom_notes", 0) >= 3


def test_api_health_handles_db_failure():
    """測試當資料庫異常時，/health 能標記 error 狀態而不崩潰。"""
    app = create_app()

    def _broken_db():
        broken_conn = sqlite3.connect(":memory:")
        broken_conn.close()  # 立即關閉製造連線異常
        yield broken_conn

    app.dependency_overrides[get_read_db] = _broken_db

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["database_connected"] is False
        assert data["status"] == "error"


def test_verify_admin_key(monkeypatch):
    """測試 API Key 認證機制（未設金鑰時依 allow_no_auth 決定放行或 503 fail-closed，設定金鑰時比對 X-API-Key）。"""
    from fastapi import HTTPException

    # 1. 本機開發放行模式（allow_no_auth=True 且無金鑰）：放行
    monkeypatch.setattr(config, "admin_api_key", None)
    monkeypatch.setattr(config, "allow_no_auth", True)
    assert verify_admin_key(None) is True
    assert verify_admin_key("any-key") is True

    # 2. 未設金鑰且未啟用開發放行旗標（allow_no_auth=False）：503 fail-closed
    monkeypatch.setattr(config, "allow_no_auth", False)
    with pytest.raises(HTTPException) as exc_info_503:
        verify_admin_key(None)
    assert exc_info_503.value.status_code == 503
    assert "CLINICBRAIN_ADMIN_API_KEY" in exc_info_503.value.detail

    # 3. 設定金鑰：正確金鑰放行（即便 allow_no_auth=False）
    monkeypatch.setattr(config, "admin_api_key", "secret-test-key")
    assert verify_admin_key("secret-test-key") is True

    # 4. 錯誤或缺少金鑰：拋出 401
    with pytest.raises(HTTPException) as exc_info:
        verify_admin_key("wrong-key")
    assert exc_info.value.status_code == 401

    with pytest.raises(HTTPException) as exc_info_missing:
        verify_admin_key(None)
    assert exc_info_missing.value.status_code == 401
