"""
clinicbrain API 組態管理模組。
支援自環境變數載入。注意：本設定不含預設診所代碼，查詢必須明確帶入 clinic_id（Path/Body 或 Header X-Clinic-ID），避免靜默查到別家診所。
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
    admin_api_key: Optional[str] = os.getenv("CLINICBRAIN_ADMIN_API_KEY", None)
    # 本機開發旗標：明確關閉管理員認證（預設 False，切勿用於對外服務）
    allow_no_auth: bool = os.getenv("CLINICBRAIN_ALLOW_NO_AUTH", "false").lower() in ("true", "1", "yes")
    # 快取統計開關（預設 True；若關閉則不寫入 cache_stats 統計資料）
    cache_stats_enabled: bool = os.getenv("CLINICBRAIN_CACHE_STATS", "true").lower() in ("true", "1", "yes")
    db_path: Path = Path(os.getenv("CLINICBRAIN_DB_PATH", str(PROJECT_ROOT / "clinic.db")))
    enable_docs: bool = os.getenv("CLINICBRAIN_ENABLE_DOCS", "true").lower() in ("true", "1", "yes")


config = APIConfig()
