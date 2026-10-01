#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - FAQ Cache 單一權威寫入模組 (faq_writer)
Phase 03 Document Ingestion Stage 1: TASK-00

架構原則（見 AGENTS.md 2.2 與 Phase 03 TASK-PLAN.md）：
- 本模組是 faq_cache 的唯一權威寫入函式，任何文件擷取管線、批次生成或後續維護
  皆必須呼叫 upsert_faqs()，嚴禁各自重複實作 INSERT/UPDATE 邏輯。
- 寫入規則：增量 UPSERT，以 (clinic_id, topic_key, question) 為唯一識別。
  - 新資料 INSERT（content_version=1）
  - 內容變更 UPDATE（遞增 content_version，更新 updated_at，清除 needs_regeneration）
  - 內容一致跳過（保留原始 created_at 與 content_version，不觸發無謂 FTS 重建）
- 嚴格合規：category='special' 項目必須具備非空 clinic_id，否則拋出 ValueError。
"""

import sqlite3
from typing import Any, Iterable, Optional

try:
    from .faq_review import has_review_status
except ImportError:
    from src.pageindex.faq_review import has_review_status

CONTENT_FIELDS = ("question", "answer", "category", "topic_key")
VALID_CATEGORIES = ("special", "general")
VALID_SOURCE_TYPES = ("manual", "llm_generated", "clinic_upload")


def upsert_faqs(
    conn: sqlite3.Connection,
    faqs: Iterable[dict[str, Any]],
    source_type: str,
) -> tuple[int, int, int]:
    """增量寫入或更新 faq_cache 資料表記錄。

    faqs: list of dict，每個 dict 欄位規範：
        - question: str（必填，非空白）
        - answer: str（必填，非空白）
        - category: 'special' | 'general'（必填）
        - clinic_id: Optional[str]（category='special' 時必填非空；general 時可為 None）
        - topic_key: Optional[str]（對應之療程/主題 slug，可為 None）
    source_type: 'manual' | 'llm_generated' | 'clinic_upload'

    審核狀態規範（Phase 09）：
        - source_type='llm_generated' 寫入時 review_status 預設為 'pending'
        - 'manual' 與 'clinic_upload' 寫入時 review_status 預設為 'approved'
        - 若資料庫尚未遷移審核欄位且欲寫入 'llm_generated'，直接拋出 RuntimeError（Fail-Closed 原則）

    回傳: (inserted, updated, unchanged)
    """
    if source_type not in VALID_SOURCE_TYPES:
        raise ValueError(
            f"無效的 source_type: '{source_type}'，合法值為 {VALID_SOURCE_TYPES}"
        )

    has_review = has_review_status(conn)
    if source_type == "llm_generated" and not has_review:
        raise RuntimeError(
            "資料庫尚未建立審核欄位，禁止寫入 llm_generated 內容！請先執行 scripts/migrate_faq_review_status.py 遷移腳本。"
        )

    target_review_status = "pending" if source_type == "llm_generated" else "approved"

    cursor = conn.cursor()
    inserted = 0
    updated = 0
    unchanged = 0

    for idx, faq in enumerate(faqs):
        question = (faq.get("question") or "").strip()
        answer = (faq.get("answer") or "").strip()
        category = (faq.get("category") or "").strip()
        clinic_id: Optional[str] = faq.get("clinic_id")
        topic_key: Optional[str] = faq.get("topic_key")

        if not question:
            raise ValueError(f"第 {idx} 筆 FAQ 缺少必填欄位 'question' 或內容為空")
        if not answer:
            raise ValueError(f"第 {idx} 筆 FAQ (question='{question}') 缺少必填欄位 'answer' 或內容為空")
        if category not in VALID_CATEGORIES:
            raise ValueError(
                f"第 {idx} 筆 FAQ (question='{question}') 之 category='{category}' 無效，必須為 {VALID_CATEGORIES} 之一"
            )

        if category == "special":
            if not clinic_id or not str(clinic_id).strip():
                raise ValueError(
                    f"category='special' 之 FAQ (question='{question}') 必須包含非空之 'clinic_id'"
                )
            clinic_id = str(clinic_id).strip()
        else:
            clinic_id = str(clinic_id).strip() if clinic_id else None

        topic_key = str(topic_key).strip() if topic_key else None

        # 以 (clinic_id, topic_key, question) 進行比對
        cursor.execute(
            """
            SELECT id, question, answer, category, topic_key, content_version
            FROM faq_cache
            WHERE clinic_id IS ? AND topic_key IS ? AND question = ?
            """,
            (clinic_id, topic_key, question),
        )
        existing = cursor.fetchone()

        if existing is None:
            if has_review:
                cursor.execute(
                    """
                    INSERT INTO faq_cache (
                        clinic_id, topic_key, question, answer, category,
                        source_type, content_version, needs_regeneration, review_status
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?)
                    """,
                    (
                        clinic_id,
                        topic_key,
                        question,
                        answer,
                        category,
                        source_type,
                        target_review_status,
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO faq_cache (
                        clinic_id, topic_key, question, answer, category,
                        source_type, content_version, needs_regeneration
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, 0)
                    """,
                    (
                        clinic_id,
                        topic_key,
                        question,
                        answer,
                        category,
                        source_type,
                    ),
                )
            inserted += 1
        else:
            existing_id, existing_q, existing_a, existing_cat, existing_topic, existing_version = existing
            existing_content = (existing_q, existing_a, existing_cat, existing_topic)
            new_content = (question, answer, category, topic_key)

            if existing_content == new_content:
                unchanged += 1
                continue

            if has_review:
                cursor.execute(
                    """
                    UPDATE faq_cache
                    SET answer = ?,
                        category = ?,
                        source_type = ?,
                        content_version = ?,
                        needs_regeneration = 0,
                        review_status = ?,
                        reviewed_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        answer,
                        category,
                        source_type,
                        existing_version + 1,
                        target_review_status,
                        existing_id,
                    ),
                )
            else:
                cursor.execute(
                    """
                    UPDATE faq_cache
                    SET answer = ?,
                        category = ?,
                        source_type = ?,
                        content_version = ?,
                        needs_regeneration = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        answer,
                        category,
                        source_type,
                        existing_version + 1,
                        existing_id,
                    ),
                )
            updated += 1

    conn.commit()
    return inserted, updated, unchanged
