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


TREE_PROMOTION_MARKER = "auto-promotion"
_PROMOTED_CONTENT_FIELDS = (
    "title", "category",
    "pre_op", "pre_op_physician_notes",
    "procedure", "procedure_physician_notes",
    "post_op_short", "post_op_short_physician_notes",
    "maintenance", "maintenance_physician_notes",
    "summary_text",
)


def tree_general_doc_id(clinic_id: str, doc_id: str) -> str:
    """計算診所推理樹昇華為一般醫學樹時的 doc_id。

    doc_id 在 page_index_trees 為全域 UNIQUE，且緻妍的 doc_id 原本就沒有診所前綴，
    單純去前綴會與來源列自身衝突，因此一律加上 'general-' 前綴：
    '3503264627-mid-lower-smas-facelift' -> 'general-mid-lower-smas-facelift'；
    'laser-skin-resurfacing'（無前綴）     -> 'general-laser-skin-resurfacing'。
    """
    prefix = f"{clinic_id}-"
    slug = doc_id[len(prefix):] if doc_id.startswith(prefix) and len(doc_id) > len(prefix) else doc_id
    return f"general-{slug}"


def promote_tree(conn: sqlite3.Connection, tree_id: int) -> dict[str, Any]:
    """將已核准之診所推理樹昇華為一般醫學共用樹（clinic_id IS NULL，approved）。

    占位規則（只新增或更新同一診所先前昇華的列，絕不覆寫他人內容）：
    - 一般醫學列不存在：新增。
    - 一般醫學列存在，且其 reviewed_by 為本診所的昇華標記：增量更新。
    - 其餘（一般醫學原生內容，或他診所已佔用）：略過並回報 general_slot_occupied。

    此函式不 commit，由呼叫端決定交易邊界（approve_tree 與 CLI 皆為單一交易）。
    """
    tree = get_tree(conn, tree_id)
    if tree is None:
        return {"status": "skipped", "reason": "not_found"}
    clinic_id = tree.get("clinic_id")
    if not clinic_id:
        return {"status": "skipped", "reason": "already_general"}

    cur = conn.cursor()
    cur.execute("PRAGMA table_info(page_index_trees)")
    if "reviewed_by" not in {row[1] for row in cur.fetchall()}:
        return {"status": "skipped", "reason": "schema_missing"}

    general_doc = tree_general_doc_id(clinic_id, tree["doc_id"])
    marker = f"{TREE_PROMOTION_MARKER}:{clinic_id}"

    cur.execute(
        "SELECT id, clinic_id, reviewed_by FROM page_index_trees WHERE doc_id = ?",
        (general_doc,),
    )
    existing = cur.fetchone()
    if existing is not None and (existing[1] is not None or existing[2] != marker):
        return {"status": "skipped", "reason": "general_slot_occupied", "doc_id": general_doc}

    values = {f: tree.get(f) for f in _PROMOTED_CONTENT_FIELDS}

    if existing is None:
        cols = ["doc_id", "clinic_id", *_PROMOTED_CONTENT_FIELDS, "source_type", "content_version",
                "needs_regeneration", "review_status", "reviewed_at", "reviewed_by"]
        # reviewed_at 使用 SQL 運算式 CURRENT_TIMESTAMP，不可當作綁定參數
        placeholders = ", ".join("?" for _ in cols[:-3]) + ", 'approved', CURRENT_TIMESTAMP, ?"
        cur.execute(
            f"""
            INSERT INTO page_index_trees ({', '.join(cols)})
            VALUES ({placeholders})
            """,
            (general_doc, None, *(values[f] for f in _PROMOTED_CONTENT_FIELDS),
             "clinic_upload", 1, 0, marker),
        )
        return {"status": "inserted", "doc_id": general_doc}

    cur.execute(
        f"SELECT {', '.join(_PROMOTED_CONTENT_FIELDS)} FROM page_index_trees WHERE id = ?",
        (existing[0],),
    )
    old = dict(zip(_PROMOTED_CONTENT_FIELDS, cur.fetchone()))
    changed = any(old[f] != values[f] for f in _PROMOTED_CONTENT_FIELDS)
    set_sql = ", ".join(f"{f} = ?" for f in _PROMOTED_CONTENT_FIELDS)
    cur.execute(
        f"""
        UPDATE page_index_trees
        SET {set_sql},
            source_type = 'clinic_upload',
            review_status = 'approved',
            reviewed_at = CURRENT_TIMESTAMP,
            reviewed_by = ?,
            content_version = content_version + ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (*(values[f] for f in _PROMOTED_CONTENT_FIELDS), marker, 1 if changed else 0, existing[0]),
    )
    return {"status": "updated" if changed else "unchanged", "doc_id": general_doc}


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
    ok = cur.rowcount > 0
    # 診所專屬推理樹核准時自動昇華為一般醫學共用樹（同一交易，失敗則整體回滾）
    if ok:
        promote_tree(conn, tree_id)
    conn.commit()
    return ok


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
