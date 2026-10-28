#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - page_index_trees 共用寫入邏輯
Phase 01 Task 3/4: 增量 UPSERT，供手寫種子（seed_trees.py）與 LLM 生成
（prompt_template.py + generate_trees.py）共用同一套寫入路徑。

單一負責來源原則：任何要寫入 page_index_trees 的程式碼都應該呼叫這裡的
upsert_trees()，不要各自重新實作 INSERT/UPDATE 邏輯——TASK-003 時
scripts/seed_database.py 曾與 seed_trees.py 各自維護一份重複範本，
造成資料不一致，此後禁止重蹈覆轍。
"""

from datetime import datetime

CONTENT_FIELDS = (
    "category",
    "pre_op",
    "pre_op_physician_notes",
    "procedure",
    "procedure_physician_notes",
    "post_op_short",
    "post_op_short_physician_notes",
    "maintenance",
    "maintenance_physician_notes",
    "summary_text",
)


# 受審核閘門控管之來源：內容實質變更時，若未明確指定 review_status，一律回到 pending。
# 防止「已核准的手寫樹被夜間重建（LLM 內容）」後仍 approved 而直接對外可見（Fail-Open）。
GATED_TREE_SOURCES = ("llm_generated", "web_upload")


def _has_column(cursor, table: str, col: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table});")
    return col in {row[1] for row in cursor.fetchall()}


def upsert_trees(conn, trees, source_type: str, review_status: str | None = None, commit: bool = True):
    """增量寫入 PageIndex 樹。

    trees: list of dict，每個 dict 必須含 'doc_id' 與 CONTENT_FIELDS 全部欄位（可選含 'title'）。
    source_type: 'manual' | 'llm_generated' | 'clinic_upload' | 'web_upload' —— 寫入
        source_type 欄位，供夜間批次/稽核分辨資料來源。
    review_status: 可選指定審核狀態 ('pending' | 'approved' | 'rejected')。
        若未指定：source_type 為 'manual' 或 'clinic_upload' 預設 'approved'，其餘預設 'pending'。

    邏輯：新資料 INSERT（content_version=1）；既有資料只有在內容真的
    變更時才 UPDATE 並遞增 content_version、更新 updated_at、清除
    needs_regeneration 標記；內容相同則跳過，避免無意義寫入與 FTS 重建。

    category == 'general'（一般醫學共用樹）允許 clinic_id 為 None；其餘類別仍須提供 clinic_id，
    缺漏即拋出 ValueError（防止特定診所資料變成無歸屬之共用資料）。
    commit: 預設 True 於寫入後提交；呼叫端需要單一交易原子性時傳入 False，由外層統一提交。
    """
    cursor = conn.cursor()
    inserted, updated, unchanged = 0, 0, 0
    has_title = _has_column(cursor, "page_index_trees", "title")
    has_status = _has_column(cursor, "page_index_trees", "review_status")

    default_status = review_status
    if default_status is None:
        default_status = "approved" if source_type in ("manual", "clinic_upload") else "pending"

    for tree in trees:
        is_general = tree.get("category") == "general"
        if not is_general and (not tree.get("clinic_id")):
            raise ValueError(f"tree dict (doc_id='{tree.get('doc_id')}') 缺少必要之 'clinic_id' 鍵")

        tree_title = tree.get("title")
        fields_to_check = list(CONTENT_FIELDS)
        if has_title:
            fields_to_check.append("title")

        cursor.execute(
            f"SELECT id, {', '.join(fields_to_check)}, content_version "
            "FROM page_index_trees WHERE doc_id = ?",
            (tree["doc_id"],),
        )
        existing = cursor.fetchone()

        if existing is None:
            insert_cols = ["doc_id", "clinic_id", *CONTENT_FIELDS, "version", "source_type", "content_version", "needs_regeneration", "indexed_at"]
            insert_vals = [tree["doc_id"], tree.get("clinic_id"), *(tree[field] for field in CONTENT_FIELDS), "2.0", source_type, 1, 0, datetime.now().isoformat()]

            if has_title:
                insert_cols.append("title")
                insert_vals.append(tree_title)
            if has_status:
                insert_cols.append("review_status")
                insert_vals.append(tree.get("review_status") or default_status)

            cursor.execute(
                f"""
                INSERT INTO page_index_trees ({', '.join(insert_cols)})
                VALUES ({', '.join('?' for _ in insert_cols)})
                """,
                tuple(insert_vals),
            )
            inserted += 1
            continue

        existing_id = existing[0]
        existing_values = existing[1:-1]
        existing_content_version = existing[-1]

        new_vals_list = [tree[field] for field in CONTENT_FIELDS]
        if has_title:
            new_vals_list.append(tree_title)
        new_values = tuple(new_vals_list)

        if existing_values == new_values:
            unchanged += 1
            continue

        update_set = [f"{field} = ?" for field in CONTENT_FIELDS]
        update_params = [tree[field] for field in CONTENT_FIELDS]

        if has_title:
            update_set.append("title = ?")
            update_params.append(tree_title)

        if has_status and "review_status" in tree:
            update_set.append("review_status = ?")
            update_params.append(tree["review_status"])
        elif has_status and source_type in GATED_TREE_SOURCES:
            update_set.append("review_status = 'pending'")
            update_set.append("reviewed_at = NULL")

        update_set.extend([
            "source_type = ?",
            "content_version = ?",
            "needs_regeneration = 0",
            "indexed_at = ?",
            "updated_at = CURRENT_TIMESTAMP",
        ])
        update_params.extend([
            source_type,
            existing_content_version + 1,
            datetime.now().isoformat(),
            existing_id,
        ])

        cursor.execute(
            f"""
            UPDATE page_index_trees
            SET {', '.join(update_set)}
            WHERE id = ?
            """,
            tuple(update_params),
        )
        updated += 1

    if commit:
        conn.commit()
    print(f"新增 {inserted} 筆、更新 {updated} 筆、內容未變跳過 {unchanged} 筆（source_type={source_type}）")
    return inserted, updated, unchanged


def set_needs_regeneration(
    conn,
    doc_ids: list[str],
    flag: bool,
) -> tuple[int, list[str]]:
    """手動標記或清除 PageIndex 樹之 needs_regeneration 旗標（BATCH-02 入口）。

    doc_ids: list of str，欲標記/清除的 doc_id 清單。
    flag: True 為標記待重建 (1)，False 為清除標記 (0)。

    規則：
    - 若傳入的 doc_ids 中有任何項目不存在於資料庫，不進行任何寫入，直接回傳 (0, missing)。
    - 僅更新 needs_regeneration 欄位，不修改 content_version、updated_at、source_type 與任何內容欄位。
    - 這是全專案把 needs_regeneration 設為 1 的唯一入口。

    回傳: (changed_count, missing_doc_ids)
    """
    if not doc_ids:
        return 0, []

    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in doc_ids)
    cursor.execute(
        f"SELECT doc_id FROM page_index_trees WHERE doc_id IN ({placeholders})",
        doc_ids,
    )
    found_doc_ids = {row[0] for row in cursor.fetchall()}
    missing = [d for d in doc_ids if d not in found_doc_ids]

    if missing:
        return 0, missing

    target_val = 1 if flag else 0
    changed = 0

    for doc_id in doc_ids:
        cursor.execute(
            """
            UPDATE page_index_trees
            SET needs_regeneration = ?
            WHERE doc_id = ? AND needs_regeneration != ?
            """,
            (target_val, doc_id, target_val),
        )
        changed += cursor.rowcount

    conn.commit()
    return changed, []

