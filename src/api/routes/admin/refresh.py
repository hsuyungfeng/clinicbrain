"""Phase 54-03: 權威醫學新知提案審核與手動巡檢 Admin API。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.dependencies import get_read_db, get_write_db
from src.api.routes.query import deep_mask_prices
from src.refresh.applier import approve_proposal, reject_proposal

router = APIRouter(prefix="/refresh", tags=["新知巡檢提案審核 (Refresh)"])


class RefreshRunRequest(BaseModel):
    daily_quota: int = Field(default=5, ge=1, le=20)
    target_type: Literal["all", "faq", "tree", "visual_edu"] = "all"
    dry_run: bool = False


@router.get("/proposals")
def list_refresh_proposals(
    status: Literal["pending", "approved", "rejected", "all"] = Query(default="pending"),
    target_type: Optional[Literal["faq", "tree", "visual_edu"]] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_read_db),
) -> dict[str, Any]:
    """列出醫學新知提案與各狀態計數（唯讀連線）。"""
    counts = {"pending": 0, "approved": 0, "rejected": 0}
    try:
        for st, cnt in conn.execute(
            "SELECT status, COUNT(*) FROM knowledge_refresh_proposals GROUP BY status"
        ).fetchall():
            if st in counts:
                counts[st] = int(cnt)

        clauses: list[str] = []
        params: list[Any] = []
        if status != "all":
            clauses.append("status = ?")
            params.append(status)
        if target_type:
            clauses.append("target_type = ?")
            params.append(target_type)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        rows = conn.execute(
            f"""
            SELECT id, target_type, target_key, clinic_id, title,
                   source_url, source_domain, evidence_summary, diff_summary,
                   current_snapshot, proposed_json, status, created_at, reviewed_at
            FROM knowledge_refresh_proposals
            {where_sql}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        return {"items": [], "counts": counts}

    items: list[dict[str, Any]] = []
    for r in rows:
        items.append(
            deep_mask_prices(
                {
                    "id": r[0],
                    "target_type": r[1],
                    "target_key": r[2],
                    "clinic_id": r[3],
                    "title": r[4],
                    "source_url": r[5],
                    "source_domain": r[6],
                    "evidence_summary": r[7],
                    "diff_summary": r[8],
                    "current_snapshot": json.loads(r[9]) if r[9] else {},
                    "proposed_json": json.loads(r[10]) if r[10] else {},
                    "status": r[11],
                    "created_at": r[12],
                    "reviewed_at": r[13],
                }
            )
        )
    return {"items": items, "counts": counts}


@router.post("/proposals/{proposal_id}/approve")
def approve_refresh_proposal(
    proposal_id: int,
    conn: sqlite3.Connection = Depends(get_write_db),
) -> dict[str, Any]:
    """核准新知提案並寫回目標知識庫。"""
    try:
        result = approve_proposal(conn, proposal_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return deep_mask_prices(result)


@router.post("/proposals/{proposal_id}/reject")
def reject_refresh_proposal(
    proposal_id: int,
    conn: sqlite3.Connection = Depends(get_write_db),
) -> dict[str, Any]:
    """退回新知提案（不寫回知識庫）。"""
    try:
        result = reject_proposal(conn, proposal_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result


@router.post("/run")
def run_refresh_cycle(
    body: RefreshRunRequest = RefreshRunRequest(),
    conn: sqlite3.Connection = Depends(get_write_db),
) -> dict[str, Any]:
    """手動觸發一次權威醫學新知巡檢。"""
    from src.refresh.detector import evaluate_and_propose, select_refresh_candidates
    from src.refresh.schema import ensure_refresh_tables
    from src.refresh.sources import fetch_official_feeds, fetch_pubmed_evidence

    ensure_refresh_tables(conn)
    candidates = select_refresh_candidates(
        conn,
        daily_quota=body.daily_quota,
        target_type=body.target_type,
    )
    official_evidences = fetch_official_feeds()[:10]
    stats = {"candidates": len(candidates), "proposed": 0, "unchanged": 0, "skipped": 0, "error": 0, "no_evidence": 0}
    for cand in candidates:
        try:
            evidences = fetch_pubmed_evidence(cand.query_hint, max_results=3) + official_evidences[:2]
            if not evidences:
                stats["no_evidence"] += 1
                continue
            outcome = evaluate_and_propose(conn, cand, evidences, dry_run=body.dry_run)
            if outcome in stats:
                stats[outcome] += 1
            else:
                stats["error"] += 1
        except Exception:
            stats["error"] += 1
    return stats
