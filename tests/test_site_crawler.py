"""Phase 38 Step 2：同網域爬蟲、優先佇列、黑名單與醫療法規清洗測試（假擷取器，離線）。"""

from __future__ import annotations

import pytest

from src.scraper import site_crawler as sc
from src.scraper.playwright_scraper import DynamicPageResult

HOST = "https://clinic.test"


def _page(url, text="", links=()):
    return DynamicPageResult(url=url, final_url=url, status=200, html="", inner_text=text, links=list(links))


def _fake_site(pages: dict[str, DynamicPageResult]):
    calls: list[str] = []

    def fetch(url):
        calls.append(url)
        if url not in pages:
            raise RuntimeError("404")
        return pages[url]

    return fetch, calls


SITE = {
    HOST + "/": _page(HOST + "/", "首頁 歡迎光臨\n首頁 歡迎光臨\n版權所有 © 2026", links=[
        "/about", "/service/a", "/faq", "/privacy", "/img/logo.jpg", "https://other.test/z", "#top", "mailto:x@y.z",
    ]),
    HOST + "/service/a": _page(HOST + "/service/a", "服務 A 的說明文字，價格 NT$1500 元", links=["/service/a/detail"]),
    HOST + "/faq": _page(HOST + "/faq", "常見問題：這個療程怎麼做？"),
    HOST + "/about": _page(HOST + "/about", "關於我們的團隊"),
    HOST + "/privacy": _page(HOST + "/privacy", "隱私權政策"),
    HOST + "/service/a/detail": _page(HOST + "/service/a/detail", "深層細節內容"),
}


def test_priority_queue_visits_service_and_faq_before_about():
    fetch, calls = _fake_site(SITE)
    result = sc.crawl_clinic_site(HOST + "/", max_pages=10, max_depth=2, fetcher=fetch, sitemap_fetcher=lambda o: [])
    order = [p.url for p in result.pages]
    assert order.index(HOST + "/service/a") < order.index(HOST + "/about")
    assert order.index(HOST + "/faq") < order.index(HOST + "/about")


def test_blacklist_and_cross_origin_are_never_fetched():
    fetch, calls = _fake_site(SITE)
    result = sc.crawl_clinic_site(HOST + "/", max_pages=10, max_depth=2, fetcher=fetch, sitemap_fetcher=lambda o: [])
    assert all("privacy" not in c and ".jpg" not in c and "other.test" not in c for c in calls)
    assert any("privacy" in s for s in result.skipped)


def test_max_pages_and_depth_limits():
    fetch, _ = _fake_site(SITE)
    limited = sc.crawl_clinic_site(HOST + "/", max_pages=2, max_depth=2, fetcher=fetch, sitemap_fetcher=lambda o: [])
    assert len(limited.pages) == 2
    fetch2, calls2 = _fake_site(SITE)
    shallow = sc.crawl_clinic_site(HOST + "/", max_pages=10, max_depth=1, fetcher=fetch2, sitemap_fetcher=lambda o: [])
    assert HOST + "/service/a/detail" not in calls2  # 深度 2 不抓取


def test_sitemap_urls_seed_the_queue():
    fetch, calls = _fake_site({**SITE, HOST + "/treatment-only": _page(HOST + "/treatment-only", "只在 sitemap 的療程頁")})
    result = sc.crawl_clinic_site(HOST + "/", max_pages=10, max_depth=1, fetcher=fetch,
                                  sitemap_fetcher=lambda o: [HOST + "/treatment-only"])
    assert any(p.url.endswith("/treatment-only") for p in result.pages)


def test_single_page_failure_is_recorded_not_fatal():
    site = {**SITE, HOST + "/faq": None}

    def fetch(url):
        if url == HOST + "/faq":
            raise RuntimeError("timeout")
        return SITE[url]

    result = sc.crawl_clinic_site(HOST + "/", max_pages=10, max_depth=2, fetcher=fetch, sitemap_fetcher=lambda o: [])
    assert any("faq" in e for e in result.errors)
    assert result.pages  # 其他頁面仍被收集


def test_cleaning_converts_to_traditional_and_masks_prices():
    text = sc.clean_page_text("这个療程 NT$1500 元\n这个療程 NT$1500 元\n© 2026 版權所有")
    assert "這個" in text
    assert "1500" not in text
    assert "版權" not in text
    assert text.count("這個療程") == 1  # 連續重複行已去除


def test_url_helpers():
    assert sc.normalize_url("HTTPS://Clinic.TEST/a#frag") == "https://clinic.test/a"
    assert sc.same_origin("https://clinic.test/x", "clinic.test")
    assert not sc.same_origin("https://evil.test/x", "clinic.test")
    assert sc.is_blacklisted("https://clinic.test/careers")
    assert sc.is_blacklisted("https://clinic.test/a.pdf")
    assert sc.priority_score("https://clinic.test/service/a") == 3
    assert sc.priority_score("https://clinic.test/random") == 0


def test_invalid_max_pages_rejected():
    with pytest.raises(ValueError):
        sc.crawl_clinic_site(HOST + "/", max_pages=0, fetcher=lambda u: _page(u), sitemap_fetcher=lambda o: [])
