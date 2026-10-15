"""Phase 23 Task 1 單元測試：網址政策、SSRF 驗證、節流與 Robots 策略。"""

import json
from pathlib import Path
import pytest

from src.scraper.policy import (
    DEFAULT_CONTACT_URL,
    DomainThrottle,
    PolicyError,
    RobotsPolicy,
    check_host_allowed,
    check_url_allowed,
    is_public_address,
    load_allowlist,
    resolve_public_addresses,
    strip_url_for_storage,
)


def test_sources_json_valid_and_matches_user_confirmation():
    """Test 9: sources.json 內容為有效 JSON，且僅含使用者確認之 www.nu-vendome.com 條目（2026-10-15 確認擴充至 /service/ 與 /service-detail/）。"""
    sources_path = Path(__file__).resolve().parent.parent / "data" / "scraper" / "sources.json"
    assert sources_path.is_file()
    data = json.loads(sources_path.read_text(encoding="utf-8"))
    assert "allowed_domains" in data
    assert len(data["allowed_domains"]) == 1
    entry = data["allowed_domains"][0]
    assert entry["host"] == "www.nu-vendome.com"
    assert entry["path_prefixes"] == ["/location-detail/", "/service/", "/service-detail/"]


def test_load_allowlist(tmp_path):
    """Test 1: load_allowlist 回傳規格化結構，缺檔、JSON 語法錯誤或缺少 allowed_domains 均拋 PolicyError。"""
    valid_file = tmp_path / "valid.json"
    valid_file.write_text(
        json.dumps(
            {
                "allowed_domains": [
                    {"host": "www.nu-vendome.com", "path_prefixes": ["/location-detail/"]}
                ]
            }
        ),
        encoding="utf-8",
    )

    loaded = load_allowlist(valid_file)
    assert "allowed_domains" in loaded
    assert "www.nu-vendome.com" in loaded["by_host"]

    # 缺檔
    with pytest.raises(PolicyError) as exc_info:
        load_allowlist(tmp_path / "non_existent.json")
    assert exc_info.value.reason == "bad_allowlist"

    # 語法錯誤
    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_text("{bad json", encoding="utf-8")
    with pytest.raises(PolicyError) as exc_info:
        load_allowlist(corrupt_file)
    assert exc_info.value.reason == "bad_allowlist"

    # 缺少 allowed_domains
    invalid_key_file = tmp_path / "invalid_key.json"
    invalid_key_file.write_text(json.dumps({"wrong_key": []}), encoding="utf-8")
    with pytest.raises(PolicyError) as exc_info:
        load_allowlist(invalid_key_file)
    assert exc_info.value.reason == "bad_allowlist"


def test_check_url_allowed_and_rejections():
    """Test 2 & Test 10: check_url_allowed 驗證 scheme, port, credentials, path_prefix, 裸網域拒絕。"""
    allowlist = {
        "allowed_domains": [
            {"host": "www.nu-vendome.com", "path_prefixes": ["/location-detail/"]}
        ],
        "by_host": {
            "www.nu-vendome.com": ["/location-detail/"]
        },
    }

    # 合法
    check_url_allowed("https://www.nu-vendome.com/location-detail/Taichung/", allowlist)
    check_url_allowed("https://www.nu-vendome.com/location-detail/Taipei?ref=1", allowlist)

    # 非 https (scheme)
    with pytest.raises(PolicyError) as exc:
        check_url_allowed("http://www.nu-vendome.com/location-detail/Taichung/", allowlist)
    assert exc.value.reason == "scheme"

    # port 8080 (port)
    with pytest.raises(PolicyError) as exc:
        check_url_allowed("https://www.nu-vendome.com:8080/location-detail/Taichung/", allowlist)
    assert exc.value.reason == "port"

    # credentials (credentials)
    with pytest.raises(PolicyError) as exc:
        check_url_allowed("https://user:pass@www.nu-vendome.com/location-detail/Taichung/", allowlist)
    assert exc.value.reason == "credentials"

    # 未列入網域 (not_allowlisted)
    with pytest.raises(PolicyError) as exc:
        check_url_allowed("https://example.com/location-detail/Taichung/", allowlist)
    assert exc.value.reason == "not_allowlisted"

    # 裸網域未在白名單 (Test 10)
    with pytest.raises(PolicyError) as exc:
        check_url_allowed("https://nu-vendome.com/location-detail/Taichung/", allowlist)
    assert exc.value.reason == "not_allowlisted"

    # 路徑前綴不符 (not_allowlisted)
    with pytest.raises(PolicyError) as exc:
        check_url_allowed("https://www.nu-vendome.com/about/", allowlist)
    assert exc.value.reason == "not_allowlisted"

    # 不合法 URL (bad_url)
    with pytest.raises(PolicyError) as exc:
        check_url_allowed("not_a_valid_url", allowlist)
    assert exc.value.reason == "bad_url"


def test_check_host_allowed():
    """Test 3: check_host_allowed 僅檢查 host 是否在白名單，供 robots.txt 使用。"""
    allowlist = {
        "by_host": {
            "www.nu-vendome.com": ["/location-detail/"]
        }
    }
    check_host_allowed("www.nu-vendome.com", allowlist)

    with pytest.raises(PolicyError) as exc:
        check_host_allowed("nu-vendome.com", allowlist)
    assert exc.value.reason == "not_allowlisted"

    with pytest.raises(PolicyError) as exc:
        check_host_allowed("example.org", allowlist)
    assert exc.value.reason == "not_allowlisted"


def test_is_public_address():
    """Test 4: is_public_address 嚴格判定公網位址，排除私有、迴圈、CGNAT、IPv4-mapped 等。"""
    # 公網 IPv4
    assert is_public_address("8.8.8.8") is True
    assert is_public_address("1.1.1.1") is True

    # 公網 IPv6
    assert is_public_address("2606:4700:4700::1111") is True

    # 私有 IPv4
    assert is_public_address("10.0.0.1") is False
    assert is_public_address("172.16.0.1") is False
    assert is_public_address("192.168.1.1") is False

    # 迴圈與未指定
    assert is_public_address("127.0.0.1") is False
    assert is_public_address("0.0.0.0") is False
    assert is_public_address("::1") is False
    assert is_public_address("::") is False

    # CGNAT (100.64.0.0/10)
    assert is_public_address("100.64.0.1") is False
    assert is_public_address("100.127.255.254") is False

    # Link-local
    assert is_public_address("169.254.1.1") is False
    assert is_public_address("fe80::1") is False

    # IPv4-mapped IPv6
    assert is_public_address("::ffff:127.0.0.1") is False
    assert is_public_address("::ffff:10.0.0.1") is False
    assert is_public_address("::ffff:8.8.8.8") is True

    # 非法 IP
    assert is_public_address("invalid-ip") is False


def test_resolve_public_addresses():
    """Test 5: resolve_public_addresses 解析 A/AAAA，任一位址非公網則拋 PolicyError(reason='private_address')。"""
    # 模擬 resolver 回傳公網 IP
    def mock_public_resolver(host):
        return ["8.8.8.8", "2001:4860:4860::8888"]

    addrs = resolve_public_addresses("www.google.com", resolver=mock_public_resolver)
    assert "8.8.8.8" in addrs

    # 模擬 resolver 回傳包含私有 IP
    def mock_private_resolver(host):
        return ["8.8.8.8", "10.0.0.1"]

    with pytest.raises(PolicyError) as exc:
        resolve_public_addresses("test.local", resolver=mock_private_resolver)
    assert exc.value.reason == "private_address"

    # 模擬 resolver 無結果
    def mock_empty_resolver(host):
        return []

    with pytest.raises(PolicyError) as exc:
        resolve_public_addresses("empty.local", resolver=mock_empty_resolver)
    assert exc.value.reason == "dns_resolution"


def test_strip_url_for_storage():
    """Test 6 & Test 11b: strip_url_for_storage 清洗 URL，只保留 scheme/host/path，支援 fixture://。"""
    # https
    assert (
        strip_url_for_storage("https://www.nu-vendome.com/location-detail/Taichung/?token=abc#section")
        == "https://www.nu-vendome.com/location-detail/Taichung/"
    )
    assert (
        strip_url_for_storage("https://user:pass@www.nu-vendome.com/location-detail///Taichung")
        == "https://www.nu-vendome.com/location-detail/Taichung"
    )

    # fixture://
    assert strip_url_for_storage("fixture://sample_a.html") == "fixture://sample_a.html"

    # fixture 路徑穿越拒絕 (bad_url)
    with pytest.raises(PolicyError) as exc:
        strip_url_for_storage("fixture://dir/a.html")
    assert exc.value.reason == "bad_url"

    with pytest.raises(PolicyError) as exc:
        strip_url_for_storage("fixture://../a.html")
    assert exc.value.reason == "bad_url"

    # 非 https 且非 fixture (bad_url)
    with pytest.raises(PolicyError) as exc:
        strip_url_for_storage("http://x.com/a")
    assert exc.value.reason == "bad_url"

    with pytest.raises(PolicyError) as exc:
        strip_url_for_storage("ftp://x.com/a")
    assert exc.value.reason == "bad_url"


def test_domain_throttle():
    """Test 7: DomainThrottle 節流測試，不同 host 獨立計時，間隔 < 3.0 拋 PolicyError。"""
    # 間隔過短
    with pytest.raises(PolicyError) as exc:
        DomainThrottle(min_interval=2.5)
    assert exc.value.reason == "interval_too_short"

    simulated_time = 100.0
    sleeps = []

    def mock_clock():
        return simulated_time

    def mock_sleep(seconds):
        nonlocal simulated_time
        sleeps.append(seconds)
        simulated_time += seconds

    throttle = DomainThrottle(min_interval=5.0, clock=mock_clock, sleep=mock_sleep)

    # 第一次請求 host A，不 sleep
    throttle.wait_turn("a.com")
    assert len(sleeps) == 0

    # 1 秒後請求 host A，需 sleep 4 秒
    simulated_time += 1.0
    throttle.wait_turn("a.com")
    assert len(sleeps) == 1
    assert sleeps[-1] == pytest.approx(4.0)

    # 請求不同 host B，不需 sleep
    throttle.wait_turn("b.com")
    assert len(sleeps) == 1


def test_robots_policy():
    """Test 8: RobotsPolicy 遵循 404 放行、401/403/5xx/例外拒絕、200 比對 UA。"""
    policy = RobotsPolicy()

    # 404 放行
    assert policy.decide(404, "", "/location-detail/Taichung/", "ClinicBrainSiteReader") is True

    # 403 / 500 拒絕
    assert policy.decide(403, "", "/location-detail/Taichung/", "ClinicBrainSiteReader") is False
    assert policy.decide(500, "", "/location-detail/Taichung/", "ClinicBrainSiteReader") is False

    # 200 內容解析
    robots_txt = """
User-agent: *
Disallow: /admin/

User-agent: ClinicBrainSiteReader
Disallow: /private/
Allow: /location-detail/
"""
    assert policy.decide(200, robots_txt, "/location-detail/Taichung/", "ClinicBrainSiteReader") is True
    assert policy.decide(200, robots_txt, "/private/secret", "ClinicBrainSiteReader") is False

    # 快取功能
    policy.cache_put("www.nu-vendome.com", True, now=1000.0)
    assert policy.cache_get("www.nu-vendome.com", now=1005.0) is True
    # 過期 (TTL 3600 秒)
    assert policy.cache_get("www.nu-vendome.com", now=5000.0) is None


def test_default_contact_url():
    """Test 11: 預設聯絡網址常數為 https://doctor-toolbox.com/clinicBot，且不含 email。"""
    assert DEFAULT_CONTACT_URL == "https://doctor-toolbox.com/clinicBot"
    assert "@" not in DEFAULT_CONTACT_URL
    assert DEFAULT_CONTACT_URL.startswith("https://")
