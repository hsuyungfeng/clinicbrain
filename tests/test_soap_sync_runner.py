"""
Taiwan Clinic Medical PageIndex RAG System - SOAP 預同步單元測試 (test_soap_sync_runner)
Phase 16 Plan 16-02: 定時增量同步契約模組與夜間預拉取整合測試
"""

from pathlib import Path
import sqlite3
import pytest

from src.sync.soap_sync_runner import (
    SoapSyncResult,
    process_soap_records,
    sync_and_ingest_soap_records,
    sync_soap_records_before_batch,
)

CLINIC = "3503190424"


def test_process_soap_records_deid_and_price_masking(monkeypatch):
    """測試 1：process_soap_records 正確執行個資去識別化與價格二次清洗。"""
    monkeypatch.setenv("CLINICBRAIN_DEID_KEY", "test-secret-key-12345")

    raw_records = [
        {
            "external_id": "ext-sync-01",
            "patient_id": "A123456789",
            "raw_text": "病患姓名：張小明，電話0912345678。自費療程15000元。S: 喉嚨痛。 O: 咽喉發紅。 A: 急性咽喉炎 P: 衛教：多喝水與休息。",
            "subjective": "喉嚨痛，電話0912345678",
            "objective": "咽喉發紅",
            "assessment": "急性咽喉炎",
            "plan": "衛教：多喝水與休息，自費5000元",
        }
    ]

    cleaned = process_soap_records(raw_records, CLINIC)
    assert len(cleaned) == 1
    rec = cleaned[0]

    assert rec["clinic_id"] == CLINIC
    assert rec["external_id"] == "ext-sync-01"
    assert rec["patient_token"].startswith("PTK-")
    assert "[電話已遮蔽]" in rec["subjective"]
    assert "[姓名已遮蔽]" in rec["raw_text"]
    assert "[請致電診所確認]" in rec["raw_text"]
    assert "[請致電診所確認]" in rec["plan"]


def test_sync_and_ingest_soap_records_idempotent(isolated_conn):
    """測試 2：sync_and_ingest_soap_records 增量寫入與冪等更新。"""
    conn = isolated_conn
    raw_records = [
        {
            "external_id": "ext-sync-02",
            "patient_token": "PTK-TEST002",
            "raw_text": "S: 發燒38.5度。 O: 扁桃腺發炎。 A: 急性扁桃腺炎 P: 衛教：請多喝溫水與充分休息。",
            "subjective": "發燒38.5度。",
            "objective": "扁桃腺發炎。",
            "assessment": "急性扁桃腺炎",
            "plan": "衛教：請多喝溫水與充分休息。",
        }
    ]

    # 首度寫入
    res1 = sync_and_ingest_soap_records(conn, raw_records, CLINIC)
    assert res1.status == "completed"
    assert res1.inserted == 1

    # 重複寫入（內容未變）
    res2 = sync_and_ingest_soap_records(conn, raw_records, CLINIC)
    assert res2.status == "completed"
    assert res2.unchanged == 1
    assert res2.inserted == 0


def test_sync_soap_records_before_batch_graceful_degrade(isolated_conn):
    """測試 3：當遠端 URL 無法連線時，前置同步掛鉤優雅降級 (status='degraded') 且不中斷。"""
    conn = isolated_conn
    local_records = [
        {
            "external_id": "ext-local-01",
            "patient_token": "PTK-LOCAL01",
            "raw_text": "S: 咳嗽。 O: 呼吸音清。 A: 急性支氣管炎 P: 衛教：請多喝水。",
            "subjective": "咳嗽。",
            "objective": "呼吸音清。",
            "assessment": "急性支氣管炎",
            "plan": "衛教：請多喝水。",
        }
    ]

    # 指定無效之遠端 URL，模擬網路異常
    res = sync_soap_records_before_batch(
        conn,
        CLINIC,
        remote_url="http://127.0.0.1:9999/invalid-endpoint-nonexistent",
        local_records=local_records,
    )

    assert res.status == "degraded"
    assert "遠端拉取失敗" in res.error_message
    # 本地紀錄仍成功入庫
    assert res.inserted == 1


def test_sync_soap_records_dry_run(isolated_conn):
    """測試 4：dry_run=True 模式下不寫入資料庫。"""
    conn = isolated_conn
    local_records = [
        {
            "external_id": "ext-dry-01",
            "patient_token": "PTK-DRY01",
            "raw_text": "S: 頭痛。 O: 正常。 A: 感冒 P: 衛教：多休息。",
            "subjective": "頭痛。",
            "objective": "正常。",
            "assessment": "感冒",
            "plan": "衛教：多休息。",
        }
    ]

    res = sync_and_ingest_soap_records(conn, local_records, CLINIC, dry_run=True)
    assert res.status == "completed"
    assert res.inserted == 0

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM soap_records WHERE external_id = 'ext-dry-01'")
    assert cur.fetchone()[0] == 0
