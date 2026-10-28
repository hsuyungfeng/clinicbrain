"""醫師改寫覆寫：只替換完全相符的句子、失敗關閉、覆寫後仍經合規檢查。"""

import json
import sqlite3

import pytest

from src.scraper.fetch import FetchResult
from src.scraper.overrides import OverrideError, apply_overrides, load_physician_overrides
from src.scraper.runner import ScrapeOptions, _process_one

CLINIC = "3503264627"
RISKY = "停用藥物與補品：術前兩週需停止服用阿斯匹靈、維他命E、銀杏等活血性藥物或食品。"
REWRITE = "術前請依醫師指示，調整正在使用的藥物或保健品。"
URL = "https://www.nu-vendome.com/service-detail/Liposuction"


def _html(body: str) -> str:
    return f"""<html><head><title>抽脂手術-凡登診所</title></head><body>
<div class="contentBuilder"><div class="mt-3 mb-3"><h2 class="h2Title">抽脂手術</h2>
<p>{body}</p></div></div></body></html>"""


def _db(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE clinic_info (clinic_id TEXT PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO clinic_info VALUES (?, ?)", (CLINIC, "凡登整形外科診所"))
    conn.commit()
    conn.close()
    return db


def _options(tmp_path, db, overrides):
    allowlist = tmp_path / "sources.json"
    allowlist.write_text('{"open_access": true, "allowed_domains": []}', encoding="utf-8")
    ov = tmp_path / "ov.json"
    ov.write_text(json.dumps(overrides, ensure_ascii=False), encoding="utf-8")
    return ScrapeOptions(clinic_id=CLINIC, allowlist_path=allowlist, db_path=db, write=False, overrides_path=ov)


def _run(tmp_path, overrides, body=RISKY):
    db = _db(tmp_path)
    fetch = FetchResult(ok=True, url=URL, final_url=URL, status=200, html=_html(body), fetched_at="2026-10-22T00:00:00+00:00")
    return _process_one(URL, fetch, options=_options(tmp_path, db, overrides))[0]


def _entry(find=RISKY, replace=REWRITE, path="/service-detail/Liposuction", ref="2026-10-22 醫師審核"):
    return {"overrides": [{"path": path, "find": find, "replace": replace, "review_ref": ref}]}


def test_apply_replaces_exact_sentence_and_reports_missing():
    text, missing = apply_overrides("甲。" + RISKY, [{"find": RISKY, "replace": REWRITE}])
    assert REWRITE in text and RISKY not in text and missing == []
    text2, missing2 = apply_overrides("甲。乙。", [{"find": "不存在", "replace": "X"}])
    assert text2 == "甲。乙。" and missing2 == ["不存在"]


def test_missing_file_means_no_overrides(tmp_path):
    assert load_physician_overrides(tmp_path / "nope.json") == {}


def test_malformed_overrides_fail_closed(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(OverrideError):
        load_physician_overrides(bad)
    no_ref = tmp_path / "noref.json"
    no_ref.write_text(json.dumps({"overrides": [{"path": "/service-detail/x", "find": "a", "replace": "b"}]}), encoding="utf-8")
    with pytest.raises(OverrideError):
        load_physician_overrides(no_ref)
    wrong_path = tmp_path / "wp.json"
    wrong_path.write_text(json.dumps(_entry(path="/location-detail/x")), encoding="utf-8")
    with pytest.raises(OverrideError):
        load_physician_overrides(wrong_path)


def test_without_override_risky_sentence_is_rejected(tmp_path):
    outcome = _run(tmp_path, {"overrides": []})
    assert outcome.drafts_count == 0
    assert outcome.rejected_count == 1


def test_physician_override_lets_rewritten_text_through_checks(tmp_path):
    outcome = _run(tmp_path, _entry())
    assert outcome.reason != "schema_drift"
    assert outcome.drafts_count == 1
    assert outcome.rejected_count == 0


def test_override_that_does_not_match_source_fails_closed(tmp_path):
    outcome = _run(tmp_path, _entry(find="來源沒有這句"))
    assert outcome.reason == "schema_drift"


def test_override_cannot_bypass_checks_when_replacement_is_still_risky(tmp_path):
    still_risky = "術前請停止服用阿斯匹靈並於手術前一週停用。"
    outcome = _run(tmp_path, _entry(replace=still_risky))
    assert outcome.drafts_count == 0
    assert outcome.rejected_count == 1
