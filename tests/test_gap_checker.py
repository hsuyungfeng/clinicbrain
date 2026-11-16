"""Phase 48-02 單元測試：每日趨勢與 Gap Checker 覆蓋率盤點及待審寫入。"""

import json
import sqlite3

import pytest

from src.batch.gap_checker import (
    TrendTopic,
    check_topic_coverage,
    derive_patient_questions,
    fetch_daily_health_trends,
    run_gap_check,
    validate_url_safety,
)
from src.scraper.policy import PolicyError


def _make_gap_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE faq_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id TEXT,
            topic_key TEXT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            category TEXT NOT NULL,
            source_type TEXT DEFAULT 'manual',
            content_version INTEGER DEFAULT 1,
            needs_regeneration INTEGER DEFAULT 0,
            review_status TEXT DEFAULT 'approved',
            reviewed_at TEXT,
            metadata TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(clinic_id, topic_key, question)
        )
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE faq_cache_fts USING fts5(
            question,
            answer,
            content='faq_cache',
            content_rowid='id',
            tokenize='trigram'
        )
        """
    )
    conn.execute(
        """
        CREATE TRIGGER faq_cache_ai AFTER INSERT ON faq_cache BEGIN
            INSERT INTO faq_cache_fts(rowid, question, answer)
            VALUES (new.id, new.question, new.answer);
        END;
        """
    )
    conn.execute(
        """
        CREATE TABLE page_index_trees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id TEXT,
            doc_id TEXT NOT NULL,
            title TEXT NOT NULL,
            source_type TEXT DEFAULT 'manual',
            review_status TEXT DEFAULT 'approved'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE nhi_catalog_1_400 (
            index_no INTEGER PRIMARY KEY,
            id TEXT,
            system TEXT,
            category TEXT,
            name TEXT,
            icd10 TEXT,
            alias TEXT,
            keywords TEXT,
            clinical_feature TEXT,
            topic_key TEXT,
            visual_available INTEGER DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        INSERT INTO nhi_catalog_1_400
        (index_no, id, system, category, name, icd10, alias, keywords, clinical_feature, topic_key, visual_available)
        VALUES (89, 'w001', 'western', '呼吸道', '感冒', 'J06.9', '[]', '[]', '上呼吸道感染', 'nhi-w001-j06-9', 1)
        """
    )
    conn.commit()
    return conn


def test_validate_url_safety_rejects_non_https_and_private_ip():
    with pytest.raises(PolicyError):
        validate_url_safety("http://example.com/feed.xml")
    with pytest.raises(PolicyError):
        validate_url_safety("https://127.0.0.1/feed.xml")


def test_fetch_daily_health_trends_sanitizes_simplified_and_prices(monkeypatch):
    monkeypatch.setenv("CLINICBRAIN_DEID_KEY", "test-deid-key-for-unit-test-only")
    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel>
      <item><title>流行性感冒预防指南 挂号费500元</title></item>
    </channel></rss>"""

    topics = fetch_daily_health_trends(
        ["https://example.org/rss.xml"],
        fetcher=lambda _u: rss_xml,
        resolver=lambda _h: ["93.184.216.34"],
    )
    assert len(topics) == 1
    assert "預防" in topics[0].title
    assert "500元" not in topics[0].title


def test_check_topic_coverage_covered_partial_uncovered():
    conn = _make_gap_db()
    qs = derive_patient_questions("流感")
    assert len(qs) == 5

    # 1. uncovered
    t_uncovered = TrendTopic(title="流感", topic_key="nhi-w005-j11-1", questions=qs)
    rep_u = check_topic_coverage(conn, t_uncovered)
    assert rep_u.status == "uncovered"
    assert len(rep_u.missing_questions) == 5

    # 2. partial（寫入 2 題 general pending/approved，且測 <3 字標題 LIKE fallback）
    conn.execute(
        "INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, review_status) VALUES (NULL, 'nhi-w005-j11-1', ?, '說明', 'general', 'approved')",
        (qs[0],),
    )
    conn.execute(
        "INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, review_status) VALUES (NULL, 'nhi-w005-j11-1', ?, '說明', 'general', 'pending')",
        (qs[1],),
    )
    conn.commit()
    rep_p = check_topic_coverage(conn, t_uncovered)
    assert rep_p.status == "partial"
    assert len(rep_p.missing_questions) == 3

    # 3. covered（補齊剩餘 3 題）
    for q in qs[2:]:
        conn.execute(
            "INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, review_status) VALUES (NULL, 'nhi-w005-j11-1', ?, '說明', 'general', 'approved')",
            (q,),
        )
    conn.commit()
    rep_c = check_topic_coverage(conn, t_uncovered)
    assert rep_c.status == "covered"
    assert rep_c.missing_questions == []


def test_run_gap_check_dry_run_and_pending_queue_write():
    conn = _make_gap_db()
    agg = [{"icd10": "J06.9", "count": 25}]

    dry_rep = run_gap_check(conn, aggregated_icd10=agg, dry_run=True)
    assert dry_rep.total_topics == 1
    assert dry_rep.uncovered == 1
    assert dry_rep.inserted_pending == 0
    assert conn.execute("SELECT COUNT(*) FROM faq_cache").fetchone()[0] == 0

    real_rep = run_gap_check(conn, aggregated_icd10=agg, dry_run=False)
    assert real_rep.uncovered == 1
    assert real_rep.inserted_pending == 5

    rows = conn.execute(
        "SELECT clinic_id, topic_key, category, source_type, review_status, metadata FROM faq_cache"
    ).fetchall()
    assert len(rows) == 5
    for clinic_id, topic_key, category, source_type, review_status, metadata_str in rows:
        assert clinic_id is None
        assert topic_key == "nhi-w001-j06-9"
        assert category == "general"
        assert source_type == "llm_generated"
        assert review_status == "pending"
        meta = json.loads(metadata_str)
        assert meta["icd10"] == "J06.9"
        assert meta["clinic_rank"] == 1
        assert meta["gap_status"] == "uncovered"
        assert meta["needs_answer"] is True
