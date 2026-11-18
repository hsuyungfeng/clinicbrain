#!/usr/bin/env python3
"""外部一般診所官網增量爬蟲與衛教提煉排程腳本。

從 doctor-toolbox-post/clinics.db 讀取擁有獨立官網的外部一般診所，
以 SHA-256 內容比對略過未變動頁面，僅對新增或改版頁面呼叫本地 LLM 提煉為
general 類別之 FAQ 與 pending 推理樹（source_type='web_upload'），
並共用 src.batch.db_lock 避免與 03:30 run_nightly_batch.py 撞鎖。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import logging
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Optional
import urllib.parse

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.batch import db_lock
from src.ingestion.convert_chinese import to_traditional
from src.scraper.distill_pipeline import distill_site_content
from src.scraper.site_crawler import deep_mask_prices

PROD_DB_PATH = PROJECT_ROOT / "clinic.db"
DEFAULT_SOURCE_DB = Path("/home/hsuyungfeng/DevSoft/doctor-toolbox-post/clinics.db")
MIN_TEXT_CHARS = 200
MAX_HTML_BYTES = 1_500_000

EXCLUDED_HOST_SUFFIXES = (
    "facebook.com", "fb.com", "fb.me", "instagram.com", "line.me",
    "google.com", "goo.gl", "youtube.com", "youtu.be", "twitter.com",
    "x.com", "pixnet.net", "xuite.net", "blogspot.com", "medi-rank.com",
    "clinics.com.tw", "olc.tw", "commonhealth.com.tw", "health.udn.com",
    "edh.tw", "heho.com.tw", "kingnet.com.tw",
)

_PROCEDURE_LINK_KEYWORDS = (
    "療程", "手術", "治療", "衛教", "適應症", "項目", "服務", "原理",
    "service", "treatment", "procedure", "surgery", "faq",
)

logger = logging.getLogger("web_research_batch")


def _is_valid_clinic_url(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if not host or host.startswith("maps."):
        return False
    return not any(host == s or host.endswith("." + s) for s in EXCLUDED_HOST_SUFFIXES)


def _ensure_cache_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS web_research_cache (
            url TEXT PRIMARY KEY,
            clinic_name TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            last_crawled_at TEXT NOT NULL,
            status TEXT NOT NULL,
            faq_inserted INTEGER NOT NULL DEFAULT 0,
            trees_written INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()


def load_candidate_sites(source_db: Path, limit_pool: int = 500) -> list[tuple[str, str]]:
    """自外部 clinics.db 收集有獨立官網的診所 (clinic_name, url)，優先採用已驗證 website_stage。"""
    if not source_db.is_file():
        raise FileNotFoundError(f"找不到來源資料庫: {source_db}")

    src_conn = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True, timeout=15)
    seen_urls: set[str] = set()
    candidates: list[tuple[str, str]] = []

    try:
        # 1. 優先讀取 website_stage 已確認找到官網的診所
        try:
            rows = src_conn.execute(
                """
                SELECT clinic_name, website_url
                FROM website_stage
                WHERE website_status = 'found'
                  AND website_url IS NOT NULL
                  AND website_url != ''
                ORDER BY scraped_at DESC
                LIMIT ?
                """,
                (limit_pool,),
            ).fetchall()
            for name, url in rows:
                if name and url and _is_valid_clinic_url(url) and url not in seen_urls:
                    seen_urls.add(url)
                    candidates.append((name.strip(), url.strip()))
        except sqlite3.OperationalError:
            pass

        # 2. 補充 clinics 主表有官網的診所
        if len(candidates) < limit_pool:
            rows = src_conn.execute(
                """
                SELECT name, website_url
                FROM clinics
                WHERE website_url IS NOT NULL
                  AND website_url != ''
                  AND website_url != 'not_found'
                  AND name NOT LIKE '%衛生所%'
                LIMIT ?
                """,
                (limit_pool * 2,),
            ).fetchall()
            for name, url in rows:
                if name and url and _is_valid_clinic_url(url) and url not in seen_urls:
                    seen_urls.add(url)
                    candidates.append((name.strip(), url.strip()))
                    if len(candidates) >= limit_pool:
                        break
    finally:
        src_conn.close()

    return candidates


def html_to_clean_text(raw_html: str) -> str:
    """將 HTML 轉為純文字並執行繁體轉換與價格遮蔽。"""
    cleaned = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav)[^>]*>.*?</\1>", " ", raw_html)
    cleaned = re.sub(r"(?is)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in cleaned.splitlines()]
    text = "\n".join(ln for ln in lines if ln)
    text = to_traditional(text)
    masked = deep_mask_prices(text)
    return masked if isinstance(masked, str) else str(masked)


def extract_procedure_links(base_url: str, raw_html: str, max_links: int = 2) -> list[str]:
    """從首頁 HTML 挑選同網域內含療程／手術／衛教關鍵字之子頁連結。"""
    base_parsed = urllib.parse.urlparse(base_url)
    base_host = (base_parsed.hostname or "").lower()
    if not base_host:
        return []
    links: list[str] = []
    seen: set[str] = {base_url.rstrip("/")}
    for m in re.finditer(r'(?is)<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw_html):
        href = html.unescape(m.group(1)).strip()
        anchor_text = re.sub(r"(?is)<[^>]+>", " ", m.group(2)).strip().lower()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        abs_url = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(abs_url)
        if parsed.scheme not in ("http", "https"):
            continue
        if (parsed.hostname or "").lower() != base_host:
            continue
        if parsed.path.lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".zip")):
            continue
        norm = abs_url.split("#", 1)[0].rstrip("/")
        if norm in seen:
            continue
        haystack = f"{abs_url.lower()} {anchor_text}"
        if any(kw in haystack for kw in _PROCEDURE_LINK_KEYWORDS):
            seen.add(norm)
            links.append(abs_url.split("#", 1)[0])
            if len(links) >= max_links:
                break
    return links


def fetch_page_text(url: str, timeout: float = 15.0) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ClinicBrainHealthEdBot/1.0)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
    }
    texts: list[str] = []
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()
        ctype = (resp.headers.get("content-type") or "").lower()
        if "text/html" not in ctype and "application/xhtml" not in ctype:
            return ""
        raw_home = resp.text[:MAX_HTML_BYTES]
        home_text = html_to_clean_text(raw_home)
        if home_text:
            texts.append(home_text)

        for sub_url in extract_procedure_links(str(resp.url), raw_home, max_links=2):
            try:
                sub_resp = client.get(sub_url)
                if sub_resp.status_code == 200:
                    sub_ctype = (sub_resp.headers.get("content-type") or "").lower()
                    if "text/html" in sub_ctype or "application/xhtml" in sub_ctype:
                        sub_text = html_to_clean_text(sub_resp.text[:MAX_HTML_BYTES])
                        if sub_text:
                            texts.append(sub_text)
            except Exception:
                continue
    return "\n\n".join(texts)


def compute_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_batch(
    *,
    db_path: Path,
    source_db: Path,
    limit: int = 10,
    time_budget_seconds: float = 2400.0,
    dry_run: bool = False,
) -> dict[str, int | str]:
    started = time.monotonic()
    candidates = load_candidate_sites(source_db, limit_pool=max(limit * 5, 100))

    stats = {
        "status": "completed",
        "candidates_loaded": len(candidates),
        "processed": 0,
        "skipped_unchanged": 0,
        "skipped_short_or_empty": 0,
        "fetch_errors": 0,
        "distilled": 0,
        "faq_inserted": 0,
        "trees_written": 0,
    }

    if dry_run:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
        try:
            cached = {}
            try:
                cached = dict(conn.execute("SELECT url, content_sha256 FROM web_research_cache").fetchall())
            except sqlite3.OperationalError:
                pass
            stats["cached_urls"] = len(cached)
            stats["would_consider"] = min(limit, len(candidates))
        finally:
            conn.close()
        return stats

    fd = db_lock.try_acquire(db_path)
    if fd is None:
        logger.warning("db_lock 已被其他批次（如 run_nightly_batch）持有，本次略過。")
        stats["status"] = "skipped_locked"
        return stats

    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _ensure_cache_table(conn)
        cached_map = dict(
            conn.execute("SELECT url, content_sha256 FROM web_research_cache").fetchall()
        )
        # 優先處理尚未爬取過的 URL，再處理已爬取過的
        ordered = [c for c in candidates if c[1] not in cached_map] + [
            c for c in candidates if c[1] in cached_map
        ]

        for clinic_name, url in ordered:
            if stats["distilled"] >= limit:
                break
            if time.monotonic() - started >= time_budget_seconds:
                stats["status"] = "budget_exhausted"
                break

            stats["processed"] += 1
            try:
                text = fetch_page_text(url)
            except Exception as exc:
                logger.warning("抓取失敗 %s (%s): %s", clinic_name, url, exc)
                stats["fetch_errors"] += 1
                continue

            if len(text) < MIN_TEXT_CHARS:
                stats["skipped_short_or_empty"] += 1
                continue

            sha = compute_sha256(text)
            if cached_map.get(url) == sha:
                stats["skipped_unchanged"] += 1
                continue

            now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
            res = distill_site_content(
                text,
                clinic_id=None,
                clinic_name=clinic_name,
                conn=conn,
                max_trees=1,
                source_url=url,
                category="general",
            )
            faq_ins = res.faq_written[0] if isinstance(res.faq_written, tuple) else 0
            tree_cnt = len(res.trees_written)

            conn.execute(
                """
                INSERT INTO web_research_cache
                    (url, clinic_name, content_sha256, last_crawled_at, status, faq_inserted, trees_written)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    clinic_name = excluded.clinic_name,
                    content_sha256 = excluded.content_sha256,
                    last_crawled_at = excluded.last_crawled_at,
                    status = excluded.status,
                    faq_inserted = excluded.faq_inserted,
                    trees_written = excluded.trees_written
                """,
                (url, clinic_name, sha, now_iso, "distilled", faq_ins, tree_cnt),
            )
            conn.commit()
            cached_map[url] = sha
            stats["distilled"] += 1
            stats["faq_inserted"] += faq_ins
            stats["trees_written"] += tree_cnt
            logger.info(
                "完成提煉: %s (%s) -> faq_inserted=%d, trees=%d",
                clinic_name,
                url,
                faq_ins,
                tree_cnt,
            )
    finally:
        conn.close()
        db_lock.release(fd)

    return stats


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    p = argparse.ArgumentParser(description="clinicbrain 外部診所官網增量爬蟲與提煉批次")
    p.add_argument("--db", type=str, default=str(PROD_DB_PATH), help="目標 clinic.db 路徑")
    p.add_argument("--source-db", type=str, default=str(DEFAULT_SOURCE_DB), help="外部診所來源 clinics.db")
    p.add_argument("--limit", type=int, default=10, help="單次最多提煉之診所官網數")
    p.add_argument("--time-budget-seconds", type=float, default=2400.0, help="時間預算（秒）")
    p.add_argument("--dry-run", action="store_true", help="預演模式（唯讀）")
    p.add_argument("--allow-prod-db", action="store_true", help="允許寫入正式 clinic.db")
    args = p.parse_args(argv)

    db_path = Path(args.db).resolve()
    if not args.dry_run and db_path == PROD_DB_PATH.resolve() and not args.allow_prod_db:
        print("拒絕寫入正式 clinic.db：請加上 --allow-prod-db 或使用 --dry-run", file=sys.stderr)
        return 2

    stats = run_batch(
        db_path=db_path,
        source_db=Path(args.source_db),
        limit=args.limit,
        time_budget_seconds=args.time_budget_seconds,
        dry_run=args.dry_run,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
