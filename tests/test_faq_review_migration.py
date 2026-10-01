"""
faq_cache 審核狀態欄位遷移腳本測試（Phase 09 BATCH-01 Task 1）。

驗證：
1. 全新 schema 包含 review_status 與 reviewed_at 欄位、預設值 approved、CHECK 約束生效。
2. 舊庫遷移：補上兩欄、既有 clinic_upload 維持 approved、llm_generated 回填為 pending、冪等性。
3. 欄位一致性：遷移後的欄位屬性與全新 schema 完全一致。
4. 交易性：ALTER 失敗時自動 ROLLBACK，資料庫回到未遷移狀態。
5. 半遷移修復：只存在一欄時補齊缺欄並回填 pending，不覆蓋已核准項目。
6. CLI 防禦：未加 --confirm-prod-backup 對正式庫連線前拒絕（結束碼 2）；--dry-run 不修改資料庫。
7. 正式庫保護：正式 clinic.db 之 sha256sum 在測試前後保持不變。
"""

import hashlib
from pathlib import Path
import sqlite3
import pytest

from scripts.migrate_faq_review_status import (
    PROD_DB_PATH,
    ALTER_REVIEW_STATUS_SQL,
    ALTER_REVIEWED_AT_SQL,
    apply_review_status_migration,
    has_review_status_column,
    main as migrate_main,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "src" / "db" / "clinic_schema.sql"

# 舊版 faq_cache DDL（不含 review_status 與 reviewed_at，供遷移測試使用）
OLD_FAQ_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS faq_cache (
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


def _get_sha256(path: Path) -> str:
    """計算指定檔案之 SHA-256 雜湊值。"""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


# ==============================================================================
# 測試項目
# ==============================================================================

def test_fresh_schema_has_review_columns(tmp_path: Path):
    """測試以全新 clinic_schema.sql 建庫時，faq_cache 包含審核欄位且 CHECK 約束生效。"""
    db_path = tmp_path / "fresh.db"
    conn = sqlite3.connect(str(db_path))
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)

    cur = conn.cursor()
    cur.execute("PRAGMA table_info(faq_cache)")
    cols = {row[1]: row for row in cur.fetchall()}

    assert "review_status" in cols
    assert "reviewed_at" in cols
    # review_status: notnull=1, dflt_value="'approved'"
    status_col = cols["review_status"]
    assert status_col[2].upper() == "TEXT"
    assert status_col[3] == 1  # notnull
    assert status_col[4] == "'approved'"

    # 測試預設值：不傳 review_status 時應為 'approved'
    cur.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category)
        VALUES ('3503190424', 'test-fresh', '問題1', '答案1', 'special')
        """
    )
    conn.commit()

    cur.execute("SELECT review_status, reviewed_at FROM faq_cache WHERE topic_key='test-fresh'")
    row = cur.fetchone()
    assert row[0] == "approved"
    assert row[1] is None

    # 測試 CHECK 約束：非 pending/approved/rejected 應報錯
    with pytest.raises(sqlite3.IntegrityError):
        cur.execute(
            """
            INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, review_status)
            VALUES ('3503190424', 'test-bogus', '問題2', '答案2', 'special', 'bogus')
            """
        )
    conn.close()


def test_migration_from_old_schema(tmp_path: Path):
    """測試舊庫遷移：既有 clinic_upload 設為 approved，既有 llm_generated 回填為 pending。"""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(OLD_FAQ_CACHE_DDL)

    # 插入一筆 clinic_upload 與一筆 llm_generated
    conn.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, content_version)
        VALUES ('3503190424', 'test-old-1', '問1', '答1', 'special', 'clinic_upload', 1)
        """
    )
    conn.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, content_version)
        VALUES ('3503190424', 'test-old-2', '問2', '答2', 'special', 'llm_generated', 1)
        """
    )
    conn.commit()
    conn.close()

    # 執行遷移
    result = apply_review_status_migration(db_path)
    assert set(result["added"]) == {"review_status", "reviewed_at"}
    assert result["backfilled_pending"] == 1
    assert result["repaired_half_state"] is False

    # 檢查遷移後資料
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT topic_key, source_type, review_status, content_version FROM faq_cache ORDER BY topic_key")
    rows = cur.fetchall()
    assert rows[0] == ("test-old-1", "clinic_upload", "approved", 1)
    assert rows[1] == ("test-old-2", "llm_generated", "pending", 1)
    conn.close()

    # 第二次執行遷移應為冪等（無任何變更）
    result2 = apply_review_status_migration(db_path)
    assert result2["added"] == []
    assert result2["backfilled_pending"] == 0
    assert result2["repaired_half_state"] is False


def test_column_definitions_consistency(tmp_path: Path):
    """測試遷移後的舊庫欄位屬性與全新 schema 庫完全相同。"""
    fresh_path = tmp_path / "fresh_def.db"
    old_path = tmp_path / "old_def.db"

    conn_fresh = sqlite3.connect(str(fresh_path))
    conn_fresh.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn_fresh.close()

    conn_old = sqlite3.connect(str(old_path))
    conn_old.executescript(OLD_FAQ_CACHE_DDL)
    conn_old.close()

    apply_review_status_migration(old_path)

    # 比對兩者的 PRAGMA table_info(faq_cache) 的 review_status 與 reviewed_at
    conn_fresh = sqlite3.connect(str(fresh_path))
    fresh_info = {r[1]: (r[2].upper(), r[3], r[4]) for r in conn_fresh.execute("PRAGMA table_info(faq_cache)")}
    conn_fresh.close()

    conn_old = sqlite3.connect(str(old_path))
    old_info = {r[1]: (r[2].upper(), r[3], r[4]) for r in conn_old.execute("PRAGMA table_info(faq_cache)")}
    conn_old.close()

    assert old_info["review_status"] == fresh_info["review_status"]
    assert old_info["reviewed_at"] == fresh_info["reviewed_at"]


def test_transaction_rollback_on_error(tmp_path: Path, monkeypatch):
    """測試遷移過程中出錯時交易自動 ROLLBACK，舊庫不遺留任何半套變更。"""
    db_path = tmp_path / "rollback.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(OLD_FAQ_CACHE_DDL)
    conn.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type)
        VALUES ('3503190424', 'test-rb', '問題', '答案', 'special', 'clinic_upload')
        """
    )
    conn.commit()
    conn.close()

    # 將第二條 ALTER 語句刻意置換為語法錯誤
    import scripts.migrate_faq_review_status as mig_mod
    monkeypatch.setattr(mig_mod, "ALTER_REVIEWED_AT_SQL", "ALTER TABLE faq_cache ADD COLUMN")

    with pytest.raises(sqlite3.OperationalError):
        apply_review_status_migration(db_path)

    # 驗證 ROLLBACK：第一個欄位 review_status 也不應該存在
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(faq_cache)")
    cols = [r[1] for r in cur.fetchall()]
    assert "review_status" not in cols
    assert "reviewed_at" not in cols
    assert not has_review_status_column(conn)
    conn.close()

    # 還原常數後重跑應成功
    monkeypatch.undo()
    result = apply_review_status_migration(db_path)
    assert set(result["added"]) == {"review_status", "reviewed_at"}


def test_half_migrated_state_repair(tmp_path: Path):
    """測試半遷移狀態修復：若只存在一欄，補齊缺欄並回填 pending，但絕不覆蓋已核准項目。"""
    # 案例 A: 只有 review_status 欄位
    db_path_a = tmp_path / "half_a.db"
    conn = sqlite3.connect(str(db_path_a))
    conn.executescript(OLD_FAQ_CACHE_DDL)
    conn.execute(ALTER_REVIEW_STATUS_SQL)
    # 插入一筆 llm_generated（預設為 approved）與一筆 clinic_upload
    conn.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type)
        VALUES ('3503190424', 'test-a-1', '問1', '答1', 'special', 'llm_generated')
        """
    )
    conn.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type)
        VALUES ('3503190424', 'test-a-2', '問2', '答2', 'special', 'clinic_upload')
        """
    )
    conn.commit()
    conn.close()

    res_a = apply_review_status_migration(db_path_a)
    assert res_a["added"] == ["reviewed_at"]
    assert res_a["repaired_half_state"] is True
    assert res_a["backfilled_pending"] == 1

    conn = sqlite3.connect(str(db_path_a))
    cur = conn.cursor()
    cur.execute("SELECT topic_key, review_status FROM faq_cache ORDER BY topic_key")
    assert cur.fetchall() == [("test-a-1", "pending"), ("test-a-2", "approved")]
    conn.close()

    # 案例 B: 只有 reviewed_at 欄位
    db_path_b = tmp_path / "half_b.db"
    conn = sqlite3.connect(str(db_path_b))
    conn.executescript(OLD_FAQ_CACHE_DDL)
    conn.execute(ALTER_REVIEWED_AT_SQL)
    conn.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type)
        VALUES ('3503190424', 'test-b-1', '問1', '答1', 'special', 'llm_generated')
        """
    )
    conn.commit()
    conn.close()

    res_b = apply_review_status_migration(db_path_b)
    assert res_b["added"] == ["review_status"]
    assert res_b["repaired_half_state"] is True
    assert res_b["backfilled_pending"] == 1

    # 案例 C: 兩欄皆在時，已被醫師核准的 llm 列絕不會被回填覆蓋
    conn = sqlite3.connect(str(db_path_b))
    conn.execute(
        "UPDATE faq_cache SET review_status='approved', reviewed_at=CURRENT_TIMESTAMP WHERE topic_key='test-b-1'"
    )
    conn.commit()
    conn.close()

    res_c = apply_review_status_migration(db_path_b)
    assert res_c["added"] == []
    assert res_c["repaired_half_state"] is False
    assert res_c["backfilled_pending"] == 0

    conn = sqlite3.connect(str(db_path_b))
    cur = conn.cursor()
    cur.execute("SELECT review_status FROM faq_cache WHERE topic_key='test-b-1'")
    assert cur.fetchone()[0] == "approved"
    conn.close()


def test_conftest_isolated_conn_has_review_status(isolated_conn):
    """測試 conftest 提供的 isolated_conn 已包含審核欄位且既有資料全為 approved。"""
    assert has_review_status_column(isolated_conn)
    cur = isolated_conn.cursor()
    cur.execute("SELECT COUNT(*) FROM faq_cache WHERE review_status != 'approved'")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM faq_cache")
    assert cur.fetchone()[0] >= 40


def test_cli_defense_on_prod_db(monkeypatch, tmp_path: Path):
    """測試 CLI 對正式庫之防禦：未帶保護旗標前先於連線阻斷，回傳碼 2。"""
    # 1. 驗證拒絕先於連線：若呼叫 sqlite3.connect 則立即 raise AssertionError
    def fail_connect(*args, **kwargs):
        raise AssertionError("不應在防禦檢查前呼叫 sqlite3.connect！")

    monkeypatch.setattr(sqlite3, "connect", fail_connect)
    exit_code = migrate_main(["--db", str(PROD_DB_PATH)])
    assert exit_code == 2

    # 2. 目標不存在
    non_existent = tmp_path / "no_such_file.db"
    assert migrate_main(["--db", str(non_existent)]) == 2

    # 3. 測試 --dry-run 對複本不修改
    monkeypatch.undo()
    test_db = tmp_path / "cli_test.db"
    conn = sqlite3.connect(str(test_db))
    conn.executescript(OLD_FAQ_CACHE_DDL)
    conn.close()

    assert migrate_main(["--db", str(test_db), "--dry-run"]) == 0
    conn = sqlite3.connect(str(test_db))
    assert not has_review_status_column(conn)
    conn.close()

    # 4. 正常執行對複本
    assert migrate_main(["--db", str(test_db)]) == 0
    conn = sqlite3.connect(str(test_db))
    assert has_review_status_column(conn)
    conn.close()


def test_prod_db_sha256_unmodified():
    """保證正式 clinic.db 之 sha256 絕未在測試過程中受到任何修改。"""
    current_sha256 = _get_sha256(PROD_DB_PATH)
    assert current_sha256 == "c51cc4d039379fe00f70d7864b29a952928233fa6caa6e72954900f4c28c65ad"
