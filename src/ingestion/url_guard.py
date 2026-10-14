"""
網址前置 SSRF 安全檢查模組。
Plan 24-02 Task 1 (D-05 第一層、PRD R5):
- 嚴格限制僅允許 https 協議
- 嚴格限制連接埠僅允許 443 (不指定時預設 443)
- 禁止 userinfo (username / password)
- 主機名稱必須非空且不得超過長度限制 (2048)
- IP 位址判定委派 Phase 23 src/scraper/policy.py 的 resolve_public_addresses (CR-23-3 單一來源)
- 零日誌（無記錄器輸出），固定繁體中文錯誤訊息，不回顯輸入或內部資訊
"""

from dataclasses import dataclass
import socket
from typing import Any, Callable, Optional, Sequence
import urllib.parse

from ..scraper.policy import PolicyError, resolve_public_addresses

MAX_URL_LENGTH = 2048
UNSAFE_URL_ERROR_MESSAGE = "網址不允許解析（僅接受已授權之公開 https 網址）"


class UnsafeUrlError(ValueError):
    """網址不符合安全規範（SSRF 防禦第一層）。"""

    def __init__(self, message: str = UNSAFE_URL_ERROR_MESSAGE) -> None:
        super().__init__(message)


@dataclass(frozen=True)
class ValidatedUrl:
    """經過安全檢驗的 URL 結構。"""

    url: str  # 去除 fragment，保留 query
    host: str  # 小寫主機名稱
    port: int  # 連接埠，固定為 443
    addresses: tuple[str, ...]  # 解析出之公網 IP 清單


def _adapt_resolver(
    res_fn: Optional[Callable],
) -> Optional[Callable[[str], Sequence[str]]]:
    """適配 resolver，支援 getaddrinfo 格式或單純主機轉 IP 字串清單。"""
    if res_fn is None or res_fn is socket.getaddrinfo:
        return None

    def _resolver_adapter(host: str) -> list[str]:
        try:
            raw = res_fn(host)
        except TypeError:
            raw = res_fn(host, 443)

        ips: list[str] = []
        for item in raw:
            if isinstance(item, str):
                ips.append(item)
            elif (
                isinstance(item, (tuple, list))
                and len(item) >= 5
                and isinstance(item[4], (tuple, list))
                and len(item[4]) >= 1
            ):
                ips.append(str(item[4][0]))
            else:
                ips.append(str(item))
        return ips

    return _resolver_adapter


def validate_public_url(
    url: str,
    *,
    resolver: Any = socket.getaddrinfo,
) -> ValidatedUrl:
    """驗證公開 HTTPS 網址之安全性與格式（D-05 第一層）。

    違規時一律拋出 UnsafeUrlError（固定繁中訊息，絕不包含主機名、IP 或輸入）。
    """
    if not isinstance(url, str):
        raise UnsafeUrlError()

    trimmed = url.strip()
    if not trimmed or len(trimmed) > MAX_URL_LENGTH:
        raise UnsafeUrlError()

    try:
        parsed = urllib.parse.urlsplit(trimmed)
    except Exception as e:
        raise UnsafeUrlError() from e

    # 1. Scheme: 僅允許 https (不區分大小寫)，無任何例外
    if (parsed.scheme or "").lower() != "https":
        raise UnsafeUrlError()

    # 2. Userinfo: 禁止包含使用者名稱或密碼
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError()

    # 3. Port: 僅允許 443 或未指定 (未指定視為 443)
    try:
        explicit_port = parsed.port
    except ValueError as e:
        raise UnsafeUrlError() from e

    if explicit_port is not None and explicit_port != 443:
        raise UnsafeUrlError()

    # 4. Hostname: 必須存在且非空
    raw_host = parsed.hostname
    if not raw_host:
        raise UnsafeUrlError()

    clean_host = raw_host.lower().strip()
    if not clean_host:
        raise UnsafeUrlError()

    # 5. IP 位址解析與公網判定 (委派 Phase 23 單一來源)
    adapted = _adapt_resolver(resolver)
    try:
        addresses = resolve_public_addresses(clean_host, resolver=adapted)
    except PolicyError as e:
        raise UnsafeUrlError() from e
    except (socket.gaierror, OSError) as e:
        raise UnsafeUrlError() from e
    except Exception as e:
        raise UnsafeUrlError() from e

    if not addresses:
        raise UnsafeUrlError()

    # 6. 去除 fragment，保留 query
    clean_url = urllib.parse.urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )

    return ValidatedUrl(
        url=clean_url,
        host=clean_host,
        port=443,
        addresses=tuple(addresses),
    )
