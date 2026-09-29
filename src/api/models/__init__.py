"""
API 資料模型套件。
"""

from .common import HealthResponse, ErrorResponse
from .query import (
    SearchHitModel,
    ClinicHoursItem,
    QueryRequest,
    QueryResponseModel,
)

__all__ = [
    "HealthResponse",
    "ErrorResponse",
    "SearchHitModel",
    "ClinicHoursItem",
    "QueryRequest",
    "QueryResponseModel",
]
