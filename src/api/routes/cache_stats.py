"""
快取統計端點模組（Phase 07 CACHE-03）。
提供管理員查詢快取命中率與熱門未命中關鍵字（需 X-API-Key 認證）。
"""

import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import get_read_db, verify_admin_key
from ..models.cache_stats import CacheStatsResponse

try:
    from ...query.cache_stats import get_cache_stats
except (ImportError, ValueError):
    from src.query.cache_stats import get_cache_stats

router = APIRouter(prefix="/api/v1/cache", tags=["快取統計（匿名聚合）"])


@router.get(
    "/stats",
    response_model=CacheStatsResponse,
    summary="查詢快取命中統計與熱門未命中主題 (GET)",
    description=(
        "提供管理員查詢匿名聚合之快取命中/未命中統計與熱門未命中關鍵字。\n"
        "此端點受管理員金鑰保護（需帶 X-API-Key）。\n"
        "資料僅包含聚合計數與系統固定路由關鍵字，絕不含任何使用者問句全文或個資。"
    ),
)
def get_stats(
    clinic_id: Optional[str] = Query(None, description="篩選特定診所代碼（選填）"),
    since: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="起始統計日期（格式：YYYY-MM-DD）"),
    top_n: int = Query(20, ge=1, le=100, description="回傳熱門未命中關鍵字筆數上限（1~100）"),
    conn: sqlite3.Connection = Depends(get_read_db),
    _auth: bool = Depends(verify_admin_key),
) -> CacheStatsResponse:
    """查詢快取短路命中率與熱門未命中主題統計。"""
    # (a) 先檢查 cache_stats 資料表是否存在
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'cache_stats'")
    if not cursor.fetchone():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="cache_stats 資料表尚未建立：請先備份後執行 python3 scripts/migrate_cache_stats.py --confirm-prod-backup（或於複本資料庫執行）",
        )

    # (b) 執行統計查詢
    norm_clinic_id = (clinic_id.strip() or None) if clinic_id else None
    try:
        result = get_cache_stats(
            conn,
            clinic_id=norm_clinic_id,
            since_date=since,
            top_n=top_n,
        )
    except sqlite3.OperationalError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="cache_stats 查詢失敗：資料表存在但讀取發生資料庫錯誤（可能為暫時性鎖定或資料庫異常），請稍後重試並檢查伺服器日誌",
        )

    # (c) 回傳結構化回應
    return CacheStatsResponse(
        hit=result["hit"],
        miss=result["miss"],
        total=result["total"],
        hit_rate=result["hit_rate"],
        top_miss_keywords=result["top_miss_keywords"],
        clinic_id=norm_clinic_id,
        since=since,
    )
