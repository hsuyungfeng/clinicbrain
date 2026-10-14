"""Phase 23 Task 2：網站素材擷取批次編排器 (runner)。

流程：
1. 擁有權閘門檢查（若有 https 網址，檢查 ownership_confirmation.json）。
2. 寫入模式抓取前探測鎖（try_acquire → release，若已被持有則立即略過，零網路請求）。
3. 先完整抓取所有網址（記憶體暫存，不設頁數上限，逐請求節流）。
4. 寫入模式權威取鎖（持有至寫入完成後釋放）。
5. 統一解析、合規檢查與 FAQ 草稿寫入（失敗隔離，單筆失敗不影響其他筆）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Callable, Optional, Sequence, Union
import urllib.parse

from src.batch import db_lock
from src.scraper.drafts import (
    ScraperDraftError,
    build_faq_drafts,
    write_faq_drafts,
)
from src.scraper.extract import extract_clinic_page
from src.scraper.fetch import (
    FetchResult,
    build_user_agent,
    fetch_page,
)
from src.scraper.policy import (
    DEFAULT_CONTACT_URL,
    DomainThrottle,
    PolicyError,
    RobotsPolicy,
    check_url_allowed,
    load_allowlist,
    strip_url_for_storage,
)
from src.scraper.report import (
    BatchReport,
    UrlOutcome,
    path_hint,
    safe_log_line,
)

logger = logging.getLogger("scraper")

OWNERSHIP_FILE = Path(__file__).resolve().parents[2] / "data" / "scraper" / "ownership_confirmation.json"


def check_ownership_confirmation(ownership_path: Union[str, Path], allowlist: dict) -> None:
    """檢查擁有權確認書面授權檔案（D-C17）。

    若檔案不存在、格式無效、confirmed_by_user 非 True，或 domain 未能完整涵蓋白名單
    所有主機名稱，則於任何網路連線與鎖探測前拒絕。
    """
    path = Path(ownership_path)
    if not path.is_file():
        raise PolicyError("ownership_unconfirmed", f"缺少擁有權確認授權檔: {path}")

    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
    except Exception as e:
        raise PolicyError("ownership_unconfirmed", f"擁有權確認檔 JSON 解析失敗: {e}") from e

    if not isinstance(data, dict):
        raise PolicyError("ownership_unconfirmed", "擁有權確認檔格式無效 (非 JSON 物件)")

    if data.get("confirmed_by_user") is not True:
        raise PolicyError("ownership_unconfirmed", "擁有權未經使用者確認 (confirmed_by_user 非 true)")

    domain = data.get("domain")
    if not isinstance(domain, str) or not domain.strip():
        raise PolicyError("ownership_unconfirmed", "擁有權確認檔缺少有效之 domain 欄位")

    clean_domain = domain.strip().lower()
    by_host = allowlist.get("by_host", {})
    for host in by_host.keys():
        host_lower = host.lower()
        if host_lower != clean_domain and not host_lower.endswith("." + clean_domain):
            raise PolicyError(
                "ownership_unconfirmed",
                f"擁有權確認網域 {clean_domain} 未涵蓋白名單主機 {host}",
            )


@dataclass
class ScrapeOptions:
    """擷取執行選項。"""

    clinic_id: str
    allowlist_path: Union[str, Path]
    ownership_path: Union[str, Path] = field(default_factory=lambda: OWNERSHIP_FILE)
    contact_url: str = DEFAULT_CONTACT_URL
    min_interval: float = 5.0
    timeout: float = 10.0
    max_bytes: int = 2 * 1024 * 1024
    write: bool = False
    db_path: Union[str, Path] = ""
    fixture_dir: Optional[Union[str, Path]] = None
    fixture_map: Optional[dict[str, str]] = None

    def __post_init__(self) -> None:
        cid = (self.clinic_id or "").strip()
        if not re.match(r"^\d{10}$", cid):
            raise ScraperDraftError("bad_clinic_id", f"clinic_id 必須為 10 碼數字代號: {self.clinic_id}")
        self.clinic_id = cid


def _fetch_all(
    urls: list[str],
    *,
    options: ScrapeOptions,
    allowlist: dict,
    throttle: DomainThrottle,
    robots: RobotsPolicy,
    user_agent: str,
    resolver: Optional[Callable] = None,
    http_get: Optional[Callable] = None,
    connector: Optional[Callable] = None,
    ssl_context: Optional[Any] = None,
    now: Optional[float] = None,
    on_event: Optional[Callable[[str], None]] = None,
) -> list[tuple[str, FetchResult]]:
    """依序安全抓取所有網址，先全部讀入記憶體清單，不設頁數上限。"""
    results: list[tuple[str, FetchResult]] = []
    iso_now = datetime.now(timezone.utc).isoformat()

    for url in urls:
        trimmed = url.strip()
        if trimmed.startswith("fixture://"):
            filename = trimmed[len("fixture://"):].split("?")[0].split("#")[0]
            html: Optional[str] = None
            if options.fixture_map and (trimmed in options.fixture_map or filename in options.fixture_map):
                html = options.fixture_map.get(trimmed) or options.fixture_map.get(filename)
            elif options.fixture_dir:
                fpath = Path(options.fixture_dir) / filename
                if fpath.is_file():
                    html = fpath.read_text(encoding="utf-8")

            if html is not None:
                if on_event:
                    on_event("get")
                results.append(
                    (
                        trimmed,
                        FetchResult(
                            ok=True,
                            url=trimmed,
                            final_url=trimmed,
                            status=200,
                            html=html,
                            fetched_at=iso_now,
                        ),
                    )
                )
            else:
                results.append(
                    (
                        trimmed,
                        FetchResult(
                            ok=False,
                            url=trimmed,
                            final_url=trimmed,
                            reason="fixture_not_found",
                            fetched_at=iso_now,
                        ),
                    )
                )
            continue

        # 檢查是否列入白名單（若非白名單，直接標記跳過，不發任何 HTTP 請求）
        try:
            check_url_allowed(trimmed, allowlist)
        except PolicyError as e:
            results.append(
                (
                    trimmed,
                    FetchResult(
                        ok=False,
                        url=trimmed,
                        final_url=trimmed,
                        reason=e.reason,
                        fetched_at=iso_now,
                    ),
                )
            )
            continue

        if on_event:
            on_event("get")

        fetch_res = fetch_page(
            trimmed,
            allowlist=allowlist,
            throttle=throttle,
            robots=robots,
            user_agent=user_agent,
            resolver=resolver,
            http_get=http_get,
            connector=connector,
            ssl_context=ssl_context,
            now=now,
            timeout=options.timeout,
            max_bytes=options.max_bytes,
        )
        results.append((trimmed, fetch_res))

    return results


def _process_one(
    url: str,
    fetch_res: FetchResult,
    *,
    options: ScrapeOptions,
    conn_factory: Optional[Callable[[], sqlite3.Connection]] = None,
    on_event: Optional[Callable[[str], None]] = None,
) -> tuple[UrlOutcome, int, int]:
    """解析單一抓取結果，執行合規檢查與草稿建置/寫入，回傳 (outcome, inserted_or_updated, unchanged)。"""
    if url.startswith("fixture://"):
        host = "fixture"
    else:
        try:
            parsed = urllib.parse.urlsplit(url)
            host = parsed.hostname or ""
        except Exception:
            host = ""

    hint = path_hint(url)
    html_bytes = len(fetch_res.html.encode("utf-8")) if fetch_res.html else 0

    if not fetch_res.ok:
        status = "skipped" if fetch_res.reason == "not_allowlisted" else "failed"
        outcome = UrlOutcome(
            host=host,
            path_hint=hint,
            status=status,
            reason=fetch_res.reason,
            html_bytes=html_bytes,
            url=url,
        )
        return outcome, 0, 0

    # 結構抽取
    page = extract_clinic_page(fetch_res.html)
    doctors_cnt = len(page.doctors)

    if not page.is_usable():
        outcome = UrlOutcome(
            host=host,
            path_hint=hint,
            status="failed",
            reason="schema_drift",
            schema_drift=True,
            doctors_count=doctors_cnt,
            html_bytes=html_bytes,
            url=url,
        )
        return outcome, 0, 0

    # 草稿建置
    try:
        clean_url = strip_url_for_storage(url)
        draft_res = build_faq_drafts(
            page,
            clinic_id=options.clinic_id,
            source_url=clean_url,
            fetched_at=fetch_res.fetched_at,
        )
    except ScraperDraftError as e:
        outcome = UrlOutcome(
            host=host,
            path_hint=hint,
            status="failed",
            reason=e.reason,
            doctors_count=doctors_cnt,
            html_bytes=html_bytes,
            url=url,
        )
        return outcome, 0, 0
    except Exception:
        outcome = UrlOutcome(
            host=host,
            path_hint=hint,
            status="failed",
            reason="unexpected",
            doctors_count=doctors_cnt,
            html_bytes=html_bytes,
            url=url,
        )
        return outcome, 0, 0

    drafts_count = len(draft_res.drafts)
    rejected_count = len(draft_res.rejected)

    if not options.write:
        outcome = UrlOutcome(
            host=host,
            path_hint=hint,
            status="ok",
            drafts_count=drafts_count,
            rejected_count=rejected_count,
            doctors_count=doctors_cnt,
            html_bytes=html_bytes,
            url=url,
        )
        return outcome, 0, 0

    # 寫入模式：獨立交易
    if on_event:
        on_event("write")

    should_close = conn_factory is None
    conn = conn_factory() if conn_factory else sqlite3.connect(str(options.db_path))
    ins, upd, unch = 0, 0, 0
    try:
        ins, upd, unch = write_faq_drafts(conn, draft_res.drafts)
        conn.commit()
        outcome = UrlOutcome(
            host=host,
            path_hint=hint,
            status="ok",
            drafts_count=drafts_count,
            rejected_count=rejected_count,
            doctors_count=doctors_cnt,
            html_bytes=html_bytes,
            url=url,
        )
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        reason_code = getattr(e, "reason", "unexpected")
        outcome = UrlOutcome(
            host=host,
            path_hint=hint,
            status="failed",
            reason=reason_code,
            drafts_count=drafts_count,
            rejected_count=rejected_count,
            doctors_count=doctors_cnt,
            html_bytes=html_bytes,
            url=url,
        )
        return outcome, 0, 0
    finally:
        if should_close:
            conn.close()

    return outcome, ins + upd, unch


def run_scrape_urls(
    urls: list[str],
    *,
    options: ScrapeOptions,
    resolver: Optional[Callable] = None,
    http_get: Optional[Callable] = None,
    connector: Optional[Callable] = None,
    ssl_context: Optional[Any] = None,
    clock: Optional[Callable[[], float]] = None,
    sleep: Optional[Callable[[float], None]] = None,
    conn_factory: Optional[Callable[[], sqlite3.Connection]] = None,
    lock_try: Optional[Callable[[Any], Optional[int]]] = None,
    lock_release: Optional[Callable[[Optional[int]], None]] = None,
    on_event: Optional[Callable[[str], None]] = None,
) -> BatchReport:
    """執行批次網址擷取核心函式。"""
    started_at = datetime.now(timezone.utc).isoformat()
    effective_lock_try = lock_try or db_lock.try_acquire
    effective_lock_release = lock_release or db_lock.release

    allowlist = load_allowlist(options.allowlist_path)
    throttle = DomainThrottle(
        min_interval=options.min_interval,
        clock=clock or time.monotonic,
        sleep=sleep or time.sleep,
    )
    robots = RobotsPolicy()
    user_agent = build_user_agent(options.contact_url)

    # 1. 擁有權確認閘門（若存在 https 網址，於任何網路與探測前檢驗）
    has_https = any(u.strip().lower().startswith("https://") for u in urls)
    if has_https:
        check_ownership_confirmation(options.ownership_path, allowlist)

    # 2. 寫入模式抓取前探測鎖（D-C18）
    if options.write:
        probe_fd = effective_lock_try(options.db_path)
        if probe_fd is None:
            finished_at = datetime.now(timezone.utc).isoformat()
            return BatchReport(
                started_at=started_at,
                finished_at=finished_at,
                status="skipped_locked",
                fetched_count=0,
            )
        effective_lock_release(probe_fd)
        if on_event:
            on_event("probe")

    # 3. 第一階段：完整抓取所有網址至記憶體
    fetch_results = _fetch_all(
        urls,
        options=options,
        allowlist=allowlist,
        throttle=throttle,
        robots=robots,
        user_agent=user_agent,
        resolver=resolver,
        http_get=http_get,
        connector=connector,
        ssl_context=ssl_context,
        now=clock() if clock else None,
        on_event=on_event,
    )

    actual_fetched = sum(1 for _, r in fetch_results if r.html)

    # 4. 第二階段：寫入模式權威取鎖
    auth_fd: Optional[int] = None
    if options.write:
        auth_fd = effective_lock_try(options.db_path)
        if auth_fd is None:
            finished_at = datetime.now(timezone.utc).isoformat()
            return BatchReport(
                started_at=started_at,
                finished_at=finished_at,
                status="skipped_locked",
                fetched_count=actual_fetched,
            )

    outcomes: list[UrlOutcome] = []
    total_written = 0
    total_unchanged = 0

    try:
        # 5. 統一解析、抽取與草稿處理
        for url, fetch_res in fetch_results:
            outcome, written, unch = _process_one(
                url,
                fetch_res,
                options=options,
                conn_factory=conn_factory,
                on_event=on_event,
            )
            outcomes.append(outcome)
            total_written += written
            total_unchanged += unch
            safe_log_line(outcome)
    finally:
        if auth_fd is not None:
            effective_lock_release(auth_fd)

    finished_at = datetime.now(timezone.utc).isoformat()
    return BatchReport(
        outcomes=outcomes,
        started_at=started_at,
        finished_at=finished_at,
        status="ok",
        drafts_written=total_written,
        unchanged=total_unchanged,
        fetched_count=actual_fetched,
    )


def scrape_one_url(
    url: str,
    *,
    options: ScrapeOptions,
    conn_factory: Optional[Callable[[], sqlite3.Connection]] = None,
    allowlist: Optional[dict] = None,
    throttle: Optional[DomainThrottle] = None,
    robots: Optional[RobotsPolicy] = None,
    **fetch_kwargs,
) -> UrlOutcome:
    """單一網址擷取便利函式。"""
    report = run_scrape_urls([url], options=options, conn_factory=conn_factory, **fetch_kwargs)
    if report.outcomes:
        return report.outcomes[0]
    return UrlOutcome(status="failed", reason="no_outcome", url=url)
