"""Phase 23 Task 1：網站擷取器安全政策、SSRF 判定、節流與 Robots 策略。"""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
import re
import socket
import threading
import time
from typing import Callable, Optional, Sequence
import urllib.parse
import urllib.robotparser

DEFAULT_CONTACT_URL = "https://doctor-toolbox.com/clinicBot"
CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")


class PolicyError(Exception):
    """安全政策違規或檢驗失敗例外。"""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason


def load_allowlist(path: str | Path) -> dict:
    """載入網域白名單設定檔並建立 host 快速查找表。"""
    file_path = Path(path)
    if not file_path.is_file():
        raise PolicyError(reason="bad_allowlist", message=f"白名單檔案不存在: {file_path}")

    try:
        content = file_path.read_text(encoding="utf-8")
        data = json.loads(content)
    except Exception as e:
        raise PolicyError(reason="bad_allowlist", message=f"白名單 JSON 解析失敗: {e}") from e

    if not isinstance(data, dict) or "allowed_domains" not in data or not isinstance(data["allowed_domains"], list):
        raise PolicyError(reason="bad_allowlist", message="白名單必須包含 'allowed_domains' 清單")

    by_host: dict[str, list[str]] = {}
    for entry in data["allowed_domains"]:
        if not isinstance(entry, dict) or "host" not in entry or not isinstance(entry["host"], str):
            raise PolicyError(reason="bad_allowlist", message="白名單項目缺少有效的 'host'")
        host = entry["host"].strip().lower()
        prefixes = entry.get("path_prefixes", ["/"])
        if not isinstance(prefixes, list):
            prefixes = ["/"]
        by_host[host] = prefixes

    # open_access=true：不要求網域列入白名單（仍強制 https、443、無憑證、SSRF 公網檢查與 robots.txt）
    return {
        "allowed_domains": data["allowed_domains"],
        "by_host": by_host,
        "open": data.get("open_access") is True,
    }


def check_url_allowed(url: str, allowlist: dict) -> None:
    """檢查請求 URL 是否符合白名單、https 與安全規範。"""
    if not isinstance(url, str) or not url.strip():
        raise PolicyError(reason="bad_url", message="URL 為空")

    try:
        parsed = urllib.parse.urlsplit(url.strip())
    except Exception as e:
        raise PolicyError(reason="bad_url", message=f"URL 格式解析失敗: {e}") from e

    if not parsed.scheme or not parsed.netloc:
        raise PolicyError(reason="bad_url", message="無效的 URL 格式")

    if parsed.scheme.lower() != "https":
        raise PolicyError(reason="scheme", message="僅允許 https 協議")

    if parsed.username or parsed.password:
        raise PolicyError(reason="credentials", message="URL 禁止包含帳號密碼憑證")

    try:
        port = parsed.port
    except ValueError:
        raise PolicyError(reason="port", message="URL 連接埠無效")

    if port is not None and port != 443:
        raise PolicyError(reason="port", message="僅允許 443 連接埠")

    if allowlist.get("open") is True:
        return

    host = (parsed.hostname or "").lower()
    by_host: dict[str, list[str]] = allowlist.get("by_host", {})
    if host not in by_host:
        raise PolicyError(reason="not_allowlisted", message=f"主機名稱 {host} 未列入白名單")

    path = parsed.path or "/"
    prefixes = by_host[host]
    matched = any(path.startswith(prefix) for prefix in prefixes)
    if not matched:
        raise PolicyError(reason="not_allowlisted", message=f"路徑 {path} 不符合允許前綴 {prefixes}")


def check_host_allowed(host: str, allowlist: dict) -> None:
    """僅檢查 host 是否在白名單內（供 robots.txt 判定）。"""
    if not isinstance(host, str) or not host.strip():
        raise PolicyError(reason="not_allowlisted", message="主機名稱為空")
    if allowlist.get("open") is True:
        return
    clean_host = host.strip().lower()
    by_host: dict[str, list[str]] = allowlist.get("by_host", {})
    if clean_host not in by_host:
        raise PolicyError(reason="not_allowlisted", message=f"主機名稱 {clean_host} 未列入白名單")


def is_public_address(ip_str: str) -> bool:
    """嚴格判定 IP 是否為全域可路由之公網位址。"""
    try:
        addr = ipaddress.ip_address(ip_str.strip())
    except ValueError:
        return False

    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped

    if isinstance(addr, ipaddress.IPv4Address):
        if addr in CGNAT_NET:
            return False

    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
    ):
        return False

    return addr.is_global


def resolve_public_addresses(
    host: str, resolver: Optional[Callable[[str], Sequence[str]]] = None
) -> list[str]:
    """解析 A/AAAA 記錄並斷言所有位址均為公網 IP。"""
    clean_host = host.strip()
    if not clean_host:
        raise PolicyError(reason="dns_resolution", message="主機名稱為空")

    addrs: list[str] = []
    if resolver is not None:
        try:
            resolved = resolver(clean_host)
            addrs = list(resolved)
        except PolicyError:
            raise
        except Exception as e:
            raise PolicyError(reason="dns_resolution", message=f"自訂 DNS 解析失敗: {e}") from e
    else:
        try:
            results = socket.getaddrinfo(clean_host, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
            seen = set()
            for item in results:
                ip_str = item[4][0]
                if ip_str not in seen:
                    seen.add(ip_str)
                    addrs.append(ip_str)
        except Exception as e:
            raise PolicyError(reason="dns_resolution", message=f"DNS 解析失敗: {e}") from e

    if not addrs:
        raise PolicyError(reason="dns_resolution", message=f"主機 {clean_host} 無任何 A/AAAA 記錄")

    for ip_str in addrs:
        if not is_public_address(ip_str):
            raise PolicyError(reason="private_address", message=f"主機 {clean_host} 包含非公網位址: {ip_str}")

    return addrs


def strip_url_for_storage(url: str) -> str:
    """清洗 URL 僅保留 scheme/host/path，移除查詢字串與 fragment；支援 fixture:// 格式。"""
    if not isinstance(url, str) or not url.strip():
        raise PolicyError(reason="bad_url", message="URL 為空")

    trimmed = url.strip()
    if trimmed.startswith("fixture://"):
        filename = trimmed[len("fixture://"):]
        if re.match(r"^[\w\-.]{1,128}$", filename) and "/" not in filename and "\\" not in filename:
            return f"fixture://{filename}"
        raise PolicyError(reason="bad_url", message=f"不合法的 fixture 檔名: {filename}")

    try:
        parsed = urllib.parse.urlsplit(trimmed)
    except Exception as e:
        raise PolicyError(reason="bad_url", message=f"URL 解析失敗: {e}") from e

    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise PolicyError(reason="bad_url", message="僅接受 https 或 fixture:// 協議")

    host = parsed.hostname.lower()
    path = parsed.path or "/"
    path = re.sub(r"/+", "/", path)

    return f"https://{host}{path}"


class DomainThrottle:
    """針對各個網域的請求間隔節流器。"""

    def __init__(
        self,
        min_interval: float = 5.0,
        clock: Optional[Callable[[], float]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        if min_interval < 3.0:
            raise PolicyError(reason="interval_too_short", message="請求間隔不得小於 3.0 秒")
        self.min_interval = float(min_interval)
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self._last_times: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait_turn(self, host: str) -> None:
        """若離同網域上次請求未滿 min_interval，等待至足夠時間。"""
        clean_host = host.strip().lower()
        with self._lock:
            now = self.clock()
            last = self._last_times.get(clean_host, 0.0)
            elapsed = now - last
            if elapsed < self.min_interval:
                needed = self.min_interval - elapsed
                self.sleep(needed)
                self._last_times[clean_host] = self.clock()
            else:
                self._last_times[clean_host] = now


class RobotsPolicy:
    """robots.txt 解析與快取決策。"""

    def __init__(self, ttl: float = 3600.0) -> None:
        self.ttl = ttl
        self._cache: dict[str, tuple[bool, float]] = {}
        self._lock = threading.Lock()

    def cache_get(self, host: str, now: float) -> Optional[bool]:
        clean_host = host.strip().lower()
        with self._lock:
            entry = self._cache.get(clean_host)
            if entry is None:
                return None
            allowed, timestamp = entry
            if now - timestamp > self.ttl:
                del self._cache[clean_host]
                return None
            return allowed

    def cache_put(self, host: str, allowed: bool, now: float) -> None:
        clean_host = host.strip().lower()
        with self._lock:
            self._cache[clean_host] = (allowed, now)

    def decide(self, status: int, body: str, path: str, user_agent_token: str) -> bool:
        if status == 404:
            return True
        if status in (401, 403) or status >= 500:
            return False
        if status == 200:
            try:
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(body.splitlines())
                return rp.can_fetch(user_agent_token, path)
            except Exception:
                return False
        return False
