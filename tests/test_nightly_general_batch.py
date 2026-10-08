"""
Taiwan Clinic Medical PageIndex RAG System - 一般醫學衛教夜間批次調度與斷點續跑測試 (test_nightly_general_batch)
Phase 17 Plan 17-02: 一般知識庫離峰批次生成管線與斷點續跑
"""

from pathlib import Path
import sqlite3
import pytest

from src.batch.run_log import RunLogger
from src.batch.runner import BatchConfig, run_batch
from src.pageindex.faq_writer import upsert_faqs
import scripts.run_nightly_batch as nightly_cli

CLINIC_ID = "3503190424"


def _dummy_llm(prompt: str) -> str:
    """測試用假 LLM 響應，依據 Prompt 動態回傳合規 JSON 問答。"""
    import json
    lines = prompt.splitlines()
    q_list = []
    for l in lines:
        if l.startswith("- ") and "？" in l:
            q_list.append(l[2:].strip())

    items = []
    for q in q_list:
        items.append({
            "question": q,
            "answer": f"關於{q[:8]}之專業衛教說明。若出現高燒持續加重、呼吸困難或急性腹痛發作，請儘速就醫。"
        })
    return json.dumps(items, ensure_ascii=False)


def test_general_only_batch(isolated_conn: sqlite3.Connection, tmp_path: Path):
    """驗證 general_only 模式僅處理 category='general' 主題，且略過樹重建與 SOAP 提煉。"""
    conn = isolated_conn
    log_dir = tmp_path / "logs"
    logger = RunLogger(log_dir, echo=False)
    seed_file = Path("data/batch/faq_seeds.json")

    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        dry_run=False,
        general_only=True,
        max_faq_topics=3,
    )

    summary = run_batch(
        conn,
        cfg,
        llm_call=_dummy_llm,
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.status == "completed"
    assert summary.soap_distilled_count == 0
    assert summary.trees_planned == 0
    assert summary.faq_topics_planned > 0
    assert summary.general_generated_count > 0

    # 驗證產出之 FAQ 均為 category='general'
    cur = conn.cursor()
    cur.execute("SELECT category, topic_key FROM faq_cache WHERE source_type = 'llm_generated'")
    rows = cur.fetchall()
    assert len(rows) > 0
    for cat, _ in rows:
        assert cat == "general"


def test_skip_general_batch(isolated_conn: sqlite3.Connection, tmp_path: Path):
    """驗證 skip_general 模式排除所有 category='general' 之主題。"""
    conn = isolated_conn
    log_dir = tmp_path / "logs"
    logger = RunLogger(log_dir, echo=False)
    seed_file = Path("data/batch/faq_seeds.json")

    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        dry_run=False,
        skip_general=True,
        max_faq_topics=5,
    )

    summary = run_batch(
        conn,
        cfg,
        llm_call=_dummy_llm,
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.status == "completed"

    # 驗證產出之 FAQ 不包含 general
    cur = conn.cursor()
    cur.execute("SELECT category FROM faq_cache WHERE source_type = 'llm_generated'")
    rows = cur.fetchall()
    for (cat,) in rows:
        assert cat != "general"


def test_mutually_exclusive_cli_flags(isolated_db_path: Path, capsys):
    """驗證 --general-only 與 --soap-only 互斥旗標會報錯退出。"""
    ret = nightly_cli.main([
        "--db", str(isolated_db_path),
        "--general-only",
        "--soap-only",
    ])
    assert ret == 2
    captured = capsys.readouterr()
    assert "互斥" in captured.err


def test_resumable_breakpoint_skip(isolated_conn: sqlite3.Connection, tmp_path: Path):
    """驗證斷點續跑能力：已存在且無 needs_regeneration 標記之題目自動跳過。"""
    conn = isolated_conn
    log_dir = tmp_path / "logs"
    logger = RunLogger(log_dir, echo=False)
    seed_file = Path("data/batch/faq_seeds.json")

    # 預先寫入特定 general FAQ (hypertension-basics 4 題)
    pre_faqs = [
        {
            "question": "什麼是高血壓？",
            "answer": "高血壓是指血壓持續高於標準值的慢性疾病。若出現異常緊繃發作，請儘速就醫。",
            "category": "general",
            "topic_key": "hypertension-basics",
            "clinic_id": None,
        },
        {
            "question": "高血壓常見症狀有哪些？",
            "answer": "初期可能無症狀或輕微頭暈。若出現異常劇烈頭痛發作，請儘速就醫。",
            "category": "general",
            "topic_key": "hypertension-basics",
            "clinic_id": None,
        },
        {
            "question": "高血壓什麼時候需要就醫？",
            "answer": "血壓異常偏高伴隨頭痛嘔吐時需就醫。若出現胸悶氣喘發作，請儘速就醫。",
            "category": "general",
            "topic_key": "hypertension-basics",
            "clinic_id": None,
        },
        {
            "question": "高血壓患者在家要如何照護？",
            "answer": "定時量血壓並保持低鹽飲食。若出現持續頭暈發作，請儘速就醫。",
            "category": "general",
            "topic_key": "hypertension-basics",
            "clinic_id": None,
        },
    ]
    upsert_faqs(conn, pre_faqs, source_type="manual")

    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        dry_run=False,
        general_only=True,
        max_faq_topics=5,
    )

    summary = run_batch(
        conn,
        cfg,
        llm_call=_dummy_llm,
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.status == "completed"
    # hypertension-basics 4 題均已存在且 needs_regeneration=0，必須計入 skipped_count
    assert summary.general_skipped_count >= 4
