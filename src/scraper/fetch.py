"""Phase 23 Task 2：受限 HTTPS 擷取器 fetch_page（IP 釘住、TLS 驗證強制、節流、重導向重檢）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import re
import socket
import ssl
import time
from typing import Callable, Optional, Sequence
import urllib.parse

from src.scraper.policy import (
    DEFAULT_CONTACT_URL,
    DomainThrottle,
    PolicyError,
    RobotsPolicy,
    check_host_allowed,
    check_url_allowed,
    is_public_address,
    resolve_public_addresses,
)

USER_AGENT_TEMPLATE = "ClinicBrainSiteReader/0.1 (+{contact})"


def build_user_agent(contact: str = DEFAULT_CONTACT_URL) -> str:
    """建構合規之 User-Agent 字串，強制包含 https 聯絡網址且不得含 email。"""
    if not isinstance(contact, str) or not contact.strip():
        raise PolicyError(reason="bad_contact", message="聯絡網址為空")

    clean = contact.strip()
    if not clean.startswith("https://") or " " in clean or "@" in clean or "mailto:" in clean:
        raise PolicyError(reason="bad_contact", message="聯絡網址必須為有效 https 網址且不得包含 email")

    return USER_AGENT_TEMPLATE.format(contact=clean)


def assert_tls_config(ctx: ssl.SSLContext | object) -> None:
    """斷言 TLS context 啟用主機名檢查且強制驗證憑證。"""
    if not getattr(ctx, "check_hostname", False) or getattr(ctx, "verify_mode", None) != ssl.CERT_REQUIRED:
        raise PolicyError(reason="tls_config", message="TLS 必須開啟 check_hostname 且 verify_mode 必須為 CERT_REQUIRED")


@dataclass
class FetchResult:
    """單一網址擷取結果。"""

    ok: bool
    url: str
    final_url: str = ""
    status: int = 0
    html: str = ""
    fetched_at: str = ""
    reason: str = ""
    error_class: str = ""


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """自訂 HTTPS 連線：覆寫 connect() 將底層 socket 釘住至已驗證 IP，保留原 Host/SNI。"""

    def __init__(
        self,
        host: str,
        port: int = 443,
        *,
        pinned_ip: str,
        connector=None,
        ssl_context=None,
        timeout: float = 10.0,
        **kwargs,
    ) -> None:
        super().__init__(host, port, timeout=timeout, **kwargs)
        self._pinned_ip = pinned_ip
        self._connector = connector or socket.create_connection
        self._ssl_context = ssl_context or ssl.create_default_context()

    def connect(self) -> None:
        assert_tls_config(self._ssl_context)
        raw_sock = self._connector((self._pinned_ip, self.port), self.timeout)
        self.sock = self._ssl_context.wrap_socket(raw_sock, server_hostname=self.host)


def default_http_get(
    pinned_ip: str,
    host: str,
    path: str,
    headers: dict[str, str],
    *,
    timeout: float = 10.0,
    max_bytes: int = 2 * 1024 * 1024,
    connector=None,
    ssl_context=None,
) -> tuple[int, dict[str, str], bytes]:
    """預設使用 _PinnedHTTPSConnection 執行 HTTP GET 請求並讀取至多 max_bytes + 1 位元組。"""
    conn = _PinnedHTTPSConnection(
        host,
        443,
        pinned_ip=pinned_ip,
        connector=connector,
        ssl_context=ssl_context,
        timeout=timeout,
    )
    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        resp_headers = {k.lower(): v for k, v in resp.getheaders()}
        body = resp.read(max_bytes + 1)
        return status, resp_headers, body
    finally:
        conn.close()


def _extract_charset(content_type: str) -> str:
    match = re.search(r"charset\s*=\s*['\"]?([\w\-]+)", content_type, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "utf-8"


def fetch_page(
    url: str,
    *,
    allowlist: dict,
    throttle: DomainThrottle,
    robots: RobotsPolicy,
    user_agent: str,
    resolver: Optional[Callable[[str], Sequence[str]]] = None,
    http_get: Optional[Callable[..., tuple[int, dict[str, str], bytes]]] = None,
    connector: Optional[Callable] = None,
    ssl_context: Optional[ssl.SSLContext] = None,
    pinned_addresses: Optional[Sequence[str]] = None,
    now: Optional[float] = None,
    timeout: float = 10.0,
    max_bytes: int = 2 * 1024 * 1024,
    max_redirects: int = 3,
) -> FetchResult:
    """受限安全 HTTPS 頁面擷取入口。"""
    effective_ssl_ctx = ssl_context or ssl.create_default_context()
    effective_http_get = http_get or default_http_get
    now_fn = (lambda: now) if now is not None else time.time
    iso_now = datetime.now(timezone.utc).isoformat()

    try:
        assert_tls_config(effective_ssl_ctx)
    except PolicyError as e:
        return FetchResult(ok=False, url=url, reason=e.reason, fetched_at=iso_now)

    current_url = url
    redirect_count = 0
    is_first_hop = True

    try:
        while True:
            # 1. 白名單與協議初篩
            check_url_allowed(current_url, allowlist)
            parsed = urllib.parse.urlsplit(current_url)
            host = parsed.hostname.lower()
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"

            # 2. robots.txt 判定 (首跳或跨網域時)
            cached_robots = robots.cache_get(host, now_fn())
            if cached_robots is None:
                # 抓取 robots.txt
                check_host_allowed(host, allowlist)
                if is_first_hop and pinned_addresses:
                    for ip_str in pinned_addresses:
                        if not is_public_address(ip_str):
                            raise PolicyError(reason="private_address", message=f"pinned_addresses 包含非公網位址: {ip_str}")
                    robots_ip = pinned_addresses[0]
                else:
                    robots_addrs = resolve_public_addresses(host, resolver)
                    robots_ip = robots_addrs[0]

                throttle.wait_turn(host)
                r_status, r_headers, r_body = effective_http_get(
                    robots_ip,
                    host,
                    "/robots.txt",
                    {"Host": host, "User-Agent": user_agent},
                    timeout=timeout,
                    max_bytes=max_bytes,
                    connector=connector,
                    ssl_context=effective_ssl_ctx,
                )
                r_text = r_body.decode("utf-8", errors="replace")
                allowed = robots.decide(r_status, r_text, path, "ClinicBrainSiteReader")
                robots.cache_put(host, allowed, now_fn())
                cached_robots = allowed

            if not cached_robots:
                return FetchResult(
                    ok=False,
                    url=url,
                    final_url=current_url,
                    reason="robots_denied",
                    fetched_at=iso_now,
                )

            # 3. 解析並釘住 IP
            if is_first_hop and pinned_addresses:
                for ip_str in pinned_addresses:
                    if not is_public_address(ip_str):
                        raise PolicyError(reason="private_address", message=f"pinned_addresses 包含非公網位址: {ip_str}")
                pinned_ip = pinned_addresses[0]
            else:
                addrs = resolve_public_addresses(host, resolver)
                pinned_ip = addrs[0]

            # 4. 節流排隊
            throttle.wait_turn(host)

            # 5. 發送頁面 HTTP 請求
            status, resp_headers, body = effective_http_get(
                pinned_ip,
                host,
                path,
                {"Host": host, "User-Agent": user_agent},
                timeout=timeout,
                max_bytes=max_bytes,
                connector=connector,
                ssl_context=effective_ssl_ctx,
            )

            # 6. 重導向處理 (301, 302, 303, 307, 308)
            if status in (301, 302, 303, 307, 308):
                redirect_count += 1
                if redirect_count > max_redirects:
                    return FetchResult(
                        ok=False,
                        url=url,
                        final_url=current_url,
                        status=status,
                        reason="too_many_redirects",
                        fetched_at=iso_now,
                    )

                loc = resp_headers.get("location")
                if not loc:
                    return FetchResult(
                        ok=False,
                        url=url,
                        final_url=current_url,
                        status=status,
                        reason="bad_url",
                        fetched_at=iso_now,
                    )

                current_url = urllib.parse.urljoin(current_url, loc)
                is_first_hop = False
                continue

            # 7. 正常或錯誤狀態碼處理
            if status == 200:
                ctype = resp_headers.get("content-type", "").lower()
                if not ctype.startswith("text/html"):
                    return FetchResult(
                        ok=False,
                        url=url,
                        final_url=current_url,
                        status=status,
                        reason="bad_content_type",
                        fetched_at=iso_now,
                    )

                if len(body) > max_bytes:
                    return FetchResult(
                        ok=False,
                        url=url,
                        final_url=current_url,
                        status=status,
                        reason="too_large",
                        fetched_at=iso_now,
                    )

                charset = _extract_charset(ctype)
                try:
                    html_text = body.decode(charset, errors="replace")
                except Exception:
                    html_text = body.decode("utf-8", errors="replace")

                return FetchResult(
                    ok=True,
                    url=url,
                    final_url=current_url,
                    status=status,
                    html=html_text,
                    fetched_at=iso_now,
                )
            else:
                return FetchResult(
                    ok=False,
                    url=url,
                    final_url=current_url,
                    status=status,
                    reason="http_status",
                    fetched_at=iso_now,
                )

    except PolicyError as e:
        return FetchResult(
            ok=False,
            url=url,
            final_url=current_url,
            reason=e.reason,
            fetched_at=iso_now,
        )
    except TimeoutError as e:
        return FetchResult(
            ok=False,
            url=url,
            final_url=current_url,
            reason="timeout",
            error_class=type(e).__name__,
            fetched_at=iso_now,
        )
    except OSError as e:
        return FetchResult(
            ok=False,
            url=url,
            final_url=current_url,
            reason="network",
            error_class=type(e).__name__,
            fetched_at=iso_now,
        )
    except Exception as e:
        return FetchResult(
            ok=False,
            url=url,
            final_url=current_url,
            reason="unexpected",
            error_class=type(e).__name__,
            fetched_at=iso_now,
        )
