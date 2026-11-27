"""Phase 54-01: 權威醫學來源白名單與 SSRF 防護採集器（PubMed E-utilities + 官方 RSS）。"""

from __future__ import annotations

import ipaddress
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List
from urllib.parse import quote_plus, urlparse

import httpx

from src.scraper.policy import is_public_address, resolve_public_addresses, strip_url_for_storage

logger = logging.getLogger(__name__)

ALLOWED_MEDICAL_DOMAINS: tuple[str, ...] = (
    "mohw.gov.tw",
    "cdc.gov.tw",
    "fda.gov.tw",
    "nhi.gov.tw",
    "hpa.gov.tw",
    "eutils.ncbi.nlm.nih.gov",
    "pubmed.ncbi.nlm.nih.gov",
    "ntuh.gov.tw",
    "vghtpe.gov.tw",
    "cgmh.org.tw",
    "cmuh.cmu.edu.tw",
)

OFFICIAL_RSS_FEEDS: tuple[str, ...] = (
    "https://www.mohw.gov.tw/rss-16-1.html",
    "https://www.fda.gov.tw/TC/rssLawMedical.ashx",
    "https://www.fda.gov.tw/TC/rssNews.ashx",
)


@dataclass(frozen=True)
class SourceEvidence:
    title: str
    url: str
    domain: str
    published_at: str
    snippet: str


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def is_allowed_medical_url(url: str, *, check_dns: bool = False) -> bool:
    """Fail-Closed 權威醫學網址白名單：強制 HTTPS/443、精確網域/子網域比對、拒絕內網 IP。"""
    if not url or not isinstance(url, str):
        return False
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() != "https":
        return False
    if parsed.port not in (None, 443):
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or _is_ip_literal(host):
        return False
    if not any(host == d or host.endswith("." + d) for d in ALLOWED_MEDICAL_DOMAINS):
        return False
    if check_dns:
        try:
            addrs = resolve_public_addresses(host)
            if not addrs or not all(is_public_address(ip) for ip in addrs):
                return False
        except Exception:
            return False
    return True


def _safe_get(client: httpx.Client, url: str, *, check_dns: bool = True) -> httpx.Response:
    if not is_allowed_medical_url(url, check_dns=check_dns):
        raise ValueError(f"網址未通過權威醫學白名單或 SSRF 檢核: {url}")
    resp = client.get(url, follow_redirects=False, timeout=15.0)
    if 300 <= resp.status_code < 400:
        raise ValueError(f"白名單採集拒絕重導向 ({resp.status_code}): {url}")
    resp.raise_for_status()
    return resp


def fetch_pubmed_evidence(
    query_en: str,
    *,
    max_results: int = 3,
    client: httpx.Client | None = None,
    check_dns: bool = True,
) -> List[SourceEvidence]:
    """透過 NCBI PubMed E-utilities API 擷取最新實證醫學摘要（免金鑰）。"""
    q = (query_en or "").strip()
    if not q:
        return []

    own_client = client is None
    cli = client or httpx.Client(headers={"User-Agent": "ClinicBrain-MedicalRefresh/1.0"})
    try:
        esearch_url = (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            f"?db=pubmed&term={quote_plus(q)}&retmax={int(max_results)}&sort=pub+date&retmode=json"
        )
        s_resp = _safe_get(cli, esearch_url, check_dns=check_dns)
        pmids = ((s_resp.json().get("esearchresult") or {}).get("idlist")) or []
        if not pmids:
            return []

        efetch_url = (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            f"?db=pubmed&id={','.join(pmids)}&retmode=xml"
        )
        f_resp = _safe_get(cli, efetch_url, check_dns=check_dns)
        return parse_pubmed_xml(f_resp.text)
    finally:
        if own_client:
            cli.close()


def parse_pubmed_xml(xml_text: str) -> List[SourceEvidence]:
    """解析 PubMed `efetch` XML 為結構化 `SourceEvidence`。"""
    root = ET.fromstring(xml_text)
    out: List[SourceEvidence] = []
    for art in root.findall(".//PubmedArticle"):
        pmid = (art.findtext(".//MedlineCitation/PMID") or "").strip()
        title = "".join(art.find(".//ArticleTitle").itertext()).strip() if art.find(".//ArticleTitle") is not None else ""
        abs_parts = ["".join(el.itertext()).strip() for el in art.findall(".//Abstract/AbstractText")]
        snippet = " ".join(p for p in abs_parts if p)[:600]
        year = (art.findtext(".//JournalIssue/PubDate/Year") or "").strip()
        month = (art.findtext(".//JournalIssue/PubDate/Month") or "").strip()
        pub_date = f"{year}-{month}".strip("-") or "recent"
        if not pmid or not title:
            continue
        url = strip_url_for_storage(f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/")
        out.append(
            SourceEvidence(
                title=title,
                url=url,
                domain="pubmed.ncbi.nlm.nih.gov",
                published_at=pub_date,
                snippet=snippet or title,
            )
        )
    return out


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _child_text(elem: ET.Element, *names: str) -> str:
    for child in elem:
        if _local_tag(child.tag) in names:
            return "".join(child.itertext()).strip()
    return ""


def _atom_link(elem: ET.Element) -> str:
    for child in elem:
        if _local_tag(child.tag) == "link":
            href = (child.attrib.get("href") or "").strip()
            if href:
                return href
            txt = "".join(child.itertext()).strip()
            if txt:
                return txt
    return ""


def parse_rss_feed(xml_text: str, base_url: str) -> List[SourceEvidence]:
    """解析官方 RSS/Atom XML（容錯 BOM／前導空白）並嚴格過濾每筆項目連結必須通過白名單。"""
    cleaned = (xml_text or "").lstrip("\ufeff \t\r\n")
    root = ET.fromstring(cleaned)
    out: List[SourceEvidence] = []
    entries = [el for el in root.iter() if _local_tag(el.tag) in ("item", "entry")]
    for item in entries:
        title = _child_text(item, "title")
        link = _atom_link(item)
        pub = _child_text(item, "pubDate", "updated", "published")
        desc = _child_text(item, "description", "summary", "content")[:400]
        target_url = link or base_url
        if not title or not is_allowed_medical_url(target_url, check_dns=False):
            continue
        parsed = urlparse(target_url)
        out.append(
            SourceEvidence(
                title=title,
                url=strip_url_for_storage(target_url),
                domain=(parsed.hostname or "").lower(),
                published_at=pub or "recent",
                snippet=desc or title,
            )
        )
    return out


def fetch_official_feeds(
    feed_urls: tuple[str, ...] = OFFICIAL_RSS_FEEDS,
    *,
    client: httpx.Client | None = None,
    check_dns: bool = True,
) -> List[SourceEvidence]:
    """批次擷取台灣官方醫療機關 RSS 公告（單一來源失敗記錄警告但不中斷整體）。"""
    own_client = client is None
    cli = client or httpx.Client(headers={"User-Agent": "ClinicBrain-MedicalRefresh/1.0"})
    items: List[SourceEvidence] = []
    try:
        for url in feed_urls:
            try:
                resp = _safe_get(cli, url, check_dns=check_dns)
                items.extend(parse_rss_feed(resp.text, url))
            except Exception as exc:
                logger.warning("官方 RSS 擷取失敗 (%s): %s: %s", url, type(exc).__name__, exc)
                continue
        return items
    finally:
        if own_client:
            cli.close()
