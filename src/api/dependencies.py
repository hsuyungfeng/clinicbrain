"""
FastAPI 相依注入（Dependencies）模組。
提供資料庫唯讀/寫入連線管理與管理員金鑰檢查。
"""

import sqlite3
from typing import Generator, Optional
from fastapi import Header, HTTPException, status
from .config import config


def get_read_db() -> Generator[sqlite3.Connection, None, None]:
    """取得資料庫唯讀連線。
    強制開啟 PRAGMA query_only = ON，從底層杜絕任何非預期寫入。
    """
    conn = sqlite3.connect(str(config.db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON;")
    try:
        yield conn
    finally:
        conn.close()


def get_write_db() -> Generator[sqlite3.Connection, None, None]:
    """取得資料庫寫入連線（供資料同步與匯入專用）。"""
    conn = sqlite3.connect(str(config.db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
    finally:
        conn.close()


def verify_admin_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="管理員認證金鑰")
) -> bool:
    """驗證管理員 API 金鑰。若環境未設定金鑰則視為開發/本地模式允許通過。"""
    if config.admin_api_key is not None:
        if not x_api_key or x_api_key != config.admin_api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="管理員認證失敗：無效或未提供 X-API-Key 金鑰",
            )
    return True
