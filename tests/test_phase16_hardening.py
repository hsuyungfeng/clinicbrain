"""Phase 16 複審加固測試：前置同步 Fail-Closed、遠端 URL 限制、提煉草稿隱蔽、批次旗標互斥。"""

import sqlite3
import pytest

from src.sync import soap_sync_runner as ssr
from src.sync.soap_sync_runner import process_soap_records, pull_remote_soap_records, SoapSyncResult

CLINIC = "3503190424"


def _rec(**kw):
    base = {"external_id": "ext-h-01", "patient_token": "PTK-H01", "subjective": "喉嚨痛", "plan": "衛教：多喝水"}
    base.update(kw)
    return base


def test_unsafe_external_id_skipped():
    stats = SoapSyncResult()
    out = process_soap_records([_rec(external_id="A123456789")], CLINIC, stats=stats)
    assert out == [] and stats.skipped_unsafe == 1


def test_unsafe_patient_token_skipped():
    out = process_soap_records([_rec(patient_token="0912345678")], CLINIC)
    assert out == []


def test_patient_id_without_key_fail_closed(monkeypatch):
    """僅有 patient_id 且無金鑰：不得以原始 id 或可預測備援值寫入。"""
    monkeypatch.delenv("CLINICBRAIN_DEID_KEY", raising=False)
    monkeypatch.delenv("CLINICBRAIN_ADMIN_API_KEY", raising=False)
    out = process_soap_records([_rec(patient_token=None, patient_id="CHART-889")], CLINIC)
    assert out == []


def test_patient_id_never_used_as_raw_token(monkeypatch):
    monkeypatch.setenv("CLINICBRAIN_DEID_KEY", "k-hardening")
    out = process_soap_records([_rec(patient_token=None, patient_id="CHART-889")], CLINIC)
    assert len(out) == 1 and "CHART-889" not in out[0]["patient_token"]


def test_tags_list_deidentified_and_joined():
    out = process_soap_records([_rec(tags=["感冒", "電話0912345678"])], CLINIC)
    assert out[0]["tags"].startswith("感冒,") and "0912345678" not in out[0]["tags"]


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x/y", "http://example.com/api"])
def test_pull_remote_rejects_unsafe_scheme(url):
    with pytest.raises(ValueError):
        pull_remote_soap_records(url, api_key="k")


def test_presync_failure_degrades_without_raising(isolated_conn):
    res = ssr.sync_soap_records_before_batch(isolated_conn, CLINIC, remote_url="file:///etc/passwd")
    assert res.status == "degraded"
    assert "/etc" not in (res.error_message or "")


def test_sync_ingest_failure_rolls_back(isolated_conn, monkeypatch):
    def boom(*a, **k):
        isolated_conn.execute("INSERT INTO soap_records (clinic_id, external_id, patient_token, raw_text) VALUES ('3503190424','rb-1','PTK-RB','x')")
        raise RuntimeError("boom")
    monkeypatch.setattr(ssr, "upsert_soap_records", boom)
    res = ssr.sync_and_ingest_soap_records(isolated_conn, [_rec()], CLINIC)
    assert res.status == "failed"
    assert isolated_conn.execute("SELECT COUNT(*) FROM soap_records WHERE external_id='rb-1'").fetchone()[0] == 0


def test_soap_flags_mutually_exclusive():
    from scripts.run_nightly_batch import create_parser
    with pytest.raises(SystemExit):
        create_parser().parse_args(["--skip-soap", "--soap-only"])


def test_distilled_pending_never_visible(isolated_conn):
    """提煉草稿未經核准前，search_faq_cache 與可見性條件一律查不到。"""
    from src.pageindex.faq_writer import upsert_faqs
    from src.pageindex.faq_review import visible_faq_sql
    faq = {"clinic_id": CLINIC, "topic_key": "care-h", "question": "【照護指引】罹患HX應注意哪些居家照護事項？",
           "answer": "1. 多休息\n\n【就醫警訊】若出現高燒超過3天或呼吸困難，請儘速就醫。", "category": "special", "metadata": "{}"}
    upsert_faqs(isolated_conn, [faq], source_type="soap_distilled")
    n = isolated_conn.execute(f"SELECT COUNT(*) FROM faq_cache WHERE topic_key='care-h' AND {visible_faq_sql(isolated_conn)}").fetchone()[0]
    assert n == 0
    assert isolated_conn.execute("SELECT review_status FROM faq_cache WHERE topic_key='care-h'").fetchone()[0] == "pending"


def test_batch_continues_when_presync_fails(isolated_conn, tmp_path):
    """前置同步失敗（不安全 URL）→ 狀態 degraded、計入 errors，但批次不中斷、仍完成提煉階段。"""
    from src.batch.run_log import RunLogger
    from src.batch.runner import BatchConfig, run_batch

    logger = RunLogger(tmp_path / "logs", echo=False)
    cfg = BatchConfig(
        seed_path=tmp_path / "unused.json",
        snapshot_dir=tmp_path / "snap",
        dry_run=False,
        soap_only=True,
        soap_clinic_id=CLINIC,
        soap_sync_url="file:///etc/passwd",
    )
    summary = run_batch(isolated_conn, cfg, llm_call=lambda p: "", health_check=lambda: None, logger=logger)
    logger.close()
    assert summary.soap_sync_status == "degraded"
    assert summary.errors >= 1
    assert summary.status == "completed"
