"""
視覺解說卡審核與對外可見查詢模組 (review)。
Phase 29: P29-SCHEMA, P29-REVIEW, P29-SERVE

設計原則：
- 醫師審核閘門：資產對外可見性受 review_status 嚴格管制，僅 approved 狀態且再次通過 validate_ir 者對外可見。
- 雙重竄改防護：
  1. set_review_status 核准前重新驗證 ir_json，不合格者拒絕核准。
  2. visible_assets 對外輸出前逐筆重新驗證 ir_json，不合格者略過不外洩。
- Fail-Closed：若資料表不存在，查詢安全回傳空清單，審核操作拋出 RuntimeError。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from .ir import validate_ir
from .writer import has_visual_assets_table

VALID_REVIEW_STATUSES = ("pending", "approved", "rejected")


def set_review_status(
    conn: sqlite3.Connection,
    topic_key: str,
    status: str,
    commit: bool = True,
) -> dict[str, Any]:
    """變更指定視覺資產之審核狀態。

    參數：
        conn: SQLite 資料庫連線
        topic_key: 資產主題鍵名
        status: 'pending' | 'approved' | 'rejected'
        commit: 是否自動提交交易

    回傳：
        {"status": "ok", "review_status": status}
        或 {"status": "not_found"}
        或 {"status": "validation_failed", "code": code}
    """
    if status not in VALID_REVIEW_STATUSES:
        raise ValueError(f"無效的 review_status: '{status}'，合法值為 {VALID_REVIEW_STATUSES}")

    if not has_visual_assets_table(conn):
        raise RuntimeError("資料庫尚未建立 visual_assets 資料表，請先執行 scripts/migrate_visual_assets.py 遷移腳本。")

    cur = conn.cursor()
    cur.execute("SELECT ir_json FROM visual_assets WHERE topic_key = ?", (topic_key,))
    row = cur.fetchone()
    if row is None:
        return {"status": "not_found"}

    ir_json_str = row[0]

    # 若欲核准，必須先重跑 validate_ir 確保內容合規（防直接修改資料庫後的非法發布）
    if status == "approved":
        try:
            ir = json.loads(ir_json_str)
        except Exception:
            return {"status": "validation_failed", "code": "schema_error"}

        ok, code = validate_ir(ir)
        if not ok:
            return {"status": "validation_failed", "code": code}

    if status == "approved":
        cur.execute(
            """
            UPDATE visual_assets
            SET review_status = 'approved',
                reviewed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE topic_key = ?
            """,
            (topic_key,),
        )
    elif status == "rejected":
        cur.execute(
            """
            UPDATE visual_assets
            SET review_status = 'rejected',
                reviewed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE topic_key = ?
            """,
            (topic_key,),
        )
    else:  # pending
        cur.execute(
            """
            UPDATE visual_assets
            SET review_status = 'pending',
                reviewed_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE topic_key = ?
            """,
            (topic_key,),
        )

    if commit:
        conn.commit()

    return {"status": "ok", "review_status": status}


def visible_assets(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """查詢所有對外可見（review_status='approved'）之視覺解說卡資產。

    安全防護：
    - 缺表時安全回傳空清單（Fail-Closed）。
    - 輸出前逐筆由 Python 執行 validate_ir 檢驗，遭竄改之非法資產自動略過不外露。
    - 輸出不包含診所私有欄位（共用資產）。
    """
    if not has_visual_assets_table(conn):
        return []

    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, topic_key, title, keywords, ir_json, source_type,
               review_status, reviewed_at, content_version, metadata,
               created_at, updated_at
        FROM visual_assets
        WHERE review_status = 'approved'
        ORDER BY id ASC
        """
    )
    rows = cur.fetchall()

    result: list[dict[str, Any]] = []
    for r in rows:
        raw_ir = r[4]
        try:
            ir = json.loads(raw_ir)
        except Exception:
            continue

        # 輸出防線：重新檢驗 IR
        ok, _ = validate_ir(ir)
        if not ok:
            continue

        try:
            kw = json.loads(r[3])
        except Exception:
            kw = []

        result.append({
            "id": r[0],
            "topic_key": r[1],
            "title": r[2],
            "keywords": kw,
            "ir": ir,
            "source_type": r[5],
            "review_status": r[6],
            "reviewed_at": r[7],
            "content_version": r[8],
            "metadata": r[9],
            "created_at": r[10],
            "updated_at": r[11],
        })

    return result
