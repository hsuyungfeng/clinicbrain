"""
FastAPI 相依注入（Dependencies）模組。
提供資料庫唯讀/寫入連線管理與管理員金鑰檢查。
"""

import sqlite3
from typing import Generator, Optional
from fastapi import Header, HTTPException, status
from .config import config
from .security import is_key_configured


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
    """驗證管理員 API 金鑰。

    採安全預設（Fail-Closed）設計：
    1. 若已設定金鑰，比對 X-API-Key，不符則拋出 401。
    2. 若未設定金鑰但明確啟用 allow_no_auth 本機開發旗標，則放行。
    3. 若未設定金鑰且未啟用開發旗標，拋出 503 服務不可用（拒絕靜默放行）。
    """
    if is_key_configured():
        if not x_api_key or x_api_key != config.admin_api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="管理員認證失敗：無效或未提供 X-API-Key 金鑰",
            )
        return True

    if config.allow_no_auth:
        return True

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="服務未正確設定管理員金鑰：請設定 CLINICBRAIN_ADMIN_API_KEY，或於本機開發時明確開啟 CLINICBRAIN_ALLOW_NO_AUTH=1",
    )
