"""Phase 54-03: 新知提案核准寫回與退回模組（原子單交易橋接唯一權威寫入路徑）。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from src.api.routes.query import deep_mask_prices
from src.pageindex.db_writer import upsert_trees
from src.pageindex.faq_writer import VALID_SOURCE_TYPES as FAQ_SOURCE_TYPES, upsert_faqs
from src.refresh.schema import ensure_refresh_tables
from src.visual.edu_generator import build_upgraded_ir
from src.visual.edu_schema import EduContent

_PHYSICIAN_NOTE_KEYS = (
    "pre_op_physician_notes",
    "procedure_physician_notes",
    "post_op_short_physician_notes",
    "maintenance_physician_notes",
)


def _fetch_pending_proposal(conn: sqlite3.Connection, proposal_id: int) -> dict[str, Any]:
    ensure_refresh_tables(conn)
    row = conn.execute(
        """
        SELECT id, target_type, target_key, clinic_id, title, source_url, source_domain,
               evidence_summary, diff_summary, current_snapshot, proposed_json, status
        FROM knowledge_refresh_proposals
        WHERE id = ?
        """,
        (proposal_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"找不到新知提案 id={proposal_id}")
    status = row[11]
    if status != "pending":
        raise ValueError(f"提案 id={proposal_id} 狀態為 '{status}'，僅可操作 'pending' 提案")
    return {
        "id": row[0],
        "target_type": row[1],
        "target_key": row[2],
        "clinic_id": row[3],
        "title": row[4],
        "source_url": row[5],
        "source_domain": row[6],
        "evidence_summary": row[7],
        "diff_summary": row[8],
        "current_snapshot": json.loads(row[9]) if row[9] else {},
        "proposed_json": json.loads(row[10]) if row[10] else {},
        "status": status,
    }


def _apply_faq(conn: sqlite3.Connection, proposal: dict[str, Any], proposed: dict[str, Any]) -> None:
    fid = int(proposal["target_key"])
    row = conn.execute(
        "SELECT id, clinic_id, topic_key, question, answer, category, source_type FROM faq_cache WHERE id = ?",
        (fid,),
    ).fetchone()
    if row is None:
        raise LookupError(f"找不到目標 FAQ id={fid}")
    _, orig_clinic_id, orig_topic_key, orig_question, orig_answer, orig_category, orig_source = row
    source_type = orig_source if orig_source in FAQ_SOURCE_TYPES else "clinic_upload"

    new_question = (proposed.get("question") or orig_question or "").strip()
    new_answer = (proposed.get("answer") or orig_answer or "").strip()
    category = (proposed.get("category") or orig_category or "general").strip()
    topic_key = proposed.get("topic_key") if "topic_key" in proposed else orig_topic_key
    clinic_id = orig_clinic_id

    upsert_faqs(
        conn,
        [
            {
                "clinic_id": clinic_id,
                "topic_key": topic_key,
                "category": category,
                "question": new_question,
                "answer": new_answer,
            }
        ],
        source_type=source_type,
        commit=False,
    )
    if new_question != orig_question:
        conn.execute("DELETE FROM faq_cache WHERE id = ?", (fid,))
    conn.execute(
        """
        UPDATE faq_cache
        SET review_status = 'approved', reviewed_at = CURRENT_TIMESTAMP
        WHERE clinic_id IS ? AND topic_key IS ? AND question = ?
        """,
        (clinic_id, topic_key, new_question),
    )


def _apply_tree(conn: sqlite3.Connection, proposal: dict[str, Any], proposed: dict[str, Any]) -> None:
    doc_id = str(proposal["target_key"])
    row = conn.execute(
        """
        SELECT clinic_id, source_type, title, category, summary_text,
               pre_op_physician_notes, procedure_physician_notes,
               post_op_short_physician_notes, maintenance_physician_notes
        FROM page_index_trees
        WHERE doc_id = ?
        """,
        (doc_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"找不到目標推理樹 doc_id={doc_id}")

    clinic_id, orig_source, orig_title, orig_category, orig_summary = (
        row[0],
        row[1] or "manual",
        row[2],
        row[3] or "special",
        row[4] or "",
    )
    tree_payload = {
        "doc_id": doc_id,
        "clinic_id": clinic_id,
        "category": orig_category,
        "summary_text": (proposed.get("summary_text") if "summary_text" in proposed else orig_summary) or "",
        "title": (proposed.get("title") or orig_title or doc_id).strip(),
        "pre_op": (proposed.get("pre_op") or "").strip(),
        "procedure": (proposed.get("procedure") or "").strip(),
        "post_op_short": (proposed.get("post_op_short") or "").strip(),
        "maintenance": (proposed.get("maintenance") or "").strip(),
        # 嚴格保留既有醫師權威指令，絕不由提案覆寫
        _PHYSICIAN_NOTE_KEYS[0]: row[5] or "",
        _PHYSICIAN_NOTE_KEYS[1]: row[6] or "",
        _PHYSICIAN_NOTE_KEYS[2]: row[7] or "",
        _PHYSICIAN_NOTE_KEYS[3]: row[8] or "",
    }
    upsert_trees(
        conn,
        [tree_payload],
        source_type=orig_source,
        review_status="approved",
        commit=False,
    )


def _apply_visual_edu(conn: sqlite3.Connection, proposal: dict[str, Any], proposed: dict[str, Any]) -> None:
    topic_key = str(proposal["target_key"])
    clinic_id = proposal["clinic_id"]
    row = conn.execute(
        """
        SELECT id, edu_json, ir_json
        FROM visual_assets
        WHERE topic_key = ? AND clinic_id IS ?
        """,
        (topic_key, clinic_id),
    ).fetchone()
    if row is None:
        raise LookupError(f"找不到目標動畫資產 topic_key={topic_key}")

    asset_id, edu_json_str, ir_json_str = row
    existing_edu = json.loads(edu_json_str) if edu_json_str else {}
    existing_ir = json.loads(ir_json_str) if ir_json_str else {}

    merged_edu = dict(proposed)
    # 鎖定既有解剖目標與器官系統，避免臨床分類漂移
    if existing_edu.get("organ_system"):
        merged_edu["organ_system"] = existing_edu["organ_system"]
    if existing_edu.get("anatomy_target"):
        merged_edu["anatomy_target"] = existing_edu["anatomy_target"]

    edu_model = EduContent.model_validate(merged_edu)
    new_ir = build_upgraded_ir(existing_ir, edu_model)

    conn.execute(
        """
        UPDATE visual_assets
        SET edu_json = ?,
            edu_updated_at = CURRENT_TIMESTAMP,
            ir_json = ?,
            content_version = COALESCE(content_version, 1) + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            edu_model.model_dump_json(),
            json.dumps(new_ir, ensure_ascii=False),
            asset_id,
        ),
    )


def approve_proposal(conn: sqlite3.Connection, proposal_id: int) -> dict[str, Any]:
    """核准新知提案並於單一交易內寫回目標知識庫。"""
    proposal = _fetch_pending_proposal(conn, proposal_id)
    proposed = deep_mask_prices(proposal["proposed_json"])
    target_type = proposal["target_type"]

    try:
        if target_type == "faq":
            _apply_faq(conn, proposal, proposed)
        elif target_type == "tree":
            _apply_tree(conn, proposal, proposed)
        elif target_type == "visual_edu":
            _apply_visual_edu(conn, proposal, proposed)
        else:
            raise ValueError(f"不支援的 target_type: {target_type}")

        conn.execute(
            """
            UPDATE knowledge_refresh_proposals
            SET status = 'approved', reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (proposal_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "id": proposal_id,
        "status": "approved",
        "target_type": target_type,
        "target_key": proposal["target_key"],
    }


def reject_proposal(conn: sqlite3.Connection, proposal_id: int) -> dict[str, Any]:
    """退回新知提案（不更動知識庫內容）。"""
    proposal = _fetch_pending_proposal(conn, proposal_id)
    conn.execute(
        """
        UPDATE knowledge_refresh_proposals
        SET status = 'rejected', reviewed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (proposal_id,),
    )
    conn.commit()
    return {
        "id": proposal_id,
        "status": "rejected",
        "target_type": proposal["target_type"],
        "target_key": proposal["target_key"],
    }
