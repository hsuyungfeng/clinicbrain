"""
FAQ 審核閘門端對端檢索、快取短路、同步匯出與 Phase 8 回歸測試（Phase 09 BATCH-01 Task 1）。

驗證重點：
1. 檢索端（search_faq_cache）：
   - FTS trigram (3+字) 與 LIKE (<3字) 分流下，pending / rejected 的 LLM FAQ 均不可見。
   - approve 後立即對外可見，reset 為 pending 或 reject 後再次隱藏。
   - 手寫 (manual) 與診所上傳 (clinic_upload) 記錄不受影響、立即可查。
2. 零回歸保證：正式庫複本既有 40 筆真實 FAQ 的檢索結果在閘門啟用前後完全一致。
3. 舊庫相容：未遷移的舊資料庫退化為排除 llm_generated，平穩降級不拋錯。
4. 快取短路對照組（handle_query 與 POST /api/v1/query）：
   - pending 時即使問句完全相同亦不短路，改走 pageindex 推理樹。
   - approve 後同一查詢立即觸發快取短路 (source='cache')。
5. 同步匯出 (POST /api/v1/sync/export)：
   - 未核准的 LLM FAQ 不匯出至雲端。
   - 增量匯出 (since_version)：approve 遞增 content_version 後能被精確增量匯出。
6. Phase 8 一般醫療諮詢入口相容性 (consult_general 與 POST /api/v1/general/query)。
"""

from pathlib import Path
import sqlite3
from fastapi.testclient import TestClient
import pytest

from src.api.app import app
from src.api.config import config
from src.general.consult import consult_general
from src.pageindex.faq_review import (
    REVIEW_APPROVED,
    REVIEW_PENDING,
    REVIEW_REJECTED,
    set_review_status,
)
from src.pageindex.faq_writer import upsert_faqs
from src.query.router import handle_query
from src.query.search import search_faq_cache

OLD_FAQ_DDL_WITH_TRIGGER = """
CREATE TABLE faq_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id TEXT,
    topic_key TEXT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category TEXT NOT NULL,
    source_type TEXT DEFAULT 'manual',
    content_version INTEGER NOT NULL DEFAULT 1,
    needs_regeneration BOOLEAN NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(clinic_id, topic_key, question)
);

CREATE VIRTUAL TABLE faq_cache_fts USING fts5(
    question, answer, content='faq_cache', content_rowid='id', tokenize='trigram'
);

CREATE TRIGGER faq_cache_ai AFTER INSERT ON faq_cache BEGIN
    INSERT INTO faq_cache_fts(rowid, question, answer)
    VALUES (new.id, new.question, new.answer);
END;
"""


def test_search_faq_cache_gate_fts_and_like(isolated_conn):
    """測試 search_faq_cache 在 FTS 與 LIKE 分流下對 LLM FAQ 之審核閘門。"""
    # 寫入一筆 general llm FAQ
    # 包含 3+ 字詞「音波拉提」與 2 字詞「拉皮」
    faq_data = [
        {
            "clinic_id": None,
            "topic_key": "zz-gate-g",
            "question": "哨兵問句-音波拉提與拉皮的差異？",
            "answer": "音波拉提屬於非侵入式保養療程，拉皮多為手術方式。",
            "category": "general",
        }
    ]
    upsert_faqs(isolated_conn, faq_data, source_type="llm_generated")

    cur = isolated_conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE topic_key='zz-gate-g'")
    faq_id = cur.fetchone()[0]

    # 1. pending 時：3+字詞 (FTS) 與 2字詞 (LIKE) 檢索均查不到
    hits_fts = search_faq_cache(isolated_conn, "音波拉提", category="general")
    assert not any(h.fields.get("topic_key") == "zz-gate-g" for h in hits_fts)

    hits_like = search_faq_cache(isolated_conn, "拉皮", category="general")
    assert not any(h.fields.get("topic_key") == "zz-gate-g" for h in hits_like)

    # 2. approve 後：兩者皆可查到
    set_review_status(isolated_conn, [faq_id], REVIEW_APPROVED)
    hits_fts_app = search_faq_cache(isolated_conn, "音波拉提", category="general")
    assert any(h.fields.get("topic_key") == "zz-gate-g" for h in hits_fts_app)

    hits_like_app = search_faq_cache(isolated_conn, "拉皮", category="general")
    assert any(h.fields.get("topic_key") == "zz-gate-g" for h in hits_like_app)

    # 3. reject 後：再次不可查
    set_review_status(isolated_conn, [faq_id], REVIEW_REJECTED)
    hits_rej = search_faq_cache(isolated_conn, "音波拉提", category="general")
    assert not any(h.fields.get("topic_key") == "zz-gate-g" for h in hits_rej)

    # 4. reset 為 pending 後：依然不可查
    set_review_status(isolated_conn, [faq_id], REVIEW_PENDING)
    hits_rst = search_faq_cache(isolated_conn, "音波拉提", category="general")
    assert not any(h.fields.get("topic_key") == "zz-gate-g" for h in hits_rst)

    # 5. manual 與 clinic_upload 哨兵記錄立即可查
    faq_manual = [
        {
            "clinic_id": None,
            "topic_key": "zz-gate-man",
            "question": "哨兵問句-手動手寫拉皮照護？",
            "answer": "手動手寫照護原則說明。",
            "category": "general",
        }
    ]
    upsert_faqs(isolated_conn, faq_manual, source_type="manual")
    hits_man = search_faq_cache(isolated_conn, "手寫拉皮", category="general")
    assert any(h.fields.get("topic_key") == "zz-gate-man" for h in hits_man)


def test_search_faq_cache_special_clinic_id(isolated_conn):
    """測試 special 類別與 clinic_id 過濾條件下審核閘門依然生效。"""
    faq_special = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-gate-spec",
            "question": "哨兵問句-診所專屬音波費用諮詢？",
            "answer": "診所專業諮詢請致電診所確認。",
            "category": "special",
        }
    ]
    upsert_faqs(isolated_conn, faq_special, source_type="llm_generated")

    cur = isolated_conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE topic_key='zz-gate-spec'")
    faq_id = cur.fetchone()[0]

    # pending 時查不到
    hits = search_faq_cache(isolated_conn, "音波費用", clinic_id="3503190424", category="special")
    assert not any(h.fields.get("topic_key") == "zz-gate-spec" for h in hits)

    # approve 後查得到
    set_review_status(isolated_conn, [faq_id], REVIEW_APPROVED)
    hits_app = search_faq_cache(isolated_conn, "音波費用", clinic_id="3503190424", category="special")
    assert any(h.fields.get("topic_key") == "zz-gate-spec" for h in hits_app)


def test_search_faq_cache_zero_regression_on_prod_replica(conn, monkeypatch):
    """測試真實資料零回歸：對正式庫既有 40 筆 clinic_upload FAQ，開關閘門之命中 id 序列完全相同。"""
    query_terms = ["甲溝炎", "術後", "雷射", "傷口", "照護", "恢復", "費用", "注意"]

    import src.query.search as search_mod

    # 1. 取得現行啟用閘門時的檢索序列
    results_with_gate: dict[str, list[int]] = {}
    for term in query_terms:
        hits = search_faq_cache(conn, term, limit=1000, clinic_id="3503190424")
        results_with_gate[term] = [h.row_id for h in hits]

    # 2. 暫時將 visible_faq_sql monkeypatch 為無條件放行 '1=1'
    monkeypatch.setattr(search_mod, "visible_faq_sql", lambda c: "1=1")

    results_without_gate: dict[str, list[int]] = {}
    for term in query_terms:
        hits = search_faq_cache(conn, term, limit=1000, clinic_id="3503190424")
        results_without_gate[term] = [h.row_id for h in hits]

    # 斷言序列逐項完全相同
    for term in query_terms:
        assert results_with_gate[term] == results_without_gate[term], f"關鍵字 '{term}' 檢索結果出現回歸差異！"

    # 至少有一組關鍵字非空
    assert any(len(res) > 0 for res in results_with_gate.values())


def test_search_faq_cache_graceful_on_old_database():
    """測試舊資料庫（無 review_status 欄位）：只排除 llm_generated，平穩降級不拋錯。"""
    conn_old = sqlite3.connect(":memory:")
    conn_old.executescript(OLD_FAQ_DDL_WITH_TRIGGER)

    conn_old.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type)
        VALUES ('3503190424', 'old-upload', '甲溝炎照護手冊', '照護說明手冊', 'special', 'clinic_upload'),
               ('3503190424', 'old-llm', '甲溝炎機器人回答', '機器人生成答案', 'special', 'llm_generated')
        """
    )
    conn_old.commit()

    hits = search_faq_cache(conn_old, "甲溝炎", clinic_id="3503190424")
    keys = [h.fields.get("topic_key") for h in hits]
    assert "old-upload" in keys
    assert "old-llm" not in keys
    conn_old.close()


def test_shortcut_comparison_control_group(isolated_conn):
    """測試快取短路對照組：pending 拒絕短路，approve 後立即短路。"""
    question = "甲溝炎術後傷口紅腫發熱需要提早回診嗎？"
    answer = "若術後傷口出現發熱泛紅且疼痛加劇，應立即回診由醫師親自診視檢查。"
    faq_data = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-gate-sc",
            "question": question,
            "answer": answer,
            "category": "special",
        }
    ]
    upsert_faqs(isolated_conn, faq_data, source_type="llm_generated")
    cur = isolated_conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE topic_key='zz-gate-sc'")
    faq_id = cur.fetchone()[0]

    # 1. pending 時：handle_query source != 'cache'
    res_pending = handle_query(isolated_conn, question, clinic_id="3503190424")
    assert res_pending.source != "cache"
    assert "zz-gate-sc" not in [hit.fields.get("topic_key") for hit in (res_pending.faq_hits or [])]

    # 2. approve 後：handle_query 立即短路為 source='cache'
    set_review_status(isolated_conn, [faq_id], REVIEW_APPROVED)
    res_app = handle_query(isolated_conn, question, clinic_id="3503190424")
    assert res_app.source == "cache"
    assert res_app.cache_answer == answer


def test_api_query_review_gate(isolated_db_path, monkeypatch):
    """測試 API 查詢端點 POST /api/v1/query 的審核閘門。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    client = TestClient(app)

    conn = sqlite3.connect(str(isolated_db_path))
    question = "甲溝炎術後傷口紅腫發熱需要提早回診嗎？"
    unique_phrase = "應立即回診由醫師親自診視檢查"
    answer = f"若術後傷口出現發熱泛紅且疼痛加劇，{unique_phrase}。"
    faq_data = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-gate-api",
            "question": question,
            "answer": answer,
            "category": "special",
        }
    ]
    upsert_faqs(conn, faq_data, source_type="llm_generated")
    cur = conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE topic_key='zz-gate-api'")
    faq_id = cur.fetchone()[0]
    conn.close()

    # 1. pending 時：查詢應走 pageindex，回傳內容不包含未核准 FAQ 唯一片語
    resp_pending = client.post("/api/v1/query", json={"query": question, "clinic_id": "3503190424"})
    assert resp_pending.status_code == 200
    data_pending = resp_pending.json()
    assert data_pending.get("source") != "cache"
    assert unique_phrase not in str(data_pending)

    # 2. approve 後：同一請求觸發快取短路，source='cache'
    conn = sqlite3.connect(str(isolated_db_path))
    set_review_status(conn, [faq_id], REVIEW_APPROVED)
    conn.close()

    resp_app = client.post("/api/v1/query", json={"query": question, "clinic_id": "3503190424"})
    assert resp_app.status_code == 200
    data_app = resp_app.json()
    assert data_app.get("source") == "cache"
    assert data_app.get("cache_answer") == answer


def test_sync_export_review_gate_and_incremental(isolated_db_path, monkeypatch):
    """測試同步匯出 POST /api/v1/sync/export 排除未核准項目與增量匯出行為。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    client = TestClient(app)

    conn = sqlite3.connect(str(isolated_db_path))
    faq = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-gate-sync",
            "question": "哨兵問句-同步匯出測試？",
            "answer": "同步匯出合規答案內容。",
            "category": "special",
        }
    ]
    upsert_faqs(conn, faq, source_type="llm_generated")
    cur = conn.cursor()
    cur.execute("SELECT id, content_version FROM faq_cache WHERE topic_key='zz-gate-sync'")
    faq_id, initial_version = cur.fetchone()
    conn.close()

    headers = {"X-API-Key": "test-admin-key"}
    monkeypatch.setattr(config, "admin_api_key", "test-admin-key")
    monkeypatch.setattr(config, "allow_no_auth", False)

    # 1. pending 時：匯出不包含該項目
    resp1 = client.post(
        "/api/v1/sync/export",
        json={"clinic_id": "3503190424", "entities": ["faqs"], "since_version": 1},
        headers=headers,
    )
    assert resp1.status_code == 200
    exported1 = resp1.json()["data"]["faqs"]
    assert not any(f["topic_key"] == "zz-gate-sync" for f in exported1)
    assert resp1.json()["counts"]["faqs"] >= 40

    # 2. approve 後：content_version 遞增為 2，since_version=2 應包含它
    conn = sqlite3.connect(str(isolated_db_path))
    set_review_status(conn, [faq_id], REVIEW_APPROVED)
    conn.close()

    resp2 = client.post(
        "/api/v1/sync/export",
        json={"clinic_id": "3503190424", "entities": ["faqs"], "since_version": 2},
        headers=headers,
    )
    assert resp2.status_code == 200
    exported2 = resp2.json()["data"]["faqs"]
    assert any(f["topic_key"] == "zz-gate-sync" for f in exported2)

    # since_version=3 則不包含它
    resp3 = client.post(
        "/api/v1/sync/export",
        json={"clinic_id": "3503190424", "entities": ["faqs"], "since_version": 3},
        headers=headers,
    )
    assert not any(f["topic_key"] == "zz-gate-sync" for f in resp3.json()["data"]["faqs"])

    # 3. reject 後：即使 since_version=1 亦不匯出
    conn = sqlite3.connect(str(isolated_db_path))
    set_review_status(conn, [faq_id], REVIEW_REJECTED)
    conn.close()

    resp4 = client.post(
        "/api/v1/sync/export",
        json={"clinic_id": "3503190424", "entities": ["faqs"], "since_version": 1},
        headers=headers,
    )
    assert not any(f["topic_key"] == "zz-gate-sync" for f in resp4.json()["data"]["faqs"])


def test_phase8_general_consult_compatibility(isolated_db_path, monkeypatch):
    """測試 Phase 8 一般醫療諮詢入口 (consult_general 與 POST /api/v1/general/query) 相容性。"""
    conn = sqlite3.connect(str(isolated_db_path))
    question = "感冒多喝水居家照護原則？"
    answer = "感冒居家照護請多加休息並補充足夠水分，如有高燒不退應就醫。"
    faq = [
        {
            "clinic_id": None,
            "topic_key": "zz-gate-gen-p8",
            "question": question,
            "answer": answer,
            "category": "general",
        }
    ]
    upsert_faqs(conn, faq, source_type="llm_generated")
    cur = conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE topic_key='zz-gate-gen-p8'")
    faq_id = cur.fetchone()[0]

    # 1. consult_general 在 pending 時查不到
    res_pending = consult_general(conn, question, limit=5)
    assert not any(f.get("topic_key") == "zz-gate-gen-p8" for f in res_pending.faq_hits)

    # 2. approve 後可查到
    set_review_status(conn, [faq_id], REVIEW_APPROVED)
    res_app = consult_general(conn, question, limit=5)
    assert any(f.get("topic_key") == "zz-gate-gen-p8" for f in res_app.faq_hits)
    conn.close()

    # 3. HTTP API POST /api/v1/general/query 相容性
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    client = TestClient(app)
    resp = client.post("/api/v1/general/query", json={"query": question})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "answered"
    assert any(f["topic_key"] == "zz-gate-gen-p8" for f in data["faq_hits"])
