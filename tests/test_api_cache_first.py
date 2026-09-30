"""
FastAPI 查詢層快取優先短路（CACHE-01 ~ CACHE-04）端對端測試。
驗證：
1. 回應結構新增 source 與 cache_answer（CACHE-02）。
2. 高信心 FAQ 原文短路回覆（CACHE-01）與價格二次遮蔽（CACHE-04）。
3. 匿名統計記錄（CACHE-03）：獨立短寫入連線、營運查詢不記 miss、失敗隔離與日誌隱私。
4. special 路由缺少 clinic_id 時維持 400 阻斷且不記統計。
"""

import logging
import re
import sqlite3
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from src.api.app import create_app
from src.api.config import config
from src.api.models.query import QueryResponseModel
import src.api.routes.query as query_module

PRICE_REGEX = re.compile(r"(?:\$|NT\$|NT\s*|新台幣)?\s*\d+(?:,\d+)*(?:\.\d+)?\s*(?:元|點|塊)")


def _insert_faq(
    db_path,
    clinic_id: str | None,
    topic_key: str,
    question: str,
    answer: str,
    category: str = "special",
):
    """直接寫入測試資料庫複本之輔助函式。"""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type)
        VALUES (?, ?, ?, ?, ?, 'clinic_upload')
        """,
        (clinic_id, topic_key, question, answer, category),
    )
    conn.commit()
    conn.close()


def _dump_stats(db_path) -> str:
    """傾印測試庫 cache_stats 整張表所有列轉成字串。"""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT id, clinic_id, stat_date, outcome, keyword, count FROM cache_stats")
    rows = cur.fetchall()
    conn.close()
    return " | ".join(str(r) for r in rows)


@pytest.fixture
def api_client(isolated_db_path, monkeypatch):
    """標準測試客戶端（預設 config.cache_stats_enabled=False）。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    app = create_app()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def stats_client(isolated_db_path, monkeypatch):
    """啟用統計記錄的測試客戶端（指向 isolated_db_path 複本）。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "cache_stats_enabled", True)
    app = create_app()
    with TestClient(app) as client:
        yield client


# ==============================================================================
# Task 1: 回應結構 source/cache_answer、短路與價格遮蔽測試
# ==============================================================================

def test_api_query_shortcut_success(api_client, isolated_db_path):
    """測試高信心 FAQ 原文查詢時回傳 200、source='cache'，並帶 cache_answer。"""
    q = "皮秒雷射術後居家冰敷重點有哪些？"
    ans = "冰敷每次十分鐘，避免用力搓揉。"
    _insert_faq(isolated_db_path, "3503190424", "t-api-a", q, ans)

    payload = {"query": q, "clinic_id": "3503190424"}
    resp = api_client.post("/api/v1/query", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["source"] == "cache"
    assert data["cache_answer"] == ans
    assert len(data["faq_hits"]) == 1
    assert data["page_index_hits"] == []
    assert data["drug_hits"] == []
    assert data["service_item_hits"] == []
    assert data["clinic_custom_notes"] == {}


def test_api_query_pageindex_fallback_and_keys_preserved(api_client):
    """測試一般查詢退回 pageindex，cache_answer 為 null，且既有 10 個欄位皆完整保留。"""
    payload = {"query": "音波拉提術後要怎麼照顧？", "clinic_id": "3503190424"}
    resp = api_client.post("/api/v1/query", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["source"] == "pageindex"
    assert data["cache_answer"] is None

    expected_keys = {
        "query", "route", "matched_keywords", "clinic_info", "clinic_hours",
        "page_index_hits", "drug_hits", "service_item_hits", "clinic_custom_notes",
        "faq_hits", "source", "cache_answer",
    }
    assert expected_keys.issubset(data.keys())


def test_api_query_source_validation():
    """測試 QueryResponseModel 對 source 欄位之值域限制。"""
    # 允許 'llm'
    m_llm = QueryResponseModel(
        query="q", route="general", source="llm",
    )
    assert m_llm.source == "llm"

    # 拒絕無效字串
    with pytest.raises(ValidationError):
        QueryResponseModel(query="q", route="general", source="invalid_source")


def test_api_query_price_masking_in_shortcut(api_client, isolated_db_path):
    """測試含金額 FAQ 短路時經 deep_mask_prices，整份回應文字零價格數字洩漏。"""
    q = "肉毒桿菌除皺方案收費說明？"
    ans = "特惠只要 3000元，雙部位 5000塊，NT$8000 起。"
    _insert_faq(isolated_db_path, "3503190424", "t-api-price", q, ans)

    payload = {"query": q, "clinic_id": "3503190424"}
    resp = api_client.post("/api/v1/query", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["source"] == "cache"
    assert "[請致電診所確認]" in data["cache_answer"]

    # 掃描整份 response.text
    matches = PRICE_REGEX.findall(resp.text)
    assert len(matches) == 0


def test_api_query_adversarial_check(api_client, isolated_db_path):
    """API 層對抗性抽查：正向短路，加『不』即退回 pageindex。"""
    q_faq = "肉毒桿菌注射完成後一週內的日常生活與飲食保養是否可以喝酒？"
    ans = "嚴禁飲酒。"
    _insert_faq(isolated_db_path, "3503190424", "t-api-neg", q_faq, ans)

    # 1. 正向
    resp_pos = api_client.post("/api/v1/query", json={"query": q_faq, "clinic_id": "3503190424"})
    assert resp_pos.status_code == 200
    assert resp_pos.json()["source"] == "cache"

    # 2. 否定變形
    q_adv = "肉毒桿菌注射完成後一週內的日常生活與飲食保養是否不可以喝酒？"
    resp_adv = api_client.post("/api/v1/query", json={"query": q_adv, "clinic_id": "3503190424"})
    assert resp_adv.status_code == 200
    assert resp_adv.json()["source"] == "pageindex"


def test_api_query_special_missing_clinic_id_returns_400(api_client, isolated_db_path):
    """測試 special 路由即使有可命中 FAQ，缺 clinic_id 仍回傳 HTTP 400。"""
    q = "音波拉提術後照護重點有哪些？"
    _insert_faq(isolated_db_path, "3503190424", "t-api-err", q, "照護說明")

    resp = api_client.post("/api/v1/query", json={"query": q})
    assert resp.status_code == 400
    assert "clinic_id" in resp.json()["detail"]


def test_api_query_all_endpoints_contain_source(api_client):
    """測試 GET /api/v1/query 與 POST /api/v1/clinics/{clinic_id}/query 皆具備 source 欄位。"""
    # GET
    res_get = api_client.get("/api/v1/query", params={"q": "乙醯胺酚"})
    assert res_get.status_code == 200
    assert "source" in res_get.json()

    # POST /clinics/{clinic_id}/query
    res_post_c = api_client.post("/api/v1/clinics/3503190424/query", json={"query": "乙醯胺酚"})
    assert res_post_c.status_code == 200
    assert "source" in res_post_c.json()


# ==============================================================================
# Task 2: 匿名統計記錄與異常隔離測試
# ==============================================================================

def test_stats_recorded_on_shortcut_hit(stats_client, isolated_db_path):
    """測試短路命中時記錄 ('3503190424', 今日, 'hit', '') count 1。"""
    q = "皮秒雷射術後居家冰敷重點有哪些？"
    _insert_faq(isolated_db_path, "3503190424", "t-st-hit", q, "冰敷每次十分鐘。")

    resp = stats_client.post("/api/v1/query", json={"query": q, "clinic_id": "3503190424"})
    assert resp.status_code == 200
    assert resp.json()["source"] == "cache"

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    cur.execute("SELECT clinic_id, outcome, keyword, count FROM cache_stats")
    rows = cur.fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0] == ("3503190424", "hit", "", 1)


def test_stats_recorded_on_eligible_miss(stats_client, isolated_db_path):
    """測試有資格短路但未命中時記錄 miss 與各關鍵字 miss_keyword。"""
    q = "音波拉提術後要怎麼照顧？"
    resp = stats_client.post("/api/v1/query", json={"query": q, "clinic_id": "3503190424"})
    assert resp.status_code == 200
    assert resp.json()["source"] == "pageindex"

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    cur.execute("SELECT outcome, keyword, count FROM cache_stats ORDER BY outcome, keyword")
    rows = cur.fetchall()
    conn.close()

    outcomes = [r[0] for r in rows]
    keywords = [r[1] for r in rows if r[0] == "miss_keyword"]

    assert "miss" in outcomes
    assert "音波" in keywords
    assert "拉提" in keywords
    assert "術後" in keywords


def test_stats_not_recorded_for_ineligible_ops_query(stats_client, isolated_db_path):
    """測試診所營運關鍵字查詢（cache_eligible=False）不計入 miss 統計。"""
    resp = stats_client.post(
        "/api/v1/query",
        json={"query": "請問診所營業時間是什麼？", "clinic_id": "3503190424"},
    )
    assert resp.status_code == 200

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM cache_stats")
    cnt = cur.fetchone()[0]
    conn.close()

    assert cnt == 0


def test_stats_accumulation_on_repeated_queries(stats_client, isolated_db_path):
    """測試同一短路問句連發 3 次，count 累加為 3。"""
    q = "皮秒雷射術後居家冰敷重點有哪些？"
    _insert_faq(isolated_db_path, "3503190424", "t-st-rep", q, "冰敷指引。")

    for _ in range(3):
        stats_client.post("/api/v1/query", json={"query": q, "clinic_id": "3503190424"})

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    cur.execute("SELECT count FROM cache_stats WHERE outcome = 'hit'")
    assert cur.fetchone()[0] == 3
    conn.close()


def test_stats_privacy_no_query_or_header_leakage(stats_client, isolated_db_path):
    """測試問句內特殊詞與 Header X-Clinic-ID 自由文字絕不落入 cache_stats。"""
    resp = stats_client.post(
        "/api/v1/query",
        json={"query": "音波拉提QZX隱私標記怎麼辦？"},
        headers={"X-Clinic-ID": "PRIVATE-TEXT-XYZ"},
    )
    assert resp.status_code == 200

    dumped = _dump_stats(isolated_db_path)
    assert "QZX" not in dumped
    assert "隱私標記" not in dumped
    assert "PRIVATE-TEXT-XYZ" not in dumped


def test_stats_not_recorded_on_400_bad_request(stats_client, isolated_db_path):
    """測試 HTTP 400 之錯誤請求不記錄任何統計。"""
    resp = stats_client.post("/api/v1/query", json={"query": "音波拉提術後照護重點有哪些？"})
    assert resp.status_code == 400

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM cache_stats")
    assert cur.fetchone()[0] == 0
    conn.close()


def test_stats_not_recorded_when_disabled(api_client, isolated_db_path):
    """測試 cache_stats_enabled=False 時查詢不寫入任何統計。"""
    resp = api_client.post("/api/v1/query", json={"query": "音波拉提術後要怎麼照顧？", "clinic_id": "3503190424"})
    assert resp.status_code == 200

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM cache_stats")
    assert cur.fetchone()[0] == 0
    conn.close()


def test_stats_exception_isolation_database_locked(stats_client, monkeypatch):
    """測試統計寫入遭遇資料庫鎖定時，查詢回應仍正常 200。"""
    def _locked_outcome(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(query_module, "record_query_outcome", _locked_outcome)

    resp = stats_client.post("/api/v1/query", json={"query": "乙醯胺酚"})
    assert resp.status_code == 200
    assert "source" in resp.json()


def test_stats_exception_isolation_table_dropped(stats_client, isolated_db_path):
    """測試當資料表被刪除（模擬正式庫未遷移）時，查詢仍正常 200。"""
    conn = sqlite3.connect(str(isolated_db_path))
    conn.execute("DROP TABLE cache_stats")
    conn.commit()
    conn.close()

    resp = stats_client.post("/api/v1/query", json={"query": "乙醯胺酚"})
    assert resp.status_code == 200


def test_stats_logging_isolation_no_sensitive_info(stats_client, monkeypatch, caplog):
    """測試統計例外日誌最多 1 則警告且不含問句、診所或關鍵字。"""
    monkeypatch.setattr(query_module, "_warned_error_types", set())

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated boom")

    monkeypatch.setattr(query_module, "record_query_outcome", _boom)

    secret_q = "音波拉提SECRET999"
    with caplog.at_level(logging.WARNING, logger="clinicbrain.cache_stats"):
        resp = stats_client.post("/api/v1/query", json={"query": secret_q, "clinic_id": "3503190424"})
        assert resp.status_code == 200

    assert len(caplog.records) == 1
    rec = caplog.records[0]
    assert "RuntimeError" in rec.message
    assert secret_q not in rec.message
    assert "3503190424" not in rec.message


def test_read_db_query_only_remains_enforced(stats_client, isolated_db_path):
    """測試主查詢使用的連線 PRAGMA query_only = ON 仍嚴格生效，拒絕寫入。"""
    # 建立一個測試連線模擬主查詢連線
    read_conn = sqlite3.connect(str(isolated_db_path))
    read_conn.execute("PRAGMA query_only = ON;")
    with pytest.raises(sqlite3.OperationalError):
        read_conn.execute("INSERT INTO cache_stats (clinic_id, stat_date, outcome) VALUES ('', '2026-09-30', 'hit')")
    read_conn.close()
