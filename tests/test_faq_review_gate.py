"""
FAQ 審核閘門與寫入狀態語意測試（Phase 09 BATCH-01 Task 2）。

驗證：
1. faq_writer.upsert_faqs 寫入狀態語意：
   - source_type='llm_generated' 新增列為 pending
   - 'manual' 與 'clinic_upload' 新增列為 approved
   - 更新語意：改答案時若改為 llm_generated 則轉為 pending（reviewed_at NULL）
   - 內容未變時保留原審核狀態
2. 舊庫 Fail-Closed：舊庫無審核欄位時，寫入 llm_generated 拋 RuntimeError 且零寫入。
3. visible_faq_sql 檢索條件片段產生（新庫 vs 舊庫，相容 NULL source_type）。
4. faq_review.set_review_status 單一寫入函式：
   - 核准/駁回、非 llm 略過、查無記錄略過、四層驗證失敗拒絕核准。
   - 可見性改變時遞增 content_version 並刷新 updated_at，可見性未改變時不遞增版本。
5. list_faqs / count_by_status / get_faq 查詢輔助函式。
"""

import sqlite3
import pytest

from src.pageindex.faq_writer import upsert_faqs
from src.pageindex.faq_review import (
    REVIEW_APPROVED,
    REVIEW_PENDING,
    REVIEW_REJECTED,
    ReviewResult,
    count_by_status,
    get_faq,
    has_review_status,
    list_faqs,
    set_review_status,
    visible_faq_sql,
)

# 舊版 faq_cache 最小可用 DDL（不含審核欄位）
OLD_FAQ_MINIMAL_DDL = """
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
"""


def test_upsert_faqs_initial_review_status(isolated_conn):
    """測試新增 FAQ 時，依據 source_type 給予正確的初始審核狀態。"""
    faqs_data = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-gate-hifu",
            "question": "哨兵問句-音波拉提效果如何？",
            "answer": "音波拉提可透過聚焦超音波刺激膠原蛋白新生。",
            "category": "special",
        }
    ]

    # 1. llm_generated 寫入應為 pending
    ins, upd, unc = upsert_faqs(isolated_conn, faqs_data, source_type="llm_generated")
    assert (ins, upd, unc) == (1, 0, 0)

    cur = isolated_conn.cursor()
    cur.execute("SELECT review_status, reviewed_at FROM faq_cache WHERE topic_key='zz-gate-hifu'")
    row = cur.fetchone()
    assert row[0] == REVIEW_PENDING
    assert row[1] is None

    # 2. manual 與 clinic_upload 應為 approved
    faqs_manual = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-gate-manual",
            "question": "哨兵問句-手寫常見問答？",
            "answer": "這是由診所人員手寫整理之問答。",
            "category": "special",
        }
    ]
    upsert_faqs(isolated_conn, faqs_manual, source_type="manual")
    cur.execute("SELECT review_status FROM faq_cache WHERE topic_key='zz-gate-manual'")
    assert cur.fetchone()[0] == REVIEW_APPROVED

    faqs_upload = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-gate-upload",
            "question": "哨兵問句-上傳常見問答？",
            "answer": "這是診所文件擷取轉換之問答。",
            "category": "special",
        }
    ]
    upsert_faqs(isolated_conn, faqs_upload, source_type="clinic_upload")
    cur.execute("SELECT review_status FROM faq_cache WHERE topic_key='zz-gate-upload'")
    assert cur.fetchone()[0] == REVIEW_APPROVED


def test_upsert_faqs_update_review_status_semantics(isolated_conn):
    """測試內容更新時的審核狀態流轉語意。"""
    # 建立一筆 approved 的 clinic_upload
    faq = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-gate-flow",
            "question": "哨兵問句-狀態流轉問答？",
            "answer": "原始版本答案。",
            "category": "special",
        }
    ]
    upsert_faqs(isolated_conn, faq, source_type="clinic_upload")

    # 以 llm_generated 更新答案 → 列應轉為 pending 且 reviewed_at 為 NULL
    faq_updated = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-gate-flow",
            "question": "哨兵問句-狀態流轉問答？",
            "answer": "LLM 覆寫的新版本答案。",
            "category": "special",
        }
    ]
    ins, upd, unc = upsert_faqs(isolated_conn, faq_updated, source_type="llm_generated")
    assert (ins, upd, unc) == (0, 1, 0)

    cur = isolated_conn.cursor()
    cur.execute("SELECT review_status, reviewed_at FROM faq_cache WHERE topic_key='zz-gate-flow'")
    row = cur.fetchone()
    assert row[0] == REVIEW_PENDING
    assert row[1] is None

    # 以 manual 更新答案 → 轉為 approved
    faq_manual_update = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-gate-flow",
            "question": "哨兵問句-狀態流轉問答？",
            "answer": "醫師手動修正之答案。",
            "category": "special",
        }
    ]
    ins, upd, unc = upsert_faqs(isolated_conn, faq_manual_update, source_type="manual")
    assert (ins, upd, unc) == (0, 1, 0)
    cur.execute("SELECT review_status FROM faq_cache WHERE topic_key='zz-gate-flow'")
    assert cur.fetchone()[0] == REVIEW_APPROVED

    # 內容未變更新 → 狀態與 reviewed_at 完全不動
    ins, upd, unc = upsert_faqs(isolated_conn, faq_manual_update, source_type="manual")
    assert (ins, upd, unc) == (0, 0, 1)


def test_upsert_faqs_fails_closed_on_old_database():
    """測試舊資料庫（無審核欄位）：llm_generated 寫入拋 RuntimeError 且零列寫入；clinic_upload 成功。"""
    conn = sqlite3.connect(":memory:")
    conn.executescript(OLD_FAQ_MINIMAL_DDL)

    faq_llm = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-gate-old-db",
            "question": "哨兵問句-舊庫測試？",
            "answer": "LLM 產出答案。",
            "category": "special",
        }
    ]

    # llm_generated 必須拋錯且拒絕寫入
    with pytest.raises(RuntimeError) as exc_info:
        upsert_faqs(conn, faq_llm, source_type="llm_generated")
    assert "審核欄位" in str(exc_info.value)

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM faq_cache")
    assert cur.fetchone()[0] == 0

    # clinic_upload 向後相容，應可正常寫入
    ins, upd, unc = upsert_faqs(conn, faq_llm, source_type="clinic_upload")
    assert (ins, upd, unc) == (1, 0, 0)
    cur.execute("SELECT COUNT(*) FROM faq_cache")
    assert cur.fetchone()[0] == 1
    conn.close()


def test_visible_faq_sql():
    """測試 visible_faq_sql 產生的 SQL 條件片段與查詢行為。"""
    # 1. 舊庫（無 review_status）
    conn_old = sqlite3.connect(":memory:")
    conn_old.executescript(OLD_FAQ_MINIMAL_DDL)
    sql_old = visible_faq_sql(conn_old)
    assert sql_old == "(source_type IS NOT 'llm_generated')"

    # 插入測試資料驗證查詢行為
    conn_old.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type)
        VALUES ('3503190424', 't1', '問1', '答1', 'special', NULL),
               ('3503190424', 't2', '問2', '答2', 'special', 'clinic_upload'),
               ('3503190424', 't3', '問3', '答3', 'special', 'llm_generated')
        """
    )
    cur = conn_old.cursor()
    cur.execute(f"SELECT topic_key FROM faq_cache WHERE {sql_old} ORDER BY topic_key")
    assert [r[0] for r in cur.fetchall()] == ["t1", "t2"]
    conn_old.close()

    # 2. 新庫（具備 review_status）
    conn_new = sqlite3.connect(":memory:")
    conn_new.executescript(OLD_FAQ_MINIMAL_DDL)
    conn_new.execute("ALTER TABLE faq_cache ADD COLUMN review_status TEXT NOT NULL DEFAULT 'approved'")
    conn_new.execute("ALTER TABLE faq_cache ADD COLUMN reviewed_at TIMESTAMP")

    sql_new = visible_faq_sql(conn_new)
    assert sql_new == "(source_type IS NOT 'llm_generated' OR review_status = 'approved')"

    conn_new.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status)
        VALUES ('3503190424', 't1', '問1', '答1', 'special', NULL, 'approved'),
               ('3503190424', 't2', '問2', '答2', 'special', 'clinic_upload', 'approved'),
               ('3503190424', 't3', '問3', '答3', 'special', 'llm_generated', 'pending'),
               ('3503190424', 't4', '問4', '答4', 'special', 'llm_generated', 'approved')
        """
    )
    cur = conn_new.cursor()
    cur.execute(f"SELECT topic_key FROM faq_cache WHERE {sql_new} ORDER BY topic_key")
    assert [r[0] for r in cur.fetchall()] == ["t1", "t2", "t4"]
    conn_new.close()


def test_set_review_status_lifecycle_and_versioning(isolated_conn):
    """測試 set_review_status 的審核生命週期、驗證攔截與版本號遞增。"""
    # 建立一筆 pending 的 llm_generated
    faq = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-gate-ver",
            "question": "哨兵問句-版本審核測試？",
            "answer": "正常合規的答案內容。",
            "category": "special",
        }
    ]
    upsert_faqs(isolated_conn, faq, source_type="llm_generated")

    cur = isolated_conn.cursor()
    cur.execute("SELECT id, content_version, updated_at FROM faq_cache WHERE topic_key='zz-gate-ver'")
    row = cur.fetchone()
    faq_id, initial_version, initial_updated = row
    assert initial_version == 1

    # 1. 核准 (pending -> approved)：可見性改變，content_version 遞增為 2
    res = set_review_status(isolated_conn, [faq_id], REVIEW_APPROVED)
    assert res.changed == [faq_id]
    assert res.skipped == []

    cur.execute("SELECT review_status, reviewed_at, content_version, updated_at FROM faq_cache WHERE id=?", (faq_id,))
    st, r_at, ver, upd_at = cur.fetchone()
    assert st == REVIEW_APPROVED
    assert r_at is not None
    assert ver == 2
    assert upd_at >= initial_updated

    # 2. 再次核准同一筆 (approved -> approved)：no_change，版本不變
    res2 = set_review_status(isolated_conn, [faq_id], REVIEW_APPROVED)
    assert res2.changed == []
    assert res2.skipped == [(faq_id, "no_change")]
    cur.execute("SELECT content_version FROM faq_cache WHERE id=?", (faq_id,))
    assert cur.fetchone()[0] == 2

    # 3. 駁回 (approved -> rejected)：可見性由可見轉為不可見，content_version 遞增為 3
    res3 = set_review_status(isolated_conn, [faq_id], REVIEW_REJECTED)
    assert res3.changed == [faq_id]
    cur.execute("SELECT review_status, content_version FROM faq_cache WHERE id=?", (faq_id,))
    assert cur.fetchone() == (REVIEW_REJECTED, 3)

    # 4. 再次轉 pending (rejected -> pending)：可見性未改變（兩者皆不可見），版本不變
    res4 = set_review_status(isolated_conn, [faq_id], REVIEW_PENDING)
    assert res4.changed == [faq_id]
    cur.execute("SELECT review_status, reviewed_at, content_version FROM faq_cache WHERE id=?", (faq_id,))
    st4, r_at4, ver4 = cur.fetchone()
    assert st4 == REVIEW_PENDING
    assert r_at4 is None  # pending 時 reviewed_at 清空
    assert ver4 == 3


def test_set_review_status_validation_guard(isolated_conn):
    """測試 set_review_status 在核准前重跑四層驗證，違規內容拒絕核准。"""
    # 直接以 raw SQL 插入一筆包含價格的違規 pending 記錄
    cur = isolated_conn.cursor()
    cur.execute(
        """
        INSERT INTO faq_cache (
            clinic_id, topic_key, question, answer, category, source_type, review_status, content_version
        ) VALUES (
            '3503190424', 'zz-gate-illegal', '哨兵問句-價格問答？', '音波拉提特惠只要 15000元 整。', 'special', 'llm_generated', 'pending', 1
        )
        """
    )
    bad_id = cur.lastrowid
    isolated_conn.commit()

    # 嘗試核准，應因四層驗證失敗而被略過
    res = set_review_status(isolated_conn, [bad_id], REVIEW_APPROVED)
    assert res.changed == []
    assert len(res.skipped) == 1
    assert res.skipped[0][0] == bad_id
    assert res.skipped[0][1].startswith("validation_failed")

    # 驗證狀態仍為 pending，content_version 仍為 1
    cur.execute("SELECT review_status, content_version FROM faq_cache WHERE id=?", (bad_id,))
    assert cur.fetchone() == (REVIEW_PENDING, 1)


def test_set_review_status_edge_cases(isolated_conn):
    """測試 set_review_status 各種邊界條件（查無、非 llm、非法狀態、舊庫）。"""
    # 1. 不存在的 id
    res_not_found = set_review_status(isolated_conn, [999999], REVIEW_APPROVED)
    assert res_not_found.skipped == [(999999, "not_found")]

    # 2. clinic_upload 項目不需審核，應回傳 not_llm_generated
    cur = isolated_conn.cursor()
    cur.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status)
        VALUES ('3503190424', 'zz-gate-upload-test', '問', '答', 'special', 'clinic_upload', 'approved')
        """
    )
    upload_id = cur.lastrowid
    isolated_conn.commit()

    res_upload = set_review_status(isolated_conn, [upload_id], REVIEW_REJECTED)
    assert res_upload.skipped == [(upload_id, "not_llm_generated")]

    # 3. 非法狀態值拋 ValueError
    with pytest.raises(ValueError):
        set_review_status(isolated_conn, [upload_id], "invalid_status")

    # 4. 舊庫執行拋 RuntimeError
    conn_old = sqlite3.connect(":memory:")
    conn_old.executescript(OLD_FAQ_MINIMAL_DDL)
    with pytest.raises(RuntimeError):
        set_review_status(conn_old, [1], REVIEW_APPROVED)
    conn_old.close()


def test_faq_review_query_helpers(isolated_conn):
    """測試 list_faqs / count_by_status / get_faq 輔助函式。"""
    # 插入幾筆測試資料
    cur = isolated_conn.cursor()
    cur.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status)
        VALUES ('3503190424', 'zz-gate-h1', '問1', '答1', 'special', 'llm_generated', 'pending'),
               ('3503190424', 'zz-gate-h2', '問2', '答2', 'special', 'llm_generated', 'approved'),
               ('3503190424', 'zz-gate-h3', '問3', '答3', 'special', 'llm_generated', 'rejected')
        """
    )
    isolated_conn.commit()

    # 1. count_by_status
    counts = count_by_status(isolated_conn)
    assert counts.get("pending", 0) >= 1
    assert counts.get("approved", 0) >= 1
    assert counts.get("rejected", 0) >= 1

    # 2. list_faqs
    pending_list = list_faqs(isolated_conn, status=REVIEW_PENDING, limit=10)
    assert any(f["topic_key"] == "zz-gate-h1" for f in pending_list)
    assert all(f["review_status"] == REVIEW_PENDING for f in pending_list)
    assert all(f["source_type"] == "llm_generated" for f in pending_list)

    # 3. get_faq
    cur.execute("SELECT id FROM faq_cache WHERE topic_key='zz-gate-h1'")
    h1_id = cur.fetchone()[0]
    faq = get_faq(isolated_conn, h1_id)
    assert faq is not None
    assert faq["topic_key"] == "zz-gate-h1"
    assert faq["question"] == "問1"
    assert faq["review_status"] == REVIEW_PENDING

    # 不存在的 id 回傳 None
    assert get_faq(isolated_conn, 999999) is None
