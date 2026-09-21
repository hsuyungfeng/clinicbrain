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



@pytest.fixture(scope="session")
def session_db_path(tmp_path_factory) -> Path:
    """Session 層級的資料庫複本（供唯讀查詢與檢索測試使用）。"""
    if not PROD_DB_PATH.exists():
        pytest.fail(f"正式資料庫不存在：{PROD_DB_PATH}，請先執行 seed 腳本建庫。")
    
    temp_dir = tmp_path_factory.mktemp("session_db")
    target_path = temp_dir / "clinic_test.db"
    shutil.copy2(PROD_DB_PATH, target_path)
    return target_path


@pytest.fixture
def conn(session_db_path: Path):
    """唯讀測試連線，連線至 session 資料庫複本。"""
    connection = sqlite3.connect(str(session_db_path))
    yield connection
    connection.close()


@pytest.fixture
def isolated_conn(tmp_path: Path):
    """Function 層級的獨立資料庫複本（供寫入、UPSERT 測試使用，測試後自動銷毀）。"""
    if not PROD_DB_PATH.exists():
        pytest.fail(f"正式資料庫不存在：{PROD_DB_PATH}")
    
    target_path = tmp_path / "clinic_isolated.db"
    shutil.copy2(PROD_DB_PATH, target_path)
    connection = sqlite3.connect(str(target_path))
    yield connection
    connection.close()
