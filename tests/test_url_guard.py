"""
Unit tests for SSRF URL guard (validate_public_url).
Plan 24-02 Task 1:
- Only HTTPS scheme allowed.
- Port strictly limited to 443 (or unspecified).
- Userinfo forbidden.
- Non-empty host within length limits (<= 2048).
- IP validation delegated to Phase 23 (resolve_public_addresses).
- All tests use injected resolver to avoid real DNS/network.
"""

from pathlib import Path
import socket
import pytest

from src.ingestion.url_guard import (
    UNSAFE_URL_ERROR_MESSAGE,
    UnsafeUrlError,
    ValidatedUrl,
    validate_public_url,
)


def _make_fake_resolver(ips: list[str]):
    """產生回傳指定 IP 字串清單的 fake resolver。"""
    def _resolver(host: str, port=None, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
            for ip in ips
        ]
    return _resolver


def test_valid_https_url_with_query_and_fragment_removal():
    resolver = _make_fake_resolver(["93.184.216.34"])
    result = validate_public_url(
        "https://www.example.com/a?b=1#fragment_here",
        resolver=resolver,
    )
    assert isinstance(result, ValidatedUrl)
    assert result.url == "https://www.example.com/a?b=1"
    assert result.host == "www.example.com"
    assert result.port == 443
    assert result.addresses == ("93.184.216.34",)


def test_valid_urls_with_explicit_443_or_default():
    resolver = _make_fake_resolver(["93.184.216.34"])
    r1 = validate_public_url("https://example.com/", resolver=resolver)
    assert r1.port == 443

    r2 = validate_public_url("https://example.com:443/", resolver=resolver)
    assert r2.port == 443
    assert r2.url == "https://example.com:443/"


def test_reject_port_80_and_8443():
    resolver = _make_fake_resolver(["93.184.216.34"])
    for u in ["https://example.com:80/", "https://example.com:8443/"]:
        with pytest.raises(UnsafeUrlError) as exc:
            validate_public_url(u, resolver=resolver)
        assert exc.value.args[0] == UNSAFE_URL_ERROR_MESSAGE


def test_reject_http_scheme():
    resolver = _make_fake_resolver(["93.184.216.34"])
    with pytest.raises(UnsafeUrlError):
        validate_public_url("http://www.example.com/", resolver=resolver)


def test_reject_localhost():
    # localhost 無論 http 或 https，或搭配任何埠，一律拒絕
    resolver = _make_fake_resolver(["127.0.0.1"])
    for u in ["http://localhost:8080/", "https://localhost/", "https://localhost:443/"]:
        with pytest.raises(UnsafeUrlError):
            validate_public_url(u, resolver=resolver)


def test_reject_other_schemes():
    resolver = _make_fake_resolver(["93.184.216.34"])
    for u in [
        "file:///etc/passwd",
        "ftp://x.com/",
        "data:text/html,x",
        "javascript:alert(1)",
        "gopher://x.com/",
    ]:
        with pytest.raises(UnsafeUrlError):
            validate_public_url(u, resolver=resolver)


def test_reject_userinfo():
    resolver = _make_fake_resolver(["93.184.216.34"])
    for u in [
        "https://user:pass@example.com/",
        "https://user@example.com/",
        "https://:pass@example.com/",
    ]:
        with pytest.raises(UnsafeUrlError):
            validate_public_url(u, resolver=resolver)


def test_reject_missing_host_and_length_limit():
    resolver = _make_fake_resolver(["93.184.216.34"])
    with pytest.raises(UnsafeUrlError):
        validate_public_url("", resolver=resolver)

    with pytest.raises(UnsafeUrlError):
        validate_public_url("   ", resolver=resolver)

    with pytest.raises(UnsafeUrlError):
        validate_public_url("https:///path", resolver=resolver)

    too_long = "https://example.com/" + ("a" * 2050)
    with pytest.raises(UnsafeUrlError):
        validate_public_url(too_long, resolver=resolver)


@pytest.mark.parametrize(
    "private_ip",
    [
        "10.0.0.1",
        "172.16.5.4",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "100.64.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:10.0.0.1",
    ],
)
def test_reject_private_and_non_global_ips(private_ip: str):
    resolver = _make_fake_resolver([private_ip])
    with pytest.raises(UnsafeUrlError) as exc:
        validate_public_url("https://internal.test/", resolver=resolver)
    assert exc.value.args[0] == UNSAFE_URL_ERROR_MESSAGE
    assert private_ip not in exc.value.args[0]
    assert "internal.test" not in exc.value.args[0]


def test_reject_mixed_public_and_private_ips():
    # 同時回傳公網與私網 IP 時，應整體拒絕
    resolver = _make_fake_resolver(["93.184.216.34", "10.0.0.1"])
    with pytest.raises(UnsafeUrlError):
        validate_public_url("https://mixed.example.com/", resolver=resolver)


def test_reject_dns_errors():
    def _failing_resolver(host: str, *args, **kwargs):
        raise socket.gaierror(-2, "Name or service not known")

    with pytest.raises(UnsafeUrlError):
        validate_public_url("https://notfound.example.com/", resolver=_failing_resolver)

    def _os_failing_resolver(host: str, *args, **kwargs):
        raise OSError("DNS network timeout")

    with pytest.raises(UnsafeUrlError):
        validate_public_url("https://oserror.example.com/", resolver=_os_failing_resolver)


def test_unsafe_url_error_fixed_traditional_chinese_no_leak():
    resolver = _make_fake_resolver(["10.0.0.1"])
    secret_host = "secret-intranet-host.corp"
    with pytest.raises(UnsafeUrlError) as exc:
        validate_public_url(f"https://{secret_host}/", resolver=resolver)
    msg = exc.value.args[0]
    assert msg == UNSAFE_URL_ERROR_MESSAGE
    assert secret_host not in msg
    assert "10.0.0.1" not in msg


def test_url_guard_module_has_no_logging_or_prints():
    code = Path("src/ingestion/url_guard.py").read_text(encoding="utf-8")
    for keyword in ["logger", "logging", "print(", "is_global", "100.64"]:
        assert keyword not in code, f"Forbidden keyword '{keyword}' found in url_guard.py"
