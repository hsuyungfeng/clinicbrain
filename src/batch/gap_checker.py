"""每日醫療趨勢與一般醫學衛教對話覆蓋率檢查器 (gap_checker)。

結合「診所高頻 ICD-10 疾病」與「每日網路最新醫療討論主題」，盤點 `faq_cache` 與
`page_index_trees` 是否已備妥對應之一般醫學問答（`covered` / `partial` / `uncovered`），
並將缺漏題單透過唯一權威路徑 `faq_writer.upsert_faqs(source_type='llm_generated')`
送入「📝 待審衛教草稿簽核」待審隊列（`review_status='pending'`）。

設計原則：
- Fail-Closed 審核隔離：一律以 `source_type='llm_generated'` 寫入 `pending`，絕不自動核准。
- 單一寫入路徑：嚴格呼叫 `src.pageindex.faq_writer.upsert_faqs`。
- 網路與內容合規：遵守 `src/scraper/policy.py`（HTTPS/443/白名單/SSRF 公網檢核），
  文字強制經 `to_traditional`、`deidentify_text`（或金鑰未設時之基礎遮蔽）與 `deep_mask_prices`。
- FTS5 中文鐵則：3+ 字走 `MATCH`，小於 3 字走 `LIKE ... ESCAPE '\\'`。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Optional, Sequence
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from src.api.routes.query import deep_mask_prices
from src.batch.faq_generator import generate_topic_faqs
from src.batch.patient_prefill_plan import INTENT_TEMPLATES
from src.batch.topic_sources import SeedTopic
from src.ingestion.convert_chinese import to_traditional
from src.ingestion.generate_faq import validate_single_faq
from src.pageindex.faq_writer import upsert_faqs
from src.pageindex.tree_review import visible_tree_sql
from src.query.search import escape_like
from src.scraper.policy import (
    PolicyError,
    check_url_allowed,
    load_allowlist,
    resolve_public_addresses,
)
from src.soap.deid import DeidKeyError, deidentify_text
from src.soap.icd10_stats import get_top_clinic_diseases

_PUNCT_SPACE_RE = re.compile(r"[\s？?！!。，,、；;：:「」『』（）()\[\]{}]+")
_PARTICLE_RE = re.compile(r"[嗎呢吧啊呀喔哦嘛]$")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MAX_FETCH_BYTES = 512 * 1024
_DEFAULT_PLACEHOLDER_ANSWER = (
    "此為系統依高頻診斷碼或近期醫療趨勢預先建立之待審衛教題目，"
    "請由本地模型自動補齊或醫師審核編修後再行發布。"
)


@dataclass
class TrendTopic:
    """每日趨勢或高頻診斷碼推演出的單一衛教主題。"""

    title: str
    topic_key: str
    icd10: Optional[str] = None
    source_name: str = "clinic_icd10"
    source_url: Optional[str] = None
    questions: list[str] = field(default_factory=list)
    clinic_rank: Optional[int] = None


@dataclass
class GapItemReport:
    """單一主題之衛教覆蓋率盤點結果。"""

    topic_key: str
    title: str
    status: str  # "covered" | "partial" | "uncovered"
    existing_questions: list[str] = field(default_factory=list)
    missing_questions: list[str] = field(default_factory=list)
    has_tree: bool = False
    icd10: Optional[str] = None
    clinic_rank: Optional[int] = None
    sources: list[str] = field(default_factory=list)


@dataclass
class GapCheckReport:
    """整體覆蓋率檢查與待審草稿寫入摘要。"""

    checked_at: str
    total_topics: int = 0
    covered: int = 0
    partial: int = 0
    uncovered: int = 0
    inserted_pending: int = 0
    updated_pending: int = 0
    unchanged: int = 0
    dry_run: bool = False
    items: list[GapItemReport] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_url_safety(
    url: str,
    allowlist: Optional[dict[str, Any]] = None,
    *,
    resolver: Optional[Callable[[str], Sequence[str]]] = None,
) -> str:
    """組合 `scraper.policy` 之 HTTPS/白名單檢查與 DNS/SSRF 公網 IP 驗證。"""
    effective_allowlist = allowlist or {"allowed_domains": [], "by_host": {}, "open": True}
    check_url_allowed(url, effective_allowlist)
    normalized = url.strip()
    parsed = urllib.parse.urlsplit(normalized)
    host = parsed.hostname or ""
    resolve_public_addresses(host, resolver=resolver)
    return normalized


def _sanitize_public_text(raw: str) -> str:
    """將外部網頁/趨勢文字轉繁體、去個資並遮蔽價格。"""
    if not raw:
        return ""
    text = _HTML_TAG_RE.sub(" ", raw)
    text = to_traditional(text).strip()
    try:
        text = deidentify_text(text)
    except DeidKeyError:
        text = deep_mask_prices(text)
    return str(deep_mask_prices(text)).strip()


def _default_http_fetcher(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "clinicbrain-trend-checker/1.0 (+https://doctor-toolbox.com)"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        data = resp.read(_MAX_FETCH_BYTES)
    return data.decode("utf-8", errors="replace")


def _slugify_title(title: str) -> str:
    ascii_part = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if ascii_part:
        return f"trend-{ascii_part[:40]}"
    hex_hash = hex(abs(hash(title)))[2:10]
    return f"trend-{hex_hash}"


def _parse_feed_or_html_items(content: str, url: str) -> list[TrendTopic]:
    """解析 RSS/Atom XML 或 HTML 標題為清潔後的 TrendTopic 清單。"""
    stripped = (content or "").lstrip()
    topics: list[TrendTopic] = []

    if stripped.startswith("<") and ("<rss" in stripped[:300].lower() or "<feed" in stripped[:300].lower()):
        try:
            root = ET.fromstring(stripped)
            for item in root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry"):
                title_el = item.find("title")
                if title_el is None:
                    title_el = item.find("{http://www.w3.org/2005/Atom}title")
                raw_title = (title_el.text or "").strip() if title_el is not None else ""
                clean_title = _sanitize_public_text(raw_title)
                if len(clean_title) < 2:
                    continue
                topics.append(
                    TrendTopic(
                        title=clean_title[:40],
                        topic_key=_slugify_title(clean_title),
                        source_name="web_trend_rss",
                        source_url=url,
                    )
                )
        except ET.ParseError:
            pass

    if not topics:
        title_matches = re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", content or "", re.IGNORECASE | re.DOTALL)
        if not title_matches:
            title_matches = re.findall(r"<title[^>]*>(.*?)</title>", content or "", re.IGNORECASE | re.DOTALL)
        for raw_title in title_matches:
            clean_title = _sanitize_public_text(raw_title)
            if len(clean_title) < 2:
                continue
            topics.append(
                TrendTopic(
                    title=clean_title[:40],
                    topic_key=_slugify_title(clean_title),
                    source_name="web_trend_html",
                    source_url=url,
                )
            )
    return topics


def fetch_daily_health_trends(
    urls: Sequence[str] = (),
    *,
    fetcher: Optional[Callable[[str], str]] = None,
    allowlist_path: Optional[Path | str] = None,
    resolver: Optional[Callable[[str], Sequence[str]]] = None,
    max_items: int = 10,
) -> list[TrendTopic]:
    """安全擷取每日醫療討論主題（未提供 URL 時安全回傳空清單）。"""
    if not urls or max_items <= 0:
        return []

    allowlist = load_allowlist(allowlist_path) if allowlist_path else None
    fetch_fn = fetcher or _default_http_fetcher
    collected: list[TrendTopic] = []
    seen_titles: set[str] = set()

    for raw_url in urls:
        safe_url = validate_url_safety(raw_url, allowlist, resolver=resolver)
        body = fetch_fn(safe_url)
        for item in _parse_feed_or_html_items(body, safe_url):
            if item.title in seen_titles:
                continue
            seen_titles.add(item.title)
            collected.append(item)
            if len(collected) >= max_items:
                return collected
    return collected


def _normalize_question(q: str) -> str:
    norm = to_traditional(q or "").strip().lower()
    norm = _PUNCT_SPACE_RE.sub("", norm)
    norm = _PARTICLE_RE.sub("", norm)
    return norm


def _char_overlap_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    set_a, set_b = set(a), set(b)
    return len(set_a & set_b) / max(len(set_a), len(set_b))


def derive_patient_questions(
    title: str,
    *,
    extra_questions: Sequence[str] = (),
) -> list[str]:
    """依疾病名稱展開 5 大標準衛教意圖問題，並合併額外熱搜口語提問。"""
    clean_title = _sanitize_public_text(title)
    if not clean_title:
        return []

    candidates: list[str] = [tpl.format(title=clean_title) for tpl in INTENT_TEMPLATES.values()]
    for q in extra_questions:
        cleaned_q = _sanitize_public_text(q)
        if cleaned_q:
            if not cleaned_q.endswith(("？", "?")):
                cleaned_q = f"{cleaned_q}？"
            candidates.append(cleaned_q)

    deduped: list[str] = []
    seen_norm: set[str] = set()
    for q in candidates:
        ok, _ = validate_single_faq({"question": q, "answer": "請由醫師或藥師評估。"})
        if not ok:
            continue
        nq = _normalize_question(q)
        if nq and nq not in seen_norm:
            seen_norm.add(nq)
            deduped.append(q)
    return deduped


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.cursor().execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _fetch_existing_general_questions(
    conn: sqlite3.Connection,
    topic_key: str,
    title: str,
) -> list[str]:
    if not _table_exists(conn, "faq_cache"):
        return []

    cur = conn.cursor()
    cols = {r[1] for r in cur.execute("PRAGMA table_info(faq_cache)").fetchall()}
    review_clause = "AND review_status IN ('approved', 'pending')" if "review_status" in cols else ""

    rows = cur.execute(
        f"""
        SELECT question
        FROM faq_cache
        WHERE category = 'general' {review_clause}
          AND topic_key = ?
        """,
        (topic_key,),
    ).fetchall()
    questions: list[str] = [r[0] for r in rows if r[0]]

    clean_title = (title or "").strip()
    if len(clean_title) >= 3 and _table_exists(conn, "faq_cache_fts"):
        try:
            fts_rows = cur.execute(
                f"""
                SELECT c.question
                FROM faq_cache_fts f
                JOIN faq_cache c ON f.rowid = c.id
                WHERE faq_cache_fts MATCH ?
                  AND c.category = 'general' {review_clause.replace('review_status', 'c.review_status')}
                LIMIT 50
                """,
                (clean_title,),
            ).fetchall()
            questions.extend(r[0] for r in fts_rows if r[0])
        except sqlite3.OperationalError:
            pass
    elif clean_title:
        like_term = f"%{escape_like(clean_title)}%"
        like_rows = cur.execute(
            f"""
            SELECT question
            FROM faq_cache
            WHERE category = 'general' {review_clause}
              AND question LIKE ? ESCAPE '\\'
            LIMIT 50
            """,
            (like_term,),
        ).fetchall()
        questions.extend(r[0] for r in like_rows if r[0])

    # 去重
    seen: set[str] = set()
    unique: list[str] = []
    for q in questions:
        if q not in seen:
            seen.add(q)
            unique.append(q)
    return unique


def _has_visible_tree(conn: sqlite3.Connection, topic_key: str, title: str) -> bool:
    if not _table_exists(conn, "page_index_trees"):
        return False
    vis = visible_tree_sql(conn)
    cur = conn.cursor()
    like_term = f"%{escape_like(title)}%"
    row = cur.execute(
        f"""
        SELECT 1
        FROM page_index_trees
        WHERE {vis}
          AND (doc_id = ? OR title LIKE ? ESCAPE '\\')
        LIMIT 1
        """,
        (topic_key, like_term),
    ).fetchone()
    return row is not None


def check_topic_coverage(conn: sqlite3.Connection, topic: TrendTopic) -> GapItemReport:
    """盤點單一主題在既有一般醫學 FAQ 與推理樹的覆蓋狀態。"""
    target_questions = topic.questions or derive_patient_questions(topic.title)
    existing_qs = _fetch_existing_general_questions(conn, topic.topic_key, topic.title)
    norm_existing = [_normalize_question(q) for q in existing_qs]
    has_tree = _has_visible_tree(conn, topic.topic_key, topic.title)

    missing: list[str] = []
    for q in target_questions:
        nq = _normalize_question(q)
        matched = any(
            nq == ex or _char_overlap_ratio(nq, ex) >= 0.85
            for ex in norm_existing
        )
        if not matched:
            missing.append(q)

    if not missing:
        status = "covered"
    elif existing_qs or has_tree:
        status = "partial"
    else:
        status = "uncovered"

    sources = [topic.source_name]
    if topic.source_url:
        sources.append(topic.source_url)

    return GapItemReport(
        topic_key=topic.topic_key,
        title=topic.title,
        status=status,
        existing_questions=existing_qs,
        missing_questions=missing,
        has_tree=has_tree,
        icd10=topic.icd10,
        clinic_rank=topic.clinic_rank,
        sources=sources,
    )


def _merge_clinic_and_trend_topics(
    conn: sqlite3.Connection,
    *,
    clinic_id: Optional[str],
    aggregated_icd10: Optional[Sequence[dict[str, Any]]],
    trend_topics: Optional[Sequence[TrendTopic]],
    trend_urls: Sequence[str],
    fetcher: Optional[Callable[[str], str]],
    allowlist_path: Optional[Path | str],
    max_topics: int,
) -> list[TrendTopic]:
    merged: dict[str, TrendTopic] = {}

    if clinic_id or aggregated_icd10:
        diseases = get_top_clinic_diseases(
            conn,
            clinic_id=clinic_id,
            aggregated_counts=aggregated_icd10,
            limit=max_topics,
        )
        for d in diseases:
            title = d["disease_name"]
            tkey = d["topic_key"] or _slugify_title(title)
            qs = derive_patient_questions(title)
            merged[tkey] = TrendTopic(
                title=title,
                topic_key=tkey,
                icd10=d["icd10"],
                source_name="clinic_icd10",
                questions=qs,
                clinic_rank=d["clinic_rank"],
            )

    fetched = list(trend_topics or [])
    if trend_urls:
        fetched.extend(
            fetch_daily_health_trends(
                trend_urls,
                fetcher=fetcher,
                allowlist_path=allowlist_path,
                max_items=max_topics,
            )
        )

    for tr in fetched:
        qs = tr.questions or derive_patient_questions(tr.title)
        if tr.topic_key in merged:
            existing = merged[tr.topic_key]
            existing.questions = derive_patient_questions(
                existing.title, extra_questions=qs
            )
            if tr.source_url and not existing.source_url:
                existing.source_url = tr.source_url
                existing.source_name = f"{existing.source_name}+{tr.source_name}"
        else:
            merged[tr.topic_key] = TrendTopic(
                title=tr.title,
                topic_key=tr.topic_key,
                icd10=tr.icd10,
                source_name=tr.source_name,
                source_url=tr.source_url,
                questions=qs,
                clinic_rank=tr.clinic_rank,
            )

    return list(merged.values())[:max_topics]


def run_gap_check(
    conn: sqlite3.Connection,
    *,
    clinic_id: Optional[str] = None,
    aggregated_icd10: Optional[Sequence[dict[str, Any]]] = None,
    trend_topics: Optional[Sequence[TrendTopic]] = None,
    trend_urls: Sequence[str] = (),
    fetcher: Optional[Callable[[str], str]] = None,
    allowlist_path: Optional[Path | str] = None,
    llm_call: Optional[Callable[[str], str]] = None,
    dry_run: bool = False,
    max_topics: int = 10,
) -> GapCheckReport:
    """執行高頻診斷碼＋每日網路趨勢之覆蓋率檢查，並將缺漏寫入 pending 待審隊列。"""
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report = GapCheckReport(checked_at=checked_at, dry_run=dry_run)

    topics = _merge_clinic_and_trend_topics(
        conn,
        clinic_id=clinic_id,
        aggregated_icd10=aggregated_icd10,
        trend_topics=trend_topics,
        trend_urls=trend_urls,
        fetcher=fetcher,
        allowlist_path=allowlist_path,
        max_topics=max_topics,
    )
    report.total_topics = len(topics)

    pending_rows: list[dict[str, Any]] = []
    for topic in topics:
        item_rep = check_topic_coverage(conn, topic)
        report.items.append(item_rep)
        if item_rep.status == "covered":
            report.covered += 1
            continue
        if item_rep.status == "partial":
            report.partial += 1
        else:
            report.uncovered += 1

        if dry_run or not item_rep.missing_questions:
            continue

        if llm_call is not None:
            seed_topic = SeedTopic(
                topic_key=topic.topic_key,
                title=topic.title,
                category="general",
                clinic_id=None,
                keywords=(),
                always=False,
                tree_doc_id=None,
                questions=tuple(item_rep.missing_questions),
            )
            gen_res = generate_topic_faqs(conn, seed_topic, llm_call)
            for faq in gen_res.valid_faqs:
                faq["metadata"] = json.dumps(
                    {
                        "origin": "daily_icd_trend_gap_check",
                        "icd10": topic.icd10,
                        "clinic_rank": topic.clinic_rank,
                        "trend_source": topic.source_name,
                        "gap_status": item_rep.status,
                        "checked_at": checked_at,
                        "needs_answer": False,
                    },
                    ensure_ascii=False,
                )
                pending_rows.append(faq)
        else:
            for q in item_rep.missing_questions:
                pending_rows.append({
                    "clinic_id": None,
                    "topic_key": topic.topic_key,
                    "question": q,
                    "answer": _DEFAULT_PLACEHOLDER_ANSWER,
                    "category": "general",
                    "metadata": json.dumps(
                        {
                            "origin": "daily_icd_trend_gap_check",
                            "icd10": topic.icd10,
                            "clinic_rank": topic.clinic_rank,
                            "trend_source": topic.source_name,
                            "gap_status": item_rep.status,
                            "checked_at": checked_at,
                            "needs_answer": True,
                        },
                        ensure_ascii=False,
                    ),
                })

    if not dry_run and pending_rows:
        inserted, updated, unchanged = upsert_faqs(
            conn, pending_rows, source_type="llm_generated"
        )
        report.inserted_pending = inserted
        report.updated_pending = updated
        report.unchanged = unchanged

    return report
