"""Phase 54-01: `knowledge_refresh_proposals` 與 `knowledge_refresh_log` 資料表與冪等遷移。"""

from __future__ import annotations

import sqlite3

_DDL = """
CREATE TABLE IF NOT EXISTS knowledge_refresh_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL CHECK(target_type IN ('faq', 'tree', 'visual_edu')),
    target_key TEXT NOT NULL,
    clinic_id TEXT,
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_domain TEXT NOT NULL,
    evidence_summary TEXT NOT NULL,
    diff_summary TEXT NOT NULL,
    current_snapshot TEXT NOT NULL,
    proposed_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_refresh_proposals_pending
    ON knowledge_refresh_proposals(target_type, target_key)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS knowledge_refresh_log (
    target_type TEXT NOT NULL CHECK(target_type IN ('faq', 'tree', 'visual_edu')),
    target_key TEXT NOT NULL,
    last_verified_at TEXT NOT NULL,
    last_status TEXT NOT NULL CHECK(last_status IN ('unchanged', 'proposed', 'error')),
    last_source_url TEXT,
    PRIMARY KEY (target_type, target_key)
);
"""


def ensure_refresh_tables(conn: sqlite3.Connection) -> None:
    """冪等建立 Phase 54 所需之提案與巡檢紀錄資料表。"""
    conn.executescript(_DDL)
    conn.commit()
