"""
自然語言查詢與多診所檢索路由模組。
負責封裝 src/query/router.py:handle_query()，支援多診所解析與嚴格二次價格遮蔽。
"""

import sqlite3
from typing import Any, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, status

from ..dependencies import get_read_db
from ..models.query import QueryRequest, QueryResponseModel

try:
    from ...query.router import handle_query, mask_prices
except (ImportError, ValueError):
    from src.query.router import handle_query, mask_prices

router = APIRouter(prefix="/api/v1", tags=["自然語言臨床與健保查詢"])


def deep_mask_prices(obj: Any) -> Any:
    """遞迴對所有巢狀資料結構（字串、字典、串列）執行價格遮蔽。
    這是在 API 序列化回傳前的二次安全防禦層，保證任何深層文字無金額數字洩漏。
    """
    if isinstance(obj, str):
        return mask_prices(obj)
    elif isinstance(obj, dict):
        return {k: deep_mask_prices(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [deep_mask_prices(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(deep_mask_prices(item) for item in obj)
    return obj


def _format_hit(hit) -> dict:
    """將 SearchHit 物件格式化為字典。"""
    return {
        "table": hit.table,
        "row_id": hit.row_id,
        "fields": hit.fields,
    }


def _execute_query(
    conn: sqlite3.Connection,
    query_str: str,
    clinic_id: Optional[str],
    limit: int,
) -> QueryResponseModel:
    """核心查詢執行與二次價格防禦封裝。"""
    try:
        raw_response = handle_query(
            conn=conn,
            query=query_str,
            clinic_id=clinic_id,
            limit=limit,
        )
    except ValueError as e:
        # 捕捉 special 路由缺少 clinic_id 之合規例外，轉換為標準 HTTP 400
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    response_dict = {
        "query": query_str,
        "route": raw_response.route,
        "matched_keywords": raw_response.matched_keywords,
        "clinic_info": raw_response.clinic_info,
        "clinic_hours": raw_response.clinic_hours,
        "page_index_hits": [_format_hit(h) for h in raw_response.page_index_hits],
        "drug_hits": [_format_hit(h) for h in raw_response.drug_hits],
        "service_item_hits": [_format_hit(h) for h in raw_response.service_item_hits],
        "clinic_custom_notes": raw_response.clinic_custom_notes,
        "faq_hits": [_format_hit(h) for h in raw_response.faq_hits],
    }

    # 執行二次價格遮蔽遞迴掃描
    sanitized_dict = deep_mask_prices(response_dict)

    return QueryResponseModel(**sanitized_dict)


@router.post(
    "/query",
    response_model=QueryResponseModel,
    summary="統一自然語言查詢入口 (POST)",
    description=(
        "接收病患或醫護端自然語言問句，由系統自動分流 special/general 路由。"
        "可於 Request Body 提供 clinic_id，或透過 Header 'X-Clinic-ID' 傳遞。"
        "所有輸出結果保證全繁體中文並經由二次價格防禦遮蔽金額。"
    ),
)
def post_query(
    request: QueryRequest,
    x_clinic_id: Optional[str] = Header(None, alias="X-Clinic-ID", description="健保特約醫事機構代碼（Header）"),
    conn: sqlite3.Connection = Depends(get_read_db),
) -> QueryResponseModel:
    # 優先序：Request Body clinic_id > Header X-Clinic-ID > None
    effective_clinic_id = (
        request.clinic_id.strip() if request.clinic_id and request.clinic_id.strip()
        else (x_clinic_id.strip() if x_clinic_id and x_clinic_id.strip() else None)
    )
    return _execute_query(conn, request.query, effective_clinic_id, request.limit)


@router.post(
    "/clinics/{clinic_id}/query",
    response_model=QueryResponseModel,
    summary="特定診所專屬查詢入口 (POST)",
    description="在 URL 路徑中明確綁定 clinic_id，適用於多診所環境下的租戶子入口。",
)
def post_clinic_scoped_query(
    request: QueryRequest,
    clinic_id: str = Path(..., description="台灣健保特約醫事機構代碼（10碼數字，如 3503190424）"),
    conn: sqlite3.Connection = Depends(get_read_db),
) -> QueryResponseModel:
    # URL 路徑參數具備最高優先權
    effective_clinic_id = clinic_id.strip()
    return _execute_query(conn, request.query, effective_clinic_id, request.limit)


@router.get(
    "/query",
    response_model=QueryResponseModel,
    summary="自然語言查詢捷徑 (GET)",
    description="支援以 URL Query String 快速發起查詢，便於瀏覽器端檢驗或偵錯。",
)
def get_query(
    q: str = Query(..., min_length=1, max_length=500, description="自然語言查詢問題"),
    clinic_id: Optional[str] = Query(None, description="健保特約醫事機構代碼（Query Param）"),
    limit: int = Query(10, ge=1, le=50, description="最大檢索筆數"),
    x_clinic_id: Optional[str] = Header(None, alias="X-Clinic-ID", description="健保特約醫事機構代碼（Header）"),
    conn: sqlite3.Connection = Depends(get_read_db),
) -> QueryResponseModel:
    effective_clinic_id = (
        clinic_id.strip() if clinic_id and clinic_id.strip()
        else (x_clinic_id.strip() if x_clinic_id and x_clinic_id.strip() else None)
    )
    return _execute_query(conn, q, effective_clinic_id, limit)
