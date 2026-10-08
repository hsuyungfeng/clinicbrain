"""
FastAPI 應用實例工廠模組。
"""

from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import config
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from .routes.admin import router as admin_router
from .routes.cache_stats import router as cache_stats_router
from .routes.general import router as general_router
from .routes.health import router as health_router
from .routes.query import router as query_router
from .routes.soap import router as soap_router
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

    # Web 管理介面安全標頭：禁止內嵌／第三方腳本、禁止被嵌入 iframe、不外洩 Referer
    @app.middleware("http")
    async def _admin_security_headers(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/admin"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
        return response

    # 掛載路由
    app.include_router(health_router)
    app.include_router(query_router)
    app.include_router(sync_router)
    app.include_router(cache_stats_router)
    app.include_router(general_router)
    app.include_router(soap_router)
    app.include_router(admin_router)

    # 掛載靜態資源 (Web 管理介面)
    static_dir = Path(__file__).resolve().parent.parent / "web" / "static"
    if static_dir.exists():
        app.mount("/admin", StaticFiles(directory=str(static_dir), html=True), name="admin")

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
