"""
Taiwan Clinic Medical PageIndex RAG System - 臨床決策推理樹審核管理模組 (tree_review)
Phase 21 Plan 21-01: 臨床推理樹之審核狀態查詢、可見性過濾、編輯與簽核

功能：
- 審核狀態檢查 (has_tree_review_status)
- 檢索隔離可見性 SQL 片段 (visible_tree_sql)
- 決策樹 CRUD (list_trees, get_tree, update_tree, approve_tree, reject_tree, delete_tree)
- 統計指標 (count_trees_by_status)
"""

from dataclasses import dataclass, field
from datetime import datetime
import sqlite3
from typing import Any, Optional

TREE_PENDING = "pending"
TREE_APPROVED = "approved"
TREE_REJECTED = "rejected"
TREE_STATUSES = frozenset([TREE_PENDING, TREE_APPROVED, TREE_REJECTED])

# 受審核閘門控管的來源：未經醫師核准（review_status='approved'）前對外完全隱蔽。
TREE_GATED_SOURCES = ("llm_generated", "web_upload")
_TREE_GATED_SQL_LIST = ", ".join(f"'{s}'" for s in TREE_GATED_SOURCES)


@dataclass
class TreeReviewResult:
    """審核操作回傳結果。"""
    changed: list[int] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)


def has_tree_review_status(conn: sqlite3.Connection) -> bool:
    """檢查 page_index_trees 資料表是否已具備 review_status 與 reviewed_at 兩欄。"""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(page_index_trees)")
    cols = {row[1] for row in cur.fetchall()}
    return ("review_status" in cols) and ("reviewed_at" in cols)


def visible_tree_sql(conn: sqlite3.Connection) -> str:
    """產生供 page_index_trees 查詢 WHERE 子句共用的可見性 SQL 片段。

    Fail-Closed 審核隔離：未核准之 llm_generated 或 web_upload 對外一律隔離。
    若資料表尚未完成遷移，則向後相容只允許非受控來源（如 manual/clinic_upload）。
    """
    if has_tree_review_status(conn):
        return f"(source_type IS NULL OR source_type NOT IN ({_TREE_GATED_SQL_LIST}) OR review_status = 'approved')"
    return f"(source_type IS NULL OR source_type NOT IN ({_TREE_GATED_SQL_LIST}))"


def count_trees_by_status(conn: sqlite3.Connection, clinic_id: Optional[str] = None) -> dict[str, int]:
    """統計各 review_status 的決策樹筆數。若未遷移則回傳空字典。"""
    if not has_tree_review_status(conn):
        return {}
    cur = conn.cursor()
    sql = "SELECT review_status, COUNT(*) FROM page_index_trees"
    params = []
    if clinic_id:
        sql += " WHERE clinic_id = ?"
        params.append(clinic_id)
    sql += " GROUP BY review_status"
    cur.execute(sql, tuple(params))
    return dict(cur.fetchall())


def list_trees(
    conn: sqlite3.Connection,
    status: Optional[str] = TREE_PENDING,
    limit: int = 50,
    offset: int = 0,
    *,
    clinic_id: Optional[str] = None,
    category: Optional[str] = None,
    source_type: Optional[str] = None,
) -> tuple[list[dict[str, Any]], int]:
    """查詢決策樹清單與總筆數。支援 status, clinic_id, category, source_type 篩選。"""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(page_index_trees)")
    cols = [row[1] for row in cur.fetchall()]

    where_clauses = []
    params: list[Any] = []

    if status and "review_status" in cols:
        where_clauses.append("review_status = ?")
        params.append(status)

    if clinic_id:
        where_clauses.append("clinic_id = ?")
        params.append(clinic_id)

    if category:
        where_clauses.append("category = ?")
        params.append(category)

    if source_type:
        where_clauses.append("source_type = ?")
        params.append(source_type)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # 計算總筆數
    cur.execute(f"SELECT COUNT(*) FROM page_index_trees {where_sql}", tuple(params))
    total = cur.fetchone()[0]

    select_cols = [
        "id", "doc_id", "clinic_id", "category",
        "pre_op", "pre_op_physician_notes",
        "procedure", "procedure_physician_notes",
        "post_op_short", "post_op_short_physician_notes",
        "maintenance", "maintenance_physician_notes",
        "summary_text", "source_type", "content_version",
        "created_at", "updated_at",
    ]
    for optional_col in ("title", "review_status", "reviewed_at", "reviewed_by"):
        if optional_col in cols:
            select_cols.append(optional_col)

    query_sql = f"""
        SELECT {', '.join(select_cols)}
        FROM page_index_trees
        {where_sql}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """
    cur.execute(query_sql, tuple(params + [limit, offset]))
    rows = cur.fetchall()

    results = []
    for r in rows:
        results.append(dict(zip(select_cols, r)))

    return results, total


def get_tree(conn: sqlite3.Connection, tree_id: int) -> Optional[dict[str, Any]]:
    """以 ID 取得單一推理樹詳情。"""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(page_index_trees)")
    cols = [row[1] for row in cur.fetchall()]

    select_cols = [
        "id", "doc_id", "clinic_id", "category",
        "pre_op", "pre_op_physician_notes",
        "procedure", "procedure_physician_notes",
        "post_op_short", "post_op_short_physician_notes",
        "maintenance", "maintenance_physician_notes",
        "summary_text", "source_type", "content_version",
        "created_at", "updated_at",
    ]
    for optional_col in ("title", "review_status", "reviewed_at", "reviewed_by"):
        if optional_col in cols:
            select_cols.append(optional_col)

    cur.execute(
        f"SELECT {', '.join(select_cols)} FROM page_index_trees WHERE id = ?",
        (tree_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip(select_cols, row))


def update_tree(
    conn: sqlite3.Connection,
    tree_id: int,
    data: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """更新決策樹內文或填寫醫師權威醫囑。"""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(page_index_trees)")
    cols = {row[1] for row in cur.fetchall()}

    updatable_fields = [
        "title", "pre_op", "pre_op_physician_notes",
        "procedure", "procedure_physician_notes",
        "post_op_short", "post_op_short_physician_notes",
        "maintenance", "maintenance_physician_notes",
        "summary_text", "category",
    ]
    set_clauses = []
    params = []

    current = get_tree(conn, tree_id)
    if current is None:
        return None

    changed = False
    for f in updatable_fields:
        if f in data and f in cols:
            set_clauses.append(f"{f} = ?")
            params.append(data[f])
            if data[f] != current.get(f):
                changed = True

    if not set_clauses:
        return current

    # 受控來源的內容一經修改，即失去先前的核准：回到 pending 重新簽核（Fail-Closed）
    if changed and current.get("source_type") in TREE_GATED_SOURCES and current.get("review_status") in ("approved", "rejected"):
        set_clauses.append("review_status = 'pending'")
        set_clauses.append("reviewed_at = NULL")

    set_clauses.append("content_version = content_version + 1")
    set_clauses.append("updated_at = CURRENT_TIMESTAMP")
    params.append(tree_id)

    cur.execute(
        f"UPDATE page_index_trees SET {', '.join(set_clauses)} WHERE id = ?",
        tuple(params),
    )
    conn.commit()
    return get_tree(conn, tree_id)


def approve_tree(
    conn: sqlite3.Connection,
    tree_id: int,
    reviewer: str = "physician",
) -> bool:
    """醫師核准指定推理樹草稿，狀態轉為 'approved'。"""
    if not has_tree_review_status(conn):
        return False
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE page_index_trees
        SET review_status = 'approved',
            reviewed_at = CURRENT_TIMESTAMP,
            reviewed_by = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND review_status != 'approved'
        """,
        (reviewer, tree_id),
    )
    conn.commit()
    return cur.rowcount > 0


def reject_tree(
    conn: sqlite3.Connection,
    tree_id: int,
    reviewer: str = "physician",
) -> bool:
    """醫師駁回指定推理樹草稿，狀態轉為 'rejected'。"""
    if not has_tree_review_status(conn):
        return False
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE page_index_trees
        SET review_status = 'rejected',
            reviewed_at = CURRENT_TIMESTAMP,
            reviewed_by = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND review_status != 'rejected'
        """,
        (reviewer, tree_id),
    )
    conn.commit()
    return cur.rowcount > 0


def delete_tree(conn: sqlite3.Connection, tree_id: int) -> bool:
    """刪除指定推理樹（僅限 pending 或 rejected 草稿）。"""
    cur = conn.cursor()
    if has_tree_review_status(conn):
        cur.execute(
            "DELETE FROM page_index_trees WHERE id = ? AND review_status != 'approved'",
            (tree_id,),
        )
    else:
        cur.execute("DELETE FROM page_index_trees WHERE id = ?", (tree_id,))
    conn.commit()
    return cur.rowcount > 0
