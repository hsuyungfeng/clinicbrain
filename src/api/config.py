"""
clinicbrain API 組態管理模組。
支援自環境變數載入。注意：本設定不含預設診所代碼，查詢必須明確帶入 clinic_id（Path/Body 或 Header X-Clinic-ID），避免靜默查到別家診所。
唯一顯式設定的窄例外為 patient_clinic_id，僅供伺服器固定匿名諮詢診所範圍，無預設值且需存在於 clinic_info 才生效。
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _read_patient_clinic_id() -> Optional[str]:
    val = os.getenv("CLINICBRAIN_PATIENT_CLINIC_ID")
    if not val:
        return None
    s = val.strip()
    return s if s else None


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

    # 匿名病人諮詢（/api/v1/general/consult）固定診所範圍：
    # 顯式設定的窄例外，沒有預設值（無字面值）；由伺服器設定而非請求決定；
    # 需存在於 clinic_info 才生效（Fail-Closed，否則視為未設定）。
    patient_clinic_id: Optional[str] = field(default_factory=_read_patient_clinic_id)


config = APIConfig()
