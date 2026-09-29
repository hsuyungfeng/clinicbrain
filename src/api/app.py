"""
FastAPI 應用實例工廠模組。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import config
from .routes.health import router as health_router


def create_app() -> FastAPI:
    """建立並設定 FastAPI 應用程式實例。"""
    app = FastAPI(
        title="clinicbrain API",
        description="緻妍診所 Taiwan PageIndex RAG 系統 HTTP API 服務層",
        version="1.0.0",
        docs_url="/docs" if config.enable_docs else None,
        redoc_url="/redoc" if config.enable_docs else None,
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
