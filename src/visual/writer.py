"""
視覺解說卡單一權威寫入模組 (writer)。
Phase 29: P29-SCHEMA, P29-IR

設計原則：
- 本模組為 visual_assets 的唯一權威寫入函式。
- 寫入前強制呼叫 validate_ir 進行整批驗證，任何一筆不合規即拋出 ValueError(code) 並整批拒絕。
- Fail-Closed：若資料庫尚未遷移（缺少 visual_assets 表），拋出 RuntimeError，不自動建表。
- 增量 UPSERT：新列 pending；既有列內容實質變更回 pending 並遞增 content_version，清空 reviewed_at；內容未變冪等跳過。
- 絕不自動核准。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable

from .ir import validate_ir

VALID_SOURCE_TYPES = ("manual", "llm_generated")


def has_visual_assets_table(conn: sqlite3.Connection) -> bool:
    """檢查資料庫是否已建立 visual_assets 資料表。"""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='visual_assets'")
    return cur.fetchone() is not None


def upsert_assets(
    conn: sqlite3.Connection,
    assets: Iterable[dict[str, Any]],
    source_type: str,
    commit: bool = True,
) -> dict[str, int]:
    """增量寫入或更新 visual_assets 資料表記錄。

    assets: iterable of dict，每個 dict 包含：
        - topic_key: str
        - title: str
        - keywords: list[str]
        - ir: dict（符合 Typed IR 規格）
        - metadata: Optional[str | dict]（選填）

    source_type: 'manual' | 'llm_generated'

    回傳：
        {"inserted": inserted, "updated": updated, "unchanged": unchanged}
    """
    if source_type not in VALID_SOURCE_TYPES:
        raise ValueError(f"無效的 source_type: '{source_type}'，合法值為 {VALID_SOURCE_TYPES}")

    if not has_visual_assets_table(conn):
        raise RuntimeError("資料庫尚未建立 visual_assets 資料表，請先執行 scripts/migrate_visual_assets.py 遷移腳本。")

    asset_list = list(assets)
    if not asset_list:
        return {"inserted": 0, "updated": 0, "unchanged": 0}

    # 1. 前置驗證：整批所有資產必須通過 validate_ir 與一致性檢查，任一失敗立即整批拒絕
    for a in asset_list:
        ir = a.get("ir")
        ok, code = validate_ir(ir)
        if not ok:
            raise ValueError(f"IR 驗證失敗: {code}")

        # 確保外層 topic_key, title, keywords 與 IR 內完全一致
        if a.get("topic_key") != ir.get("topic_key"):
            raise ValueError("外層 topic_key 與 IR 內 topic_key 不一致")
        if a.get("title") != ir.get("title"):
            raise ValueError("外層 title 與 IR 內 title 不一致")
        if a.get("keywords") != ir.get("keywords"):
            raise ValueError("外層 keywords 與 IR 內 keywords 不一致")

    # 2. 逐筆 UPSERT
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(visual_assets)")
    has_clinic_col = "clinic_id" in [row[1] for row in cur.fetchall()]

    inserted = 0
    updated = 0
    unchanged = 0

    for a in asset_list:
        raw_clinic = a.get("clinic_id")
        if raw_clinic is not None:
            if not isinstance(raw_clinic, str):
                raise ValueError(f"clinic_id 必須為字串或 None，得到 {type(raw_clinic).__name__}")
            clinic_id = raw_clinic.strip() or None
        else:
            clinic_id = None

        topic_key = a["topic_key"]
        title = a["title"]
        keywords_json = json.dumps(a["keywords"], ensure_ascii=False)
        ir_json = json.dumps(a["ir"], ensure_ascii=False)
        raw_meta = a.get("metadata")
        metadata_str = json.dumps(raw_meta, ensure_ascii=False) if isinstance(raw_meta, (dict, list)) else (raw_meta or None)

        if has_clinic_col:
            cur.execute(
                "SELECT title, keywords, ir_json, content_version FROM visual_assets WHERE clinic_id IS ? AND topic_key = ?",
                (clinic_id, topic_key)
            )
        else:
            cur.execute(
                "SELECT title, keywords, ir_json, content_version FROM visual_assets WHERE topic_key = ?",
                (topic_key,)
            )
        existing = cur.fetchone()

        if existing is None:
            # 新增記錄：review_status 恆為 pending，content_version 預設 1
            if has_clinic_col:
                cur.execute(
                    """
                    INSERT INTO visual_assets (
                        clinic_id, topic_key, title, keywords, ir_json, source_type,
                        review_status, reviewed_at, content_version, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, 1, ?)
                    """,
                    (clinic_id, topic_key, title, keywords_json, ir_json, source_type, metadata_str),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO visual_assets (
                        topic_key, title, keywords, ir_json, source_type,
                        review_status, reviewed_at, content_version, metadata
                    ) VALUES (?, ?, ?, ?, ?, 'pending', NULL, 1, ?)
                    """,
                    (topic_key, title, keywords_json, ir_json, source_type, metadata_str),
                )
            inserted += 1
        else:
            old_title, old_kw_json, old_ir_json, _ = existing
            # 比對內容是否實質變更
            if old_title == title and old_kw_json == keywords_json and old_ir_json == ir_json:
                unchanged += 1
            else:
                # 內容實質變更：重設為 pending，清除 reviewed_at，content_version+1
                if has_clinic_col:
                    cur.execute(
                        """
                        UPDATE visual_assets SET
                            title = ?,
                            keywords = ?,
                            ir_json = ?,
                            source_type = ?,
                            review_status = 'pending',
                            reviewed_at = NULL,
                            content_version = content_version + 1,
                            metadata = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE clinic_id IS ? AND topic_key = ?
                        """,
                        (title, keywords_json, ir_json, source_type, metadata_str, clinic_id, topic_key),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE visual_assets SET
                            title = ?,
                            keywords = ?,
                            ir_json = ?,
                            source_type = ?,
                            review_status = 'pending',
                            reviewed_at = NULL,
                            content_version = content_version + 1,
                            metadata = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE topic_key = ?
                        """,
                        (title, keywords_json, ir_json, source_type, metadata_str, topic_key),
                    )
                updated += 1

    if commit:
        conn.commit()

    return {"inserted": inserted, "updated": updated, "unchanged": unchanged}
