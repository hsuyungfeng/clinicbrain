"""Phase 34 Plan 03：template_override 欄位遷移與覆寫優先序測試（隔離副本／記憶體資料庫）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.migrate_visual_template_override import main as migrate_main
from src.visual.autodraft import autodraft_from_tree, infer_scene1_blueprint


def _old_visual_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE visual_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id TEXT,
            topic_key TEXT NOT NULL,
            title TEXT NOT NULL,
            metadata TEXT
        );
        INSERT INTO visual_assets (clinic_id, topic_key, title, metadata)
        VALUES ('3503190424', 'tree-old-row', '舊列', NULL);
        """
    )
    conn.commit()
    conn.close()


def test_migration_adds_column_and_preserves_rows(tmp_path):
    db = tmp_path / "copy.db"
    _old_visual_db(db)
    assert migrate_main(["--db", str(db)]) == 0
    conn = sqlite3.connect(str(db))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(visual_assets)")}
        assert "template_override" in cols
        row = conn.execute("SELECT title, template_override FROM visual_assets").fetchone()
        assert row == ("舊列", None)
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_path):
    db = tmp_path / "copy.db"
    _old_visual_db(db)
    assert migrate_main(["--db", str(db)]) == 0
    assert migrate_main(["--db", str(db)]) == 0


def test_dry_run_does_not_modify_database(tmp_path):
    db = tmp_path / "copy.db"
    _old_visual_db(db)
    before = db.read_bytes()
    assert migrate_main(["--db", str(db), "--dry-run"]) == 0
    assert db.read_bytes() == before


def test_prod_db_requires_confirm_flag():
    from scripts.migrate_visual_template_override import PROD_DB

    if not PROD_DB.exists():
        pytest.skip("正式庫不存在")
    assert migrate_main(["--db", str(PROD_DB)]) == 2


def test_override_takes_precedence_over_keyword_inference():
    tree = {"doc_id": "x", "title": "全方位抽脂體雕手術", "summary_text": "", "procedure": "", "template_override": "process_diagram"}
    bp, info = infer_scene1_blueprint(tree)
    assert bp == "process_diagram"
    assert info["params_template"]


def test_without_override_behaviour_is_unchanged():
    """無覆寫（欄位缺失或為 None）時，推斷結果必須與 Phase 33 完全相同。"""
    base = {"doc_id": "x", "title": "全方位抽脂體雕手術", "summary_text": "", "procedure": ""}
    bp_missing, info_missing = infer_scene1_blueprint(base)
    bp_none, info_none = infer_scene1_blueprint({**base, "template_override": None})
    assert (bp_missing, info_missing) == (bp_none, info_none)


def test_unknown_override_is_rejected_before_llm(tmp_path):
    db = tmp_path / "copy.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE visual_assets (
            id INTEGER PRIMARY KEY, clinic_id TEXT, topic_key TEXT NOT NULL,
            template_override TEXT, UNIQUE(clinic_id, topic_key)
        );
        INSERT INTO visual_assets (clinic_id, topic_key, template_override)
        VALUES ('3503190424', 'tree-override-test', 'no_such_blueprint');
        """
    )
    conn.commit()

    def _must_not_call(prompt):
        raise AssertionError("非法覆寫不得呼叫 LLM")

    tree = {"doc_id": "override-test", "clinic_id": "3503190424", "title": "測試", "summary_text": "", "procedure": ""}
    res = autodraft_from_tree(conn, tree, llm_call=_must_not_call)
    assert res == {"status": "error", "code": "unknown_blueprint"}
    conn.close()


# ---- 34-03 接上：覆寫設定函式與管理端 API ----

def _migrated_copy(isolated_db_path):
    from tests.conftest import apply_visual_migration

    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    conn.execute(
        "INSERT INTO visual_assets (clinic_id, topic_key, title, keywords, ir_json, source_type, review_status) "
        "VALUES ('3503190424', 'tree-override-ui', '測試', '[]', '{}', 'llm_generated', 'approved')"
    )
    conn.commit()
    row_id = conn.execute("SELECT id FROM visual_assets WHERE topic_key = 'tree-override-ui'").fetchone()[0]
    return conn, row_id


def test_set_template_override_rejects_unknown_and_resets_approved(isolated_db_path):
    from src.visual.review import set_template_override

    conn, row_id = _migrated_copy(isolated_db_path)
    try:
        with pytest.raises(ValueError, match="unknown_blueprint"):
            set_template_override(conn, row_id, "no_such_blueprint")
        res = set_template_override(conn, row_id, "process_diagram")
        assert res["template_override"] == "process_diagram"
        assert res["review_status"] == "pending"  # 已核准草稿改值後回到待審（Fail-Closed）
        again = set_template_override(conn, row_id, "process_diagram")
        assert again["status"] == "unchanged"
        cleared = set_template_override(conn, row_id, None)
        assert cleared["template_override"] is None
    finally:
        conn.close()


def test_admin_routes_list_blueprints_and_put_override(isolated_db_path, monkeypatch):
    from fastapi.testclient import TestClient
    from src.api.app import app
    from src.api.config import config

    conn, row_id = _migrated_copy(isolated_db_path)
    conn.close()
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "admin_api_key", "")
    with TestClient(app) as client:
        bp = client.get("/api/v1/admin/visual-blueprints").json()["blueprints"]
        assert "surgical_action" in bp and "contrast" in bp
        bad = client.put(f"/api/v1/admin/visuals/{row_id}/template-override", json={"template": "nope"})
        assert bad.status_code == 422
        ok = client.put(f"/api/v1/admin/visuals/{row_id}/template-override", json={"template": "surgical_action"})
        assert ok.status_code == 200 and ok.json()["template_override"] == "surgical_action"
        detail = client.get(f"/api/v1/admin/visuals/{row_id}").json()
        assert detail["template_override"] == "surgical_action"
        extra = client.put(f"/api/v1/admin/visuals/{row_id}/template-override", json={"template": "contrast", "x": 1})
        assert extra.status_code == 422
        missing = client.put("/api/v1/admin/visuals/999999/template-override", json={"template": "contrast"})
        assert missing.status_code == 404
