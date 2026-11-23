"""Phase 54-01: 白名單採集器與提案資料表測試。"""

from __future__ import annotations

import sqlite3

import httpx

from src.refresh.schema import ensure_refresh_tables
from src.refresh.sources import (
    fetch_pubmed_evidence,
    is_allowed_medical_url,
    parse_rss_feed,
)


def test_whitelist_strict_subdomain_and_ssrf_bounds() -> None:
    # 合法白名單（含子網域）
    assert is_allowed_medical_url("https://www.cdc.gov.tw/RSS/RssXml/Emerald/1") is True
    assert is_allowed_medical_url("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi") is True
    # 拒絕 HTTP、非 443 埠、內網 IP、前綴/後綴繞過網域
    assert is_allowed_medical_url("http://www.cdc.gov.tw/news") is False
    assert is_allowed_medical_url("https://www.cdc.gov.tw:8443/news") is False
    assert is_allowed_medical_url("https://127.0.0.1/admin") is False
    assert is_allowed_medical_url("https://cdc.gov.tw.evil.com/phish") is False
    assert is_allowed_medical_url("https://xcdc.gov.tw/phish") is False


def test_ensure_refresh_tables_idempotent_and_unique_pending() -> None:
    conn = sqlite3.connect(":memory:")
    ensure_refresh_tables(conn)
    ensure_refresh_tables(conn)
    conn.execute(
        "INSERT INTO knowledge_refresh_proposals "
        "(target_type, target_key, title, source_url, source_domain, evidence_summary, diff_summary, current_snapshot, proposed_json) "
        "VALUES ('faq', '12', '測試', 'https://www.cdc.gov.tw/a', 'www.cdc.gov.tw', 'ev', 'diff', '{}', '{}')"
    )
    # 同一筆 pending 不可重複寫入
    try:
        conn.execute(
            "INSERT INTO knowledge_refresh_proposals "
            "(target_type, target_key, title, source_url, source_domain, evidence_summary, diff_summary, current_snapshot, proposed_json) "
            "VALUES ('faq', '12', '測試', 'https://www.cdc.gov.tw/b', 'www.cdc.gov.tw', 'ev', 'diff', '{}', '{}')"
        )
        assert False, "應觸發部分唯一索引阻擋重複 pending 提案"
    except sqlite3.IntegrityError:
        pass


def test_fetch_pubmed_and_rss_parsing() -> None:
    sample_xml = """<?xml version="1.0"?>
    <PubmedArticleSet>
      <PubmedArticle>
        <MedlineCitation>
          <PMID>39999999</PMID>
          <Article>
            <Journal><JournalIssue><PubDate><Year>2026</Year><Month>Oct</Month></PubDate></JournalIssue></Journal>
            <ArticleTitle>Updated colonic diverticulitis guideline.</ArticleTitle>
            <Abstract><AbstractText>Seeds and nuts do not increase risk.</AbstractText></Abstract>
          </Article>
        </MedlineCitation>
      </PubmedArticle>
    </PubmedArticleSet>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if "esearch.fcgi" in str(request.url):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["39999999"]}})
        return httpx.Response(200, text=sample_xml)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    evs = fetch_pubmed_evidence("diverticulitis", client=client, check_dns=False)
    assert len(evs) == 1
    assert evs[0].domain == "pubmed.ncbi.nlm.nih.gov"
    assert "Seeds and nuts" in evs[0].snippet

    rss_xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item><title>疾管署最新流感公費疫苗指引</title><link>https://www.cdc.gov.tw/Bulletin/Detail/123</link><pubDate>2026-11-19</pubDate></item>
      <item><title>外部農場</title><link>https://xcdc.gov.tw/spam</link></item>
    </channel></rss>"""
    rss_items = parse_rss_feed(rss_xml, "https://www.cdc.gov.tw/RSS")
    assert len(rss_items) == 1
    assert rss_items[0].title == "疾管署最新流感公費疫苗指引"
