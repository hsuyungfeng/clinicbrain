"""一般醫療諮詢 API 路由模組。

提供 /api/v1/general/query 匿名對外端點：
- 僅支援 POST 方法，問句不進入 URL。
- 自動掛載存取日誌過濾器，確保問句與呼叫端 IP 不被 uvicorn 記錄。
- 匿名端點：不要求金鑰認證，不綁定特定診所代碼。
- 隱私防禦：自訂 AnonymousRoute 攔截驗證錯誤，回傳固定文字 422，絕不回顯問句或錯誤細節。
"""

import dataclasses
import sqlite3
from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from ..access_log_filter import install_access_log_filter
from ..dependencies import get_read_db
from ..models.general import GeneralConsultResponse, GeneralQueryRequest
from .query import deep_mask_prices
from ...general.consult import consult_general

# 模組載入時自動安裝日誌過濾器（具冪等性）
install_access_log_filter()

INVALID_REQUEST_DETAIL = "請求格式不正確"


class AnonymousRoute(APIRoute):
    """自訂 APIRoute 子類：封裝驗證錯誤以防止使用者輸入反射洩漏。"""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError:
                return JSONResponse({"detail": INVALID_REQUEST_DETAIL}, status_code=422)

        return handler


router = APIRouter(
    prefix="/api/v1/general",
    tags=["一般醫療諮詢（匿名）"],
    route_class=AnonymousRoute,
)


@router.post(
    "/query",
    response_model=GeneralConsultResponse,
    summary="一般醫療衛教諮詢（匿名對外入口）",
    description=(
        "提供公眾匿名進行一般醫療與衛教諮詢之對外入口：\n"
        "- 匿名設計：無須登入或提供金鑰，系統不記錄問句原文或提問歷史。\n"
        "- 安全傳輸：僅接受 POST 請求（問句置於請求主體，不進入 URL 與存取日誌）。\n"
        "- 醫療防禦：自動辨識急重症徵候並提供緊急就醫指示，絕不捏造診斷。\n"
        "- 法定免責：所有回覆皆附帶法定醫療免責宣告，無法取代醫師親自診察。"
    ),
)
def post_general_query(
    request: GeneralQueryRequest,
    conn: sqlite3.Connection = Depends(get_read_db),
) -> GeneralConsultResponse:
    """執行一般諮詢查詢並回傳已清洗結果。"""
    result = consult_general(conn, request.query, request.limit)
    raw_dict = dataclasses.asdict(result)
    clean_dict = deep_mask_prices(raw_dict)
    return GeneralConsultResponse(**clean_dict)
