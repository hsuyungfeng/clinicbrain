"""Phase 54-02: 本機 LLM 實質差異比對器與合規防護測試。"""

from __future__ import annotations

import json
import sqlite3

import pytest

from src.refresh.detector import evaluate_and_propose, select_refresh_candidates
from src.refresh.schema import ensure_refresh_tables
from src.refresh.sources import SourceEvidence


def _seed_test_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE faq_cache (
            id INTEGER PRIMARY KEY, clinic_id TEXT, topic_key TEXT,
            question TEXT, answer TEXT, category TEXT, review_status TEXT
        );
        CREATE TABLE page_index_trees (
            doc_id TEXT PRIMARY KEY, clinic_id TEXT, title TEXT,
            pre_op TEXT, procedure TEXT, post_op_short TEXT, maintenance TEXT,
            pre_op_physician_notes TEXT, review_status TEXT
        );
        CREATE TABLE visual_assets (
            topic_key TEXT PRIMARY KEY, clinic_id TEXT, title TEXT,
            edu_json TEXT, review_status TEXT
        );
        CREATE TABLE cache_stats (
            id INTEGER PRIMARY KEY, clinic_id TEXT, stat_date TEXT,
            outcome TEXT, keyword TEXT, count INTEGER
        );
        """
    )
    conn.execute(
        "INSERT INTO faq_cache VALUES (1, NULL, 'diverticulitis', '大腸憩室炎可以吃堅果嗎？', '過去建議避免堅果種子。', 'general', 'approved')"
    )
    conn.execute(
        "INSERT INTO page_index_trees VALUES ('hifu-lifting', '3503190424', '音波拉提', '術前評估', '治療步驟', '術後冰敷', '定期保養', '醫師筆記保留', 'approved')"
    )
    ensure_refresh_tables(conn)
    return conn


def test_detector_unchanged_logs_without_proposal() -> None:
    conn = _seed_test_db()
    cands = select_refresh_candidates(conn, daily_quota=5, target_type="faq")
    assert len(cands) == 1
    ev = [SourceEvidence("Study", "https://pubmed.ncbi.nlm.nih.gov/1/", "pubmed.ncbi.nlm.nih.gov", "2026", "No change.")]
    res = evaluate_and_propose(
        conn,
        cands[0],
        ev,
        llm_call=lambda _p: json.dumps({"has_material_change": False, "diff_summary": "無異動", "proposed_payload": {}}),
    )
    assert res == "unchanged"
    assert conn.execute("SELECT COUNT(*) FROM knowledge_refresh_proposals").fetchone()[0] == 0
    assert conn.execute("SELECT last_status FROM knowledge_refresh_log WHERE target_key='1'").fetchone()[0] == "unchanged"


def test_detector_proposes_traditional_masked_and_strips_physician_notes() -> None:
    conn = _seed_test_db()
    cands = select_refresh_candidates(conn, daily_quota=5, target_type="tree")
    assert len(cands) == 1
    ev = [SourceEvidence("Guideline", "https://pubmed.ncbi.nlm.nih.gov/2/", "pubmed.ncbi.nlm.nih.gov", "2026", "New post-op protocol.")]
    llm_out = json.dumps(
        {
            "has_material_change": True,
            "diff_summary": "更新术后照护说明",
            "proposed_payload": {
                "title": "音波拉提",
                "pre_op": "術前評估更新",
                "procedure": "治療步驟更新",
                "post_op_short": "術後溫和保濕",
                "maintenance": "定期防曬保養",
                "pre_op_physician_notes": "LLM不應填寫此欄",
            },
        },
        ensure_ascii=False,
    )
    res = evaluate_and_propose(conn, cands[0], ev, llm_call=lambda _p: llm_out)
    assert res == "proposed"
    row = conn.execute("SELECT diff_summary, proposed_json, status FROM knowledge_refresh_proposals").fetchone()
    assert row[2] == "pending"
    assert "術後" in row[0]  # 簡轉繁
    proposed = json.loads(row[1])
    assert "pre_op_physician_notes" not in proposed


def test_detector_rejects_forbidden_phrase() -> None:
    conn = _seed_test_db()
    cands = select_refresh_candidates(conn, daily_quota=5, target_type="faq")
    ev = [SourceEvidence("Study", "https://pubmed.ncbi.nlm.nih.gov/3/", "pubmed.ncbi.nlm.nih.gov", "2026", "Update.")]
    bad_out = json.dumps(
        {
            "has_material_change": True,
            "diff_summary": "更新",
            "proposed_payload": {"question": "大腸憩室炎", "answer": "保證有效根治！"},
        },
        ensure_ascii=False,
    )
    with pytest.raises(ValueError, match="保證療效禁詞"):
        evaluate_and_propose(conn, cands[0], ev, llm_call=lambda _p: bad_out)
