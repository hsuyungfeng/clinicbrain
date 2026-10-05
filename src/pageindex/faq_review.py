"""
Taiwan Clinic Medical PageIndex RAG System - FAQ 審核管理模組 (faq_review)
Phase 09 Nightly Batch & Physician Review Gate: Task 2
Phase 12 General Content Generation: DEBT-03 (人工標記重生成與審核增強)

功能：
- 唯一權威的審核狀態寫入介面 (set_review_status)
- 審核前執行多層醫療合規驗證（價格、簡體字、政治立場、保證療效、用藥劑量與就醫警訊）
- 可見性改變時自動遞增 content_version 並刷新 updated_at，確保同步契約正確匯出
- 提供檢索端共用的可見性查詢片段 visible_faq_sql
- 人工重生成標記入口 (mark_for_regeneration)，旗標清除由 faq_writer（內容變更）與 clear_regeneration_flag
"""

from dataclasses import dataclass, field
import sqlite3
from typing import Any, Optional

REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"
REVIEW_STATUSES = frozenset([REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED])


@dataclass
class ReviewResult:
    """審核操作回傳結果。"""
    changed: list[int] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)


def has_review_status(conn: sqlite3.Connection) -> bool:
    """檢查 faq_cache 資料表是否已具備 review_status 與 reviewed_at 兩欄。"""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(faq_cache)")
    cols = {row[1] for row in cur.fetchall()}
    return ("review_status" in cols) and ("reviewed_at" in cols)


def visible_faq_sql(conn: sqlite3.Connection) -> str:
    """產生供 faq_cache 查詢 WHERE 子句共用的可見性 SQL 片段。"""
    if has_review_status(conn):
        return "(source_type IS NOT 'llm_generated' OR review_status = 'approved')"
    return "(source_type IS NOT 'llm_generated')"


def count_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    """統計各 review_status 的資料筆數。若未遷移則回傳空字典。"""
    if not has_review_status(conn):
        return {}
    cur = conn.cursor()
    cur.execute("SELECT review_status, COUNT(*) FROM faq_cache GROUP BY review_status")
    return dict(cur.fetchall())


def list_faqs(
    conn: sqlite3.Connection,
    status: str = REVIEW_PENDING,
    limit: int = 50,
    offset: int = 0,
    *,
    topic_key: Optional[str] = None,
) -> list[dict[str, Any]]:
    """列出指定審核狀態的 LLM 生成 FAQ 列表（依 id 升冪排列）。可選 topic_key 篩選。"""
    if not has_review_status(conn):
        return []
    cur = conn.cursor()
    where_clauses = ["source_type = 'llm_generated'", "review_status = ?"]
    params: list[Any] = [status]
    if topic_key is not None:
        where_clauses.append("topic_key = ?")
        params.append(topic_key)
    where_sql = " AND ".join(where_clauses)
    params.extend([limit, offset])
    cur.execute(
        f"""
        SELECT id, clinic_id, topic_key, question, answer, category,
               source_type, content_version, needs_regeneration,
               review_status, reviewed_at, created_at, updated_at
        FROM faq_cache
        WHERE {where_sql}
        ORDER BY id ASC
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    )
    columns = [
        "id", "clinic_id", "topic_key", "question", "answer", "category",
        "source_type", "content_version", "needs_regeneration",
        "review_status", "reviewed_at", "created_at", "updated_at",
    ]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def validation_report(faq: dict[str, Any]) -> dict[str, Any]:
    """
    對指定 FAQ 執行多層醫療合規驗證並回傳報告字典。
    回傳格式: {"ok": bool, "reason": Optional[str]}
    旗標: check_dosage=True, require_doctor_warning=(category == 'general')
    """
    from src.ingestion.generate_faq import validate_single_faq

    category = faq.get("category")
    is_valid, reason = validate_single_faq(
        {"question": faq.get("question", ""), "answer": faq.get("answer", "")},
        check_dosage=True,
        require_doctor_warning=(category == "general"),
    )
    return {"ok": is_valid, "reason": reason if not is_valid else None}


def get_faq(conn: sqlite3.Connection, faq_id: int) -> Optional[dict[str, Any]]:
    """取得指定 ID 之 FAQ 詳細資訊。"""
    has_review = has_review_status(conn)
    cur = conn.cursor()
    if has_review:
        cur.execute(
            """
            SELECT id, clinic_id, topic_key, question, answer, category,
                   source_type, content_version, needs_regeneration,
                   review_status, reviewed_at, created_at, updated_at
            FROM faq_cache
            WHERE id = ?
            """,
            (faq_id,),
        )
        columns = [
            "id", "clinic_id", "topic_key", "question", "answer", "category",
            "source_type", "content_version", "needs_regeneration",
            "review_status", "reviewed_at", "created_at", "updated_at",
        ]
    else:
        cur.execute(
            """
            SELECT id, clinic_id, topic_key, question, answer, category,
                   source_type, content_version, needs_regeneration,
                   created_at, updated_at
            FROM faq_cache
            WHERE id = ?
            """,
            (faq_id,),
        )
        columns = [
            "id", "clinic_id", "topic_key", "question", "answer", "category",
            "source_type", "content_version", "needs_regeneration",
            "created_at", "updated_at",
        ]
    row = cur.fetchone()
    return dict(zip(columns, row)) if row else None


def mark_for_regeneration(
    conn: sqlite3.Connection,
    faq_ids: list[int],
) -> ReviewResult:
    """
    手動標記指定被駁回之 LLM 生成 FAQ 為待重新生成 (needs_regeneration = 1)。

    規則：
    - 未遷移審核欄位時拋出 RuntimeError
    - 僅允許標記 source_type='llm_generated' 且 review_status='rejected' 的列
    - 若已經被標記 (needs_regeneration == 1)，回報 skipped ('already_marked')
    - 標記操作不變更 content_version，亦不變更 review_status
    """
    if not has_review_status(conn):
        raise RuntimeError(
            "資料庫尚未建立審核欄位，請先執行 scripts/migrate_faq_review_status.py 遷移腳本！"
        )

    changed: list[int] = []
    skipped: list[tuple[int, str]] = []

    cur = conn.cursor()
    for faq_id in faq_ids:
        cur.execute(
            """
            SELECT id, source_type, review_status, needs_regeneration
            FROM faq_cache
            WHERE id = ?
            """,
            (faq_id,),
        )
        row = cur.fetchone()
        if row is None:
            skipped.append((faq_id, "not_found"))
            continue

        _, src_type, status, needs_reg = row
        if src_type != "llm_generated":
            skipped.append((faq_id, "not_llm_generated"))
            continue

        if status != REVIEW_REJECTED:
            skipped.append((faq_id, "not_rejected"))
            continue

        if needs_reg == 1:
            skipped.append((faq_id, "already_marked"))
            continue

        cur.execute(
            "UPDATE faq_cache SET needs_regeneration = 1 WHERE id = ?",
            (faq_id,),
        )
        changed.append(faq_id)

    conn.commit()
    return ReviewResult(changed=changed, skipped=skipped)


def clear_regeneration_flag(
    conn: sqlite3.Connection,
    faq_ids: list[int],
) -> int:
    """
    清除指定 FAQ 之重新生成旗標 (needs_regeneration = 0)。
    僅對 source_type='llm_generated' AND review_status='rejected' AND needs_regeneration=1 之列生效。
    回傳實際清除旗標之筆數。
    """
    if not has_review_status(conn) or not faq_ids:
        return 0

    placeholders = ",".join("?" for _ in faq_ids)
    cur = conn.cursor()
    cur.execute(
        f"""
        UPDATE faq_cache
        SET needs_regeneration = 0
        WHERE id IN ({placeholders})
          AND source_type = 'llm_generated'
          AND review_status = 'rejected'
          AND needs_regeneration = 1
        """,
        faq_ids,
    )
    affected = cur.rowcount
    conn.commit()
    return affected


def regen_marked_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """
    查詢目前所有被標記重生成且處於 rejected 之 LLM 生成 FAQ 列表。
    若資料庫尚未建立審核欄位則回傳空列表。
    """
    if not has_review_status(conn):
        return []

    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, clinic_id, topic_key, question
        FROM faq_cache
        WHERE source_type = 'llm_generated'
          AND review_status = 'rejected'
          AND needs_regeneration = 1
        ORDER BY id ASC
        """
    )
    return [
        {"id": row[0], "clinic_id": row[1], "topic_key": row[2], "question": row[3]}
        for row in cur.fetchall()
    ]


def set_review_status(
    conn: sqlite3.Connection,
    faq_ids: list[int],
    new_status: str,
    *,
    enforce_general_warning: bool = False,
) -> ReviewResult:
    """
    修改指定 FAQ 之審核狀態。
    本函式為 faq_cache.review_status 之唯一寫入途徑。

    規則：
    - new_status 必須屬於 REVIEW_STATUSES
    - 僅允許審核 source_type='llm_generated' 的記錄（手寫與診所上傳恆為可見）
    - 核准前重跑醫療合規驗證（含價格、簡體字、政治立場、保證療效、用藥劑量與可選的 general 就醫警訊檢查），違規者拒絕核准
    - 當可見性改變時（approved 與非 approved 之間轉換），遞增 content_version 並更新 updated_at
    """
    if new_status not in REVIEW_STATUSES:
        raise ValueError(
            f"無效的審核狀態: '{new_status}'，合法值為 {sorted(REVIEW_STATUSES)}"
        )

    if not has_review_status(conn):
        raise RuntimeError(
            "資料庫尚未建立審核欄位，請先執行 scripts/migrate_faq_review_status.py 遷移腳本！"
        )

    changed: list[int] = []
    skipped: list[tuple[int, str]] = []

    cur = conn.cursor()
    for faq_id in faq_ids:
        cur.execute(
            """
            SELECT id, source_type, review_status, question, answer, content_version, category
            FROM faq_cache
            WHERE id = ?
            """,
            (faq_id,),
        )
        row = cur.fetchone()
        if row is None:
            skipped.append((faq_id, "not_found"))
            continue

        _, src_type, old_status, question, answer, _, category = row
        if src_type != "llm_generated":
            skipped.append((faq_id, "not_llm_generated"))
            continue

        if old_status == new_status:
            skipped.append((faq_id, "no_change"))
            continue

        # 核准前重跑醫療合規驗證
        if new_status == REVIEW_APPROVED:
            from src.ingestion.generate_faq import validate_single_faq
            require_warning = bool(enforce_general_warning and category == "general")
            is_valid, reason = validate_single_faq(
                {"question": question, "answer": answer},
                check_dosage=True,
                require_doctor_warning=require_warning,
            )
            if not is_valid:
                skipped.append((faq_id, f"validation_failed: {reason}"))
                continue

        # 判定是否造成可見性改變
        was_visible = (old_status == REVIEW_APPROVED)
        will_be_visible = (new_status == REVIEW_APPROVED)
        visibility_changed = (was_visible != will_be_visible)

        if visibility_changed:
            if new_status == REVIEW_PENDING:
                cur.execute(
                    """
                    UPDATE faq_cache
                    SET review_status = ?,
                        reviewed_at = NULL,
                        content_version = content_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (new_status, faq_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE faq_cache
                    SET review_status = ?,
                        reviewed_at = CURRENT_TIMESTAMP,
                        content_version = content_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (new_status, faq_id),
                )
        else:
            if new_status == REVIEW_PENDING:
                cur.execute(
                    """
                    UPDATE faq_cache
                    SET review_status = ?,
                        reviewed_at = NULL
                    WHERE id = ?
                    """,
                    (new_status, faq_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE faq_cache
                    SET review_status = ?,
                        reviewed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (new_status, faq_id),
                )

        changed.append(faq_id)

    conn.commit()
    return ReviewResult(changed=changed, skipped=skipped)
