"""
clinicbrain API 組態管理模組。
支援自環境變數載入，並提供台灣醫療體系之預設值（例如緻妍診所代碼 3503190424）。
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class APIConfig:
    host: str = os.getenv("CLINICBRAIN_HOST", "127.0.0.1")
    port: int = int(os.getenv("CLINICBRAIN_PORT", "8000"))
    default_clinic_id: str = os.getenv("CLINICBRAIN_DEFAULT_CLINIC_ID", "3503190424")
    admin_api_key: Optional[str] = os.getenv("CLINICBRAIN_ADMIN_API_KEY", None)
    # 本機開發旗標：明確關閉管理員認證（預設 False，切勿用於對外服務）
    allow_no_auth: bool = os.getenv("CLINICBRAIN_ALLOW_NO_AUTH", "false").lower() in ("true", "1", "yes")
    db_path: Path = Path(os.getenv("CLINICBRAIN_DB_PATH", str(PROJECT_ROOT / "clinic.db")))
    enable_docs: bool = os.getenv("CLINICBRAIN_ENABLE_DOCS", "true").lower() in ("true", "1", "yes")


config = APIConfig()
