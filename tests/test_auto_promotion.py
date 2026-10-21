"""
Phase 32 Plan 32-01：診所核准即昇華為一般醫學共用資產（Auto-Promotion）測試。

涵蓋：
- 視覺解說卡：診所核准自動昇華（去前綴、approved、占位保護、重新核准更新）。
- 臨床推理樹：診所核准自動昇華（general- 前綴避開全域 UNIQUE doc_id、占位保護）。
- 搜尋：一般醫學模式只回傳已核准之推理樹。
- CLI：dry-run 零寫入、副本實寫且冪等、正式庫防護、缺庫拒絕。

所有測試一律使用隔離副本（isolated_db_path），絕不寫入正式庫 clinic.db。
測試資料使用獨有的 topic_key / doc_id 前綴（promo-test-*），避免與副本既有資料衝突。
"""

import copy
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tests.conftest import apply_visual_migration
from scripts.promote_clinic_assets_to_general import PROD_DB_PATH
from scripts.promote_clinic_assets_to_general import main as promote_main
from src.pageindex.db_writer import upsert_trees
from src.pageindex.tree_review import approve_tree, promote_tree, tree_general_doc_id
from src.query.search import search_page_index_trees
from src.visual.review import (
    promote_visual_row,
    set_review_status,
    visible_assets,
    visual_general_topic_key,
)
from src.visual.writer import upsert_assets

CLINIC_A = "3503190424"  # 緻妍（doc_id 無前綴）
CLINIC_B = "3503264627"  # 凡登（doc_id 與 topic_key 含前綴）

SAMPLE_IR = {
    "topic_key": "autologous-fat-grafting",
    "title": "自體脂肪移植手術簡介",
    "keywords": ["自體脂肪", "抽脂填補", "脂肪移植"],
    "scenes": [
        {
            "blueprint": "process_diagram",
            "title": "脂肪抽取與純化",
            "caption": "利用專業抽脂技術自腹部或大腿抽取多餘脂肪，經過離心純化技術篩選出健康完整的脂肪細胞以供後續填補。",
            "labels": [
                {"text": "抽取脂肪", "tone": "neutral"},
                {"text": "離心純化", "tone": "optimal"},
            ],
        },
        {
            "blueprint": "contrast",
            "title": "注射填補方式",
            "caption": "醫師採用多層次微量注射技術將脂肪分散注入目標部位，能使組織均勻吸收營養並減少局部硬塊發生的風險。",
            "labels": [
                {"text": "分層注射", "tone": "optimal"},
                {"text": "過量填補", "tone": "warning"},
            ],
        },
        {
            "blueprint": "timeline",
            "title": "術後照護週期",
            "caption": "術後初期需避免劇烈擠壓填補區域，保持規律作息與均衡營養，通常在數週後組織便會逐步達到一定程度的穩定。",
            "labels": [
                {"text": "避免按壓", "tone": "warning"},
                {"text": "穩定成形", "tone": "optimal"},
            ],
        },
    ],
}


def _visual_ir(topic_key: str, title: str) -> dict:
    ir = copy.deepcopy(SAMPLE_IR)
    ir["topic_key"] = topic_key
    ir["title"] = title
    return ir


def _upsert_visual(conn, clinic_id, topic_key, title):
    ir = _visual_ir(topic_key, title)
    upsert_assets(
        conn,
        [{"clinic_id": clinic_id, "topic_key": topic_key, "title": title, "keywords": ir["keywords"], "ir": ir}],
        source_type="llm_generated",
    )


def _general_visual(conn, topic_key):
    cur = conn.execute(
        "SELECT title, review_status, metadata FROM visual_assets WHERE clinic_id IS NULL AND topic_key = ?",
        (topic_key,),
    )
    return cur.fetchone()


def _tree_row(doc_id, clinic_id, summary):
    return {
        "doc_id": doc_id,
        "clinic_id": clinic_id,
        "title": f"{doc_id} 測試標題",
        "category": "special",
        "pre_op": "術前須知測試內容。",
        "pre_op_physician_notes": None,
        "procedure": "療程步驟測試內容。",
        "procedure_physician_notes": None,
        "post_op_short": "術後照護測試內容。",
        "post_op_short_physician_notes": None,
        "maintenance": "長期維持測試內容。",
        "maintenance_physician_notes": None,
        "summary_text": summary,
    }


def _tree_id(conn, doc_id):
    return conn.execute("SELECT id FROM page_index_trees WHERE doc_id = ?", (doc_id,)).fetchone()[0]


def _general_tree(conn, doc_id):
    return conn.execute(
        "SELECT clinic_id, review_status, source_type, reviewed_by FROM page_index_trees WHERE doc_id = ?",
        (doc_id,),
    ).fetchone()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 視覺解說卡：核准即昇華
# ---------------------------------------------------------------------------

def test_visual_key_strips_clinic_prefix():
    assert visual_general_topic_key(CLINIC_B, "tree-3503264627-mid-lower-smas-facelift") == "tree-mid-lower-smas-facelift"
    assert visual_general_topic_key(CLINIC_B, "3503264627-foo") == "foo"
    # 無前綴者原樣保留（與來源列 clinic_id 不同鍵，不會衝突）
    assert visual_general_topic_key(CLINIC_A, "tree-laser-skin-resurfacing") == "tree-laser-skin-resurfacing"


def test_clinic_visual_approval_auto_promotes_to_general(isolated_db_path: Path):
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        _upsert_visual(conn, CLINIC_B, "tree-3503264627-promo-alpha", "測試昇華 alpha")
        res = set_review_status(conn, "tree-3503264627-promo-alpha", "approved", clinic_id=CLINIC_B)

        assert res["status"] == "ok"
        assert res["promotion"] == {"status": "inserted", "topic_key": "tree-promo-alpha"}
        title, status, metadata = _general_visual(conn, "tree-promo-alpha")
        assert status == "approved"
        assert "promoted_from_clinic_id" in metadata and CLINIC_B in metadata
        # 一般醫學共用卡：對一般醫學查詢（clinic_id=None）可見
        keys = [a["topic_key"] for a in visible_assets(conn, clinic_id=None)]
        assert "tree-promo-alpha" in keys
    finally:
        conn.close()


def test_pending_clinic_visual_is_not_promoted(isolated_db_path: Path):
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        _upsert_visual(conn, CLINIC_B, "tree-3503264627-promo-pending", "測試待審 pending")
        assert _general_visual(conn, "tree-promo-pending") is None
    finally:
        conn.close()


def test_general_native_slot_is_never_overwritten(isolated_db_path: Path):
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        _upsert_visual(conn, None, "tree-promo-beta", "一般醫學原生內容 beta")
        set_review_status(conn, "tree-promo-beta", "approved", clinic_id=None)

        _upsert_visual(conn, CLINIC_B, "tree-3503264627-promo-beta", "診所版本 beta")
        res = set_review_status(conn, "tree-3503264627-promo-beta", "approved", clinic_id=CLINIC_B)

        assert res["promotion"]["status"] == "skipped"
        assert res["promotion"]["reason"] == "general_slot_occupied"
        title, status, _ = _general_visual(conn, "tree-promo-beta")
        assert title == "一般醫學原生內容 beta"
        assert status == "approved"
    finally:
        conn.close()


def test_reapproval_updates_own_promoted_row(isolated_db_path: Path):
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        _upsert_visual(conn, CLINIC_A, "tree-3503190424-promo-gamma", "舊標題 gamma")
        set_review_status(conn, "tree-3503190424-promo-gamma", "approved", clinic_id=CLINIC_A)
        assert _general_visual(conn, "tree-promo-gamma")[0] == "舊標題 gamma"

        # 診所修訂後重新核准：內容變更 → 先 pending → 再核准時同步更新一般醫學列
        _upsert_visual(conn, CLINIC_A, "tree-3503190424-promo-gamma", "新標題 gamma")
        set_review_status(conn, "tree-3503190424-promo-gamma", "approved", clinic_id=CLINIC_A)

        title, status, _ = _general_visual(conn, "tree-promo-gamma")
        assert title == "新標題 gamma"
        assert status == "approved"
    finally:
        conn.close()


def test_promote_visual_row_rejects_invalid_ir_and_rolls_back(isolated_db_path: Path):
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        bad_ir = _visual_ir("tree-3503264627-promo-bad", "壞資料")
        bad_ir["scenes"][0]["caption"] = "含阿拉伯數字 123 的非法說明"
        with pytest.raises(ValueError):
            promote_visual_row(
                conn,
                clinic_id=CLINIC_B,
                topic_key="tree-3503264627-promo-bad",
                title=bad_ir["title"],
                keywords_json='["測試"]',
                ir_json=json.dumps(bad_ir, ensure_ascii=False),
                source_type="llm_generated",
                metadata=None,
            )
        conn.rollback()
        assert _general_visual(conn, "tree-promo-bad") is None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 臨床推理樹：核准即昇華
# ---------------------------------------------------------------------------

def test_clinic_tree_approval_auto_promotes_with_general_doc_id(isolated_db_path: Path):
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        upsert_trees(conn, [_tree_row("3503264627-promo-test-gamma", CLINIC_B, "測試摘要關鍵字甲")],
                     source_type="llm_generated", review_status="pending")
        assert approve_tree(conn, _tree_id(conn, "3503264627-promo-test-gamma")) is True

        general_doc = tree_general_doc_id(CLINIC_B, "3503264627-promo-test-gamma")
        assert general_doc == "general-promo-test-gamma"
        clinic_id, status, source, reviewed_by = _general_tree(conn, general_doc)
        assert clinic_id is None
        assert status == "approved"
        assert source == "clinic_upload"
        assert reviewed_by == f"auto-promotion:{CLINIC_B}"
    finally:
        conn.close()


def test_unprefixed_clinic_tree_does_not_collide_on_unique_doc_id(isolated_db_path: Path):
    """緻妍的 doc_id 無前綴：去前綴會與來源列自身衝突，因此必須加 general- 前綴。"""
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        upsert_trees(conn, [_tree_row("promo-test-delta", CLINIC_A, "測試摘要關鍵字乙")],
                     source_type="llm_generated", review_status="pending")
        assert approve_tree(conn, _tree_id(conn, "promo-test-delta")) is True

        assert _general_tree(conn, "general-promo-test-delta")[0] is None
        # 來源列仍保留診所歸屬且已核准
        assert _general_tree(conn, "promo-test-delta")[:2] == (CLINIC_A, "approved")
    finally:
        conn.close()


def test_tree_slot_occupied_by_other_clinic_is_skipped_without_overwrite(isolated_db_path: Path):
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        upsert_trees(conn, [_tree_row("promo-test-eps", CLINIC_A, "甲診所摘要關鍵字")],
                     source_type="llm_generated", review_status="pending")
        approve_tree(conn, _tree_id(conn, "promo-test-eps"))

        # 另一診所以不同 doc_id 但同 slug 核准：昇華應被略過，不覆寫甲診所版本
        upsert_trees(conn, [_tree_row("3503264627-promo-test-eps", CLINIC_B, "乙診所摘要關鍵字")],
                     source_type="llm_generated", review_status="pending")
        assert approve_tree(conn, _tree_id(conn, "3503264627-promo-test-eps")) is True

        res = promote_tree(conn, _tree_id(conn, "3503264627-promo-test-eps"))
        assert res == {"status": "skipped", "reason": "general_slot_occupied", "doc_id": "general-promo-test-eps"}
        clinic_id, status, _, reviewed_by = _general_tree(conn, "general-promo-test-eps")
        assert reviewed_by == f"auto-promotion:{CLINIC_A}"
        assert conn.execute(
            "SELECT summary_text FROM page_index_trees WHERE doc_id = 'general-promo-test-eps'"
        ).fetchone()[0] == "甲診所摘要關鍵字"
        # 乙診所列本身仍已核准
        assert _general_tree(conn, "3503264627-promo-test-eps")[:2] == (CLINIC_B, "approved")
    finally:
        conn.close()


def test_general_mode_search_returns_only_approved_trees(isolated_db_path: Path):
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        upsert_trees(conn, [_tree_row("promo-test-zeta", CLINIC_A, "專屬療程測試關鍵字丙")],
                     source_type="llm_generated", review_status="pending")
        # 待審草稿：一般醫學模式下不得出現
        hits = search_page_index_trees(conn, "專屬療程測試關鍵字丙", clinic_id=None)
        assert all(h.fields["doc_id"] != "promo-test-zeta" for h in hits)

        approve_tree(conn, _tree_id(conn, "promo-test-zeta"))
        hits = search_page_index_trees(conn, "專屬療程測試關鍵字丙", clinic_id=None)
        doc_ids = {h.fields["doc_id"] for h in hits}
        assert "general-promo-test-zeta" in doc_ids
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 一鍵昇華 CLI
# ---------------------------------------------------------------------------

def _seed_clinic_visual_approved_without_promotion(path: Path, clinic_id: str, topic_key: str, title: str):
    """以直接 SQL 造成「已核准但尚未昇華」的歷史資料，供 CLI 回填測試使用。"""
    conn = sqlite3.connect(str(path))
    try:
        _upsert_visual(conn, clinic_id, topic_key, title)
        conn.execute(
            "UPDATE visual_assets SET review_status = 'approved' WHERE clinic_id = ? AND topic_key = ?",
            (clinic_id, topic_key),
        )
        conn.commit()
    finally:
        conn.close()


def test_cli_dry_run_leaves_database_byte_identical(isolated_db_path: Path):
    apply_visual_migration(isolated_db_path)
    _seed_clinic_visual_approved_without_promotion(isolated_db_path, CLINIC_B, "tree-3503264627-promo-cli-a", "CLI 測試 a")
    before = _sha256(isolated_db_path)

    assert promote_main(["--db", str(isolated_db_path), "--dry-run"]) == 0
    assert _sha256(isolated_db_path) == before


def test_cli_real_run_on_copy_promotes_and_is_idempotent(isolated_db_path: Path):
    apply_visual_migration(isolated_db_path)
    _seed_clinic_visual_approved_without_promotion(isolated_db_path, CLINIC_B, "tree-3503264627-promo-cli-b", "CLI 測試 b")

    assert promote_main(["--db", str(isolated_db_path)]) == 0
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        assert _general_visual(conn, "tree-promo-cli-b")[1] == "approved"
    finally:
        conn.close()

    # 第二次執行：不會新增重複列（冪等）
    conn = sqlite3.connect(str(isolated_db_path))
    before_count = conn.execute("SELECT COUNT(*) FROM visual_assets WHERE clinic_id IS NULL").fetchone()[0]
    conn.close()
    assert promote_main(["--db", str(isolated_db_path)]) == 0
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        assert conn.execute("SELECT COUNT(*) FROM visual_assets WHERE clinic_id IS NULL").fetchone()[0] == before_count
    finally:
        conn.close()


def test_cli_refuses_prod_db_without_flag_and_does_not_touch_it():
    if not PROD_DB_PATH.exists():
        pytest.skip("正式庫不存在")
    before = _sha256(PROD_DB_PATH)
    assert promote_main(["--db", str(PROD_DB_PATH)]) == 2
    assert _sha256(PROD_DB_PATH) == before


def test_cli_missing_db_returns_2(tmp_path: Path):
    assert promote_main(["--db", str(tmp_path / "nope.db")]) == 2


def test_cli_clinic_filter_limits_scope(isolated_db_path: Path, capsys):
    apply_visual_migration(isolated_db_path)
    assert promote_main(["--db", str(isolated_db_path), "--dry-run", "--clinic-id", CLINIC_A]) == 0
    out = capsys.readouterr().out
    assert "昇華統計" in out
