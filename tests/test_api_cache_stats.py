"""
FastAPI 快取統計查詢端點（CACHE-03）端對端測試。
驗證：
1. GET /api/v1/cache/stats 查詢彙總與過濾功能。
2. 管理員 API Key 認證保護（401 / 200）。
3. 兩種 503 錯誤之明確區分（表缺失提示遷移 vs 表存在但查詢錯誤）。
4. 405 Method Not Allowed。
5. 端到端連通性（查詢寫入與統計讀取整合）。
6. 營運問句不影響統計。
"""

import sqlite3
from fastapi.testclient import TestClient
import pytest

from src.api.app import create_app
from src.api.config import config
from src.query.cache_stats import (
    ROUTE_KEYWORD_VOCAB,
    record_query_outcome,
)
import src.api.routes.cache_stats as cache_stats_route


@pytest.fixture
def stats_api(isolated_db_path, monkeypatch):
    """建立指向 isolated_db_path 測試資料庫複本之 TestClient。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    app = create_app()
    with TestClient(app) as client:
        yield client


def test_get_cache_stats_empty(stats_api):
    """測試資料庫無統計資料時回傳全 0 與 null hit_rate。"""
    resp = stats_api.get("/api/v1/cache/stats")
    assert resp.status_code == 200
    data = resp.json()

    assert data["hit"] == 0
    assert data["miss"] == 0
    assert data["total"] == 0
    assert data["hit_rate"] is None
    assert data["top_miss_keywords"] == []
    assert data["clinic_id"] is None
    assert data["since"] is None


def test_get_cache_stats_aggregated_data(stats_api, isolated_db_path):
    """測試正確彙總 hit、miss、hit_rate 與熱門未命中關鍵字。"""
    conn = sqlite3.connect(str(isolated_db_path))
    # 3 次 hit
    for _ in range(3):
        record_query_outcome(conn, clinic_id="3503190424", hit=True, matched_keywords=[])
    # 1 次 miss（帶 音波 與 拉提）
    record_query_outcome(conn, clinic_id="3503190424", hit=False, matched_keywords=["音波", "拉提"])
    # 1 次 miss（僅帶 音波）
    record_query_outcome(conn, clinic_id="3503190424", hit=False, matched_keywords=["音波"])
    conn.close()

    resp = stats_api.get("/api/v1/cache/stats")
    assert resp.status_code == 200
    data = resp.json()

    assert data["hit"] == 3
    assert data["miss"] == 2
    assert data["total"] == 5
    assert data["hit_rate"] == 0.6

    top_kw = data["top_miss_keywords"]
    assert len(top_kw) == 2
    assert top_kw[0] == {"keyword": "音波", "count": 2}
    assert top_kw[1] == {"keyword": "拉提", "count": 1}

    # 驗證關鍵字全屬 ROUTE_KEYWORD_VOCAB 白名單
    for item in top_kw:
        assert item["keyword"] in ROUTE_KEYWORD_VOCAB


def test_get_cache_stats_clinic_id_filter(stats_api, isolated_db_path):
    """測試依 clinic_id 篩選統計資料。"""
    conn = sqlite3.connect(str(isolated_db_path))
    record_query_outcome(conn, clinic_id="3503190424", hit=True, matched_keywords=[])
    record_query_outcome(conn, clinic_id="", hit=True, matched_keywords=[])
    conn.close()

    # 1. 篩選緻妍診所
    resp = stats_api.get("/api/v1/cache/stats", params={"clinic_id": "3503190424"})
    assert resp.status_code == 200
    assert resp.json()["hit"] == 1
    assert resp.json()["clinic_id"] == "3503190424"

    # 2. 篩選不存在之診所 -> 回傳 0
    resp_none = stats_api.get("/api/v1/cache/stats", params={"clinic_id": "9999999999"})
    assert resp_none.status_code == 200
    assert resp_none.json()["hit"] == 0


def test_get_cache_stats_since_filter(stats_api, isolated_db_path):
    """測試 since 日期篩選與格式驗證。"""
    conn = sqlite3.connect(str(isolated_db_path))
    record_query_outcome(conn, clinic_id="3503190424", hit=True, matched_keywords=[])
    conn.close()

    # 1. 未來日期 -> 0
    resp_future = stats_api.get("/api/v1/cache/stats", params={"since": "2099-01-01"})
    assert resp_future.status_code == 200
    assert resp_future.json()["hit"] == 0

    # 2. 格式錯誤 -> 422
    resp_invalid = stats_api.get("/api/v1/cache/stats", params={"since": "not-a-date"})
    assert resp_invalid.status_code == 422


def test_get_cache_stats_top_n_validation(stats_api, isolated_db_path):
    """測試 top_n 參數數量控制與邊界校驗。"""
    conn = sqlite3.connect(str(isolated_db_path))
    record_query_outcome(conn, clinic_id="3503190424", hit=False, matched_keywords=["音波", "拉提", "雷射"])
    conn.close()

    # top_n = 1
    resp_1 = stats_api.get("/api/v1/cache/stats", params={"top_n": 1})
    assert resp_1.status_code == 200
    assert len(resp_1.json()["top_miss_keywords"]) == 1

    # top_n = 0 -> 422
    assert stats_api.get("/api/v1/cache/stats", params={"top_n": 0}).status_code == 422
    # top_n = 101 -> 422
    assert stats_api.get("/api/v1/cache/stats", params={"top_n": 101}).status_code == 422


def test_get_cache_stats_admin_key_protection(isolated_db_path, monkeypatch):
    """測試 X-API-Key 認證保護（缺/錯 401，正確 200）。"""
    monkeypatch.setattr(config, "admin_api_key", "test-secret-key")
    monkeypatch.setattr(config, "allow_no_auth", False)
    monkeypatch.setattr(config, "db_path", isolated_db_path)

    app = create_app()
    with TestClient(app) as client:
        # 1. 未帶金鑰 -> 401
        res_no_key = client.get("/api/v1/cache/stats")
        assert res_no_key.status_code == 401

        # 2. 錯誤金鑰 -> 401
        res_wrong = client.get("/api/v1/cache/stats", headers={"X-API-Key": "wrong-key"})
        assert res_wrong.status_code == 401

        # 3. 正確金鑰 -> 200
        res_ok = client.get("/api/v1/cache/stats", headers={"X-API-Key": "test-secret-key"})
        assert res_ok.status_code == 200


def test_get_cache_stats_response_keys_exact_set(stats_api):
    """測試回應鍵集合恰為 {hit, miss, total, hit_rate, top_miss_keywords, clinic_id, since}。"""
    resp = stats_api.get("/api/v1/cache/stats")
    assert resp.status_code == 200
    expected_keys = {"hit", "miss", "total", "hit_rate", "top_miss_keywords", "clinic_id", "since"}
    assert set(resp.json().keys()) == expected_keys


def test_get_cache_stats_table_missing_503(stats_api, isolated_db_path):
    """測試當資料表不存在時回傳 503 並提示執行 migrate_cache_stats.py。"""
    conn = sqlite3.connect(str(isolated_db_path))
    conn.execute("DROP TABLE cache_stats")
    conn.commit()
    conn.close()

    resp = stats_api.get("/api/v1/cache/stats")
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "migrate_cache_stats.py" in detail
    assert "cache_stats 資料表尚未建立" in detail


def test_get_cache_stats_query_failure_503(stats_api, monkeypatch):
    """測試當表存在但讀取失敗時回傳 503，且不提及遷移腳本（可與表缺失區分）。"""
    def _locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache_stats_route, "get_cache_stats", _locked)

    resp = stats_api.get("/api/v1/cache/stats")
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "查詢失敗" in detail
    assert "migrate_cache_stats.py" not in detail


def test_get_cache_stats_method_not_allowed(stats_api):
    """測試 POST / PUT / DELETE 方法回傳 405 Method Not Allowed。"""
    assert stats_api.post("/api/v1/cache/stats").status_code == 405
    assert stats_api.put("/api/v1/cache/stats").status_code == 405
    assert stats_api.delete("/api/v1/cache/stats").status_code == 405


def test_get_cache_stats_end_to_end_flow(isolated_db_path, monkeypatch):
    """端到端測試：透過 POST /query 產生短路與未命中，再透過 GET /stats 驗證讀寫通暢。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "cache_stats_enabled", True)

    # 1. 插入一筆 special FAQ
    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type)
        VALUES ('3503190424', 't-stats-e2e', '皮秒雷射術後居家冰敷重點有哪些？', '冰敷每次十分鐘，避免用力搓揉。', 'special', 'manual')
        """
    )
    conn.commit()
    conn.close()

    app = create_app()
    with TestClient(app) as client:
        # 2. 觸發一次短路命中
        res_hit = client.post(
            "/api/v1/query",
            json={"query": "皮秒雷射術後居家冰敷重點有哪些？", "clinic_id": "3503190424"},
        )
        assert res_hit.status_code == 200
        assert res_hit.json()["source"] == "cache"

        # 3. 觸發一次有資格的未命中
        res_miss = client.post(
            "/api/v1/query",
            json={"query": "音波拉提術後要怎麼照顧？", "clinic_id": "3503190424"},
        )
        assert res_miss.status_code == 200
        assert res_miss.json()["source"] == "pageindex"

        # 4. 讀取統計端點
        res_stats = client.get("/api/v1/cache/stats")
        assert res_stats.status_code == 200
        stats = res_stats.json()
        assert stats["hit"] >= 1
        assert stats["miss"] >= 1
        assert stats["total"] >= 2
        assert stats["hit_rate"] is not None


def test_get_cache_stats_ops_query_does_not_affect_miss(isolated_db_path, monkeypatch):
    """測試含診所營運關鍵字之查詢不計入 miss 統計。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "cache_stats_enabled", True)

    app = create_app()
    with TestClient(app) as client:
        # 先取得目前 miss 數
        init_miss = client.get("/api/v1/cache/stats").json()["miss"]

        # 呼叫營運問句
        res_ops = client.post(
            "/api/v1/query",
            json={"query": "請問診所營業時間是什麼？", "clinic_id": "3503190424"},
        )
        assert res_ops.status_code == 200

        # miss 數維持不變
        new_miss = client.get("/api/v1/cache/stats").json()["miss"]
        assert new_miss == init_miss
