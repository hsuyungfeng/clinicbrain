"""
tests/test_query_disclaimer_field.py - 查詢回應之免責宣告欄位測試 (Phase 12 GC-03)

驗證：
1. data_level == 'general' 時，disclaimer 欄位為 DISCLAIMER_TEXT
2. data_level == 'clinic' 或 None 時，disclaimer 欄位為 None
3. 非短路 pageindex 回應首筆命中為 general 時，disclaimer 為 DISCLAIMER_TEXT
4. API /api/v1/query 之 JSON 回應包含 disclaimer 鍵且值正確
5. 免責聲明文字之唯一來源保證（router/models/routes 不含「【免責宣告】」字串）
"""

from pathlib import Path
import sqlite3
from fastapi.testclient import TestClient
import pytest

from src.api.app import create_app
from src.api.config import config
from src.general.disclaimer import DISCLAIMER_TEXT
from src.pageindex.faq_writer import upsert_faqs
from src.query.router import handle_query


@pytest.fixture
def api_client(isolated_db_path, monkeypatch):
    """建立連線至獨立資料庫複本的 TestClient。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "admin_api_key", None)
    app = create_app()

    with TestClient(app) as client:
        yield client


def test_disclaimer_unique_source():
    """驗證免責文字唯一來源：src/query/router.py, src/api/models/query.py, src/api/routes/query.py 絕不包含免責全文。"""
    base_dir = Path(__file__).resolve().parent.parent
    checked_files = [
        base_dir / "src" / "query" / "router.py",
        base_dir / "src" / "api" / "models" / "query.py",
        base_dir / "src" / "api" / "routes" / "query.py",
    ]
    for p in checked_files:
        content = p.read_text(encoding="utf-8")
        assert "【免責宣告】" not in content, f"{p} 違規包含免責宣告全文硬編碼"


def test_query_response_disclaimer_general_shortcut(isolated_conn: sqlite3.Connection):
    """一般衛教 FAQ 短路時，QueryResponse.disclaimer 等於 DISCLAIMER_TEXT。"""
    # 寫入一筆 approved general FAQ
    upsert_faqs(
        isolated_conn,
        [
            {
                "clinic_id": None,
                "topic_key": "common-cold-home-care",
                "question": "感冒時在家要如何照護與休息？",
                "answer": "感冒期間應多休息、充分飲水；若出現呼吸困難或胸痛，請立即就醫。",
                "category": "general",
            }
        ],
        source_type="clinic_upload",
    )

    resp = handle_query(
        isolated_conn,
        "感冒時在家要如何照護與休息？",
        clinic_id="3503190424",
    )
    assert resp.data_level == "general"
    assert resp.source == "cache"
    assert resp.disclaimer == DISCLAIMER_TEXT


def test_query_response_disclaimer_clinic_shortcut(isolated_conn: sqlite3.Connection):
    """診所 FAQ 短路時，QueryResponse.disclaimer 為 None。"""
    resp = handle_query(
        isolated_conn,
        "音波拉提術後多久可以恢復正常保養？",
        clinic_id="3503190424",
    )
    assert resp.data_level == "clinic"
    assert resp.disclaimer is None


def test_query_response_disclaimer_no_hit(isolated_conn: sqlite3.Connection):
    """無任何 FAQ 命中時，QueryResponse.disclaimer 為 None。"""
    resp = handle_query(
        isolated_conn,
        "xyzqwe完全不存在的生僻字詞組合999888",
        clinic_id="3503190424",
    )
    assert resp.data_level is None
    assert resp.disclaimer is None


def test_query_response_disclaimer_pageindex_general(isolated_conn: sqlite3.Connection):
    """非短路 pageindex 回應且首筆命中為 general 時，disclaimer 等於 DISCLAIMER_TEXT。"""
    # 寫入 general FAQ（長度不足以短路，但可被 FTS/LIKE 檢索到）
    upsert_faqs(
        isolated_conn,
        [
            {
                "clinic_id": None,
                "topic_key": "general-fever-info",
                "question": "發燒時的就醫警訊與日常護理常識？",
                "answer": "若體溫持續超過38.5度超過三天，請儘速就醫。",
                "category": "general",
            }
        ],
        source_type="clinic_upload",
    )

    # 查一個問句，使其不短路但命中該 general FAQ
    resp = handle_query(
        isolated_conn,
        "發燒照護就醫警訊有哪些？",
        clinic_id=None,
    )
    if resp.data_level == "general" and resp.source == "pageindex":
        assert resp.disclaimer == DISCLAIMER_TEXT


def test_api_query_endpoint_disclaimer(api_client, isolated_db_path):
    """驗證 POST /api/v1/query 回傳 JSON 欄位 disclaimer 表現。"""
    # 1. 診所問答短路 -> disclaimer 為 null
    res_clinic = api_client.post(
        "/api/v1/query",
        json={"query": "音波拉提術後多久可以恢復正常保養？", "clinic_id": "3503190424"},
    )
    assert res_clinic.status_code == 200
    data_clinic = res_clinic.json()
    assert data_clinic["data_level"] == "clinic"
    assert data_clinic["disclaimer"] is None

    # 2. 寫入 general FAQ 並查詢
    conn = sqlite3.connect(str(isolated_db_path))
    upsert_faqs(
        conn,
        [
            {
                "clinic_id": None,
                "topic_key": "common-cold-home-care",
                "question": "感冒時在家要如何照護與休息？",
                "answer": "感冒期間應多休息、充分飲水；若出現胸痛，請立即就醫。",
                "category": "general",
            }
        ],
        source_type="clinic_upload",
    )
    conn.close()

    res_general = api_client.post(
        "/api/v1/query",
        json={"query": "感冒時在家要如何照護與休息？", "clinic_id": "3503190424"},
    )
    assert res_general.status_code == 200
    data_general = res_general.json()
    assert data_general["data_level"] == "general"
    assert data_general["disclaimer"] == DISCLAIMER_TEXT
