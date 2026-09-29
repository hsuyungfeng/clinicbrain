"""
API 資料同步模型模組（Phase 05 TASK-03: Bidirectional Sync Contract）。
定義 doctor-toolbox.com 與 clinicbrain 間之匯出入 Request / Response Schema。
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SyncExportRequest(BaseModel):
    clinic_id: str = Field(..., description="診所代碼，例如 '3503190424'")
    since_version: int = Field(default=0, ge=0, description="增量匯出之起始版本號（含）")
    entities: List[str] = Field(
        default=["trees", "faqs", "notes", "hours"],
        description="欲匯出的實體類別清單，可選: trees, faqs, notes, hours",
    )


class SyncExportResponse(BaseModel):
    clinic_id: str = Field(..., description="診所代碼")
    exported_at: str = Field(..., description="匯出時間（ISO 8601 格式）")
    counts: Dict[str, int] = Field(..., description="各實體匯出筆數統計")
    data: Dict[str, Any] = Field(..., description="匯出之實體資料字典")


class SyncImportRequest(BaseModel):
    clinic_id: str = Field(..., description="診所代碼，例如 '3503190424'")
    data: Dict[str, Any] = Field(..., description="匯入資料字典，可包含 trees, faqs, notes, hours")
    auto_convert_simplified: bool = Field(default=True, description="是否自動將簡體中文轉換為台灣正體中文")


class SyncImportResponse(BaseModel):
    success: bool = Field(..., description="是否匯入成功")
    sync_id: int = Field(..., description="同步紀錄日誌 ID (sync_logs.id)")
    summary: Dict[str, int] = Field(..., description="各類別處理統計（新增、更新、未變等）")
    message: str = Field(..., description="處理結果訊息（繁體中文）")


class SyncLogItem(BaseModel):
    id: int
    clinic_id: Optional[str] = None
    sync_type: str
    direction: str
    status: str
    record_count: int
    payload_summary: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
