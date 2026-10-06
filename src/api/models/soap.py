"""
Taiwan Clinic Medical PageIndex RAG System - SOAP 相關 Pydantic 資料模型
Phase 14: 臨床語音與 SOAP 紀錄擷取 (D-04, D-05, D-08)
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SoapRecordInput(BaseModel):
    """外部推播單筆 SOAP 紀錄輸入模型。"""

    external_id: str = Field(..., description="外部系統記錄唯一代碼（例如 doctor-toolbox 產生）")
    patient_id: Optional[str] = Field(None, description="外部病患代號（若提供明文將自動去識別化為 patient_token）")
    patient_token: Optional[str] = Field(None, description="已去識別化之病患代號（優先使用）")
    subjective: Optional[str] = Field(None, description="S: 主訴、病史")
    objective: Optional[str] = Field(None, description="O: 客觀檢查、理學檢驗")
    assessment: Optional[str] = Field(None, description="A: 評估、診斷")
    plan: Optional[str] = Field(None, description="P: 處置、計畫、衛教")
    raw_text: Optional[str] = Field(None, description="推播原始臨床文字")
    transcript: Optional[str] = Field(None, description="語音轉錄原始文字（raw_text 之相容欄位）")
    tags: Optional[List[str]] = Field(default_factory=list, description="處置、科別或 ICD-10 標籤清單")


class SoapIngestRequest(BaseModel):
    """批次接收推播 SOAP 請求模型。"""

    clinic_id: str = Field(..., description="台灣健保特約醫事機構代碼（例如 '3503190424'）")
    records: List[SoapRecordInput] = Field(..., min_length=1, description="SOAP 紀錄清單")


class SoapIngestResponse(BaseModel):
    """推播寫入回應模型。"""

    success: bool = Field(..., description="是否處理成功")
    summary: Dict[str, int] = Field(..., description="寫入統計：inserted, updated, unchanged")
    message: str = Field(..., description="繁體中文處置訊息")
    general_insights_summary: Optional[Dict[str, Any]] = Field(
        None, description="從推播文字中自動萃取之一般醫學疾病、症狀與照護要點統計"
    )


class SoapRecordItem(BaseModel):
    """單筆 SOAP 紀錄調閱與檢索回傳模型。"""

    id: int
    clinic_id: str
    external_id: str
    patient_token: str
    subjective: Optional[str]
    objective: Optional[str]
    assessment: Optional[str]
    plan: Optional[str]
    raw_text: str
    tags: List[str]
    created_at: str
    updated_at: str


class SoapSearchRequest(BaseModel):
    """醫師專用臨床歷史檢索請求模型。"""

    query: str = Field(..., min_length=1, description="臨床關鍵字查詢（支援繁體中文 trigram 檢索）")
    clinic_id: str = Field(..., description="欲查詢之機構代碼（嚴格同診所隔離）")
    tag: Optional[str] = Field(None, description="可選之標籤篩選條件")
    limit: int = Field(default=20, ge=1, le=100, description="最多回傳筆數")


class SoapSearchResponse(BaseModel):
    """醫師專用臨床檢索回應模型。"""

    total: int = Field(..., description="匹配總筆數")
    records: List[SoapRecordItem] = Field(..., description="匹配之 SOAP 紀錄清單")
