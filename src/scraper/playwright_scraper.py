"""Phase 38 Step 1：基於 Playwright 的動態頁面擷取器（SPA 友善）。

設計原則：
1. 無頭 Chromium 渲染後才擷取，解決 React／Vue／Webflow 等 SPA 只拿到空殼 HTML 的問題。
2. 阻斷無關資源（圖片、媒體、字型、已知分析追蹤腳本），加速渲染並降低外連風險。
3. 僅接受 http／https；拒絕 file://、data: 等本機或內嵌協定。
4. 純擷取，不寫資料庫、不做價格遮蔽（清洗在 site_crawler 與 distill_pipeline 統一處理）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

# 阻斷的資源類型（不影響文字內容擷取）
BLOCKED_RESOURCE_TYPES: frozenset[str] = frozenset({"image", "media", "font"})

# 已知分析追蹤與廣告網域關鍵字（URL 含任一字串即阻斷）
BLOCKED_URL_MARKERS: tuple[str, ...] = (
    "google-analytics.com",
    "googletagmanager.com",
    "googlesyndication.com",
    "doubleclick.net",
    "facebook.net",
    "connect.facebook",
    "hotjar.com",
    "clarity.ms",
    "analytics.",
    "/analytics.js",
    "tracking",
)

ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})


class ScraperError(Exception):
    """擷取失敗（協定不允許、導覽逾時等）。訊息不含 URL 內容以外之敏感資訊。"""


@dataclass
class DynamicPageResult:
    url: str
    final_url: str
    status: Optional[int]
    html: str
    inner_text: str
    links: list[str] = field(default_factory=list)
    blocked_requests: int = 0
    waited_ms: int = 0


def is_allowed_url(url: str) -> bool:
    """僅允許 http／https 且含主機名稱。"""
    parsed = urlparse(url or "")
    return parsed.scheme in ALLOWED_SCHEMES and bool(parsed.netloc)


def is_blocked_request(url: str, resource_type: str) -> bool:
    """判斷單一網路請求是否應阻斷（資源型別或已知追蹤網域）。"""
    if resource_type in BLOCKED_RESOURCE_TYPES:
        return True
    lowered = (url or "").lower()
    return any(marker in lowered for marker in BLOCKED_URL_MARKERS)


def stable_length_reached(samples: list[int], required: int = 2) -> bool:
    """文字長度穩定判定：最近 required 次取樣相同且非零，視為動態內容已渲染完成。"""
    if len(samples) < required:
        return False
    tail = samples[-required:]
    return tail[0] > 0 and all(x == tail[0] for x in tail)


def _wait_for_render(page: Any, timeout_ms: int) -> int:
    """以文字長度穩定與 networkidle 降級退避等待 SPA 渲染；回傳實際等待毫秒數。"""
    started = time.monotonic()
    deadline = started + timeout_ms / 1000.0
    samples: list[int] = []
    while time.monotonic() < deadline:
        try:
            length = int(page.evaluate("() => (document.body ? document.body.innerText : '').length"))
        except Exception:  # noqa: BLE001 — 導覽中途的執行環境切換屬暫時性，繼續取樣
            length = 0
        samples.append(length)
        if stable_length_reached(samples):
            break
        page.wait_for_timeout(400)
    try:
        page.wait_for_load_state("networkidle", timeout=min(2000, timeout_ms))
    except Exception:  # noqa: BLE001 — networkidle 逾時屬正常降級，不視為失敗
        pass
    return int((time.monotonic() - started) * 1000)


def fetch_dynamic_page(
    url: str,
    timeout_ms: int = 15000,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
) -> DynamicPageResult:
    """以無頭 Chromium 渲染頁面並擷取 HTML、純內文與同頁所有超連結。

    不合法協定拋 ScraperError；導覽失敗同樣以 ScraperError 回報（不回傳半成品）。
    """
    if not is_allowed_url(url):
        raise ScraperError("僅允許 http 或 https 網址")

    from playwright.sync_api import sync_playwright

    blocked = {"count": 0}

    def _route(route: Any) -> None:
        request = route.request
        if is_blocked_request(request.url, request.resource_type):
            blocked["count"] += 1
            route.abort()
        else:
            route.continue_()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=user_agent, locale="zh-TW")
            page = context.new_page()
            page.route("**/*", _route)
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception as exc:  # noqa: BLE001
                raise ScraperError(f"導覽失敗：{type(exc).__name__}") from exc
            waited = _wait_for_render(page, timeout_ms)
            html = page.content()
            inner_text = page.inner_text("body") if page.query_selector("body") else ""
            links = page.eval_on_selector_all(
                "a[href]", "els => els.map(e => e.href)"
            )
            status = response.status if response is not None else None
            final_url = page.url
            context.close()
        finally:
            browser.close()

    return DynamicPageResult(
        url=url,
        final_url=final_url,
        status=status,
        html=html,
        inner_text=inner_text,
        links=[str(x) for x in links if isinstance(x, str)],
        blocked_requests=blocked["count"],
        waited_ms=waited,
    )
