"""
tests/test_regen_observability.py - DEBT-03 重生成可觀測性補強（複審 W7）

涵蓋：
1. mark_for_regeneration 帶 seed_questions 時，種子外的列回報 not_in_seed 且不設旗標
2. settle_regen_flags 的 details 參數回報 unchanged/failed 的列 id（回傳 dict 維持不變）
3. review_faq list 顯示「待重生」標記
4. review_faq mark-regen --seed 對種子外題目回傳 1 並提示 not_in_seed
"""

import json
from pathlib import Path
import sqlite3

from scripts.review_faq import main as review_cli_main
from src.batch.topic_sources import SeedTopic
from src.pageindex.faq_review import REVIEW_REJECTED, mark_for_regeneration, set_review_status
from src.pageindex.faq_writer import upsert_faqs

CLINIC = "3503190424"
TOPIC = "test-regen-obs"


def _seed_rejected(conn: sqlite3.Connection, question: str) -> int:
    upsert_faqs(
        conn,
        [{"clinic_id": CLINIC, "topic_key": TOPIC, "question": question, "answer": "舊答案", "category": "special"}],
        source_type="llm_generated",
    )
    fid = conn.execute("SELECT id FROM faq_cache WHERE question = ?", (question,)).fetchone()[0]
    set_review_status(conn, [fid], REVIEW_REJECTED)
    return fid


def test_regen_mark_not_in_seed_skipped(isolated_conn: sqlite3.Connection):
    in_id = _seed_rejected(isolated_conn, "種子內題目？")
    out_id = _seed_rejected(isolated_conn, "種子外題目？")
    seed_q = {(CLINIC, TOPIC, "種子內題目？")}

    res = mark_for_regeneration(isolated_conn, [in_id, out_id], seed_questions=seed_q)

    assert res.changed == [in_id]
    assert res.skipped == [(out_id, "not_in_seed")]
    flags = dict(isolated_conn.execute("SELECT id, needs_regeneration FROM faq_cache WHERE id IN (?, ?)", (in_id, out_id)))
    assert flags == {in_id: 1, out_id: 0}


def test_regen_mark_without_seed_unchanged_behavior(isolated_conn: sqlite3.Connection):
    fid = _seed_rejected(isolated_conn, "不帶種子檢查題目？")
    res = mark_for_regeneration(isolated_conn, [fid])
    assert res.changed == [fid]


def test_regen_settle_details_report_ids(isolated_conn: sqlite3.Connection):
    from src.batch.faq_generator import TopicGenResult, settle_regen_flags

    unchanged_id = _seed_rejected(isolated_conn, "結果相同題目？")
    failed_id = _seed_rejected(isolated_conn, "被拒絕題目？")
    mark_for_regeneration(isolated_conn, [unchanged_id, failed_id])
    topic = SeedTopic(
        topic_key=TOPIC, title="t", category="special", clinic_id=CLINIC,
        keywords=(), always=True, tree_doc_id=None, questions=(),
    )
    res = TopicGenResult(
        topic_key=TOPIC, requested=2, skipped_existing=0,
        valid=[{"question": "結果相同題目？", "answer": "舊答案"}],
        regen_questions=["結果相同題目？", "被拒絕題目？"],
    )
    details: dict = {}
    out = settle_regen_flags(isolated_conn, topic, res, details=details)

    assert out == {"regenerated": 0, "unchanged": 1, "failed": 1}
    assert details["unchanged_ids"] == [unchanged_id]
    assert details["failed_ids"] == [failed_id]


def test_regen_list_shows_flag(isolated_db_path: Path, capsys):
    conn = sqlite3.connect(str(isolated_db_path))
    fid = _seed_rejected(conn, "旗標顯示題目？")
    mark_for_regeneration(conn, [fid])
    conn.close()

    code = review_cli_main(["--db", str(isolated_db_path), "list", "--status", "rejected", "--limit", "500"])
    out = capsys.readouterr().out
    assert code == 0
    line = next(ln for ln in out.splitlines() if ln.startswith(f"{fid} ") or ln.startswith(f"{fid:<6}"))
    assert "待重生" in line


def test_regen_cli_mark_not_in_seed(isolated_db_path: Path, tmp_path: Path, capsys):
    conn = sqlite3.connect(str(isolated_db_path))
    fid = _seed_rejected(conn, "CLI種子外題目？")
    conn.close()
    seed = tmp_path / "seed.json"
    seed.write_text(
        json.dumps({"schema_version": 1, "topics": [{
            "topic_key": TOPIC, "title": "測試", "category": "special", "clinic_id": CLINIC,
            "keywords": [], "always": True, "questions": ["另一題不同的問題？"],
        }], "tree_procedure_names": {}}, ensure_ascii=False),
        encoding="utf-8",
    )

    code = review_cli_main(["--db", str(isolated_db_path), "mark-regen", "--seed", str(seed), str(fid)])
    out = capsys.readouterr().out
    assert code == 1
    assert "not_in_seed" in out
    conn = sqlite3.connect(str(isolated_db_path))
    assert conn.execute("SELECT needs_regeneration FROM faq_cache WHERE id = ?", (fid,)).fetchone()[0] == 0
    conn.close()
