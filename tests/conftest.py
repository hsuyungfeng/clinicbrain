"""
pytest 共用 fixture 與測試隔離設定。
嚴格規則：測試套件絕不直接操作正式的 clinic.db，以複本進行測試隔離。
"""

import shutil
import sqlite3
import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROD_DB_PATH = PROJECT_ROOT / "clinic.db"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))



def _ensure_faq_cache(db_path: Path):
    """確保測試複本資料庫具備 faq_cache 與其 FTS5 / Triggers 結構。"""
    schema_sql_path = PROJECT_ROOT / "src" / "db" / "clinic_schema.sql"
    if not schema_sql_path.exists():
        return
    sql_text = schema_sql_path.read_text(encoding="utf-8")
    start_marker = "CREATE TABLE IF NOT EXISTS faq_cache"
    end_marker = "-- ========================================\n-- Sample Data"
    start_pos = sql_text.find(start_marker)
    end_pos = sql_text.find(end_marker)
    if start_pos != -1:
        faq_ddl = sql_text[start_pos:end_pos] if end_pos != -1 else sql_text[start_pos:]
        temp_conn = sqlite3.connect(str(db_path))
        temp_conn.executescript(faq_ddl)
        temp_conn.close()

        from scripts.migrate_faq_review_status import apply_review_status_migration
        apply_review_status_migration(db_path)


@pytest.fixture(scope="session")
def session_db_path(tmp_path_factory) -> Path:
    """Session 層級的資料庫複本（供唯讀查詢與檢索測試使用）。"""
    if not PROD_DB_PATH.exists():
        pytest.fail(f"正式資料庫不存在：{PROD_DB_PATH}，請先執行 seed 腳本建庫。")
    
    temp_dir = tmp_path_factory.mktemp("session_db")
    target_path = temp_dir / "clinic_test.db"
    shutil.copy2(PROD_DB_PATH, target_path)
    _ensure_faq_cache(target_path)
    return target_path


@pytest.fixture
def conn(session_db_path: Path):
    """唯讀測試連線，連線至 session 資料庫複本。"""
    connection = sqlite3.connect(str(session_db_path))
    yield connection
    connection.close()


@pytest.fixture
def isolated_db_path(tmp_path: Path) -> Path:
    """Function 層級的獨立資料庫檔案路徑。"""
    if not PROD_DB_PATH.exists():
        pytest.fail(f"正式資料庫不存在：{PROD_DB_PATH}")

    target_path = tmp_path / "clinic_isolated.db"
    shutil.copy2(PROD_DB_PATH, target_path)
    _ensure_faq_cache(target_path)
    return target_path


@pytest.fixture
def isolated_conn(isolated_db_path: Path):
    """Function 層級的獨立資料庫複本連線（供寫入、UPSERT 測試使用，測試後自動銷毀）。"""
    connection = sqlite3.connect(str(isolated_db_path))
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def _default_allow_no_auth(monkeypatch):
    """既有測試預設視為開發模式放行；驗證強制行為的測試須自行覆寫為 False。"""
    from src.api.config import config
    monkeypatch.setattr(config, "allow_no_auth", True)


@pytest.fixture(autouse=True)
def _disable_cache_stats_by_default(monkeypatch):
    """預設關閉統計寫入，避免測試意外寫入任何資料庫；驗證統計行為的測試須自行改回 True 並指向複本資料庫。"""
    from src.api.config import config
    monkeypatch.setattr(config, "cache_stats_enabled", False)
