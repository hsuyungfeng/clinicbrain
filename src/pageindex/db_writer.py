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


def upsert_trees(conn, trees, source_type: str):
    """增量寫入 PageIndex 樹。

    trees: list of dict，每個 dict 必須含 'doc_id' 與 CONTENT_FIELDS 全部欄位。
    source_type: 'manual' | 'llm_generated' | 'clinic_upload' —— 寫入
        source_type 欄位，供夜間批次/稽核分辨資料來源。

    邏輯：新資料 INSERT（content_version=1）；既有資料只有在內容真的
    變更時才 UPDATE 並遞增 content_version、更新 updated_at、清除
    needs_regeneration 標記；內容相同則跳過，避免無意義寫入與 FTS 重建。
    """
    cursor = conn.cursor()
    inserted, updated, unchanged = 0, 0, 0

    for tree in trees:
        cursor.execute(
            f"SELECT id, {', '.join(CONTENT_FIELDS)}, content_version "
            "FROM page_index_trees WHERE doc_id = ?",
            (tree["doc_id"],),
        )
        existing = cursor.fetchone()

        if existing is None:
            cursor.execute(
                f"""
                INSERT INTO page_index_trees (
                    doc_id, {', '.join(CONTENT_FIELDS)},
                    version, source_type, content_version,
                    needs_regeneration, indexed_at
                ) VALUES (?, {', '.join('?' for _ in CONTENT_FIELDS)}, ?, ?, ?, ?, ?)
                """,
                (
                    tree["doc_id"],
                    *(tree[field] for field in CONTENT_FIELDS),
                    "2.0",
                    source_type,
                    1,
                    0,
                    datetime.now().isoformat(),
                ),
            )
            inserted += 1
            continue

        existing_id = existing[0]
        existing_values = existing[1:-1]
        existing_content_version = existing[-1]
        new_values = tuple(tree[field] for field in CONTENT_FIELDS)

        if existing_values == new_values:
            unchanged += 1
            continue

        cursor.execute(
            f"""
            UPDATE page_index_trees
            SET {', '.join(f'{field} = ?' for field in CONTENT_FIELDS)},
                source_type = ?,
                content_version = ?,
                needs_regeneration = 0,
                indexed_at = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                *new_values,
                source_type,
                existing_content_version + 1,
                datetime.now().isoformat(),
                existing_id,
            ),
        )
        updated += 1

    conn.commit()
    print(f"新增 {inserted} 筆、更新 {updated} 筆、內容未變跳過 {unchanged} 筆（source_type={source_type}）")
    return inserted, updated, unchanged
