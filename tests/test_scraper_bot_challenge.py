"""機器人防護頁偵測：HTTP 200 的防護頁必須標記為 bot_challenge，且不重試、不解析。"""

from src.scraper.fetch import fetch_page, is_bot_challenge, build_user_agent
from src.scraper.policy import DomainThrottle, RobotsPolicy

ALLOWLIST = {
    "allowed_domains": [{"host": "www.nu-vendome.com", "path_prefixes": ["/location-detail/"]}],
    "by_host": {"www.nu-vendome.com": ["/location-detail/"]},
    "open": False,
}

INCAPSULA_PAGE = (
    b'<html><head><META NAME="robots" CONTENT="noindex,nofollow">'
    b'<script src="/_Incapsula_Resource?SWJIYLWA=abc"></script></head><body></body></html>'
)
NORMAL_PAGE = "<html><body><h1>一般頁面</h1></body></html>".encode("utf-8")


def _run(body: bytes):
    calls = []

    def mock_http_get(pinned_ip, host, path, headers, **kwargs):
        calls.append(path)
        if path == "/robots.txt":
            return (404, {}, b"")
        return (200, {"content-type": "text/html; charset=utf-8"}, body)

    return fetch_page(
        "https://www.nu-vendome.com/location-detail/x",
        allowlist=ALLOWLIST,
        throttle=DomainThrottle(min_interval=3.0, sleep=lambda s: None),
        robots=RobotsPolicy(),
        user_agent=build_user_agent(),
        resolver=lambda h: ["8.8.8.8"],
        http_get=mock_http_get,
    ), calls


def test_bot_challenge_page_is_rejected_without_retry():
    res, calls = _run(INCAPSULA_PAGE)
    assert res.ok is False
    assert res.reason == "bot_challenge"
    # 只有 robots 與一次頁面請求，不重試、不嘗試繞過
    assert calls == ["/robots.txt", "/location-detail/x"]


def test_normal_html_page_still_succeeds():
    res, _ = _run(NORMAL_PAGE)
    assert res.ok is True
    assert "一般頁面" in res.html


def test_marker_detection_is_specific():
    assert is_bot_challenge(INCAPSULA_PAGE.decode("utf-8"))
    assert is_bot_challenge('<script src="https://challenges.cloudflare.com/x" id="cf_chl_opt"></script>')
    assert not is_bot_challenge("<html><body>服務介紹：眼科雷射</body></html>")
