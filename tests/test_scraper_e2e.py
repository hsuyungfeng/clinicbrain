"""Phase 23 Task 4：網站素材擷取端到端整合測試 (E2E)。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import pytest

from src.pageindex.faq_review import (
    has_metadata_column,
    has_review_status,
    set_review_status,
    visible_faq_sql,
)
from src.scraper.drafts import GUARANTEE_PHRASES
from src.scraper.runner import ScrapeOptions, run_scrape_urls

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scraper"
SOURCES_JSON = Path(__file__).parents[1] / "data" / "scraper" / "sources.json"
PROD_DB_PATH = Path(__file__).parents[1] / "clinic.db"


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_scraper_end_to_end_lifecycle(isolated_conn):
    """端到端測試：以 fixture 進行離線寫入、隱蔽性檢驗、醫師審核通過、冪等重跑與正式庫零異動。"""
    prod_hash_before = _hash_file(PROD_DB_PATH)

    assert has_metadata_column(isolated_conn)
    assert has_review_status(isolated_conn)

    # 1. 執行批次擷取寫入
    urls = ["fixture://clinic_sample_a.html"]
    options = ScrapeOptions(
        clinic_id="3503190424",
        allowlist_path=SOURCES_JSON,
        write=True,
        fixture_dir=FIXTURES_DIR,
        db_path=":memory:",  # 由 conn_factory 接管
    )

    report1 = run_scrape_urls(
        urls,
        options=options,
        conn_factory=lambda: isolated_conn,
        lock_try=lambda p: 101,
        lock_release=lambda fd: None,
    )

    assert report1.status == "ok"
    assert report1.summary["ok"] == 1
    assert report1.summary["drafts_written"] == 2
    assert report1.summary["unchanged"] == 0

    # 2. 查驗資料庫中草稿屬性與 metadata
    cur = isolated_conn.execute(
        "SELECT id, question, answer, source_type, review_status, metadata FROM faq_cache WHERE topic_key LIKE 'web-%'"
    )
    rows = cur.fetchall()
    assert len(rows) == 2

    draft_ids = []
    for r in rows:
        row_id, q, a, src_type, rev_status, meta_raw = r
        draft_ids.append(row_id)
        assert src_type == "web_upload"
        assert rev_status == "pending"

        meta = json.loads(meta_raw)
        assert meta["origin"] == "web_scrape"
        assert meta["source_url"] == "fixture://clinic_sample_a.html"
        assert meta["fetched_at"]
        assert "doctors" not in meta["extracted"]

        # 檢驗問答不含外部機構敏感資訊與禁詞
        assert "台北市中山區南京東路" not in q
        assert "台北市中山區南京東路" not in a
        assert "02-2500-1234" not in q
        assert "02-2500-1234" not in a
        assert "王小明" not in q
        assert "王小明" not in a
        assert "1500" not in q
        assert "1500" not in a
        assert "NT$" not in q
        assert "NT$" not in a
        for phrase in GUARANTEE_PHRASES:
            assert phrase not in q
            assert phrase not in a

    # 3. 審核前隱蔽驗證：對外可見查詢完全不出現
    vis_sql = visible_faq_sql(isolated_conn)
    cur = isolated_conn.execute(
        f"SELECT COUNT(*) FROM faq_cache WHERE topic_key LIKE 'web-%' AND ({vis_sql})"
    )
    visible_count = cur.fetchone()[0]
    assert visible_count == 0

    # 4. 人工審核模擬：核准其中一筆
    res = set_review_status(isolated_conn, [draft_ids[0]], "approved")
    isolated_conn.commit()
    assert len(res.changed) == 1
    assert res.changed[0] == draft_ids[0]

    # 核准後：該筆可見，另一筆仍隱蔽
    cur = isolated_conn.execute(
        f"SELECT COUNT(*) FROM faq_cache WHERE topic_key LIKE 'web-%' AND ({vis_sql})"
    )
    assert cur.fetchone()[0] == 1

    # 5. 冪等重跑：同批次再次執行，unchanged 為 2，drafts_written 為 0
    report2 = run_scrape_urls(
        urls,
        options=options,
        conn_factory=lambda: isolated_conn,
        lock_try=lambda p: 101,
        lock_release=lambda fd: None,
    )
    assert report2.status == "ok"
    assert report2.summary["drafts_written"] == 0
    assert report2.summary["unchanged"] == 2

    # 6. 正式資料庫完整性驗證：正式 clinic.db 零異動
    prod_hash_after = _hash_file(PROD_DB_PATH)
    assert prod_hash_before == prod_hash_after
