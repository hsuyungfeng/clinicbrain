"""
API 路由套件。
"""

from .health import router as health_router
from .query import router as query_router
from .sync import router as sync_router
from .visual import router as visual_router

__all__ = ["health_router", "query_router", "sync_router", "visual_router"]
