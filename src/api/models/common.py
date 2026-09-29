"""
通用 Pydantic 資料模型。
"""

from typing import Dict, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """系統健康檢查回應模型。"""
    status: str = Field("ok", description="系統狀態：'ok' (正常), 'degraded' (部分降級), 'error' (異常)")
    database_connected: bool = Field(..., description="資料庫連線狀態")
    tables_count: Dict[str, int] = Field(default_factory=dict, description="各資料表即時記錄筆數統計")
    llm_available: bool = Field(..., description="本地 LLM 推理引擎是否存活")
    llm_model: Optional[str] = Field(None, description="當前本地 LLM 模型名稱")
    version: str = Field("1.0.0", description="API 服務版本")


class ErrorResponse(BaseModel):
    """標準錯誤回應模型。"""
    detail: str = Field(..., description="錯誤詳細繁體中文說明")
    error_code: Optional[str] = Field(None, description="內部自訂錯誤代碼")
