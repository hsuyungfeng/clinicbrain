"""Phase 23 Task 1 & Task 2 單元測試：報告資料結構、安全日誌與批次編排。"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import pytest

from src.scraper.policy import PolicyError
from src.scraper.report import (
    BatchReport,
    UrlOutcome,
    path_hint,
    safe_log_line,
)
from src.scraper.runner import (
    OWNERSHIP_FILE,
    ScrapeOptions,
    check_ownership_confirmation,
    run_scrape_urls,
    scrape_one_url,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scraper"
SAMPLE_A_HTML = (FIXTURES_DIR / "clinic_sample_a.html").read_text(encoding="utf-8")
MISSING_HTML = (FIXTURES_DIR / "clinic_missing_fields.html").read_text(encoding="utf-8")
SOURCES_JSON = Path(__file__).parents[1] / "data" / "scraper" / "sources.json"


# =========================================================================
# Task 1 測試：報告資料結構與安全日誌
# =========================================================================

def test_url_outcome_to_dict_keys_and_privacy():
    """Task 1 Test 1 & 5: UrlOutcome.to_dict() 嚴格限定 keys，不含 url、html、醫師姓名與內文。"""
    outcome = UrlOutcome(
        host="www.example.com",
        path_hint="/location-detail/Taichung",
        status="ok",
        reason="",
        drafts_count=3,
        rejected_count=1,
        schema_drift=False,
        doctors_count=2,
        html_bytes=1024,
        url="https://www.example.com/location-detail/Taichung?token=secret#section",
    )
    d = outcome.to_dict()
    expected_keys = {
        "host",
        "path_hint",
        "status",
        "reason",
        "drafts_count",
        "rejected_count",
        "schema_drift",
        "doctors_count",
        "html_bytes",
    }
    assert set(d.keys()) == expected_keys
    assert "url" not in d
    assert "token" not in json.dumps(d)
    assert isinstance(d["doctors_count"], int)
    assert d["doctors_count"] == 2


def test_batch_report_to_json_and_summary_fields():
    """Task 1 Test 2: BatchReport.to_json() 可解析，summary 欄位齊全且不含上限截斷欄位。"""
    outcomes = [
        UrlOutcome(host="x.com", path_hint="/a/b", status="ok", drafts_count=2, html_bytes=500),
        UrlOutcome(host="x.com", path_hint="/c/d", status="failed", reason="network", html_bytes=0),
        UrlOutcome(host="y.com", path_hint="/e/f", status="skipped", reason="not_allowlisted", html_bytes=0),
        UrlOutcome(host="x.com", path_hint="/g/h", status="failed", schema_drift=True, reason="schema_drift", html_bytes=300),
    ]
    report = BatchReport(
        outcomes=outcomes,
        started_at="2026-10-14T08:00:00Z",
        finished_at="2026-10-14T08:01:00Z",
        status="ok",
        drafts_written=2,
        unchanged=1,
        fetched_count=2,
    )
    json_str = report.to_json()
    parsed = json.loads(json_str)

    assert parsed["status"] == "ok"
    summary = parsed["summary"]
    assert summary["total"] == 4
    assert summary["ok"] == 1
    assert summary["failed"] == 2
    assert summary["schema_drift"] == 1
    assert summary["drafts_written"] == 2
    assert summary["unchanged"] == 1
    assert summary["skipped_by_policy"] == 1
    assert summary["skipped_locked"] is False
    assert summary["fetched_count"] == 2
    assert summary["total_html_bytes"] == 800
    assert "skipped_over_limit" not in summary
    assert "max_pages" not in summary


def test_safe_log_line():
    """Task 1 Test 3: safe_log_line 輸出格式正確，不含敏感文字。"""
    outcome = UrlOutcome(
        host="www.example.com",
        path_hint="/location/test",
        status="ok",
        reason="",
        drafts_count=5,
        url="https://www.example.com/location/test?patient=secret",
    )
    line = safe_log_line(outcome)
    assert line == "scrape host=www.example.com path=/location/test status=ok reason= drafts=5"
    assert "secret" not in line
    assert "patient" not in line


def test_path_hint():
    """Task 1 Test 4: path_hint 正確取前兩段並剔除 query string 與 fragment。"""
    assert path_hint("https://x.com/a/b/c?token=1#f") == "/a/b"
    assert path_hint("https://x.com/a") == "/a"
    assert path_hint("https://x.com/") == "/"
    assert path_hint("fixture://sample_a.html?secret=1") == "/sample_a.html"
    assert path_hint("") == "/"


# =========================================================================
# Task 2 測試：批次編排器 (runner)
# =========================================================================

def _fake_resolver(host: str) -> list[str]:
    return ["93.184.216.34"]


def test_runner_partial_fetch_failure(tmp_path, isolated_conn):
    """Task 2 Test 1: 三個網址，中間一個 fetch 失敗，報告 total=3, failed=1, 其餘兩筆寫入草稿。"""
    urls = [
        "https://www.nu-vendome.com/location-detail/1/",
        "https://www.nu-vendome.com/location-detail/fail/",
        "https://www.nu-vendome.com/location-detail/2/",
    ]
    options = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=OWNERSHIP_FILE,
        write=True,
        db_path=tmp_path / "fake.db",
    )

    sample_b_html = SAMPLE_A_HTML.replace("極致皮秒蜂巢雷射", "水飛梭深層淨膚保養").replace("果酸煥膚角質調理", "音波拉提緊緻肌膚保養")

    def fake_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return 404, {}, b""
        if "fail" in path:
            raise OSError("network drop")
        if "/2/" in path:
            return 200, {"content-type": "text/html; charset=utf-8"}, sample_b_html.encode("utf-8")
        return 200, {"content-type": "text/html; charset=utf-8"}, SAMPLE_A_HTML.encode("utf-8")

    report = run_scrape_urls(
        urls,
        options=options,
        resolver=_fake_resolver,
        http_get=fake_http_get,
        sleep=lambda s: None,
        conn_factory=lambda: isolated_conn,
        lock_try=lambda p: 101,
        lock_release=lambda fd: None,
    )

    assert report.summary["total"] == 3
    assert report.summary["ok"] == 2
    assert report.summary["failed"] == 1
    assert report.summary["drafts_written"] == 4  # 每個 sample_a 有 2 個 service
    assert report.outcomes[1].status == "failed"
    assert report.outcomes[1].reason == "network"


def test_runner_schema_drift(tmp_path, isolated_conn):
    """Task 2 Test 2: extract 為 schema_drift 時，該筆 outcome.schema_drift=True，不寫入草稿。"""
    urls = [
        "https://www.nu-vendome.com/location-detail/normal/",
        "https://www.nu-vendome.com/location-detail/drift/",
    ]
    options = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=OWNERSHIP_FILE,
        write=True,
        db_path=tmp_path / "fake.db",
    )

    def fake_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return 404, {}, b""
        if "drift" in path:
            return 200, {"content-type": "text/html; charset=utf-8"}, MISSING_HTML.encode("utf-8")
        return 200, {"content-type": "text/html; charset=utf-8"}, SAMPLE_A_HTML.encode("utf-8")

    report = run_scrape_urls(
        urls,
        options=options,
        resolver=_fake_resolver,
        http_get=fake_http_get,
        sleep=lambda s: None,
        conn_factory=lambda: isolated_conn,
        lock_try=lambda p: 101,
        lock_release=lambda fd: None,
    )

    assert report.summary["total"] == 2
    assert report.summary["ok"] == 1
    assert report.summary["failed"] == 1
    assert report.summary["schema_drift"] == 1
    assert report.outcomes[1].schema_drift is True
    assert report.outcomes[1].reason == "schema_drift"
    assert report.summary["drafts_written"] == 2


def test_runner_unallowlisted_url(tmp_path):
    """Task 2 Test 3: 封閉模式下白名單外網址，outcome.reason='not_allowlisted'，計入 skipped_by_policy，HTTP 請求數為 0。"""
    closed_allowlist = tmp_path / "closed_sources.json"
    closed_allowlist.write_text(
        json.dumps({
            "open_access": False,
            "allowed_domains": [{"host": "www.nu-vendome.com", "path_prefixes": ["/location-detail/"]}]
        }),
        encoding="utf-8",
    )
    urls = [
        "https://www.evil-site.com/location-detail/1/",
        "https://www.nu-vendome.com/other-path/secret",
    ]
    options = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=closed_allowlist,
        ownership_path=OWNERSHIP_FILE,
        write=False,
    )

    http_calls = []

    def fake_http_get(pinned_ip, host, path, headers, **kwargs):
        http_calls.append(path)
        return 200, {}, b""

    report = run_scrape_urls(
        urls,
        options=options,
        resolver=_fake_resolver,
        http_get=fake_http_get,
        sleep=lambda s: None,
    )

    assert len(http_calls) == 0
    assert report.summary["total"] == 2
    assert report.summary["skipped_by_policy"] == 2
    assert report.outcomes[0].reason == "not_allowlisted"
    assert report.outcomes[1].reason == "not_allowlisted"


def test_runner_unexpected_write_exception(tmp_path, isolated_conn, monkeypatch):
    """Task 2 Test 4: 任一網址寫入拋出非預期例外時，呼叫 conn.rollback()，該筆 reason='unexpected'，其餘不受影響。"""
    urls = [
        "https://www.nu-vendome.com/location-detail/1/",
        "https://www.nu-vendome.com/location-detail/err/",
        "https://www.nu-vendome.com/location-detail/2/",
    ]
    options = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=OWNERSHIP_FILE,
        write=True,
        db_path=tmp_path / "fake.db",
    )

    import src.scraper.runner as runner_mod

    orig_write = runner_mod.write_faq_drafts

    def mock_write(conn, drafts):
        for d in drafts:
            if "location-detail/err" in d.get("metadata", ""):
                raise RuntimeError("disk failure simulation")
        return orig_write(conn, drafts)

    monkeypatch.setattr(runner_mod, "write_faq_drafts", mock_write)

    sample_b_html = SAMPLE_A_HTML.replace("極致皮秒蜂巢雷射", "水飛梭深層淨膚保養").replace("果酸煥膚角質調理", "音波拉提緊緻肌膚保養")

    def fake_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return 404, {}, b""
        if "/2/" in path:
            return 200, {"content-type": "text/html; charset=utf-8"}, sample_b_html.encode("utf-8")
        return 200, {"content-type": "text/html; charset=utf-8"}, SAMPLE_A_HTML.encode("utf-8")

    report = run_scrape_urls(
        urls,
        options=options,
        resolver=_fake_resolver,
        http_get=fake_http_get,
        sleep=lambda s: None,
        conn_factory=lambda: isolated_conn,
        lock_try=lambda p: 101,
        lock_release=lambda fd: None,
    )

    assert report.summary["total"] == 3
    assert report.summary["ok"] == 2
    assert report.summary["failed"] == 1
    assert report.outcomes[1].reason == "unexpected"
    assert report.summary["drafts_written"] == 4


def test_runner_throttle_and_event_sequence(tmp_path):
    """Task 2 Test 5: 同網域三筆，throttle 逐請求套用。"""
    urls = [
        "https://www.nu-vendome.com/location-detail/1/",
        "https://www.nu-vendome.com/location-detail/2/",
        "https://www.nu-vendome.com/location-detail/3/",
    ]
    options = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=OWNERSHIP_FILE,
        write=False,
        min_interval=5.0,
    )

    time_val = 1000.0
    sleeps = []

    def fake_clock():
        return time_val

    def fake_sleep(sec):
        nonlocal time_val
        sleeps.append(sec)
        time_val += sec

    def fake_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return 404, {}, b""
        return 200, {"content-type": "text/html; charset=utf-8"}, SAMPLE_A_HTML.encode("utf-8")

    report = run_scrape_urls(
        urls,
        options=options,
        resolver=_fake_resolver,
        http_get=fake_http_get,
        clock=fake_clock,
        sleep=fake_sleep,
    )

    assert report.summary["total"] == 3
    # robots 請求 1 次 + 3 次頁面請求 = 4 次請求，後 3 次觸發 sleep
    assert len(sleeps) >= 2


def test_runner_dry_run_behavior(tmp_path):
    """Task 2 Test 6: dry-run (write=False) 不呼叫 conn_factory、不呼叫鎖、drafts_written=0。"""
    urls = ["https://www.nu-vendome.com/location-detail/1/"]
    options = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=OWNERSHIP_FILE,
        write=False,
    )

    conn_called = False
    lock_called = False

    def fake_conn():
        nonlocal conn_called
        conn_called = True
        return None

    def fake_lock(p):
        nonlocal lock_called
        lock_called = True
        return 101

    def fake_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return 404, {}, b""
        return 200, {"content-type": "text/html; charset=utf-8"}, SAMPLE_A_HTML.encode("utf-8")

    report = run_scrape_urls(
        urls,
        options=options,
        resolver=_fake_resolver,
        http_get=fake_http_get,
        sleep=lambda s: None,
        conn_factory=fake_conn,
        lock_try=fake_lock,
    )

    assert not conn_called
    assert not lock_called
    assert report.summary["drafts_written"] == 0
    assert report.outcomes[0].drafts_count == 2


def test_runner_lock_probe_skipped(tmp_path):
    """Task 2 Test 7: write=True 時，抓取前探測鎖返回 None，立即回傳 skipped_locked，零網路請求。"""
    urls = ["https://www.nu-vendome.com/location-detail/1/"]
    options = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=OWNERSHIP_FILE,
        write=True,
        db_path=tmp_path / "fake.db",
    )

    http_calls = []
    resolver_calls = []

    def fake_http_get(pinned_ip, host, path, headers, **kwargs):
        http_calls.append(path)
        return 200, {}, b""

    def fake_resolver(h):
        resolver_calls.append(h)
        return ["93.184.216.34"]

    report = run_scrape_urls(
        urls,
        options=options,
        resolver=fake_resolver,
        http_get=fake_http_get,
        sleep=lambda s: None,
        lock_try=lambda p: None,  # 持鎖探測失敗
    )

    assert report.status == "skipped_locked"
    assert report.summary["skipped_locked"] is True
    assert len(http_calls) == 0
    assert len(resolver_calls) == 0


def test_runner_authoritative_lock_skipped(tmp_path):
    """Task 2 Test 7b: write=True，探測成功但寫入階段權威取鎖失敗，回傳 skipped_locked，抓取數 > 0，釋放探測 fd。"""
    urls = ["https://www.nu-vendome.com/location-detail/1/"]
    options = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=OWNERSHIP_FILE,
        write=True,
        db_path=tmp_path / "fake.db",
    )

    lock_calls = 0
    released_fds = []

    def mock_lock_try(p):
        nonlocal lock_calls
        lock_calls += 1
        if lock_calls == 1:
            return 999  # 探測成功
        return None  # 寫入階段失敗

    def mock_release(fd):
        released_fds.append(fd)

    def fake_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return 404, {}, b""
        return 200, {"content-type": "text/html; charset=utf-8"}, SAMPLE_A_HTML.encode("utf-8")

    report = run_scrape_urls(
        urls,
        options=options,
        resolver=_fake_resolver,
        http_get=fake_http_get,
        sleep=lambda s: None,
        lock_try=mock_lock_try,
        lock_release=mock_release,
    )

    assert report.status == "skipped_locked"
    assert report.summary["fetched_count"] > 0
    assert 999 in released_fds


def test_runner_probe_before_get(tmp_path):
    """Task 2 Test 7c: write=True 時，事件序列中 probe 事件早於所有 get 事件。"""
    urls = ["https://www.nu-vendome.com/location-detail/1/"]
    options = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=OWNERSHIP_FILE,
        write=True,
        db_path=tmp_path / "fake.db",
    )

    events = []

    def on_event(ev):
        events.append(ev)

    def fake_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return 404, {}, b""
        return 200, {"content-type": "text/html; charset=utf-8"}, SAMPLE_A_HTML.encode("utf-8")

    run_scrape_urls(
        urls,
        options=options,
        resolver=_fake_resolver,
        http_get=fake_http_get,
        sleep=lambda s: None,
        lock_try=lambda p: 101,
        lock_release=lambda fd: None,
        on_event=on_event,
    )

    assert "probe" in events
    assert "get" in events
    probe_idx = events.index("probe")
    get_idx = events.index("get")
    assert probe_idx < get_idx


def test_runner_transaction_isolation(tmp_path, isolated_conn, monkeypatch):
    """Task 2 Test 8: 每個網址獨立交易，第一筆成功提交、第二筆失敗 rollback，第一筆仍在。"""
    urls = [
        "https://www.nu-vendome.com/location-detail/1/",
        "https://www.nu-vendome.com/location-detail/fail_tx/",
    ]
    options = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=OWNERSHIP_FILE,
        write=True,
        db_path=tmp_path / "fake.db",
    )

    import src.scraper.runner as runner_mod

    orig_write = runner_mod.write_faq_drafts

    def mock_write(conn, drafts):
        for d in drafts:
            if "fail_tx" in d.get("metadata", ""):
                raise ValueError("tx fail")
        return orig_write(conn, drafts)

    monkeypatch.setattr(runner_mod, "write_faq_drafts", mock_write)

    def fake_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return 404, {}, b""
        return 200, {"content-type": "text/html; charset=utf-8"}, SAMPLE_A_HTML.encode("utf-8")

    report = run_scrape_urls(
        urls,
        options=options,
        resolver=_fake_resolver,
        http_get=fake_http_get,
        sleep=lambda s: None,
        conn_factory=lambda: isolated_conn,
        lock_try=lambda p: 101,
        lock_release=lambda fd: None,
    )

    assert report.summary["ok"] == 1
    assert report.summary["failed"] == 1
    assert report.summary["drafts_written"] == 2

    # 查證資料庫
    cur = isolated_conn.execute("SELECT COUNT(*) FROM faq_cache WHERE topic_key LIKE 'web-%' AND metadata NOT LIKE '%service-detail%'")
    assert cur.fetchone()[0] == 2


def test_runner_fetch_before_write(tmp_path, isolated_conn):
    """Task 2 Test 9: 先抓後寫：所有 get 事件早於第一個 write 事件。"""
    urls = [
        "https://www.nu-vendome.com/location-detail/1/",
        "https://www.nu-vendome.com/location-detail/2/",
    ]
    options = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=OWNERSHIP_FILE,
        write=True,
        db_path=tmp_path / "fake.db",
    )

    events = []

    def on_event(ev):
        events.append(ev)

    def fake_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return 404, {}, b""
        return 200, {"content-type": "text/html; charset=utf-8"}, SAMPLE_A_HTML.encode("utf-8")

    run_scrape_urls(
        urls,
        options=options,
        resolver=_fake_resolver,
        http_get=fake_http_get,
        sleep=lambda s: None,
        conn_factory=lambda: isolated_conn,
        lock_try=lambda p: 101,
        lock_release=lambda fd: None,
        on_event=on_event,
    )

    # 找到最後一個 get 與第一個 write
    last_get = max(i for i, ev in enumerate(events) if ev == "get")
    first_write = min(i for i, ev in enumerate(events) if ev == "write")
    assert last_get < first_write


def test_runner_no_page_limit_and_total_bytes(tmp_path):
    """Task 2 Test 10: 不設頁數上限，傳入 45 個網址全部被抓取，計數正確，無 skipped_over_limit。"""
    urls = [f"https://www.nu-vendome.com/location-detail/{i}/" for i in range(45)]
    options = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=OWNERSHIP_FILE,
        write=False,
    )

    def fake_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return 404, {}, b""
        return 200, {"content-type": "text/html; charset=utf-8"}, SAMPLE_A_HTML.encode("utf-8")

    report = run_scrape_urls(
        urls,
        options=options,
        resolver=_fake_resolver,
        http_get=fake_http_get,
        sleep=lambda s: None,
    )

    assert report.summary["total"] == 45
    assert report.summary["ok"] == 45
    assert "skipped_over_limit" not in report.summary
    expected_bytes = len(SAMPLE_A_HTML.encode("utf-8")) * 45
    assert report.summary["total_html_bytes"] == expected_bytes


def test_runner_no_html_files_written(tmp_path, isolated_conn):
    """Task 2 Test 11: 整個流程結束後，不產生任何 html 檔案。"""
    urls = ["https://www.nu-vendome.com/location-detail/1/"]
    options = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=OWNERSHIP_FILE,
        write=True,
        db_path=tmp_path / "fake.db",
    )

    def fake_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return 404, {}, b""
        return 200, {"content-type": "text/html; charset=utf-8"}, SAMPLE_A_HTML.encode("utf-8")

    run_scrape_urls(
        urls,
        options=options,
        resolver=_fake_resolver,
        http_get=fake_http_get,
        sleep=lambda s: None,
        conn_factory=lambda: isolated_conn,
        lock_try=lambda p: 101,
        lock_release=lambda fd: None,
    )

    html_files = list(tmp_path.glob("*.html"))
    assert len(html_files) == 0


def test_runner_ownership_gate(tmp_path):
    """Task 2 Test 12: 擁有權確認閘門 (a) 缺檔 (b) confirmed_by_user=False (c) domain 未涵蓋 (d) 正常。"""
    urls = ["https://www.nu-vendome.com/location-detail/1/"]

    # (a) 缺檔
    opts_no_file = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=tmp_path / "non_existent.json",
        write=False,
    )
    with pytest.raises(PolicyError) as exc_a:
        run_scrape_urls(urls, options=opts_no_file)
    assert exc_a.value.reason == "ownership_unconfirmed"

    # (b) confirmed_by_user 為 False
    bad_b = tmp_path / "bad_b.json"
    bad_b.write_text(json.dumps({"domain": "nu-vendome.com", "confirmed_by_user": False}), encoding="utf-8")
    opts_bad_b = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=bad_b,
        write=False,
    )
    with pytest.raises(PolicyError) as exc_b:
        run_scrape_urls(urls, options=opts_bad_b)
    assert exc_b.value.reason == "ownership_unconfirmed"

    # (c) domain 未涵蓋白名單 host
    bad_c = tmp_path / "bad_c.json"
    bad_c.write_text(json.dumps({"domain": "other-clinic.com", "confirmed_by_user": True}), encoding="utf-8")
    opts_bad_c = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=bad_c,
        write=False,
    )
    with pytest.raises(PolicyError) as exc_c:
        run_scrape_urls(urls, options=opts_bad_c)
    assert exc_c.value.reason == "ownership_unconfirmed"

    # (d) 正常通過
    good_d = tmp_path / "good_d.json"
    good_d.write_text(json.dumps({"domain": "nu-vendome.com", "confirmed_by_user": True}), encoding="utf-8")
    opts_good_d = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=good_d,
        write=False,
    )

    def fake_http_get(pinned_ip, host, path, headers, **kwargs):
        if path == "/robots.txt":
            return 404, {}, b""
        return 200, {"content-type": "text/html; charset=utf-8"}, SAMPLE_A_HTML.encode("utf-8")

    report = run_scrape_urls(
        urls,
        options=opts_good_d,
        resolver=_fake_resolver,
        http_get=fake_http_get,
        sleep=lambda s: None,
    )
    assert report.status == "ok"


def test_runner_fixture_url_exempt_from_ownership(tmp_path, isolated_conn):
    """Task 2 Test 13: 僅含 fixture:// 來源時，不需 ownership 檔即可執行 dry-run 與寫入。"""
    urls = ["fixture://sample_a.html"]
    opts = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        ownership_path=tmp_path / "non_existent.json",  # 故意指向不存在路徑
        write=True,
        db_path=tmp_path / "fake.db",
        fixture_map={"sample_a.html": SAMPLE_A_HTML},
    )

    report = run_scrape_urls(
        urls,
        options=opts,
        conn_factory=lambda: isolated_conn,
        lock_try=lambda p: 101,
        lock_release=lambda fd: None,
    )

    assert report.status == "ok"
    assert report.summary["ok"] == 1
    assert report.summary["drafts_written"] == 2
