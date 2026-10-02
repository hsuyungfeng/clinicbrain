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


# 收集階段即時量測正式庫雜湊（只讀），供結尾測試比對
_PROD_SHA256_AT_START = _get_sha256(PROD_DB_PATH)


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


def test_extract_column_definition_matches_schema():
    """測試 extract_column_definition 對真實 schema 擷取之結果符合預期。"""
    from scripts.migrate_faq_review_status import extract_column_definition
    schema_text = SCHEMA_PATH.read_text(encoding="utf-8")
    status_def = extract_column_definition(schema_text, "faq_cache", "review_status")
    at_def = extract_column_definition(schema_text, "faq_cache", "reviewed_at")

    assert status_def == "TEXT NOT NULL DEFAULT 'approved' CHECK (review_status IN ('pending', 'approved', 'rejected'))"
    assert at_def == "TIMESTAMP"


def test_extract_column_definition_fail_closed():
    """測試 extract_column_definition 在缺欄位、缺區塊、註解符號非法、括號單引號不平衡時 fail-closed。"""
    from scripts.migrate_faq_review_status import extract_column_definition

    # 1. 缺 table 區塊
    with pytest.raises(RuntimeError, match="無法於 schema 中找到資料表"):
        extract_column_definition("CREATE TABLE other (id INT);", "faq_cache", "review_status")

    # 2. 缺欄位
    dummy_schema = "CREATE TABLE IF NOT EXISTS faq_cache (\n    id INT\n);"
    with pytest.raises(RuntimeError, match="無法於資料表 faq_cache 區塊中找到欄位"):
        extract_column_definition(dummy_schema, "faq_cache", "review_status")

    # 3. 單引號內含 --
    bad_quote = "CREATE TABLE IF NOT EXISTS faq_cache (\n    col1 TEXT DEFAULT '--bad',\n);"
    with pytest.raises(RuntimeError, match="包含註解標記"):
        extract_column_definition(bad_quote, "faq_cache", "col1")

    # 4. 括號不平衡
    bad_paren = "CREATE TABLE IF NOT EXISTS faq_cache (\n    col1 TEXT CHECK (a > 0,\n);"
    with pytest.raises(RuntimeError, match="括號不平衡"):
        extract_column_definition(bad_paren, "faq_cache", "col1")


def test_build_add_column_sql():
    """測試 build_add_column_sql 產生正確之 ALTER TABLE 語法。"""
    from scripts.migrate_faq_review_status import build_add_column_sql
    sql = build_add_column_sql("faq_cache", "reviewed_at", "TIMESTAMP")
    assert sql == "ALTER TABLE faq_cache ADD COLUMN reviewed_at TIMESTAMP"


def test_alter_follows_schema_definition(tmp_path: Path):
    """證明測試：修改 schema 定義時，遷移行為隨之改變。"""
    db1 = tmp_path / "old1.db"
    db2 = tmp_path / "old2.db"
    for db in (db1, db2):
        conn = sqlite3.connect(str(db))
        conn.executescript(OLD_FAQ_CACHE_DDL)
        conn.close()

    orig_schema = SCHEMA_PATH.read_text(encoding="utf-8")
    mod_schema = orig_schema.replace("DEFAULT 'approved' CHECK", "DEFAULT 'pending' CHECK", 1)
    assert mod_schema != orig_schema

    tmp_schema_file = tmp_path / "modified_schema.sql"
    tmp_schema_file.write_text(mod_schema, encoding="utf-8")

    # db1 套用修改後的 schema 複本
    apply_review_status_migration(db1, schema_path=tmp_schema_file)
    conn1 = sqlite3.connect(str(db1))
    cur1 = conn1.cursor()
    cur1.execute("PRAGMA table_info(faq_cache)")
    cols1 = {r[1]: r for r in cur1.fetchall()}
    assert cols1["review_status"][4] == "'pending'"
    conn1.close()

    # db2 套用預設真實 schema
    apply_review_status_migration(db2)
    conn2 = sqlite3.connect(str(db2))
    cur2 = conn2.cursor()
    cur2.execute("PRAGMA table_info(faq_cache)")
    cols2 = {r[1]: r for r in cur2.fetchall()}
    assert cols2["review_status"][4] == "'approved'"
    conn2.close()


def test_unparseable_schema_fails_closed_before_connect(tmp_path: Path, monkeypatch):
    """測試 schema 不可解析時在連線資料庫之前即 fail-closed，目標資料庫零變動。"""
    db = tmp_path / "unparseable_test.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(OLD_FAQ_CACHE_DDL)
    conn.close()

    orig_schema = SCHEMA_PATH.read_text(encoding="utf-8")
    lines = [l for l in orig_schema.splitlines() if not l.strip().startswith("review_status TEXT")]
    bad_schema_text = "\n".join(lines)
    bad_schema_path = tmp_path / "bad_schema.sql"
    bad_schema_path.write_text(bad_schema_text, encoding="utf-8")

    def fail_connect(*args, **kwargs):
        raise AssertionError("不應在 schema 解析失敗前呼叫 sqlite3.connect！")

    monkeypatch.setattr(sqlite3, "connect", fail_connect)

    with pytest.raises(RuntimeError, match="無法於資料表 faq_cache 區塊中找到欄位 review_status"):
        apply_review_status_migration(db, schema_path=bad_schema_path)

    monkeypatch.undo()

    # 檢查目標資料庫未被修改
    conn = sqlite3.connect(str(db))
    assert not has_review_status_column(conn)
    conn.close()


def test_migration_script_has_no_handwritten_column_ddl():
    """去重守門測試：確保遷移腳本原始碼不含手寫欄位定義關鍵字。"""
    script_path = PROJECT_ROOT / "scripts" / "migrate_faq_review_status.py"
    source = script_path.read_text(encoding="utf-8")

    forbidden_tokens = [
        "DEFAULT 'approved'",
        "CHECK (review_status",
        "TIMESTAMP",
    ]
    for token in forbidden_tokens:
        assert token not in source, f"遷移腳本中不得手寫欄位定義關鍵字: {token}"


def test_prod_db_sha256_unmodified():
    """保證正式 clinic.db 在整段測試期間未被修改（與收集階段即時量測值比對，不釘死絕對雜湊）。"""
    assert _get_sha256(PROD_DB_PATH) == _PROD_SHA256_AT_START

