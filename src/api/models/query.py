"""
自然語言查詢與檢索相關 Pydantic 模型。
"""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class SearchHitModel(BaseModel):
    """檢索命中項目模型。"""
    table: str = Field(..., description="來源資料表名稱（如 drugs, service_items, page_index_trees, faq_cache）")
    row_id: Any = Field(..., description="資料表 row_id 或主鍵代碼（例如 int 或字串代碼）")
    fields: Dict[str, Any] = Field(default_factory=dict, description="命中之結構化欄位內容")


class ClinicHoursItem(BaseModel):
    """門診時間表項目模型。"""
    day_of_week: str = Field(..., description="星期名稱（例如：星期一）")
    morning_start: Optional[str] = Field(None, description="早診開始時間（例如：09:00）")
    morning_end: Optional[str] = Field(None, description="早診結束時間（例如：12:00）")
    afternoon_start: Optional[str] = Field(None, description="午診開始時間（例如：13:30）")
    afternoon_end: Optional[str] = Field(None, description="午診結束時間（例如：17:30）")
    evening_start: Optional[str] = Field(None, description="晚診開始時間")
    evening_end: Optional[str] = Field(None, description="晚診結束時間")
    is_open: bool = Field(True, description="當日是否有看診")


class QueryRequest(BaseModel):
    """自然語言查詢請求模型。"""
    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="自然語言查詢問題（例如：'請問音波拉提術後要怎麼照顧？' 或 '普拿疼有健保給付嗎？'）",
        examples=["音波拉提術後保養", "乙醯胺酚"],
    )
    clinic_id: Optional[str] = Field(
        None,
        description="台灣健保特約醫事機構代碼（10碼數字，例如：'3503190424'）。若未提供亦可從 Header X-Clinic-ID 解析。",
        examples=["3503190424"],
    )
    limit: int = Field(
        10,
        ge=1,
        le=50,
        description="最大檢索命中筆數（預設 10，範圍 1~50）",
    )


class QueryResponseModel(BaseModel):
    """自然語言查詢結構化回應模型。"""
    query: str = Field(..., description="使用者輸入之原始查詢問句")
    route: str = Field(
        ...,
        description="語意路由分類：'special' (特化療程/診所資訊) 或 'general' (健保通用藥品/服務項目)",
    )
    matched_keywords: List[str] = Field(default_factory=list, description="路由偵測命中之關鍵字列表")
    clinic_info: Optional[Dict[str, Any]] = Field(None, description="診所基本營運資訊（僅在 special 路由且涉及營運時出現）")
    clinic_hours: List[Dict[str, Any]] = Field(default_factory=list, description="診所門診時間表")
    page_index_hits: List[SearchHitModel] = Field(default_factory=list, description="PageIndex 臨床決策樹命中結果")
    drug_hits: List[SearchHitModel] = Field(default_factory=list, description="健保藥品檢索命中結果（含 OTC 本地化名稱）")
    service_item_hits: List[SearchHitModel] = Field(default_factory=list, description="健保醫療服務給付項目命中結果")
    clinic_custom_notes: Dict[str, str] = Field(default_factory=dict, description="診所自訂注意事項備註（已價格遮蔽）")
    faq_hits: List[SearchHitModel] = Field(default_factory=list, description="常見問答 FAQ 快取檢索命中結果")
    source: Literal["cache", "pageindex", "llm"] = Field(
        "pageindex",
        description="答案來源出處：'cache'（高信心 FAQ 原文短路）、'pageindex'（臨床推理樹與全文檢索彙整）、'llm'（預留給未來 LLM 合成生成，現行不出現）",
    )
    cache_answer: Optional[str] = Field(
        None,
        description="當 source 為 'cache' 時的 FAQ 原文答案（已完成價格遮蔽），其餘情況為 null",
    )
