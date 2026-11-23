"""Phase 54-03: 新知提案審核與寫回 API 端對端測試。"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.dependencies import get_read_db, get_write_db
from src.refresh.schema import ensure_refresh_tables


@pytest.fixture()
def isolated_api_db(tmp_path: Path):
    src_db = Path(__file__).resolve().parents[1] / "clinic.db"
    dst_db = tmp_path / "clinic_test.db"
    shutil.copy2(src_db, dst_db)

    conn = sqlite3.connect(dst_db)
    ensure_refresh_tables(conn)
    conn.close()

    def _override_read():
        c = sqlite3.connect(dst_db, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA query_only = ON;")
        try:
            yield c
        finally:
            c.close()

    def _override_write():
        c = sqlite3.connect(dst_db, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON;")
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_read_db] = _override_read
    app.dependency_overrides[get_write_db] = _override_write
    try:
        yield dst_db
    finally:
        app.dependency_overrides.clear()


def test_refresh_proposals_approve_and_reject_flow(isolated_api_db: Path):
    conn = sqlite3.connect(isolated_api_db)
    # 1. 取得一筆真實已核准 FAQ、一筆推理樹、一筆 visual_edu 資產
    faq_row = conn.execute(
        "SELECT id, clinic_id, topic_key, question, answer, category, content_version "
        "FROM faq_cache WHERE review_status = 'approved' LIMIT 1"
    ).fetchone()
    assert faq_row is not None
    fid, faq_cid, faq_tk, faq_q, faq_a, faq_cat, faq_ver = faq_row

    tree_row = conn.execute(
        "SELECT doc_id, clinic_id, title, pre_op, procedure, post_op_short, maintenance, "
        "pre_op_physician_notes, content_version "
        "FROM page_index_trees WHERE review_status = 'approved' LIMIT 1"
    ).fetchone()
    assert tree_row is not None
    doc_id, tree_cid, tree_title, pre_op, proc, post_op, maint, orig_notes, tree_ver = tree_row
    # 寫入測試醫師筆記驗證核准寫回時不得覆寫
    conn.execute(
        "UPDATE page_index_trees SET pre_op_physician_notes = '醫師專屬警語不可覆寫' WHERE doc_id = ?",
        (doc_id,),
    )

    vis_row = conn.execute(
        "SELECT topic_key, clinic_id, title, edu_json, ir_json, content_version "
        "FROM visual_assets WHERE review_status = 'approved' AND edu_json IS NOT NULL LIMIT 1"
    ).fetchone()
    assert vis_row is not None
    vis_tk, vis_cid, vis_title, vis_edu_str, vis_ir_str, vis_ver = vis_row
    vis_edu = json.loads(vis_edu_str)
    vis_ir = json.loads(vis_ir_str)
    orig_organ = vis_ir.get("organ_system")
    orig_target = vis_ir.get("anatomy_target")

    # 2. 插入 4 筆 pending 提案（faq approve, tree approve, visual_edu approve, faq reject）
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO knowledge_refresh_proposals
        (target_type, target_key, clinic_id, title, source_url, source_domain,
         evidence_summary, diff_summary, current_snapshot, proposed_json, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            "faq",
            str(fid),
            faq_cid,
            faq_q,
            "https://pubmed.ncbi.nlm.nih.gov/39999991/",
            "pubmed.ncbi.nlm.nih.gov",
            "最新指引更新",
            "補充最新術後追蹤建議",
            json.dumps({"question": faq_q, "answer": faq_a}, ensure_ascii=False),
            json.dumps(
                {"question": faq_q, "answer": f"{faq_a}（依據最新指引補充：建議一週後回診追蹤）", "category": faq_cat, "topic_key": faq_tk},
                ensure_ascii=False,
            ),
        ),
    )
    faq_pid = cur.lastrowid

    cur.execute(
        """
        INSERT INTO knowledge_refresh_proposals
        (target_type, target_key, clinic_id, title, source_url, source_domain,
         evidence_summary, diff_summary, current_snapshot, proposed_json, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            "tree",
            doc_id,
            tree_cid,
            tree_title,
            "https://www.mohw.gov.tw/cp-16-99999-1.html",
            "www.mohw.gov.tw",
            "衛福部衛教更新",
            "更新術後短期照護說明",
            json.dumps({"title": tree_title, "pre_op": pre_op, "procedure": proc, "post_op_short": post_op, "maintenance": maint}, ensure_ascii=False),
            json.dumps(
                {
                    "title": tree_title,
                    "pre_op": pre_op,
                    "procedure": proc,
                    "post_op_short": f"{post_op}；並留意紅腫熱痛警訊。",
                    "maintenance": maint,
                    "pre_op_physician_notes": "惡意竄改筆記",
                },
                ensure_ascii=False,
            ),
        ),
    )
    tree_pid = cur.lastrowid

    mutated_edu = dict(vis_edu)
    mutated_edu["organ_system"] = "wrong_system"
    mutated_edu["anatomy_target"] = "wrong_target"
    mutated_edu["definition"] = dict(vis_edu["definition"])
    mutated_edu["definition"]["summary"] = "依據最新實證醫學指引更新之衛教定義與臨床照護重點說明。"
    cur.execute(
        """
        INSERT INTO knowledge_refresh_proposals
        (target_type, target_key, clinic_id, title, source_url, source_domain,
         evidence_summary, diff_summary, current_snapshot, proposed_json, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            "visual_edu",
            vis_tk,
            vis_cid,
            vis_title,
            "https://pubmed.ncbi.nlm.nih.gov/39999992/",
            "pubmed.ncbi.nlm.nih.gov",
            "動畫衛教實證更新",
            "更新一句話摘要",
            json.dumps(vis_edu, ensure_ascii=False),
            json.dumps(mutated_edu, ensure_ascii=False),
        ),
    )
    vis_pid = cur.lastrowid

    # 另一筆待退回提案（用假的 target_key 即可，退回不碰知識庫）
    cur.execute(
        """
        INSERT INTO knowledge_refresh_proposals
        (target_type, target_key, clinic_id, title, source_url, source_domain,
         evidence_summary, diff_summary, current_snapshot, proposed_json, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            "faq",
            "999999",
            None,
            "測試退回提案",
            "https://www.fda.gov.tw/TC/news.aspx",
            "www.fda.gov.tw",
            "測試實證",
            "測試差異",
            "{}",
            "{}",
        ),
    )
    rej_pid = cur.lastrowid
    conn.commit()
    conn.close()

    client = TestClient(app)

    # 3. 查詢待審列表
    r = client.get("/api/v1/admin/refresh/proposals?status=pending")
    assert r.status_code == 200
    data = r.json()
    assert data["counts"]["pending"] >= 4

    # 4. 核准 FAQ 提案
    r = client.post(f"/api/v1/admin/refresh/proposals/{faq_pid}/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    # 重複核准必須回 409
    r_dup = client.post(f"/api/v1/admin/refresh/proposals/{faq_pid}/approve")
    assert r_dup.status_code == 409

    # 5. 核准 Tree 提案
    r = client.post(f"/api/v1/admin/refresh/proposals/{tree_pid}/approve")
    assert r.status_code == 200

    # 6. 核准 Visual Edu 提案
    r = client.post(f"/api/v1/admin/refresh/proposals/{vis_pid}/approve")
    assert r.status_code == 200

    # 7. 退回提案
    r = client.post(f"/api/v1/admin/refresh/proposals/{rej_pid}/reject")
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"

    # 8. 不存在的提案 -> 404
    r_404 = client.post("/api/v1/admin/refresh/proposals/8888888/approve")
    assert r_404.status_code == 404

    # 9. 驗證資料庫寫回結果
    verify = sqlite3.connect(isolated_api_db)
    new_faq = verify.execute(
        "SELECT answer, content_version, review_status FROM faq_cache WHERE id = ?", (fid,)
    ).fetchone()
    assert "建議一週後回診追蹤" in new_faq[0]
    assert new_faq[1] == (faq_ver or 1) + 1
    assert new_faq[2] == "approved"

    new_tree = verify.execute(
        "SELECT post_op_short, pre_op_physician_notes, content_version, review_status "
        "FROM page_index_trees WHERE doc_id = ?",
        (doc_id,),
    ).fetchone()
    assert "紅腫熱痛警訊" in new_tree[0]
    assert new_tree[1] == "醫師專屬警語不可覆寫"
    assert new_tree[2] == (tree_ver or 1) + 1
    assert new_tree[3] == "approved"

    new_vis = verify.execute(
        "SELECT edu_json, ir_json, content_version FROM visual_assets WHERE topic_key = ? AND clinic_id IS ?",
        (vis_tk, vis_cid),
    ).fetchone()
    new_edu = json.loads(new_vis[0])
    new_ir = json.loads(new_vis[1])
    assert new_edu["definition"]["summary"] == "依據最新實證醫學指引更新之衛教定義與臨床照護重點說明。"
    assert new_ir.get("organ_system") == orig_organ
    assert new_ir.get("anatomy_target") == orig_target
    assert new_vis[2] == (vis_ver or 1) + 1
    verify.close()


def test_admin_ui_contains_refresh_tab():
    root = Path(__file__).resolve().parents[1]
    html = (root / "src/web/static/index.html").read_text(encoding="utf-8")
    js = (root / "src/web/static/app.js").read_text(encoding="utf-8")
    assert 'data-tab="tab-refresh"' in html
    assert 'id="tab-refresh"' in html
    assert "loadRefreshProposals" in js


def test_refresh_run_endpoint_with_mocked_sources(isolated_api_db: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.refresh.sources.fetch_official_feeds", lambda *a, **kw: [])
    monkeypatch.setattr("src.refresh.sources.fetch_pubmed_evidence", lambda *a, **kw: [])
    client = TestClient(app)
    r = client.post("/api/v1/admin/refresh/run", json={"daily_quota": 2, "target_type": "all", "dry_run": True})
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"] == 2
    assert body["no_evidence"] == 2
    assert body["error"] == 0
