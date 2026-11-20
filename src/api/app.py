"""
FastAPI 應用實例工廠模組。
"""

from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import config
from pathlib import Path
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from .routes.admin import router as admin_router
from .routes.cache_stats import router as cache_stats_router
from .routes.general import router as general_router
from .routes.health import router as health_router
from .routes.query import router as query_router
from .routes.soap import router as soap_router
from .routes.sync import router as sync_router
from .routes.visual import router as visual_router
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
    # 安全防護：禁止 allow_origins=["*"] 與 allow_credentials=True 並存（防止反射憑證漏洞）
    cors_origins = config.cors_origins
    is_wildcard = "*" in cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=not is_wildcard,
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
                "style-src 'self' 'unsafe-inline'; "
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
    app.include_router(visual_router)

    # 掛載靜態資源 (Web 管理介面與 3D 視覺組件)
    static_dir = Path(__file__).resolve().parent.parent / "web" / "static"
    if static_dir.exists():
        app.mount("/admin", StaticFiles(directory=str(static_dir), html=True), name="admin")
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/edu/{topic_key}", tags=["衛教單張"], summary="獨立可分享／可列印衛教單張頁面")
    def edu_share_page(topic_key: str):
        """回傳獨立雙軌衛教單張頁面，由前端向 `/api/v1/visual/edu/{topic_key}` 載入內容。"""
        edu_html = static_dir / "edu.html"
        if not edu_html.exists():
            return HTMLResponse("<h1>衛教單張尚未部署</h1>", status_code=404)
        return FileResponse(path=str(edu_html), media_type="text/html; charset=utf-8")

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
