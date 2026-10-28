"""Phase 38 Step 1：Playwright 動態擷取器測試（本機 HTTP 伺服器，零外網）。"""

from __future__ import annotations

import http.server
import threading

import pytest

from src.scraper import playwright_scraper as ps

SPA_PAGE = """<!doctype html><html><head><script src="/analytics.js"></script></head>
<body><div id="root"></div><img src="/big.png">
<script>setTimeout(function () {
  document.getElementById('root').innerText = '感冒衛教 SPA 內容已渲染完成';
}, 300);</script>
<a href="/service/a">療程介紹</a><a href="https://other.example/x">外站</a>
</body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    requested: list[str] = []

    def do_GET(self):  # noqa: N802
        type(self).requested.append(self.path)
        body = SPA_PAGE.encode("utf-8") if self.path in ("/", "/service/a") else b""
        self.send_response(200 if body or self.path == "/analytics.js" else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8" if body else "application/octet-stream")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 靜音測試伺服器日誌
        return


@pytest.fixture()
def local_site():
    _Handler.requested = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base
    server.shutdown()
    server.server_close()


def test_fetch_renders_spa_text_and_same_page_links(local_site):
    result = ps.fetch_dynamic_page(local_site + "/", timeout_ms=15000)
    assert "感冒衛教 SPA 內容已渲染完成" in result.inner_text
    assert "<div id=\"root\">" in result.html
    assert any(link.endswith("/service/a") for link in result.links)
    assert any("other.example" in link for link in result.links)  # 連結本身保留，過濾交由爬蟲


def test_media_and_tracker_requests_are_blocked(local_site):
    result = ps.fetch_dynamic_page(local_site + "/", timeout_ms=15000)
    assert result.blocked_requests >= 2
    assert "/big.png" not in _Handler.requested
    assert "/analytics.js" not in _Handler.requested


def test_rejects_non_http_schemes_without_launching_browser():
    with pytest.raises(ps.ScraperError):
        ps.fetch_dynamic_page("file:///etc/passwd")
    with pytest.raises(ps.ScraperError):
        ps.fetch_dynamic_page("javascript:alert(1)")


def test_navigation_failure_is_wrapped(tmp_path):
    with pytest.raises(ps.ScraperError):
        ps.fetch_dynamic_page("http://127.0.0.1:9/", timeout_ms=3000)


def test_blocking_rules_are_pure_and_correct():
    assert ps.is_blocked_request("https://x.test/a.jpg", "image")
    assert ps.is_blocked_request("https://www.google-analytics.com/g.js", "script")
    assert not ps.is_blocked_request("https://x.test/app.js", "script")
    assert ps.is_allowed_url("https://clinic.test/")
    assert not ps.is_allowed_url("https:///nohost")


def test_stable_length_detection():
    assert not ps.stable_length_reached([])
    assert not ps.stable_length_reached([0, 0])  # 空白頁不視為穩定
    assert not ps.stable_length_reached([10, 20])
    assert ps.stable_length_reached([10, 20, 20])
