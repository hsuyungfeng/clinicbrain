"""Phase 23 Task 2 單元測試：受限 HTTPS 擷取器 fetch_page。"""

from datetime import datetime, timezone
import ssl
from types import SimpleNamespace
import pytest

from src.scraper.fetch import (
    FetchResult,
    _PinnedHTTPSConnection,
    assert_tls_config,
    build_user_agent,
    fetch_page,
)
from src.scraper.policy import DomainThrottle, PolicyError, RobotsPolicy

ALLOWLIST = {
    "allowed_domains": [
        {"host": "www.nu-vendome.com", "path_prefixes": ["/location-detail/"]}
    ],
    "by_host": {
        "www.nu-vendome.com": ["/location-detail/"]
    },
}


def test_build_user_agent():
    """Test 1: build_user_agent 格式與不合法 contact 拒絕。"""
    ua = build_user_agent()
    assert ua == "ClinicBrainSiteReader/0.1 (+https://doctor-toolbox.com/clinicBot)"

    with pytest.raises(PolicyError) as exc:
        build_user_agent("mailto:ops@example.com")
    assert exc.value.reason == "bad_contact"

    with pytest.raises(PolicyError) as exc:
        build_user_agent("https://a.example/x@y")
    assert exc.value.reason == "bad_contact"

    with pytest.raises(PolicyError) as exc:
        build_user_agent("")
    assert exc.value.reason == "bad_contact"


def test_fetch_page_bad_content_type():
    """Test 2: 注入 http_get 回應 Content-Type application/pdf -> bad_content_type。"""
    def mock_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return (404, {}, b"")
        return (200, {"content-type": "application/pdf"}, b"%PDF-1.4...")

    throttle = DomainThrottle(min_interval=3.0, sleep=lambda s: None)
    robots = RobotsPolicy()
    resolver = lambda h: ["8.8.8.8"]

    res = fetch_page(
        "https://www.nu-vendome.com/location-detail/test",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        resolver=resolver,
        http_get=mock_http_get,
    )
    assert res.ok is False
    assert res.reason == "bad_content_type"


def test_fetch_page_too_many_redirects():
    """Test 3: 重導向超過 3 次 -> too_many_redirects。"""
    calls = 0

    def mock_http_get(pinned_ip, host, path, headers, **kwargs):
        nonlocal calls
        calls += 1
        if path == "/robots.txt":
            return (404, {}, b"")
        return (302, {"location": "/location-detail/next"}, b"")

    throttle = DomainThrottle(min_interval=3.0, sleep=lambda s: None)
    robots = RobotsPolicy()
    resolver = lambda h: ["8.8.8.8"]

    res = fetch_page(
        "https://www.nu-vendome.com/location-detail/start",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        resolver=resolver,
        http_get=mock_http_get,
        max_redirects=3,
    )
    assert res.ok is False
    assert res.reason == "too_many_redirects"
    # 1 次 robots + 1 次原始請求 + 3 次重導向 = 5 次
    # 頁面本身發出 4 次
    assert calls == 5


def test_fetch_page_redirect_to_http():
    """Test 4: 重導向至 http -> scheme 拒絕，不發出第二次請求。"""
    page_calls = 0

    def mock_http_get(pinned_ip, host, path, headers, **kwargs):
        nonlocal page_calls
        if path == "/robots.txt":
            return (404, {}, b"")
        page_calls += 1
        return (302, {"location": "http://www.nu-vendome.com/location-detail/x"}, b"")

    throttle = DomainThrottle(min_interval=3.0, sleep=lambda s: None)
    robots = RobotsPolicy()
    resolver = lambda h: ["8.8.8.8"]

    res = fetch_page(
        "https://www.nu-vendome.com/location-detail/start",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        resolver=resolver,
        http_get=mock_http_get,
    )
    assert res.ok is False
    assert res.reason == "scheme"
    assert page_calls == 1


def test_fetch_page_redirect_to_private():
    """Test 5: 重導向後解析出私有 IP -> private_address 拒絕。"""
    call_addrs = []

    def mock_resolver(h):
        if not call_addrs:
            return ["8.8.8.8"]
        return ["10.0.0.5"]

    def mock_http_get(pinned_ip, host, path, headers, **kwargs):
        call_addrs.append(pinned_ip)
        if path == "/robots.txt":
            return (404, {}, b"")
        return (302, {"location": "https://www.nu-vendome.com/location-detail/x"}, b"")

    throttle = DomainThrottle(min_interval=3.0, sleep=lambda s: None)
    robots = RobotsPolicy()

    res = fetch_page(
        "https://www.nu-vendome.com/location-detail/start",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        resolver=mock_resolver,
        http_get=mock_http_get,
    )
    assert res.ok is False
    assert res.reason == "private_address"
    assert "10.0.0.5" not in call_addrs


def test_fetch_page_too_large():
    """Test 6: 回應超過 max_bytes -> too_large。"""
    def mock_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return (404, {}, b"")
        return (200, {"content-type": "text/html"}, b"a" * 150)

    throttle = DomainThrottle(min_interval=3.0, sleep=lambda s: None)
    robots = RobotsPolicy()
    resolver = lambda h: ["8.8.8.8"]

    res = fetch_page(
        "https://www.nu-vendome.com/location-detail/start",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        resolver=resolver,
        http_get=mock_http_get,
        max_bytes=100,
    )
    assert res.ok is False
    assert res.reason == "too_large"


def test_fetch_page_timeout():
    """Test 7: http_get 拋出 TimeoutError -> timeout，error_class 為 TimeoutError。"""
    def mock_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return (404, {}, b"")
        raise TimeoutError("連線超時")

    throttle = DomainThrottle(min_interval=3.0, sleep=lambda s: None)
    robots = RobotsPolicy()
    resolver = lambda h: ["8.8.8.8"]

    res = fetch_page(
        "https://www.nu-vendome.com/location-detail/start",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        resolver=resolver,
        http_get=mock_http_get,
    )
    assert res.ok is False
    assert res.reason == "timeout"
    assert res.error_class == "TimeoutError"


def test_fetch_page_robots_denied():
    """Test 8: robots.txt 回 403 -> robots_denied，頁面請求不發出。"""
    page_called = False

    def mock_http_get(pinned_ip, host, path, headers, **kwargs):
        nonlocal page_called
        if path == "/robots.txt":
            return (403, {}, b"")
        page_called = True
        return (200, {"content-type": "text/html"}, b"<html></html>")

    throttle = DomainThrottle(min_interval=3.0, sleep=lambda s: None)
    robots = RobotsPolicy()
    resolver = lambda h: ["8.8.8.8"]

    res = fetch_page(
        "https://www.nu-vendome.com/location-detail/start",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        resolver=resolver,
        http_get=mock_http_get,
    )
    assert res.ok is False
    assert res.reason == "robots_denied"
    assert page_called is False


def test_fetch_page_success_utf8():
    """Test 9: 正常 200 回應與 UTF-8 中文解析成功。"""
    def mock_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return (404, {}, b"")
        return (200, {"content-type": "text/html; charset=utf-8"}, "<html>台中分院臨床處置</html>".encode("utf-8"))

    throttle = DomainThrottle(min_interval=3.0, sleep=lambda s: None)
    robots = RobotsPolicy()
    resolver = lambda h: ["8.8.8.8"]

    res = fetch_page(
        "https://www.nu-vendome.com/location-detail/Taichung/",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        resolver=resolver,
        http_get=mock_http_get,
    )
    assert res.ok is True
    assert "台中分院臨床處置" in res.html
    assert res.final_url == "https://www.nu-vendome.com/location-detail/Taichung/"
    assert res.fetched_at.endswith("Z") or "+00:00" in res.fetched_at


def test_fetch_page_dns_rebinding_defense():
    """Test 10: DNS rebinding 防護，第二次 DNS 回傳私有 IP 立即攔截。"""
    resolver_calls = 0

    def mock_resolver(h):
        nonlocal resolver_calls
        resolver_calls += 1
        if resolver_calls == 1:
            return ["8.8.4.4"]  # robots
        return ["10.0.0.1"]  # 頁面

    connected_ips = []

    def mock_connector(addr, timeout):
        connected_ips.append(addr[0])
        return SimpleNamespace()

    def mock_http_get(pinned_ip, host, path, headers, **kwargs):
        connected_ips.append(pinned_ip)
        if path == "/robots.txt":
            return (404, {}, b"")
        return (200, {"content-type": "text/html"}, b"<html></html>")

    throttle = DomainThrottle(min_interval=3.0, sleep=lambda s: None)
    robots = RobotsPolicy()

    res = fetch_page(
        "https://www.nu-vendome.com/location-detail/Taichung/",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        resolver=mock_resolver,
        http_get=mock_http_get,
        connector=mock_connector,
    )
    assert res.ok is False
    assert res.reason == "private_address"
    assert "10.0.0.1" not in connected_ips


def test_pinned_connection_and_tls_config():
    """Test 11: 釘住已驗證 IP、TLS 驗證參數與 Host 標頭。"""
    connected_addrs = []
    wrapped_params = {}

    def fake_connector(addr, timeout):
        connected_addrs.append(addr)
        return SimpleNamespace()

    fake_ctx = SimpleNamespace(
        check_hostname=True,
        verify_mode=ssl.CERT_REQUIRED,
    )

    def fake_wrap_socket(sock, server_hostname):
        wrapped_params["server_hostname"] = server_hostname
        return SimpleNamespace()

    fake_ctx.wrap_socket = fake_wrap_socket

    conn = _PinnedHTTPSConnection(
        "www.nu-vendome.com",
        port=443,
        pinned_ip="8.8.4.4",
        connector=fake_connector,
        ssl_context=fake_ctx,
    )
    conn.connect()

    assert connected_addrs == [("8.8.4.4", 443)]
    assert wrapped_params["server_hostname"] == "www.nu-vendome.com"


def test_throttle_not_bypassable():
    """Test 12: 節流 wait_turn 在每次 http_get 之前都被呼叫。"""
    events = []

    class EventThrottle(DomainThrottle):
        def wait_turn(self, host):
            events.append(("wait", host))

    throttle = EventThrottle(min_interval=3.0, sleep=lambda s: None)

    def mock_http_get(pinned_ip, host, path, headers, **kwargs):
        events.append(("get", path))
        if path == "/robots.txt":
            return (404, {}, b"")
        return (200, {"content-type": "text/html"}, b"<html>ok</html>")

    robots = RobotsPolicy()
    resolver = lambda h: ["8.8.8.8"]

    res = fetch_page(
        "https://www.nu-vendome.com/location-detail/Taichung/",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        resolver=resolver,
        http_get=mock_http_get,
    )
    assert res.ok is True
    # 事件順序為 wait robots, get robots, wait page, get page
    assert events == [
        ("wait", "www.nu-vendome.com"),
        ("get", "/robots.txt"),
        ("wait", "www.nu-vendome.com"),
        ("get", "/location-detail/Taichung/"),
    ]


def test_robots_path_exemption_only():
    """Test 13: robots.txt 路徑豁免，頁面非白名單路徑被拒絕。"""
    throttle = DomainThrottle(min_interval=3.0, sleep=lambda s: None)
    robots = RobotsPolicy()
    resolver = lambda h: ["8.8.8.8"]

    res = fetch_page(
        "https://www.nu-vendome.com/other/page",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        resolver=resolver,
    )
    assert res.ok is False
    assert res.reason == "not_allowlisted"


def test_fetch_page_ipv4_mapped():
    """Test 14: resolver 回傳 IPv4-mapped 私有 IP 立即拒絕。"""
    throttle = DomainThrottle(min_interval=3.0, sleep=lambda s: None)
    robots = RobotsPolicy()
    resolver = lambda h: ["::ffff:10.0.0.1"]

    res = fetch_page(
        "https://www.nu-vendome.com/location-detail/Taichung/",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        resolver=resolver,
    )
    assert res.ok is False
    assert res.reason == "private_address"


def test_fetch_page_network_error():
    """Test 15: 網路例外轉為 reason='network'，且 error_class 為類別名稱。"""
    def mock_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return (404, {}, b"")
        raise OSError("連線重設")

    throttle = DomainThrottle(min_interval=3.0, sleep=lambda s: None)
    robots = RobotsPolicy()
    resolver = lambda h: ["8.8.8.8"]

    res = fetch_page(
        "https://www.nu-vendome.com/location-detail/Taichung/",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        resolver=resolver,
        http_get=mock_http_get,
    )
    assert res.ok is False
    assert res.reason == "network"
    assert res.error_class == "OSError"


def test_tls_config_assertions():
    """Test 17 & 18: check_hostname=False 或 verify_mode 非 CERT_REQUIRED 立即拒絕。"""
    throttle = DomainThrottle(min_interval=3.0, sleep=lambda s: None)
    robots = RobotsPolicy()

    # check_hostname False
    bad_ctx1 = SimpleNamespace(check_hostname=False, verify_mode=ssl.CERT_REQUIRED)
    res1 = fetch_page(
        "https://www.nu-vendome.com/location-detail/Taichung/",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        ssl_context=bad_ctx1,
    )
    assert res1.ok is False
    assert res1.reason == "tls_config"

    # verify_mode 非 CERT_REQUIRED
    bad_ctx2 = SimpleNamespace(check_hostname=True, verify_mode=ssl.CERT_NONE)
    res2 = fetch_page(
        "https://www.nu-vendome.com/location-detail/Taichung/",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        ssl_context=bad_ctx2,
    )
    assert res2.ok is False
    assert res2.reason == "tls_config"


def test_default_ssl_context():
    """Test 19: 預設 SSL context 具備 check_hostname=True 與 verify_mode=CERT_REQUIRED。"""
    ctx = ssl.create_default_context()
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert_tls_config(ctx)


def test_fetch_page_pinned_addresses_support():
    """Test 20 (CR-23-1): pinned_addresses 傳入支援。"""
    resolved_called = False

    def mock_resolver(h):
        nonlocal resolved_called
        resolved_called = True
        return ["1.1.1.1"]

    used_ip = None

    def mock_http_get(pinned_ip, host, path, headers, **kwargs):
        nonlocal used_ip
        used_ip = pinned_ip
        if path == "/robots.txt":
            return (404, {}, b"")
        return (200, {"content-type": "text/html"}, b"<html>pinned</html>")

    throttle = DomainThrottle(min_interval=3.0, sleep=lambda s: None)
    robots = RobotsPolicy()

    # 傳入公網 pinned_addresses
    res = fetch_page(
        "https://www.nu-vendome.com/location-detail/Taichung/",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        pinned_addresses=["8.8.8.8"],
        resolver=mock_resolver,
        http_get=mock_http_get,
    )
    assert res.ok is True
    assert used_ip == "8.8.8.8"
    assert resolved_called is False

    # 傳入私有 pinned_addresses -> private_address 拒絕
    res_bad = fetch_page(
        "https://www.nu-vendome.com/location-detail/Taichung/",
        allowlist=ALLOWLIST,
        throttle=throttle,
        robots=robots,
        user_agent=build_user_agent(),
        pinned_addresses=["10.0.0.1"],
    )
    assert res_bad.ok is False
    assert res_bad.reason == "private_address"
