"""
Phase 29 Task 1: 視覺解說卡資料表結構遷移與單一來源驗證測試。
"""

import sqlite3
import subprocess
import sys
from pathlib import Path
import pytest

from scripts.migrate_cache_stats import extract_cache_stats_ddl
from scripts.migrate_soap_schema import extract_soap_ddl
import tests.conftest as conftest_module

# 待實作之遷移模組
try:
    from scripts.migrate_visual_assets import (
        extract_visual_ddl,
        apply_visual_schema,
        main as migrate_main,
        PROD_DB_PATH,
        SCHEMA_PATH,
    )
except ImportError:
    # 測試先寫（RED 階段）
    extract_visual_ddl = None
    apply_visual_schema = None
    migrate_main = None
    PROD_DB_PATH = Path("clinic.db")
    SCHEMA_PATH = Path("src/db/clinic_schema.sql")


def test_import_migrate_visual_assets():
    """驗證 migrate_visual_assets 模組存在且可匯入。"""
    assert extract_visual_ddl is not None, "scripts/migrate_visual_assets.py 必須定義 extract_visual_ddl"
    assert apply_visual_schema is not None, "scripts/migrate_visual_assets.py 必須定義 apply_visual_schema"
    assert migrate_main is not None, "scripts/migrate_visual_assets.py 必須定義 main"


def test_schema_location_and_old_migrations_regression():
    """回歸測試：既有遷移與 conftest 擷取 DDL 絕不包含 visual_ 表。"""
    schema_text = SCHEMA_PATH.read_text(encoding="utf-8")

    # 1. extract_cache_stats_ddl 不含 visual_
    cache_ddl = extract_cache_stats_ddl(schema_text)
    assert "visual_assets" not in cache_ddl
    assert "visual_stats" not in cache_ddl

    # 2. extract_soap_ddl 不含 visual_
    soap_ddl = extract_soap_ddl(schema_text)
    assert "visual_assets" not in soap_ddl
    assert "visual_stats" not in soap_ddl

    # 3. conftest 的 faq_cache 擷取範圍不含 visual_
    start_marker = "CREATE TABLE IF NOT EXISTS faq_cache"
    end_marker = "-- ========================================\n-- Sample Data"
    start_pos = schema_text.find(start_marker)
    end_pos = schema_text.find(end_marker)
    faq_ddl = schema_text[start_pos:end_pos]
    assert "visual_assets" not in faq_ddl
    assert "visual_stats" not in faq_ddl


def test_isolated_db_default_has_no_visual_tables(isolated_conn):
    """驗證隔離副本預設不含 visual 表（天然未遷移副本）。"""
    cursor = isolated_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'visual_%'")
    tables = [r[0] for r in cursor.fetchall()]
    assert tables == [], f"隔離副本預設不得含 visual 表，但發現了：{tables}"


def test_extract_visual_ddl():
    """驗證 extract_visual_ddl 擷取出完整 visual_assets 與 visual_stats DDL。"""
    schema_text = SCHEMA_PATH.read_text(encoding="utf-8")
    ddl = extract_visual_ddl(schema_text)

    assert "CREATE TABLE IF NOT EXISTS visual_assets" in ddl
    assert "CREATE TABLE IF NOT EXISTS visual_stats" in ddl
    assert "CREATE INDEX IF NOT EXISTS idx_visual_stats_date" in ddl
    assert "clinic_id" not in ddl.split("visual_assets")[1].split("visual_stats")[0], "visual_assets 不得含 clinic_id"

    # 若缺少起始標記應拋出 RuntimeError
    with pytest.raises(RuntimeError):
        extract_visual_ddl("CREATE TABLE dummy (id INTEGER);")


def test_apply_visual_schema_and_idempotence(isolated_db_path):
    """驗證 apply_visual_schema 建立資料表與索引，且重複執行具冪等性。"""
    # 第一次套用
    apply_visual_schema(isolated_db_path)

    conn = sqlite3.connect(str(isolated_db_path))
    cursor = conn.cursor()

    # 驗證 visual_assets
    cursor.execute("PRAGMA table_info(visual_assets)")
    asset_cols = {row[1]: row[2] for row in cursor.fetchall()}
    assert "id" in asset_cols
    assert "topic_key" in asset_cols
    assert "title" in asset_cols
    assert "keywords" in asset_cols
    assert "ir_json" in asset_cols
    assert "source_type" in asset_cols
    assert "review_status" in asset_cols
    assert "reviewed_at" in asset_cols
    assert "content_version" in asset_cols
    assert "metadata" in asset_cols
    assert "created_at" in asset_cols
    assert "updated_at" in asset_cols
    assert "clinic_id" not in asset_cols, "visual_assets 不得含 clinic_id 欄位"

    # 驗證 visual_stats
    cursor.execute("PRAGMA table_info(visual_stats)")
    stats_cols = {row[1]: row[2] for row in cursor.fetchall()}
    assert "id" in stats_cols
    assert "topic_key" in stats_cols
    assert "stat_date" in stats_cols
    assert "event" in stats_cols
    assert "count" in stats_cols

    # 驗證索引
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_visual_stats_date'")
    assert cursor.fetchone() is not None

    conn.close()

    # 第二次套用（冪等性測試）
    apply_visual_schema(isolated_db_path)


def test_visual_tables_constraints(isolated_db_path):
    """驗證 visual_assets 與 visual_stats 的 CHECK 約束與 UNIQUE 約束。"""
    apply_visual_schema(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    cursor = conn.cursor()

    # 1. visual_assets 合法插入
    cursor.execute(
        """
        INSERT INTO visual_assets (topic_key, title, keywords, ir_json, source_type, review_status)
        VALUES ('test-topic', '測試標題', '["關鍵字"]', '{"scenes":[]}', 'manual', 'pending')
        """
    )
    conn.commit()

    # 非法 source_type CHECK
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute(
            """
            INSERT INTO visual_assets (topic_key, title, keywords, ir_json, source_type)
            VALUES ('test-topic-2', '標題', '[]', '{}', 'invalid_source')
            """
        )

    # 非法 review_status CHECK
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute(
            """
            INSERT INTO visual_assets (topic_key, title, keywords, ir_json, source_type, review_status)
            VALUES ('test-topic-3', '標題', '[]', '{}', 'manual', 'published')
            """
        )

    # 2. visual_stats 合法插入
    cursor.execute(
        """
        INSERT INTO visual_stats (topic_key, stat_date, event, count)
        VALUES ('test-topic', '2026-10-19', 'shown', 1)
        """
    )
    conn.commit()

    # 非法 event CHECK
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute(
            """
            INSERT INTO visual_stats (topic_key, stat_date, event, count)
            VALUES ('test-topic', '2026-10-19', 'clicked', 1)
            """
        )

    # UNIQUE(topic_key, stat_date, event)
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute(
            """
            INSERT INTO visual_stats (topic_key, stat_date, event, count)
            VALUES ('test-topic', '2026-10-19', 'shown', 2)
            """
        )

    conn.close()


def test_cli_dry_run(isolated_db_path, capsys):
    """驗證 --dry-run 僅印出 DDL，不修改資料庫。"""
    exit_code = migrate_main(["--db", str(isolated_db_path), "--dry-run"])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "CREATE TABLE IF NOT EXISTS visual_assets" in captured.out

    # 資料庫中應無表
    conn = sqlite3.connect(str(isolated_db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'visual_%'")
    assert cursor.fetchall() == []
    conn.close()


def test_cli_refuse_prod_db_without_confirm_flag(capsys):
    """驗證目標為正式庫且未帶 --confirm-prod-backup 時在連線前以結束碼 2 拒絕。"""
    exit_code = migrate_main(["--db", str(PROD_DB_PATH)])
    assert exit_code == 2

    captured = capsys.readouterr()
    assert "【操作拒絕】目標為正式資料庫" in captured.err


def test_conftest_apply_visual_migration_helper(isolated_db_path):
    """驗證 tests/conftest.py 提供的 apply_visual_migration 輔助函式。"""
    assert hasattr(conftest_module, "apply_visual_migration"), "conftest 必須提供 apply_visual_migration"
    conftest_module.apply_visual_migration(isolated_db_path)

    conn = sqlite3.connect(str(isolated_db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='visual_assets'")
    assert cursor.fetchone() is not None
    conn.close()
