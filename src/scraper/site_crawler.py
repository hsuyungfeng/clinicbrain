"""Phase 38 Step 2：同網域子頁面自動收集與醫療法規清洗（Sitemap + 優先佇列 BFS）。

設計原則：
1. 嚴格同源：僅接受與起始網址相同 hostname 的連結，絕不跨站。
2. 優先探索：療程、服務、衛教、醫師介紹等關鍵路徑先抓（heapq 優先佇列）；黑名單頁面與媒體檔直接略過。
3. 清洗順序固定：純內文去重複行 → opencc 台灣正體（s2twp）→ deep_mask_prices 價格遮蔽。
4. 擷取器可注入（fetcher），測試以假擷取器取代真實瀏覽器，確保單元測試離線可重現。
"""

from __future__ import annotations

import heapq
import itertools
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urldefrag, urljoin, urlparse

from src.ingestion.convert_chinese import to_traditional
from src.scraper.playwright_scraper import DynamicPageResult, fetch_dynamic_page

try:
    from src.api.routes.query import deep_mask_prices
except Exception:  # pragma: no cover — 與 tree_distiller 相同的降級路徑
    from src.query.router import mask_prices as _mask

    def deep_mask_prices(obj):  # type: ignore[no-redef]
        return _mask(obj) if isinstance(obj, str) else obj

# 優先探索關鍵字與權重（路徑或連結文字包含即加權，越高越先抓）
PRIORITY_KEYWORDS: dict[str, int] = {
    "service": 3,
    "treatment": 3,
    "faq": 3,
    "service-detail": 3,
    "服務": 3,
    "療程": 3,
    "衛教": 3,
    "about": 2,
    "doctor": 2,
    "orthopedic": 2,
    "case": 2,
    "關於": 2,
    "醫師": 2,
}

# 黑名單：路徑或連結包含即略過（無關頁面與個資敏感頁）
BLACKLIST_MARKERS: tuple[str, ...] = (
    "privacy", "隱私", "terms", "條款", "career", "recruit", "job", "人才", "招募",
    "login", "logout", "cart", "checkout", "sitemap", "contact", "聯絡",
)

# 不抓取的檔案副檔名（媒體與文件）
BLOCKED_EXTENSIONS: tuple[str, ...] = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp",
    ".mp4", ".mov", ".avi", ".mp3", ".wav",
    ".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".css", ".js", ".json", ".xml",
)

_SENTENCE_SPACE_RE = re.compile(r"[ \t　]+")
_COPYRIGHT_RE = re.compile(r"(©|copyright|版權所有|all rights reserved)", re.IGNORECASE)


@dataclass
class CrawledPage:
    url: str
    depth: int
    priority: int
    text: str


@dataclass
class CrawledSiteResult:
    start_url: str
    pages: list[CrawledPage] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def normalize_url(url: str) -> str:
    """移除片段（#...）並統一小寫主機名稱；路徑與查詢字串保留。"""
    clean, _frag = urldefrag(url.strip())
    parsed = urlparse(clean)
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme.lower()}://{netloc}{path}{query}"


def same_origin(url: str, origin_host: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and parsed.netloc.lower() == origin_host.lower()


def is_blacklisted(url: str) -> bool:
    lowered = url.lower()
    if any(marker in lowered for marker in BLACKLIST_MARKERS):
        return True
    path = urlparse(lowered).path
    return any(path.endswith(ext) for ext in BLOCKED_EXTENSIONS)


def priority_score(url: str, anchor_text: str = "") -> int:
    """依路徑與錨點文字計算探索優先權重；無關鍵字為 0。"""
    haystack = f"{urlparse(url).path.lower()} {anchor_text.lower()}"
    return sum(weight for keyword, weight in PRIORITY_KEYWORDS.items() if keyword in haystack)


def clean_page_text(raw: str) -> str:
    """純內文清洗：去除空白與連續重複行、移除版權行，再做正體轉換與價格遮蔽（順序固定）。"""
    lines: list[str] = []
    previous = None
    for line in raw.splitlines():
        cleaned = _SENTENCE_SPACE_RE.sub(" ", line).strip()
        if len(cleaned) < 2 or _COPYRIGHT_RE.search(cleaned):
            continue
        if cleaned == previous:
            continue
        lines.append(cleaned)
        previous = cleaned
    text = "\n".join(lines)
    text = to_traditional(text)
    masked = deep_mask_prices(text)
    return masked if isinstance(masked, str) else str(masked)


def discover_sitemap_urls(origin: str, *, timeout: float = 10.0) -> list[str]:
    """讀取 {origin}/sitemap.xml 之 <loc>；失敗回傳空清單（站點無 sitemap 屬正常情形）。"""
    try:
        with urllib.request.urlopen(f"{origin.rstrip('/')}/sitemap.xml", timeout=timeout) as resp:  # noqa: S310
            body = resp.read(2_000_000)
        root = ET.fromstring(body)
    except Exception:  # noqa: BLE001
        return []
    urls = []
    for elem in root.iter():
        if elem.tag.endswith("loc") and elem.text:
            urls.append(elem.text.strip())
    return urls


def crawl_clinic_site(
    start_url: str,
    max_pages: int = 8,
    max_depth: int = 2,
    *,
    fetcher: Optional[Callable[[str], DynamicPageResult]] = None,
    sitemap_fetcher: Optional[Callable[[str], list[str]]] = None,
) -> CrawledSiteResult:
    """同源 BFS＋優先佇列收集子頁面，回傳已清洗之頁面文字。

    max_pages 為含起始頁的總抓取上限；max_depth 為起始頁為 0 的最大連結深度。
    單一頁面抓取失敗僅記錄於 errors，不中斷整體探索。
    """
    if max_pages < 1:
        raise ValueError("max_pages 必須 >= 1")
    fetch = fetcher or (lambda u: fetch_dynamic_page(u))
    sitemap = sitemap_fetcher or discover_sitemap_urls

    start = normalize_url(start_url)
    origin_host = urlparse(start).netloc
    origin = f"{urlparse(start).scheme}://{origin_host}"
    result = CrawledSiteResult(start_url=start)

    counter = itertools.count()
    queue: list[tuple[int, int, int, str]] = []  # (-priority, depth, seq, url)
    visited: set[str] = set()

    def enqueue(url: str, depth: int, anchor: str = "") -> None:
        norm = normalize_url(url)
        if norm in visited or not same_origin(norm, origin_host):
            return
        if is_blacklisted(norm):
            result.skipped.append(norm)
            return
        if depth > max_depth:
            return
        heapq.heappush(queue, (-priority_score(norm, anchor), depth, next(counter), norm))

    enqueue(start, 0)
    for loc in sitemap(origin):
        enqueue(loc, 1)

    while queue and len(result.pages) < max_pages:
        neg_prio, depth, _seq, url = heapq.heappop(queue)
        if url in visited:
            continue
        visited.add(url)
        try:
            page = fetch(url)
        except Exception as exc:  # noqa: BLE001 — 單頁失敗不中斷整站探索
            result.errors.append(f"{url}：{type(exc).__name__}")
            continue
        text = clean_page_text(page.inner_text or "")
        if text:
            result.pages.append(CrawledPage(url=url, depth=depth, priority=-neg_prio, text=text))
        if depth < max_depth:
            for href in page.links:
                absolute = urljoin(url, href)
                enqueue(absolute, depth + 1)

    return result
