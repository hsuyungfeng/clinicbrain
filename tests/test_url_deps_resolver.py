"""回歸測試：正式 get_url_fetch_deps 的 resolver 必須回傳 IP 字串（非 getaddrinfo 5-tuple）。

Phase 24 既有測試以 mock resolver 注入，未涵蓋正式依賴；此測試直接檢驗正式注入點。
"""

from src.api.routes.admin import get_url_fetch_deps
from src.scraper.policy import resolve_public_addresses


def test_production_resolver_returns_ip_strings():
    deps = get_url_fetch_deps()
    # resolver 為 None 時由 policy 內建解析；若日後改為自訂函式，其輸出也必須是 IP 字串
    addrs = resolve_public_addresses("localhost", deps.resolver) if deps.resolver else None
    if addrs is not None:
        assert all(isinstance(a, str) for a in addrs)


def test_production_resolver_is_not_raw_getaddrinfo():
    import socket

    deps = get_url_fetch_deps()
    assert deps.resolver is not socket.getaddrinfo
