"""
pytest 共用 fixture 與測試隔離設定。
嚴格規則：測試套件絕不直接操作正式的 clinic.db，以複本進行測試隔離。
"""

import shutil
import sqlite3
import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROD_DB_PATH = PROJECT_ROOT / "clinic.db"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))



def _ensure_faq_cache(db_path: Path):
    """確保測試複本資料庫具備 faq_cache 與其 FTS5 / Triggers 結構。"""
    schema_sql_path = PROJECT_ROOT / "src" / "db" / "clinic_schema.sql"
    if not schema_sql_path.exists():
        return
    sql_text = schema_sql_path.read_text(encoding="utf-8")
    start_marker = "CREATE TABLE IF NOT EXISTS faq_cache"
    end_marker = "-- ========================================\n-- Sample Data"
    start_pos = sql_text.find(start_marker)
    end_pos = sql_text.find(end_marker)
    if start_pos != -1:
        faq_ddl = sql_text[start_pos:end_pos] if end_pos != -1 else sql_text[start_pos:]
        temp_conn = sqlite3.connect(str(db_path))
        temp_conn.executescript(faq_ddl)
        temp_conn.close()

        from scripts.migrate_faq_review_status import apply_review_status_migration
        apply_review_status_migration(db_path)


def _reset_cache_stats(db_path: Path):
    """讓測試複本的 cache_stats 恆為空表，與正式庫累積的真實統計脫鉤（僅動複本）。"""
    schema_sql_path = PROJECT_ROOT / "src" / "db" / "clinic_schema.sql"
    sql_text = schema_sql_path.read_text(encoding="utf-8")
    start_pos = sql_text.find("CREATE TABLE IF NOT EXISTS cache_stats")
    end_pos = sql_text.find("-- ========================================\n-- Sample Data")
    if start_pos == -1:
        return
    ddl = sql_text[start_pos:end_pos] if end_pos != -1 else sql_text[start_pos:]
    temp_conn = sqlite3.connect(str(db_path))
    temp_conn.executescript(ddl)
    temp_conn.execute("DELETE FROM cache_stats")
    temp_conn.commit()
    temp_conn.close()


def _ensure_soap_records(db_path: Path):
    """確保測試複本資料庫具備 soap_records 與其 FTS5 / Triggers 結構。"""
    schema_sql_path = PROJECT_ROOT / "src" / "db" / "clinic_schema.sql"
    if not schema_sql_path.exists():
        return
    sql_text = schema_sql_path.read_text(encoding="utf-8")
    from scripts.migrate_soap_schema import extract_soap_ddl
    soap_ddl = extract_soap_ddl(sql_text)
    temp_conn = sqlite3.connect(str(db_path))
    temp_conn.executescript(soap_ddl)
    temp_conn.close()


def _ensure_faq_metadata(db_path: Path):
    """確保測試複本具備 faq_cache.metadata 欄位（寫入路徑不會自動 ALTER）。"""
    from scripts.migrate_faq_metadata import apply_metadata_migration
    apply_metadata_migration(db_path)


def _reset_tree_titles(db_path: Path):
    """重置隔離副本推理樹標題為 NULL。

    隔離副本不得隨正式庫的標題資料變動，使預生成測試回到補標題前的狀態。
    表或欄位不存在時安靜略過。
    """
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE page_index_trees SET title = NULL")
        conn.commit()
        conn.close()
    except Exception:
        pass


def _reset_visual_tables(db_path: Path):
    """隔離副本預設不套用 visual 表（各測試需要時顯式呼叫 apply_visual_migration）。"""
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("DROP TABLE IF EXISTS visual_assets")
        conn.execute("DROP TABLE IF EXISTS visual_stats")
        conn.commit()
        conn.close()
    except Exception:
        pass


def apply_visual_migration(db_path: Path):

    """為測試複本套用 visual_assets 與 visual_stats 結構（預設不套用，各測試需要時顯式呼叫）。"""
    from scripts.migrate_visual_assets import apply_visual_schema
    apply_visual_schema(db_path)


@pytest.fixture(scope="session")

def session_db_path(tmp_path_factory) -> Path:
    """Session 層級的資料庫複本（供唯讀查詢與檢索測試使用）。"""
    if not PROD_DB_PATH.exists():
        pytest.fail(f"正式資料庫不存在：{PROD_DB_PATH}，請先執行 seed 腳本建庫。")
    
    temp_dir = tmp_path_factory.mktemp("session_db")
    target_path = temp_dir / "clinic_test.db"
    shutil.copy2(PROD_DB_PATH, target_path)
    _ensure_faq_cache(target_path)
    _reset_cache_stats(target_path)
    _ensure_soap_records(target_path)
    _ensure_faq_metadata(target_path)
    return target_path


@pytest.fixture
def conn(session_db_path: Path):
    """唯讀測試連線，連線至 session 資料庫複本。"""
    connection = sqlite3.connect(str(session_db_path))
    yield connection
    connection.close()


@pytest.fixture
def isolated_db_path(tmp_path: Path) -> Path:
    """Function 層級的獨立資料庫檔案路徑。"""
    if not PROD_DB_PATH.exists():
        pytest.fail(f"正式資料庫不存在：{PROD_DB_PATH}")

    target_path = tmp_path / "clinic_isolated.db"
    shutil.copy2(PROD_DB_PATH, target_path)
    _ensure_faq_cache(target_path)
    _reset_cache_stats(target_path)
    _ensure_soap_records(target_path)
    _ensure_faq_metadata(target_path)
    _reset_tree_titles(target_path)
    _reset_visual_tables(target_path)
    yield target_path

    # 測試結束即刪除副本（每份約 45 MB；不清理會耗盡 /tmp 配額）
    target_path.unlink(missing_ok=True)


@pytest.fixture
def isolated_conn(isolated_db_path: Path):
    """Function 層級的獨立資料庫複本連線（供寫入、UPSERT 測試使用，測試後自動銷毀）。"""
    connection = sqlite3.connect(str(isolated_db_path))
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def _default_allow_no_auth(monkeypatch):
    """既有測試預設視為開發模式放行；驗證強制行為的測試須自行覆寫為 False。"""
    from src.api.config import config
    monkeypatch.setattr(config, "allow_no_auth", True)


@pytest.fixture(autouse=True)
def _disable_cache_stats_by_default(monkeypatch):
    """預設關閉統計寫入，避免測試意外寫入任何資料庫；驗證統計行為的測試須自行改回 True 並指向複本資料庫。"""
    from src.api.config import config
    monkeypatch.setattr(config, "cache_stats_enabled", False)


@pytest.fixture(autouse=True)
def _block_outbound_network_for_scraper(monkeypatch):
    """防止測試發出任何真實對外網路請求，僅允許本機 loopback (127.0.0.0/8, ::1, localhost)。"""
    import socket
    import ipaddress

    orig_create_connection = socket.create_connection
    orig_connect = socket.socket.connect
    orig_getaddrinfo = socket.getaddrinfo

    def is_loopback(host_or_ip):
        if not host_or_ip:
            return True
        host_str = str(host_or_ip).strip().lower()
        if host_str in ("localhost", "127.0.0.1", "::1"):
            return True
        try:
            ip = ipaddress.ip_address(host_str)
            return ip.is_loopback
        except ValueError:
            return False

    def guarded_create_connection(address, *args, **kwargs):
        host = address[0]
        if not is_loopback(host):
            raise RuntimeError("測試禁止真實網路連線")
        return orig_create_connection(address, *args, **kwargs)

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, (tuple, list)) else address
        if not is_loopback(host):
            raise RuntimeError("測試禁止真實網路連線")
        return orig_connect(self, address)

    def guarded_getaddrinfo(host, port, *args, **kwargs):
        if not is_loopback(host):
            raise RuntimeError("測試禁止真實網路連線")
        return orig_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


@pytest.fixture(autouse=True)
def _forbid_real_llm_endpoint(monkeypatch):
    """防止測試呼叫 127.0.0.1:8080 (llama-server) 真實模型端點。"""
    import urllib.request
    orig_urlopen = urllib.request.urlopen

    def guarded_urlopen(req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        url_lower = url.lower()
        if "127.0.0.1:8080" in url_lower or "localhost:8080" in url_lower:
            raise AssertionError("測試不得呼叫真實 LLM")
        return orig_urlopen(req, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", guarded_urlopen)


@pytest.fixture(autouse=True)
def _forbid_real_patient_llm(monkeypatch):
    """防止病人端諮詢相關測試意外觸發真實 default_patient_llm。"""
    def _raise_error(*args, **kwargs):
        raise AssertionError("測試不得呼叫真實 LLM")

    import src.general.patient_consult as pc
    if not hasattr(pc, "_orig_default_patient_llm"):
        pc._orig_default_patient_llm = pc.default_patient_llm
        pc._orig_default_patient_compose_llm = pc.default_patient_compose_llm

    monkeypatch.setattr(pc, "default_patient_llm", _raise_error, raising=False)
    monkeypatch.setattr(pc, "default_patient_compose_llm", _raise_error, raising=False)

    try:
        import src.api.routes.general as rg
        monkeypatch.setattr(rg, "default_patient_llm", _raise_error, raising=False)
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _reset_patient_clinic_id(monkeypatch):
    """於每個測試前將全域 config.patient_clinic_id 設為 None，避免環境變數污染其他測試。"""
    from src.api.config import config
    monkeypatch.setattr(config, "patient_clinic_id", None)


@pytest.fixture(scope="session")
def playwright_browser():
    """Session 層級 Playwright Chromium 實例（不可用時自動 skip）。"""
    try:
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        browser = p.chromium.launch()
        yield browser
        browser.close()
        p.stop()
    except Exception as e:
        pytest.skip(f"Playwright 或 Chromium 不可用：{e}")


@pytest.fixture
def playwright_page(playwright_browser):
    """Function 層級 Playwright 頁面實例。"""
    page = playwright_browser.new_page(viewport={"width": 1000, "height": 700})
    yield page
    page.close()

