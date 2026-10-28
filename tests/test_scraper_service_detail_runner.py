"""批次擷取器：/service-detail/ 服務詳細頁改用詳細頁解析器（離線合成 HTML）。"""

import sqlite3

from src.scraper.fetch import FetchResult
from src.scraper.runner import ScrapeOptions, _process_one

CLINIC = "3503264627"
DETAIL_HTML = """<html><head><title>雙眼皮手術-凡登診所</title></head><body>
<div class="contentBuilder"><div class="mt-3 mb-3"><h2 class="h2Title">雙眼皮手術</h2><p>雙眼皮手術可改善眼皮皺摺，恢復期約一週，術後需避免按壓。</p></div></div>
</body></html>"""


def _db(tmp_path, name: str | None):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE clinic_info (clinic_id TEXT PRIMARY KEY, name TEXT)")
    if name is not None:
        conn.execute("INSERT INTO clinic_info VALUES (?, ?)", (CLINIC, name))
    conn.commit()
    conn.close()
    return db


def _options(tmp_path, db):
    allowlist = tmp_path / "sources.json"
    allowlist.write_text('{"open_access": true, "allowed_domains": []}', encoding="utf-8")
    return ScrapeOptions(clinic_id=CLINIC, allowlist_path=allowlist, db_path=db, write=False)


def _ok(url: str, html: str) -> FetchResult:
    return FetchResult(ok=True, url=url, final_url=url, status=200, html=html, fetched_at="2026-10-22T00:00:00+00:00")


def test_service_detail_page_yields_draft_candidates(tmp_path):
    db = _db(tmp_path, "凡登整形外科診所")
    url = "https://www.nu-vendome.com/service-detail/eyelid-surgery/"
    outcome, written, _ = _process_one(url, _ok(url, DETAIL_HTML), options=_options(tmp_path, db))
    assert outcome.reason != "schema_drift"
    assert outcome.drafts_count >= 1
    assert written == 0  # dry-run：不寫入


def test_service_detail_without_clinic_name_is_schema_drift(tmp_path):
    db = _db(tmp_path, None)
    url = "https://www.nu-vendome.com/service-detail/eyelid-surgery/"
    outcome, _, _ = _process_one(url, _ok(url, DETAIL_HTML), options=_options(tmp_path, db))
    assert outcome.reason == "schema_drift"


def test_service_detail_without_title_is_schema_drift(tmp_path):
    db = _db(tmp_path, "凡登整形外科診所")
    url = "https://www.nu-vendome.com/service-detail/eyelid-surgery/"
    outcome, _, _ = _process_one(url, _ok(url, "<html><body>無標題頁面</body></html>"), options=_options(tmp_path, db))
    assert outcome.reason == "schema_drift"


def test_clinic_pages_still_use_clinic_extractor(tmp_path):
    """非服務詳細頁路徑維持原本的診所頁抽取，不受影響（不因服務詳細頁解析而誤判）。"""
    db = _db(tmp_path, "凡登整形外科診所")
    url = "https://www.nu-vendome.com/location-detail/taichung/"
    outcome, _, _ = _process_one(url, _ok(url, DETAIL_HTML), options=_options(tmp_path, db))
    # 診所頁抽取器找不到院所資訊與服務清單，應維持 schema_drift
    assert outcome.reason == "schema_drift"
