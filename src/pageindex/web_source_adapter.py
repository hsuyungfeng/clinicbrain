"""
Phase 23 網頁擷取與解析模組之適配器。
Plan 24-02 Task 2 (D-09, D-10, D-14, D-15):
- 將 Phase 23 擷取結果 (FetchResult) 與結構化解析 (ExtractedClinicPage) 適配為上傳管線可用資料。
- 嚴格只提取服務項目與營業時間進入文字管線，身分與醫師資訊不進入文字管線。
- 提供行程內單例節流器與 robots 政策。
- 零日誌、零 print，例外不回顯任何機敏資訊。
"""

from dataclasses import dataclass
import socket
from typing import Any, Callable, Optional, Sequence

from ..scraper.extract import ExtractedClinicPage, extract_clinic_page
from ..scraper.fetch import FetchResult, fetch_page
from ..scraper.policy import (
    DomainThrottle,
    RobotsPolicy,
    strip_url_for_storage,
)

__all__ = [
    "fetch_clinic_page",
    "UrlFetchDeps",
    "UrlPageResult",
    "UrlFetchError",
    "build_service_text",
    "optional_missing_fields",
    "get_shared_throttle",
    "get_shared_robots",
]

# 行程內單例節流器與 robots.txt 政策（D-14）
_SHARED_THROTTLE = DomainThrottle(min_interval=5.0)
_SHARED_ROBOTS = RobotsPolicy()


def get_shared_throttle() -> DomainThrottle:
    """取得模組級共用節流器。"""
    return _SHARED_THROTTLE


def get_shared_robots() -> RobotsPolicy:
    """取得模組級共用 robots 政策。"""
    return _SHARED_ROBOTS


@dataclass(frozen=True)
class UrlFetchDeps:
    """網址擷取依賴項結構（D-23 唯一注入點）。"""

    allowlist: dict
    throttle: DomainThrottle
    robots: RobotsPolicy
    user_agent: str
    resolver: Any = socket.getaddrinfo
    http_get: Optional[Callable[..., tuple[int, dict[str, str], bytes]]] = None


@dataclass(frozen=True)
class UrlPageResult:
    """網頁擷取與結構化解析結果。"""

    page: ExtractedClinicPage
    source_url: str  # 原始請求 URL 經 strip_url_for_storage 處理，不採重導向終點
    fetched_at: str  # 取自 FetchResult.fetched_at (ISO 8601 UTC)


class UrlFetchError(Exception):
    """網頁擷取失敗例外。訊息保持為空，reason 記錄失敗代碼。"""

    def __init__(self, reason: str) -> None:
        super().__init__("")
        self.reason = reason


def fetch_clinic_page(
    url: str,
    *,
    deps: UrlFetchDeps,
    pinned_addresses: Optional[Sequence[str]] = None,
) -> UrlPageResult:
    """呼叫 Phase 23 擷取器並解析診所頁面內容（CR-23-1 相容）。"""
    # 原始請求 URL 去除 query / fragment，作為固定溯源 URL
    clean_source_url = strip_url_for_storage(url)

    result: FetchResult = fetch_page(
        url,
        allowlist=deps.allowlist,
        throttle=deps.throttle,
        robots=deps.robots,
        user_agent=deps.user_agent,
        resolver=deps.resolver,
        http_get=deps.http_get,
        pinned_addresses=pinned_addresses,
    )

    if not result.ok:
        raise UrlFetchError(result.reason or "unexpected")

    page = extract_clinic_page(result.html)
    return UrlPageResult(
        page=page,
        source_url=clean_source_url,
        fetched_at=result.fetched_at,
    )


def build_service_text(page: ExtractedClinicPage) -> str:
    """將結構化診所頁面轉為 FAQ 草稿管線可用內文（D-10）。

    僅允許服務項目與營業時間進入文字。
    嚴禁包含 institution_name、address、phone、doctors 任一資訊。
    """
    sections: list[str] = []

    # 1. 營業時間（首段）
    if page.business_hours and page.business_hours.strip():
        sections.append(f"營業時間：{page.business_hours.strip()}")

    # 2. 服務項目（每項一段）
    for s in page.services:
        s_name = s.get("name", "").strip() if isinstance(s, dict) else ""
        s_desc = s.get("description", "").strip() if isinstance(s, dict) else ""
        if not s_name:
            continue

        if s_desc:
            sections.append(f"服務項目：{s_name}\n{s_desc}")
        else:
            sections.append(f"服務項目：{s_name}")

    return "\n\n".join(sections).strip()


def optional_missing_fields(page: ExtractedClinicPage) -> list[str]:
    """回傳非必要欄位中為空者。順序固定為 address, phone, business_hours, doctors。"""
    missing: list[str] = []

    if not page.address or not page.address.strip():
        missing.append("address")

    if not page.phone or not page.phone.strip():
        missing.append("phone")

    if not page.business_hours or not page.business_hours.strip():
        missing.append("business_hours")

    if not page.doctors:
        missing.append("doctors")

    return missing
