"""
Taiwan Clinic Medical PageIndex RAG System - SOAP 紀錄單一權威寫入模組 (soap_writer)
Phase 14: 臨床語音與 SOAP 紀錄擷取 (D-01, D-02, D-05)

遵循 AGENTS.md 單一負責來源原則：所有寫入 soap_records 資料表的操作
必須一律經由 upsert_soap_records()，嚴禁各自重寫 INSERT/UPDATE。
"""

import sqlite3
from typing import Any, Iterable, Tuple

SOAP_CONTENT_FIELDS = (
    "patient_token",
    "subjective",
    "objective",
    "assessment",
    "plan",
    "raw_text",
    "tags",
)


def upsert_soap_records(
    conn: sqlite3.Connection,
    records: Iterable[dict[str, Any]],
    clinic_id: str,
) -> Tuple[int, int, int]:
    """增量寫入或更新 soap_records 資料表記錄。

    records: list of dict，每個 dict 欄位規範：
        - external_id: str（必填，非空白）
        - patient_token: str（必填，非空白）
        - subjective: Optional[str]
        - objective: Optional[str]
        - assessment: Optional[str]
        - plan: Optional[str]
        - raw_text: str（必填，原始推播文字）
        - tags: Optional[str]（逗號分隔字串或 JSON 標籤）
    clinic_id: str（必填，非空白，對應 clinic_info.clinic_id）

    回傳: (inserted, updated, unchanged)
    """
    clean_clinic_id = (clinic_id or "").strip()
    if not clean_clinic_id:
        raise ValueError("寫入 SOAP 紀錄時 clinic_id 必須為非空字串")

    cursor = conn.cursor()
    inserted = 0
    updated = 0
    unchanged = 0

    for idx, rec in enumerate(records):
        external_id = (rec.get("external_id") or "").strip()
        patient_token = (rec.get("patient_token") or "").strip()
        raw_text = (rec.get("raw_text") or "").strip()
        subjective = (rec.get("subjective") or "").strip()
        objective = (rec.get("objective") or "").strip()
        assessment = (rec.get("assessment") or "").strip()
        plan = (rec.get("plan") or "").strip()
        tags = (rec.get("tags") or "").strip()

        if not external_id:
            raise ValueError(f"第 {idx} 筆 SOAP 紀錄缺少必填欄位 'external_id'")
        if not patient_token:
            raise ValueError(
                f"第 {idx} 筆 SOAP 紀錄 (external_id='{external_id}') 缺少必填欄位 'patient_token'"
            )
        if not raw_text:
            raise ValueError(
                f"第 {idx} 筆 SOAP 紀錄 (external_id='{external_id}') 缺少必填欄位 'raw_text'"
            )

        # 以 (clinic_id, external_id) 比對
        cursor.execute(
            """
            SELECT id, patient_token, subjective, objective, assessment, plan, raw_text, tags
            FROM soap_records
            WHERE clinic_id = ? AND external_id = ?
            """,
            (clean_clinic_id, external_id),
        )
        existing = cursor.fetchone()

        new_content = (
            patient_token,
            subjective,
            objective,
            assessment,
            plan,
            raw_text,
            tags,
        )

        if existing is None:
            cursor.execute(
                """
                INSERT INTO soap_records (
                    clinic_id, external_id, patient_token, subjective,
                    objective, assessment, plan, raw_text, tags,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (clean_clinic_id, external_id, *new_content),
            )
            inserted += 1
        else:
            existing_id = existing[0]
            existing_content = tuple(existing[1:])

            if existing_content == new_content:
                unchanged += 1
                continue

            cursor.execute(
                """
                UPDATE soap_records
                SET patient_token = ?,
                    subjective = ?,
                    objective = ?,
                    assessment = ?,
                    plan = ?,
                    raw_text = ?,
                    tags = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*new_content, existing_id),
            )
            updated += 1

    conn.commit()
    return inserted, updated, unchanged
