"""一般醫療諮詢端點 POST /api/v1/general/query 整合與端對端測試。"""

import hashlib
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.config import config
from src.general.disclaimer import (
    DISCLAIMER_TEXT,
    EMERGENCY_MESSAGE,
    FILLER_OCCLUSION_ADDENDUM,
    NO_MATCH_MESSAGE,
    RED_FLAG_DISCLAIMER_TEXT,
    URGENT_MESSAGE,
)
from src.pageindex.faq_writer import upsert_faqs


@pytest.fixture
def general_api_client(isolated_db_path, monkeypatch):
    """建立指向隔離測試資料庫的 API TestClient。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    app = create_app()
    with TestClient(app) as client:
        yield client


def test_anonymous_query_success_no_query_in_body(isolated_db_path, general_api_client):
    """測試匿名諮詢成功：正常回傳 answered，且回應體不回顯 query 欄位。"""
    conn = sqlite3.connect(isolated_db_path)
    faq = {
        "question": "感冒時要多喝水嗎",
        "answer": "感冒期間應多補充水分與電解質，充分休息以利康復。",
        "category": "general",
        "clinic_id": None,
        "topic_key": "common-cold",
    }
    upsert_faqs(conn, [faq], source_type="manual")
    conn.close()

    resp = general_api_client.post(
        "/api/v1/general/query", json={"query": "感冒時要多喝水嗎"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "answered"
    assert "query" not in data
    assert len(data["faq_hits"]) >= 1
    assert data["faq_hits"][0]["topic_key"] == "common-cold"


def test_disclaimer_present_in_all_states(isolated_db_path, general_api_client):
    """測試 GENERAL-01：三種狀態（answered, no_match, red_flag）皆附帶非空免責聲明。"""
    conn = sqlite3.connect(isolated_db_path)
    faq = {
        "question": "流感需要戴口罩嗎",
        "answer": "建議佩戴口罩避免飛沫傳染他人。",
        "category": "general",
        "clinic_id": None,
        "topic_key": "flu",
    }
    upsert_faqs(conn, [faq], source_type="manual")
    conn.close()

    # 1. answered
    r_answered = general_api_client.post(
        "/api/v1/general/query", json={"query": "流感需要戴口罩嗎"}
    )
    assert r_answered.json()["disclaimer"] == DISCLAIMER_TEXT

    # 2. no_match
    r_no_match = general_api_client.post(
        "/api/v1/general/query", json={"query": "無相符哨兵詞彙"}
    )
    assert r_no_match.json()["disclaimer"] == DISCLAIMER_TEXT

    # 3. red_flag
    r_red_flag = general_api_client.post(
        "/api/v1/general/query", json={"query": "我胸口好痛"}
    )
    assert r_red_flag.json()["disclaimer"] == RED_FLAG_DISCLAIMER_TEXT


def test_no_match_returns_honest_message(general_api_client):
    """測試查無資料時誠實回應 NO_MATCH_MESSAGE 與空清單。"""
    resp = general_api_client.post(
        "/api/v1/general/query", json={"query": "完全不存在的主題哨兵詞語"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "no_match"
    assert data["message"] == NO_MATCH_MESSAGE
    assert data["faq_hits"] == []
    assert data["guide_hits"] == []


def test_red_flag_triggers_emergency_and_no_search(general_api_client, monkeypatch):
    """測試 GENERAL-02：紅旗命中時回傳就醫指示，且證明未執行任何檢索或外部模型呼叫。"""
    def fail_search(*args, **kwargs):
        raise AssertionError("紅旗命中時不得執行檢索！")

    def fail_terms(*args, **kwargs):
        raise AssertionError("紅旗命中時不得呼叫 extract_search_terms！")

    def fail_handle_query(*args, **kwargs):
        raise AssertionError("一般端點不得呼叫 handle_query！")

    monkeypatch.setattr("src.general.consult.search_faq_cache", fail_search)
    monkeypatch.setattr("src.general.consult.search_text", fail_search)
    monkeypatch.setattr("src.general.consult.extract_search_terms", fail_terms)
    monkeypatch.setattr("src.query.router.handle_query", fail_handle_query)

    # 1. Emergency 胸痛
    resp = general_api_client.post(
        "/api/v1/general/query", json={"query": "我胸口好痛"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "red_flag"
    assert data["red_flag_level"] == "emergency"
    assert data["message"] == EMERGENCY_MESSAGE
    assert "119" in data["message"]

    # 2. Urgent 高燒不退
    resp_urgent = general_api_client.post(
        "/api/v1/general/query", json={"query": "發燒三天都不退"}
    )
    assert resp_urgent.status_code == 200
    assert resp_urgent.json()["red_flag_level"] == "urgent"
    assert resp_urgent.json()["message"] == URGENT_MESSAGE

    # 3. Emergency 填充劑血管阻塞 E08
    resp_filler = general_api_client.post(
        "/api/v1/general/query", json={"query": "打完玻尿酸鼻頭發黑"}
    )
    assert resp_filler.status_code == 200
    data_filler = resp_filler.json()
    assert data_filler["red_flag_level"] == "emergency"
    assert FILLER_OCCLUSION_ADDENDUM in data_filler["message"]


def test_clinic_isolation_and_parameter_ignored(isolated_db_path, general_api_client):
    """測試 GENERAL-04：診所特定資訊與藥品隔離，夾帶 clinic_id 與 Header 被靜默忽略。"""
    conn = sqlite3.connect(isolated_db_path)
    special_faq = {
        "question": "感冒後能做雷射嗎",
        "answer": "感冒期間不建議雷射。診所專屬標記甲。",
        "category": "special",
        "clinic_id": "3503190424",
        "topic_key": "laser-cold",
    }
    upsert_faqs(conn, [special_faq], source_type="manual")
    conn.close()

    # 查詢與 special FAQ 重疊關鍵字之問句
    resp_normal = general_api_client.post(
        "/api/v1/general/query", json={"query": "感冒後能做雷射嗎"}
    )
    text = resp_normal.text
    assert "診所專屬標記甲" not in text
    assert "3503190424" not in text
    assert "緻妍" not in text

    # Body 夾帶 clinic_id 與 Header X-Clinic-ID
    resp_tamper = general_api_client.post(
        "/api/v1/general/query",
        json={"query": "感冒後能做雷射嗎", "clinic_id": "3503190424"},
        headers={"X-Clinic-ID": "3503190424"},
    )
    assert resp_tamper.status_code == 200
    # 結果與未夾帶完全相等
    assert resp_normal.json() == resp_tamper.json()

    # 查詢營業時間與地址，確認不回傳診所資訊
    resp_ops = general_api_client.post(
        "/api/v1/general/query", json={"query": "請問診所營業時間與地址"}
    )
    assert resp_ops.status_code == 200
    ops_data = resp_ops.json()
    assert ops_data["status"] == "no_match"
    assert "clinic_hours" not in ops_data
    assert "clinic_info" not in ops_data


def test_no_auth_required_even_in_prod_mode(general_api_client, monkeypatch):
    """測試認證決策：即使正式模式下未傳金鑰，一般諮詢端點仍公開放行（對照 sync 則 401）。"""
    monkeypatch.setattr(config, "allow_no_auth", False)
    monkeypatch.setattr(config, "admin_api_key", "prod-secret-key-12345")

    # 未帶金鑰呼叫 general query -> 200
    resp = general_api_client.post(
        "/api/v1/general/query", json={"query": "一般衛教問句"}
    )
    assert resp.status_code == 200

    # 對照組：未帶金鑰呼叫 sync export -> 401
    resp_sync = general_api_client.post(
        "/api/v1/sync/export", json={"clinic_id": "3503190424"}
    )
    assert resp_sync.status_code == 401


def test_only_post_method_allowed(general_api_client):
    """測試僅接受 POST，GET 請求回傳 405 Method Not Allowed。"""
    resp = general_api_client.get("/api/v1/general/query?q=發燒怎麼辦")
    assert resp.status_code == 405


@pytest.mark.parametrize(
    "payload",
    [
        {"query": ""},
        {"query": "   "},
        {"query": "a" * 301},
        {"query": "正常問句", "limit": 0},
        {"query": "正常問句", "limit": 11},
    ],
)
def test_input_validation_returns_422(general_api_client, payload):
    """測試輸入格式驗證，不符規格一律回傳 422 且內容為固定文字。"""
    resp = general_api_client.post("/api/v1/general/query", json=payload)
    assert resp.status_code == 422
    assert resp.json() == {"detail": "請求格式不正確"}


def test_validation_error_does_not_echo_input(general_api_client):
    """安全測試：自訂 AnonymousRoute 攔截驗證錯誤，絕不反射哨兵問句或詳細錯誤。"""
    sentinel = "哨兵使用者機密問句九八七"

    cases = [
        # 1. 超長輸入 (>300)
        {"json": {"query": sentinel * 50}},
        # 2. 純空白
        {"json": {"query": "   "}},
        # 3. query 為 list
        {"json": {"query": ["abc", sentinel]}},
        # 4. query 為 dict
        {"json": {"query": {"secret": sentinel}}},
        # 5. body 為 list
        {"json": [sentinel]},
        # 6. 非法 JSON
        {
            "content": f'{{"query": "{sentinel}'.encode("utf-8"),
            "headers": {"Content-Type": "application/json"},
        },
        # 7. text/plain
        {
            "content": sentinel.encode("utf-8"),
            "headers": {"Content-Type": "text/plain"},
        },
    ]

    for kwargs in cases:
        resp = general_api_client.post("/api/v1/general/query", **kwargs)
        assert resp.status_code == 422
        assert sentinel not in resp.text
        assert "input" not in resp.text
        assert "ctx" not in resp.text
        assert "loc" not in resp.text
        assert resp.json() == {"detail": "請求格式不正確"}


def test_price_masking_defense_on_response(isolated_db_path, general_api_client):
    """價格防禦測試：回應經過 deep_mask_prices 二次清洗，無金額外洩。"""
    conn = sqlite3.connect(isolated_db_path)
    faq = {
        "question": "自費感冒藥費用",
        "answer": "特效自費藥品約 1500 元，請向醫師諮詢。",
        "category": "general",
        "clinic_id": None,
        "topic_key": "cold-price",
    }
    upsert_faqs(conn, [faq], source_type="manual")
    conn.close()

    resp = general_api_client.post(
        "/api/v1/general/query", json={"query": "自費感冒藥費用"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "1500 元" not in resp.text
    assert "1500元" not in resp.text
    assert "[請致電診所確認]" in resp.text


def test_read_only_and_no_stats_recorded(isolated_db_path, general_api_client):
    """唯讀測試：確認端點執行不進行任何寫入，不寫入 cache_stats，資料庫完全未變。"""
    conn = sqlite3.connect(isolated_db_path)
    cur = conn.cursor()

    # 計算各表列數
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall() if not row[0].startswith("sqlite_")]
    initial_counts = {}
    for t in tables:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        initial_counts[t] = cur.fetchone()[0]

    # 計算檔案 hash
    with open(isolated_db_path, "rb") as f:
        initial_sha = hashlib.sha256(f.read()).hexdigest()
    conn.close()

    # 執行一般諮詢請求
    resp = general_api_client.post(
        "/api/v1/general/query", json={"query": "感冒喝水"}
    )
    assert resp.status_code == 200

    # 驗證資料庫狀態不變
    conn2 = sqlite3.connect(isolated_db_path)
    cur2 = conn2.cursor()
    for t in tables:
        cur2.execute(f"SELECT COUNT(*) FROM {t}")
        count_after = cur2.fetchone()[0]
        assert count_after == initial_counts[t], f"表 {t} 的列數被改變！"
    conn2.close()

    with open(isolated_db_path, "rb") as f:
        after_sha = hashlib.sha256(f.read()).hexdigest()
    assert after_sha == initial_sha, "資料庫檔案在請求後被寫入！"


def test_router_mounting_additive():
    """測試路由掛載附加性：既有端點與新端點皆存在。"""
    app = create_app()
    paths = list(app.openapi()["paths"].keys())
    assert "/api/v1/general/query" in paths
    assert "/api/v1/query" in paths
    assert "/api/v1/sync/export" in paths
    assert "/health" in paths
