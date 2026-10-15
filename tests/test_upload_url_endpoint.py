"""
Integration, security, and contract tests for POST /api/v1/admin/upload-url.
Plan 24-02 Task 3:
- SSRF prevention (unsafe schemes, private IPs, localhost, port != 443).
- Display name validation (mandatory, deidentified, masked).
- Target check (faq only).
- Offline fixture pipeline with dependency injection (get_url_fetch_deps).
- Preview vs. Write modes.
- Provenance metadata formatting and zero doctors leakage.
- Identity stripping and drift defense.
- Phase 23 contract tests (pinned_addresses, allowlist, redirect hops).
"""

from collections.abc import Generator
import inspect
import json
import logging
from pathlib import Path
import sqlite3
import pytest
from starlette.testclient import TestClient

from src.api.app import app
from src.api.config import config
from src.api.routes.admin import (
    _URL_FETCH_LOCK,
    get_url_fetch_deps,
    upload_admin_file,
    upload_admin_url,
)
from src.ingestion.url_guard import UnsafeUrlError, validate_public_url
from src.pageindex.web_source_adapter import (
    UrlFetchDeps,
    UrlFetchError,
    UrlPageResult,
    build_service_text,
    optional_missing_fields,
)
from src.scraper.extract import ExtractedClinicPage, extract_clinic_page
from src.scraper.fetch import build_user_agent, fetch_page
from src.scraper.policy import DomainThrottle, PolicyError, RobotsPolicy

CLINIC_ID = "3503190424"
SAMPLE_A_PATH = Path("tests/fixtures/scraper/clinic_sample_a.html")


@pytest.fixture
def isolated_db_path(tmp_path: Path):
    """提供乾淨且已套用 review_status 與 metadata 欄位的 SQLite 測試庫（測試後刪除副本）。"""
    src_db = Path("clinic.db")
    isolated = tmp_path / "clinic_isolated.db"

    conn_src = sqlite3.connect(str(src_db))
    conn_iso = sqlite3.connect(str(isolated))
    conn_src.backup(conn_iso)
    conn_src.close()

    # 確保 faq_cache 包含 review_status 與 metadata 欄位
    cur = conn_iso.cursor()
    columns = [row[1] for row in cur.execute("PRAGMA table_info(faq_cache)").fetchall()]
    if "review_status" not in columns:
        cur.execute("ALTER TABLE faq_cache ADD COLUMN review_status TEXT NOT NULL DEFAULT 'approved'")
    if "metadata" not in columns:
        cur.execute("ALTER TABLE faq_cache ADD COLUMN metadata TEXT")
    conn_iso.commit()
    conn_iso.close()

    yield isolated
    # 測試結束即刪除副本（每份約 45 MB；不清理會耗盡 /tmp 配額）
    isolated.unlink(missing_ok=True)


@pytest.fixture
def client(isolated_db_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    assert isolated_db_path != config.db_path, "禁止指向正式 clinic.db"
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "admin_api_key", "")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _make_mock_deps(
    *,
    html: str = "",
    robots_status: int = 404,
    page_status: int = 200,
    resolver_ips: list[str] | None = None,
    http_error: Exception | None = None,
) -> tuple[UrlFetchDeps, list[dict]]:
    """建立測試用 UrlFetchDeps 與呼叫記錄器。"""
    calls: list[dict] = []
    ips = resolver_ips if resolver_ips is not None else ["93.184.216.34"]

    def _resolver(host: str, *args, **kwargs):
        return ips

    def _http_get(pinned_ip: str, host: str, path: str, headers: dict, *args, **kwargs):
        calls.append({
            "pinned_ip": pinned_ip,
            "host": host,
            "path": path,
            "headers": headers,
        })
        if http_error:
            raise http_error

        if path.endswith("/robots.txt"):
            if robots_status == 403:
                return 403, {"content-type": "text/plain"}, b"User-agent: *\nDisallow: /"
            return robots_status, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /"

        content = html.encode("utf-8")
        return page_status, {"content-type": "text/html; charset=utf-8"}, content

    allowlist = {
        "allowed_domains": [
            {
                "host": "www.nu-vendome.com",
                "path_prefixes": ["/location-detail/"],
            }
        ],
        "by_host": {
            "www.nu-vendome.com": ["/location-detail/"],
        },
    }

    clock_val = [1000.0]

    def _clock():
        return clock_val[0]

    def _sleep(sec):
        clock_val[0] += sec

    deps = UrlFetchDeps(
        allowlist=allowlist,
        throttle=DomainThrottle(min_interval=5.0, clock=_clock, sleep=_sleep),
        robots=RobotsPolicy(),
        user_agent=build_user_agent(),
        resolver=_resolver,
        http_get=_http_get,
    )
    return deps, calls


# =========================================================================
# SSRF 與前置參數防禦測試
# =========================================================================

def test_unsafe_scheme_rejected(client: TestClient):
    deps, calls = _make_mock_deps()
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "http://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": CLINIC_ID,
            "name": "測試名稱",
        },
    )
    assert resp.status_code == 400
    assert len(calls) == 0


def test_private_ip_rejected(client: TestClient):
    deps, calls = _make_mock_deps(resolver_ips=["10.0.0.5"])
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": CLINIC_ID,
            "name": "測試名稱",
        },
    )
    assert resp.status_code == 400
    assert len(calls) == 0


def test_localhost_rejected_without_flag_or_env(client: TestClient):
    deps, calls = _make_mock_deps(resolver_ips=["127.0.0.1"])
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    for u in ["http://localhost:8080/", "https://localhost/"]:
        resp = client.post(
            "/api/v1/admin/upload-url",
            data={
                "url": u,
                "clinic_id": CLINIC_ID,
                "name": "測試名稱",
            },
        )
        assert resp.status_code == 400
        assert len(calls) == 0


def test_port_80_and_8443_rejected(client: TestClient):
    deps, calls = _make_mock_deps()
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    for u in [
        "https://www.nu-vendome.com:80/location-detail/Taichung/",
        "https://www.nu-vendome.com:8443/location-detail/Taichung/",
    ]:
        resp = client.post(
            "/api/v1/admin/upload-url",
            data={"url": u, "clinic_id": CLINIC_ID, "name": "測試名稱"},
        )
        assert resp.status_code == 400
        assert len(calls) == 0


def test_missing_name_400(client: TestClient):
    deps, calls = _make_mock_deps()
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": CLINIC_ID,
            "name": "   ",
        },
    )
    assert resp.status_code == 400
    assert len(calls) == 0


def test_name_with_phone_400(client: TestClient):
    deps, calls = _make_mock_deps()
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": CLINIC_ID,
            "name": "請聯絡 0912-345-678 專案",
        },
    )
    assert resp.status_code == 400
    assert len(calls) == 0


def test_target_tree_rejected_400(client: TestClient):
    deps, calls = _make_mock_deps()
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": CLINIC_ID,
            "name": "測試項目",
            "target": "tree",
        },
    )
    assert resp.status_code == 400
    assert "僅支援常見問答" in resp.json()["detail"]
    assert len(calls) == 0


def test_user_agent_is_fixed_and_env_free(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    expected_ua = "ClinicBrainSiteReader/0.1 (+https://doctor-toolbox.com/clinicBot)"
    html = SAMPLE_A_PATH.read_text(encoding="utf-8")
    deps, calls = _make_mock_deps(html=html)
    assert deps.user_agent == expected_ua

    env_name = "".join(["CLINICBRAIN_", "SCRAPER_CONTACT"])
    monkeypatch.setenv(env_name, "evil@attacker.corp")
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": CLINIC_ID,
            "name": "台中分院",
            "preview_only": "true",
        },
    )
    assert resp.status_code == 200
    assert deps.user_agent == expected_ua


# =========================================================================
# 離線流程、預覽與寫入測試
# =========================================================================

def test_offline_fixture_pipeline(client: TestClient):
    html = SAMPLE_A_PATH.read_text(encoding="utf-8")
    deps, calls = _make_mock_deps(html=html)
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": CLINIC_ID,
            "name": "台中分院",
            "preview_only": "true",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["preview_only"] is True
    assert data["name"] == "台中分院"
    assert data["missing_fields"] == []
    assert len(data["faqs_preview"]) > 0


def test_preview_writes_nothing(client: TestClient, isolated_db_path: Path):
    html = SAMPLE_A_PATH.read_text(encoding="utf-8")
    deps, calls = _make_mock_deps(html=html)
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    conn = sqlite3.connect(str(isolated_db_path))
    before_count = conn.execute("SELECT COUNT(*) FROM faq_cache").fetchone()[0]
    conn.close()

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": CLINIC_ID,
            "name": "預覽測試項目",
            "preview_only": "true",
        },
    )
    assert resp.status_code == 200

    conn = sqlite3.connect(str(isolated_db_path))
    after_count = conn.execute("SELECT COUNT(*) FROM faq_cache").fetchone()[0]
    conn.close()
    assert before_count == after_count


def test_write_mode_pending_web_upload(client: TestClient, isolated_db_path: Path):
    html = SAMPLE_A_PATH.read_text(encoding="utf-8")
    deps, calls = _make_mock_deps(html=html)
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": CLINIC_ID,
            "name": "寫入審核測試",
            "preview_only": "false",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["preview_only"] is False
    assert data["review_status"] == "pending"

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT topic_key, source_type, review_status, metadata FROM faq_cache WHERE clinic_id = ? AND topic_key = 'doc-寫入審核測試'",
        (CLINIC_ID,),
    ).fetchall()
    conn.close()

    assert len(rows) > 0
    for r in rows:
        assert r[0] == "doc-寫入審核測試"
        assert r[1] == "web_upload"
        assert r[2] == "pending"
        assert r[3] is not None


def test_write_mode_metadata_provenance(client: TestClient, isolated_db_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_page = ExtractedClinicPage(
        institution_name="範例醫美診所",
        address="台北市中山區南京東路一段 100 號",
        phone="02-2500-1234",
        business_hours="週一至週五 09:00 - 18:00",
        services=[{"name": "皮秒蜂巢雷射", "description": "撫平細紋"}],
        doctors=[{"name": "王小明", "specialty": "微整形雕塑"}],
        schema_version="1",
    )
    fixed_fetched_at = "2026-10-14T12:00:00+00:00"
    fixed_source_url = "https://www.nu-vendome.com/location-detail/Taichung/"

    def _mock_fetch_clinic_page(*args, **kwargs):
        return UrlPageResult(
            page=fake_page,
            source_url=fixed_source_url,
            fetched_at=fixed_fetched_at,
        )

    import src.api.routes.admin as admin_mod
    monkeypatch.setattr(admin_mod, "fetch_clinic_page", _mock_fetch_clinic_page)

    deps, calls = _make_mock_deps()
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/?query=ignore#frag",
            "clinic_id": CLINIC_ID,
            "name": "溯源測試",
            "preview_only": "false",
        },
    )
    assert resp.status_code == 200

    conn = sqlite3.connect(str(isolated_db_path))
    meta_json = conn.execute(
        "SELECT metadata FROM faq_cache WHERE clinic_id = ? AND topic_key = 'doc-溯源測試' LIMIT 1",
        (CLINIC_ID,),
    ).fetchone()[0]
    conn.close()

    meta = json.loads(meta_json)
    assert meta["origin"] == "web_scrape"
    assert meta["schema_version"] == "1"
    assert "?" not in meta["source_url"]
    assert meta["source_url"] == fixed_source_url
    assert meta["fetched_at"] == fixed_fetched_at

    extracted = meta["extracted"]
    assert set(extracted.keys()) == {"institution_name", "address", "phone", "business_hours"}
    assert "02-2500-1234" not in extracted["phone"]  # 電話已被遮蔽
    assert "doctors" not in meta
    assert "王小明" not in meta_json
    assert "微整形雕塑" not in meta_json


def test_source_url_strips_query_from_request(client: TestClient, isolated_db_path: Path):
    html = SAMPLE_A_PATH.read_text(encoding="utf-8")
    deps, calls = _make_mock_deps(html=html)
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/?token=secret123#myanchor",
            "clinic_id": CLINIC_ID,
            "name": "清除查詢字串測試",
            "preview_only": "false",
        },
    )
    assert resp.status_code == 200

    conn = sqlite3.connect(str(isolated_db_path))
    meta_json = conn.execute(
        "SELECT metadata FROM faq_cache WHERE clinic_id = ? AND topic_key = 'doc-清除查詢字串測試' LIMIT 1",
        (CLINIC_ID,),
    ).fetchone()[0]
    conn.close()

    meta = json.loads(meta_json)
    assert "token" not in meta["source_url"]
    assert "secret123" not in meta["source_url"]
    assert meta["source_url"] == "https://www.nu-vendome.com/location-detail/Taichung/"


def test_identity_not_in_draft_text(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    captured_raw: list[str] = []
    import src.api.routes.admin as admin_mod
    orig_text_to_faqs = admin_mod._text_to_faq_drafts

    def _intercept_text_to_faqs(raw_text, topic, clinic_id):
        captured_raw.append(raw_text)
        return orig_text_to_faqs(raw_text, topic, clinic_id)

    monkeypatch.setattr(admin_mod, "_text_to_faq_drafts", _intercept_text_to_faqs)

    html = SAMPLE_A_PATH.read_text(encoding="utf-8")
    deps, calls = _make_mock_deps(html=html)
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": CLINIC_ID,
            "name": "隱私洩漏防禦測試",
            "preview_only": "true",
        },
    )
    assert resp.status_code == 200
    assert len(captured_raw) == 1
    raw = captured_raw[0]

    # 機構名稱、地址、電話、醫師資訊皆不應進入 raw_text
    assert "範例醫美診所" not in raw
    assert "南京東路" not in raw
    assert "02-2500-1234" not in raw
    assert "王小明" not in raw

    # 亦不應出現在任何 Q&A 預覽中
    for item in resp.json()["faqs_preview"]:
        assert "範例醫美診所" not in item["question"]
        assert "範例醫美診所" not in item["answer"]
        assert "王小明" not in item["answer"]


def test_build_service_text_only_services_and_hours():
    page = ExtractedClinicPage(
        institution_name="範例診所",
        address="台北市中山區南京東路",
        phone="02-1234-5678",
        business_hours="週一至週五 09:00 - 18:00",
        services=[
            {"name": "皮秒雷射", "description": "改善暗沉"},
            {"name": "果酸煥膚", "description": "去除角質"},
        ],
        doctors=[{"name": "李醫師", "specialty": "皮膚專科"}],
    )
    text = build_service_text(page)
    assert "營業時間：週一至週五 09:00 - 18:00" in text
    assert "服務項目：皮秒雷射\n改善暗沉" in text
    assert "服務項目：果酸煥膚\n去除角質" in text

    # 絕不含非服務項目資訊
    assert "範例診所" not in text
    assert "南京東路" not in text
    assert "02-1234-5678" not in text
    assert "李醫師" not in text
    assert "皮膚專科" not in text


def test_schema_drift_422_no_draft(client: TestClient, isolated_db_path: Path, monkeypatch: pytest.MonkeyPatch):
    drift_page = ExtractedClinicPage(
        institution_name="改版診所",
        services=[],  # 缺服務項目 -> is_usable() 為 False
        schema_drift=True,
    )
    assert drift_page.is_usable() is False

    import src.api.routes.admin as admin_mod
    monkeypatch.setattr(
        admin_mod,
        "fetch_clinic_page",
        lambda *args, **kwargs: UrlPageResult(page=drift_page, source_url="https://x.com", fetched_at="..."),
    )

    deps, calls = _make_mock_deps()
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": CLINIC_ID,
            "name": "改版失敗測試",
            "preview_only": "false",
        },
    )
    assert resp.status_code == 422
    assert "疑似網站改版" in resp.json()["detail"]


def test_metadata_column_missing_returns_503_before_fetch(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    import src.api.routes.admin as admin_mod
    monkeypatch.setattr(admin_mod, "has_metadata_column", lambda conn: False)

    deps, calls = _make_mock_deps()
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": CLINIC_ID,
            "name": "缺欄位測試",
            "preview_only": "false",
        },
    )
    assert resp.status_code == 503
    assert len(calls) == 0  # 必須在發出請求前即中斷


def test_fetch_error_returns_502_without_detail(client: TestClient):
    deps, calls = _make_mock_deps(http_error=RuntimeError("secret internal error string"))
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": CLINIC_ID,
            "name": "內部錯誤不洩漏測試",
        },
    )
    assert resp.status_code == 502
    assert "secret internal error string" not in resp.text


def test_robots_denied_returns_403(client: TestClient):
    deps, calls = _make_mock_deps(robots_status=403)
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": CLINIC_ID,
            "name": "Robots拒絕測試",
        },
    )
    assert resp.status_code == 403
    assert "robots.txt" in resp.json()["detail"]


def test_http_status_returns_502(client: TestClient):
    deps, calls = _make_mock_deps(page_status=404)
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": CLINIC_ID,
            "name": "頁面找不到測試",
        },
    )
    assert resp.status_code == 502


def test_missing_fields_surfaced():
    page = ExtractedClinicPage(
        institution_name="範例診所",
        address="",
        phone="02-1234-5678",
        business_hours="",
        services=[{"name": "皮秒雷射"}],
        doctors=[],
    )
    missing = optional_missing_fields(page)
    assert missing == ["address", "business_hours", "doctors"]


def test_clinic_must_exist(client: TestClient):
    deps, calls = _make_mock_deps()
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": "nonexistent_clinic_id",
            "name": "診所不存在測試",
        },
    )
    assert resp.status_code == 404


def test_endpoint_logs_nothing(client: TestClient, caplog: pytest.LogCaptureFixture):
    html = SAMPLE_A_PATH.read_text(encoding="utf-8")
    deps, calls = _make_mock_deps(html=html)
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    with caplog.at_level(logging.DEBUG):
        resp = client.post(
            "/api/v1/admin/upload-url",
            data={
                "url": "https://www.nu-vendome.com/location-detail/Taichung/",
                "clinic_id": CLINIC_ID,
                "name": "日誌安全測試",
                "preview_only": "true",
            },
        )
    assert resp.status_code == 200
    for record in caplog.records:
        msg = record.getMessage()
        assert "nu-vendome.com" not in msg
        assert "日誌安全測試" not in msg
        assert "https://" not in msg


def test_lock_busy_returns_429(client: TestClient):
    deps, calls = _make_mock_deps()
    app.dependency_overrides[get_url_fetch_deps] = lambda: deps

    acquired = _URL_FETCH_LOCK.acquire(blocking=False)
    assert acquired is True
    try:
        resp = client.post(
            "/api/v1/admin/upload-url",
            data={
                "url": "https://www.nu-vendome.com/location-detail/Taichung/",
                "clinic_id": CLINIC_ID,
                "name": "並發鎖測試",
            },
        )
        assert resp.status_code == 429
        assert len(calls) == 0
    finally:
        _URL_FETCH_LOCK.release()


def test_bad_allowlist_returns_503(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    import src.api.routes.admin as admin_mod

    def _failing_load(path):
        raise PolicyError(reason="bad_allowlist", message="無法讀取")

    monkeypatch.setattr(admin_mod, "load_allowlist", _failing_load)

    # 清除 override 以便測試預設 get_url_fetch_deps 之失敗處理
    app.dependency_overrides.clear()

    resp = client.post(
        "/api/v1/admin/upload-url",
        data={
            "url": "https://www.nu-vendome.com/location-detail/Taichung/",
            "clinic_id": CLINIC_ID,
            "name": "白名單損壞測試",
        },
    )
    assert resp.status_code == 503
    assert "白名單" in resp.json()["detail"]


def test_upload_file_endpoint_unchanged(client: TestClient):
    """回歸測試：既有 /upload 檔案端點不受 /upload-url 新增影響。"""
    resp = client.post(
        "/api/v1/admin/upload",
        files={"file": ("test.txt", b"plain text", "text/plain")},
        data={"clinic_id": CLINIC_ID, "preview_only": "true"},
    )
    # 不支援 .txt 應回 400
    assert resp.status_code == 400


# =========================================================================
# Phase 23 契約測試（直接呼叫 fetch_page，無外部網路）
# =========================================================================

def test_contract_pinned_addresses_param_exists():
    sig = inspect.signature(fetch_page)
    assert "pinned_addresses" in sig.parameters
    assert "http_get" in sig.parameters
    assert "resolver" in sig.parameters
    assert "opener" not in sig.parameters


def test_contract_pinned_addresses_connects_only_to_pinned():
    recorded_ips = []

    def _http_get(pinned_ip, host, path, headers, *args, **kwargs):
        recorded_ips.append(pinned_ip)
        if path.endswith("/robots.txt"):
            return 200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /"
        return 200, {"content-type": "text/html"}, b"<html>OK</html>"

    allowlist = {
        "allowed_domains": [{"host": "www.nu-vendome.com", "path_prefixes": ["/"]}],
        "by_host": {"www.nu-vendome.com": ["/"]},
    }
    throttle = DomainThrottle(min_interval=5.0, sleep=lambda s: None)
    robots = RobotsPolicy()

    # 1. 正常公網 pinned IP
    res = fetch_page(
        "https://www.nu-vendome.com/",
        allowlist=allowlist,
        throttle=throttle,
        robots=robots,
        user_agent="test",
        resolver=lambda host: ["8.8.4.4", "10.0.0.9"],
        http_get=_http_get,
        pinned_addresses=("8.8.4.4",),
    )
    assert res.ok is True
    assert "10.0.0.9" not in recorded_ips
    assert "8.8.4.4" in recorded_ips

    # 2. pinned 含私網位址 -> 應被拒絕
    res_private = fetch_page(
        "https://www.nu-vendome.com/",
        allowlist=allowlist,
        throttle=throttle,
        robots=robots,
        user_agent="test",
        resolver=lambda host: ["8.8.4.4"],
        http_get=_http_get,
        pinned_addresses=("10.0.0.5",),
    )
    assert res_private.ok is False
    assert res_private.reason == "private_address"


def test_contract_empty_allowlist_blocks_before_network():
    called = []

    def _http_get(*args, **kwargs):
        called.append(1)
        return 200, {}, b""

    res = fetch_page(
        "https://www.nu-vendome.com/",
        allowlist={"allowed_domains": [], "by_host": {}},
        throttle=DomainThrottle(min_interval=5.0, sleep=lambda s: None),
        robots=RobotsPolicy(),
        user_agent="test",
        http_get=_http_get,
    )
    assert res.ok is False
    assert res.reason == "not_allowlisted"
    assert len(called) == 0


def test_contract_redirect_hop_revalidated():
    hops = []

    def _http_get(pinned_ip, host, path, headers, *args, **kwargs):
        hops.append((host, path))
        if path.endswith("/robots.txt"):
            return 200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /"
        # 第一跳回傳 302 重導向到私網位址解析之網域
        return 302, {"location": "https://other.example/page"}, b""

    allowlist = {
        "allowed_domains": [
            {"host": "www.nu-vendome.com", "path_prefixes": ["/"]},
            {"host": "other.example", "path_prefixes": ["/"]},
        ],
        "by_host": {
            "www.nu-vendome.com": ["/"],
            "other.example": ["/"],
        },
    }

    def _resolver(host):
        if host == "other.example":
            return ["10.0.0.5"]
        return ["93.184.216.34"]

    res = fetch_page(
        "https://www.nu-vendome.com/first",
        allowlist=allowlist,
        throttle=DomainThrottle(min_interval=5.0, sleep=lambda s: None),
        robots=RobotsPolicy(),
        user_agent="test",
        resolver=_resolver,
        http_get=_http_get,
    )
    assert res.ok is False
    assert res.reason == "private_address"
    # 第二跳頁面不得被抓取
    assert ("other.example", "/page") not in hops


def test_contract_redirect_to_http_rejected():
    def _http_get(pinned_ip, host, path, headers, *args, **kwargs):
        if path.endswith("/robots.txt"):
            return 200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /"
        return 302, {"location": "http://www.nu-vendome.com/insecure"}, b""

    allowlist = {
        "allowed_domains": [{"host": "www.nu-vendome.com", "path_prefixes": ["/"]}],
        "by_host": {"www.nu-vendome.com": ["/"]},
    }

    res = fetch_page(
        "https://www.nu-vendome.com/start",
        allowlist=allowlist,
        throttle=DomainThrottle(min_interval=5.0, sleep=lambda s: None),
        robots=RobotsPolicy(),
        user_agent="test",
        resolver=lambda host: ["93.184.216.34"],
        http_get=_http_get,
    )
    assert res.ok is False
    assert res.reason == "scheme"
