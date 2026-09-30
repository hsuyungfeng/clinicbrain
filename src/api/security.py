"""
clinicbrain API 安全認證組態檢核模組。
提供單一認證組態檢查邏輯，供啟動腳本與 FastAPI lifespan 共用。
"""

from typing import Any, Optional

ADMIN_KEY_ENV = "CLINICBRAIN_ADMIN_API_KEY"
ALLOW_NO_AUTH_ENV = "CLINICBRAIN_ALLOW_NO_AUTH"


class AuthConfigError(RuntimeError):
    """API 認證組態錯誤（未設定管理員金鑰且未明確開啟本機開發放行模式）。"""
    pass


def is_key_configured(cfg: Optional[Any] = None) -> bool:
    """檢查管理員 API 金鑰是否已有效設定（非 None 且非純空白字串）。"""
    if cfg is None:
        from .config import config as cfg
    return bool((cfg.admin_api_key or "").strip())


def build_refusal_message() -> str:
    """產生未設定金鑰時的繁體中文拒絕啟動說明。"""
    return (
        "【安全防護拒絕啟動】未設定管理員金鑰，拒絕啟動服務！\n"
        f"為確保對外 API 服務安全，必須設定環境變數 {ADMIN_KEY_ENV}。\n"
        "\n"
        "處置方式：\n"
        f"  1. [生產/對外模式] 請先設定環境變數 {ADMIN_KEY_ENV}：\n"
        "     可執行以下指令產生安全隨機金鑰：\n"
        '     python3 -c "import secrets; print(secrets.token_urlsafe(32))"\n'
        f"     export {ADMIN_KEY_ENV}=\"<請自行產生的長隨機字串>\"\n"
        "\n"
        f"  2. [僅限本機開發] 若為本機開發且確需停用認證，請明確加上 --allow-no-auth 旗標，\n"
        f"     或設定環境變數 {ALLOW_NO_AUTH_ENV}=1。\n"
        "     ⚠️ 警告：開發模式下同步端點將完全失去認證保護，切勿用於對外服務！"
    )


def build_dev_warning() -> str:
    """產生本機開發無認證模式下的繁體中文警告訊息。"""
    return (
        "⚠️ 【警告】管理員認證已停用（--allow-no-auth 或 CLINICBRAIN_ALLOW_NO_AUTH=1 生效中）！\n"
        "所有同步端點無需金鑰即可呼叫，切勿用於對外服務！"
    )


def check_auth_config(cfg: Optional[Any] = None) -> str:
    """檢查 API 認證組態狀態。

    回傳：
        - "enforced": 金鑰已設定，強制執行 API Key 認證
        - "dev_no_auth": 未設定金鑰但明確啟用本機開發旗標放行

    拋出：
        - AuthConfigError: 未設定金鑰且未啟用本機開發旗標
    """
    if cfg is None:
        from .config import config as cfg

    if is_key_configured(cfg):
        return "enforced"
    elif cfg.allow_no_auth:
        return "dev_no_auth"
    else:
        raise AuthConfigError(build_refusal_message())
