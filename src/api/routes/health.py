"""
系統健康檢查與監控路由。
"""

import sqlite3
from typing import Dict
from fastapi import APIRouter, Depends
from ..dependencies import get_read_db
from ..models.common import HealthResponse

try:
    from ...pageindex.llm_client import check_llm_health, LocalLLMUnavailableError
except (ImportError, ValueError):
    from src.pageindex.llm_client import check_llm_health, LocalLLMUnavailableError

router = APIRouter(tags=["系統健康與狀態"])

_MONITORED_TABLES = (
    "drugs",
    "service_items",
    "page_index_trees",
    "faq_cache",
    "clinic_info",
    "clinic_hours",
    "clinic_custom_notes",
)


def _get_table_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    """統計各資料表筆數，若資料表不存在則記錄為 0。"""
    counts = {}
    cursor = conn.cursor()
    for table in _MONITORED_TABLES:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            row = cursor.fetchone()
            counts[table] = row[0] if row else 0
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            counts[table] = 0
    return counts


@router.get("/health", response_model=HealthResponse, summary="取得系統健康與資料表狀態")
def get_health(conn: sqlite3.Connection = Depends(get_read_db)) -> HealthResponse:
    """即時回報 SQLite 連線狀況、各核心資料表筆數與本地 LLM (llama-server) 存活狀態。"""
    database_connected = False
    tables_count = {}
    try:
        tables_count = _get_table_counts(conn)
        database_connected = True
    except Exception:
        database_connected = False

    llm_available = False
    llm_model = None
    try:
        model_id = check_llm_health(timeout=2)
        llm_available = True
        llm_model = model_id
    except (LocalLLMUnavailableError, Exception):
        llm_available = False
        llm_model = None

    if not database_connected:
        status_str = "error"
    elif not llm_available:
        status_str = "degraded"
    else:
        status_str = "ok"

    return HealthResponse(
        status=status_str,
        database_connected=database_connected,
        tables_count=tables_count,
        llm_available=llm_available,
        llm_model=llm_model,
        version="1.0.0",
    )
