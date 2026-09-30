"""
FastAPI 應用實例工廠模組。
"""

from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import config
from .routes.health import router as health_router
from .routes.query import router as query_router
from .routes.sync import router as sync_router
from .security import build_dev_warning, check_auth_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理：啟動時檢查 API 認證組態。"""
    mode = check_auth_config()
    if mode == "dev_no_auth":
        logging.getLogger("uvicorn.error").warning(build_dev_warning())
    yield


def create_app() -> FastAPI:
    """建立並設定 FastAPI 應用程式實例。"""
    app = FastAPI(
        title="clinicbrain API",
        description="緻妍診所 Taiwan PageIndex RAG 系統 HTTP API 服務層",
        version="1.0.0",
        docs_url="/docs" if config.enable_docs else None,
        redoc_url="/redoc" if config.enable_docs else None,
        lifespan=lifespan,
    )

    # 跨來源資源共享 (CORS) 設定
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 掛載路由
    app.include_router(health_router)
    app.include_router(query_router)
    app.include_router(sync_router)

    @app.get("/", tags=["根端點"], summary="服務根端點資訊")
    def root():
        """提供服務基本資訊與健康狀態捷徑。"""
        return {
            "service": "clinicbrain",
            "name": "緻妍診所 Taiwan PageIndex RAG 系統",
            "version": "1.0.0",
            "status": "running",
            "docs": "/docs" if config.enable_docs else None,
        }

    return app


app = create_app()
