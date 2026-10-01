"""一般醫療諮詢 API 資料模型。

定義匿名一般諮詢之請求與回應格式：
- 嚴格字元長度限制（1-300 字），純空白不放行。
- 不提供 clinic_id 欄位，徹底杜絕機構綁定。
- 回應模型不回顯使用者輸入之問句（query），保障匿名與個資隱私。
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


class GeneralQueryRequest(BaseModel):
    """一般醫療諮詢查詢請求。"""

    query: str = Field(
        ...,
        min_length=1,
        max_length=300,
        description="一般醫療衛教諮詢問句（1-300 字元）",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=10,
        description="回傳結果數量上限（1-10，預設 5）",
    )

    @field_validator("query")
    @classmethod
    def validate_query_not_blank(cls, v: str) -> str:
        """檢查問句去除前後空白後不可為空。"""
        stripped = v.strip()
        if not stripped:
            raise ValueError("查詢字串不可為空白")
        return stripped


class GeneralFaqItem(BaseModel):
    """一般醫療問答項目。"""

    topic_key: Optional[str] = Field(None, description="主題識別碼")
    question: str = Field(..., description="衛教問題")
    answer: str = Field(..., description="衛教解答")


class GeneralGuideItem(BaseModel):
    """一般醫療衛教指引項目。"""

    doc_id: str = Field(..., description="指引文件識別碼")
    summary_text: Optional[str] = Field(None, description="指引概述")
    pre_op: Optional[str] = Field(None, description="處置前說明")
    procedure: Optional[str] = Field(None, description="處置過程")
    post_op_short: Optional[str] = Field(None, description="短期照護")
    maintenance: Optional[str] = Field(None, description="長期維持")


class GeneralConsultResponse(BaseModel):
    """一般醫療諮詢回應模型。"""

    status: Literal["red_flag", "answered", "no_match"] = Field(
        ..., description="諮詢判定狀態"
    )
    red_flag_level: Optional[Literal["emergency", "urgent"]] = Field(
        None, description="紅旗緊急等級（僅 status='red_flag' 時有值）"
    )
    message: str = Field(..., description="系統說明或就醫指引訊息")
    disclaimer: str = Field(..., description="法定醫療免責聲明")
    faq_hits: list[GeneralFaqItem] = Field(
        default_factory=list, description="相關一般衛教問答"
    )
    guide_hits: list[GeneralGuideItem] = Field(
        default_factory=list, description="相關一般衛教指引"
    )
