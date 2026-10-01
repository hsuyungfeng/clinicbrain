"""
Taiwan Clinic Medical PageIndex RAG System - FAQ 審核管理模組 (faq_review)
Phase 09 Nightly Batch & Physician Review Gate: Task 2

功能：
- 唯一權威的審核狀態寫入介面 (set_review_status)
- 審核前執行四層醫療合規驗證（價格、簡體字、政治立場、保證療效）
- 可見性改變時自動遞增 content_version 並刷新 updated_at，確保同步契約正確匯出
- 提供檢索端共用的可見性查詢片段 visible_faq_sql
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
) -> list[dict[str, Any]]:
    """列出指定審核狀態的 LLM 生成 FAQ 列表（依 id 升冪排列）。"""
    if not has_review_status(conn):
        return []
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, clinic_id, topic_key, question, answer, category,
               source_type, content_version, needs_regeneration,
               review_status, reviewed_at, created_at, updated_at
        FROM faq_cache
        WHERE source_type = 'llm_generated' AND review_status = ?
        ORDER BY id ASC
        LIMIT ? OFFSET ?
        """,
        (status, limit, offset),
    )
    columns = [
        "id", "clinic_id", "topic_key", "question", "answer", "category",
        "source_type", "content_version", "needs_regeneration",
        "review_status", "reviewed_at", "created_at", "updated_at",
    ]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


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


def set_review_status(
    conn: sqlite3.Connection,
    faq_ids: list[int],
    new_status: str,
) -> ReviewResult:
    """
    修改指定 FAQ 之審核狀態。
    本函式為 faq_cache.review_status 之唯一寫入途徑。

    規則：
    - new_status 必須屬於 REVIEW_STATUSES
    - 僅允許審核 source_type='llm_generated' 的記錄（手寫與診所上傳恆為可見）
    - 核准前重跑四層醫療合規驗證，違規者拒絕核准
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
            SELECT id, source_type, review_status, question, answer, content_version
            FROM faq_cache
            WHERE id = ?
            """,
            (faq_id,),
        )
        row = cur.fetchone()
        if row is None:
            skipped.append((faq_id, "not_found"))
            continue

        _, src_type, old_status, question, answer, _ = row
        if src_type != "llm_generated":
            skipped.append((faq_id, "not_llm_generated"))
            continue

        if old_status == new_status:
            skipped.append((faq_id, "no_change"))
            continue

        # 核准前重跑四層醫療合規驗證
        if new_status == REVIEW_APPROVED:
            from src.ingestion.generate_faq import validate_single_faq
            is_valid, reason = validate_single_faq({"question": question, "answer": answer})
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
