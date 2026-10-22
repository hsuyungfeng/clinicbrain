"""Phase 34 2.32：回答引用的推理樹附上已核准動畫；衛教 FAQ 不自動昇華。（隔離副本）"""

from __future__ import annotations

import copy
import sqlite3

from tests.conftest import apply_visual_migration
from src.visual.match import visuals_for_tree_sources
from src.visual.review import set_review_status
from src.visual.writer import upsert_assets

CLINIC_A = "3503190424"
CLINIC_B = "3503264627"
_IR = {
    "topic_key": "x",
    "title": "測試動畫標題",
    "keywords": ["測試關鍵字"],
    "scenes": [
        {"blueprint": "process_diagram", "title": "甲", "caption": "這是一段足夠長的說明文字，用來測試動畫的附加與排序規則是否正確運作。", "labels": [{"text": "標籤", "tone": "neutral"}]},
        {"blueprint": "contrast", "title": "乙", "caption": "這是另一段足夠長的說明文字，用來測試對照場景在回答引用時的附加行為正確與否。", "labels": [{"text": "標籤", "tone": "neutral"}]},
        {"blueprint": "timeline", "title": "丙", "caption": "這是最後一段足夠長的說明文字，恢復程度因人而異，需由醫師當面評估後才能判斷。", "labels": [{"text": "標籤", "tone": "neutral"}]},
    ],
}


def _approve_clinic_card(conn, clinic_id: str, topic: str) -> None:
    ir = copy.deepcopy(_IR)
    ir["topic_key"] = topic
    upsert_assets(conn, [{"clinic_id": clinic_id, "topic_key": topic, "title": ir["title"],
                          "keywords": ir["keywords"], "ir": ir}], source_type="llm_generated")
    set_review_status(conn, topic, "approved", clinic_id=clinic_id)


def _db(isolated_db_path):
    apply_visual_migration(isolated_db_path)
    return sqlite3.connect(str(isolated_db_path))


def test_clinic_context_prefers_clinic_card_then_general(isolated_db_path):
    conn = _db(isolated_db_path)
    try:
        _approve_clinic_card(conn, CLINIC_B, f"tree-{CLINIC_B}-zz-src-alpha")  # 昇華為 tree-zz-src-alpha
        doc = f"{CLINIC_B}-zz-src-alpha"
        got = visuals_for_tree_sources(conn, [doc], clinic_id=CLINIC_B)
        assert len(got) == 1
        assert got[0]["topic_key"] == f"tree-{CLINIC_B}-zz-src-alpha"  # 診所版優先
        assert "clinic_id" not in got[0]  # 對外格式不暴露診所代碼
    finally:
        conn.close()


def test_other_clinic_gets_shared_copy_never_foreign_clinic_card(isolated_db_path):
    conn = _db(isolated_db_path)
    try:
        _approve_clinic_card(conn, CLINIC_B, f"tree-{CLINIC_B}-zz-src-beta")
        doc = f"{CLINIC_B}-zz-src-beta"
        got = visuals_for_tree_sources(conn, [doc], clinic_id=CLINIC_A)
        assert [g["topic_key"] for g in got] == ["tree-zz-src-beta"]  # 只拿一般醫學共用版
    finally:
        conn.close()


def test_general_context_prefers_shared_copy(isolated_db_path):
    conn = _db(isolated_db_path)
    try:
        _approve_clinic_card(conn, CLINIC_B, f"tree-{CLINIC_B}-zz-src-gamma")
        got = visuals_for_tree_sources(conn, [f"{CLINIC_B}-zz-src-gamma"], clinic_id=None)
        assert [g["topic_key"] for g in got] == ["tree-zz-src-gamma"]
    finally:
        conn.close()


def test_same_procedure_returns_one_visual_and_missing_returns_empty(isolated_db_path):
    conn = _db(isolated_db_path)
    try:
        _approve_clinic_card(conn, CLINIC_B, f"tree-{CLINIC_B}-zz-src-delta")
        dup = visuals_for_tree_sources(conn, [f"{CLINIC_B}-zz-src-delta", "zz-src-delta"], clinic_id=CLINIC_B)
        assert len(dup) == 1
        assert visuals_for_tree_sources(conn, ["no-such-tree-doc"], clinic_id=CLINIC_B) == []
        assert visuals_for_tree_sources(conn, [], clinic_id=None) == []
    finally:
        conn.close()


def test_clinic_faq_approval_never_creates_general_rows(isolated_db_path):
    """衛教 FAQ 保持每家診所專屬：核准診所 FAQ 不會在一般醫學池新增任何列。"""
    from src.pageindex.faq_review import set_review_status as faq_set_status

    conn = _db(isolated_db_path)
    try:
        cur = conn.execute("PRAGMA table_info(faq_cache)")
        cols = {r[1] for r in cur.fetchall()}
        assert "review_status" in cols
        conn.execute(
            "INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status) "
            "VALUES (?, 'zz-faq-topic', '測試診所問題？', '測試診所回答文字。', 'special', 'clinic_upload', 'pending')",
            (CLINIC_B,),
        )
        conn.commit()
        fid = conn.execute("SELECT id FROM faq_cache WHERE topic_key = 'zz-faq-topic'").fetchone()[0]
        before = conn.execute("SELECT COUNT(*) FROM faq_cache WHERE clinic_id IS NULL").fetchone()[0]
        faq_set_status(conn, [fid], "approved")
        after = conn.execute("SELECT COUNT(*) FROM faq_cache WHERE clinic_id IS NULL").fetchone()[0]
        assert after == before
    finally:
        conn.close()
