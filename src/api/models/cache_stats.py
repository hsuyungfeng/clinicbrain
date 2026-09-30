"""
快取統計相關 Pydantic 模型（Phase 07 CACHE-03）。
僅包含聚合計數與系統固定路由關鍵字，保證零個資洩漏。
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class MissKeywordCount(BaseModel):
    """未命中路由關鍵字計數模型。"""
    keyword: str = Field(..., description="命中的固定路由詞表關鍵字（僅限白名單詞彙）")
    count: int = Field(..., ge=0, description="未命中次數累計")


class CacheStatsResponse(BaseModel):
    """快取命中與未命中聚合統計回應模型。"""
    hit: int = Field(..., ge=0, description="快取短路命中總次數")
    miss: int = Field(..., ge=0, description="有資格短路但未命中快取之查詢總次數")
    total: int = Field(..., ge=0, description="有資格短路之查詢總次數 (hit + miss)")
    hit_rate: Optional[float] = Field(None, description="快取短路命中率 (hit / total)，無資料時為 null")
    top_miss_keywords: List[MissKeywordCount] = Field(default_factory=list, description="熱門未命中關鍵字排行（依次數降冪）")
    clinic_id: Optional[str] = Field(None, description="篩選之診所代碼（null 表示不分診所總計）")
    since: Optional[str] = Field(None, description="篩選之起始日期 (YYYY-MM-DD)")
