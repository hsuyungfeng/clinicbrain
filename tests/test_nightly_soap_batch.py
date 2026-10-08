"""
Taiwan Clinic Medical PageIndex RAG System - 夜間 SOAP 提煉批次單元測試 (test_nightly_soap_batch)
Phase 16 Plan 16-01: 夜間批次核心擴充與 SOAP 提煉子任務整合測試
"""

from pathlib import Path
import sqlite3
import pytest

from src.batch.run_log import RunLogger
from src.batch.runner import BatchConfig, run_batch
from src.soap.soap_writer import upsert_soap_records
import scripts.run_nightly_batch as nightly_cli

CLINIC = "3503190424"


def _seed_soap_records(conn: sqlite3.Connection):
    """為測試庫寫入足夠觸發提煉的 SOAP 紀錄（至少 2 筆相同疾病與衛教要點）。"""
    records = [
        {
            "clinic_id": CLINIC,
            "external_id": "ext001",
            "patient_token": "hash001",
            "raw_text": "S: 喉嚨刺痛，畏寒。 O: 咽喉紅腫。 A: 急性咽喉炎 P: 衛教：請多喝溫水與充分休息。開立止痛藥。",
            "subjective": "喉嚨刺痛，畏寒。",
            "objective": "咽喉紅腫。",
            "assessment": "急性咽喉炎",
            "plan": "衛教：請多喝溫水與充分休息。開立止痛藥。",
        },
        {
            "clinic_id": CLINIC,
            "external_id": "ext002",
            "patient_token": "hash002",
            "raw_text": "S: 吞嚥困難。 O: 扁桃腺腫大。 A: 急性咽喉炎 P: 衛教：請多喝溫水與充分休息。",
            "subjective": "吞嚥困難。",
            "objective": "扁桃腺腫大。",
            "assessment": "急性咽喉炎",
            "plan": "衛教：請多喝溫水與充分休息。",
        },
    ]
    upsert_soap_records(conn, records, CLINIC)


def test_run_batch_default_executes_soap_distill(isolated_conn, tmp_path: Path):
    """測試 1：run_batch 預設執行 SOAP 提煉並將結果記錄於 BatchSummary。"""
    conn = isolated_conn
    _seed_soap_records(conn)

    log_dir = tmp_path / "logs"
    logger = RunLogger(log_dir, echo=False)
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text('{"schema_version": 1, "topics": [], "tree_procedure_names": {}}', encoding="utf-8")

    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        dry_run=False,
        skip_faq=True,
        skip_trees=True,
        enable_soap_distill=True,
        soap_clinic_id=CLINIC,
        soap_min_occurrences=2,
    )

    summary = run_batch(
        conn,
        cfg,
        llm_call=lambda p: "",
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.status == "completed"
    assert summary.soap_distilled_count == 1
    assert summary.soap_conditions == ["急性咽喉炎"]

    # 驗證成功寫入 pending 草稿
    cur = conn.cursor()
    cur.execute("SELECT review_status, source_type FROM faq_cache WHERE topic_key = 'care-急性咽喉炎'")
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "pending"
    assert row[1] == "soap_distilled"


def test_run_batch_skip_soap(isolated_conn, tmp_path: Path):
    """測試 2：enable_soap_distill=False 旗標正確略過 SOAP 提煉。"""
    conn = isolated_conn
    _seed_soap_records(conn)

    log_dir = tmp_path / "logs"
    logger = RunLogger(log_dir, echo=False)
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text('{"schema_version": 1, "topics": [], "tree_procedure_names": {}}', encoding="utf-8")

    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        dry_run=False,
        skip_faq=True,
        skip_trees=True,
        enable_soap_distill=False,
    )

    summary = run_batch(
        conn,
        cfg,
        llm_call=lambda p: "",
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.soap_distilled_count == 0
    assert summary.soap_conditions == []


def test_run_batch_soap_only(isolated_conn, tmp_path: Path):
    """測試 3：soap_only=True 時僅執行 SOAP 提煉並立即回傳。"""
    conn = isolated_conn
    _seed_soap_records(conn)

    log_dir = tmp_path / "logs"
    logger = RunLogger(log_dir, echo=False)
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text('{"schema_version": 1, "topics": [], "tree_procedure_names": {}}', encoding="utf-8")

    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        dry_run=False,
        soap_only=True,
        soap_clinic_id=CLINIC,
        soap_min_occurrences=2,
    )

    summary = run_batch(
        conn,
        cfg,
        llm_call=lambda p: "",
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.status == "completed"
    assert summary.soap_distilled_count == 1
    assert summary.faq_topics_planned == 0


def test_cli_soap_flags(isolated_db_path: Path, tmp_path: Path):
    """測試 4：CLI 命令列 --skip-soap 與 --soap-only 旗標解析與執行。"""
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        _seed_soap_records(conn)
    finally:
        conn.close()

    seed_file = tmp_path / "seeds.json"
    seed_file.write_text('{"schema_version": 1, "topics": [], "tree_procedure_names": {}}', encoding="utf-8")
    log_dir = tmp_path / "logs"

    # 測試 --soap-only 與 --dry-run
    ret = nightly_cli.main(
        [
            "--db", str(isolated_db_path),
            "--seed-file", str(seed_file),
            "--log-dir", str(log_dir),
            "--dry-run",
            "--soap-only",
            "--soap-clinic-id", CLINIC,
            "--soap-min-occurrences", "2",
        ]
    )
    assert ret == 0
