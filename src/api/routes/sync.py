"""
doctor-toolbox.com 雙向資料同步端點模組（Phase 05 TASK-03）。
提供官方 RESTful JSON 契約，負責知識庫、門診時間、自訂備註之增量匯出與驗證匯入。
嚴格遵守單一權威寫入路徑（upsert_trees、upsert_faqs、upsert_clinic_note），
並記錄每次操作至 sync_logs 審計資料表。
"""

from datetime import datetime
import json
import logging
import re
import sqlite3
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import get_read_db, get_write_db, verify_admin_key
from ..models.sync import (
    SyncExportRequest,
    SyncExportResponse,
    SyncImportRequest,
    SyncImportResponse,
    SyncLogItem,
)
from .query import deep_mask_prices

try:
    from ...pageindex.db_writer import upsert_trees, CONTENT_FIELDS
    from ...pageindex.faq_writer import upsert_faqs
    from ...clinic.custom_notes import upsert_clinic_note, VALID_SECTIONS
    from ...query.router import get_clinic_hours, get_clinic_custom_notes, mask_prices
    from ...ingestion.convert_chinese import to_traditional
    from ...pageindex.faq_review import visible_faq_sql
except (ImportError, ValueError):
    from src.pageindex.db_writer import upsert_trees, CONTENT_FIELDS
    from src.pageindex.faq_writer import upsert_faqs
    from src.clinic.custom_notes import upsert_clinic_note, VALID_SECTIONS
    from src.query.router import get_clinic_hours, get_clinic_custom_notes, mask_prices
    from src.ingestion.convert_chinese import to_traditional
    from src.pageindex.faq_review import visible_faq_sql

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sync", tags=["doctor-toolbox.com 雙向資料同步"])

# 常見簡體字樣本檢測
_SIMPLIFIED_CHAR_SAMPLE = set("这个国实现们来对进为产时问题号线还没会说诊评体门医处术发区专护")

# 醫療廣告與法規禁用誇大保證療效詞彙（含簡繁與異體字）
_FORBIDDEN_PHRASES = (
    "保證有效",
    "保证有效",
    "一定能消除",
    "保證消除",
    "保证消除",
    "保證治癒",
    "保证治愈",
    "保證根除",
    "保证根除",
    "百分之百有效",
    "100%有效",
    "永久根除",
    "physician_notes",
)

# 政治與主權立場爭議詞彙（含簡繁與台/臺異體字對應）
_POLITICAL_STANCE_PHRASES = (
    "不可分割的一部分",
    "一个中国",
    "一個中國",
    "中国台湾",
    "中國台灣",
    "中国臺灣",
    "中國臺灣",
    "台湾地区",
    "台灣地區",
    "臺灣地區",
    "台湾省",
    "台灣省",
    "臺灣省",
)


def _ensure_sync_logs_table(conn: sqlite3.Connection) -> None:
    """確保 sync_logs 資料表及其索引存在。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id TEXT REFERENCES clinic_info(clinic_id),
            sync_type TEXT NOT NULL,         -- 'export' | 'import'
            direction TEXT NOT NULL,         -- 'push' | 'pull'
            status TEXT NOT NULL,            -- 'success' | 'failed' | 'partial'
            record_count INTEGER DEFAULT 0,
            payload_summary TEXT,            -- 簡要摘要（嚴禁記錄病患個資與具體價格）
            error_message TEXT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sync_logs_clinic_id ON sync_logs(clinic_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sync_logs_started_at ON sync_logs(started_at);")
    conn.commit()


def sanitize_and_validate_import_data(data: Any, auto_convert_simplified: bool = True) -> Any:
    """遞迴檢核與清洗匯入資料：
    1. 繁中轉換/驗證（可選自動轉換，若停用則檢出簡體即報錯）
    2. 禁用誇大或保證療效詞彙攔截（拋出 HTTP 400）
    3. 政治立場詞彙攔截（拋出 HTTP 400）
    4. 價格清洗遮蔽（非價格文字欄位價格屏蔽為 [請致電診所確認]）
    """
    if isinstance(data, str):
        raw_text = data

        # 前置政治立場與違規禁詞掃描（避免轉換前漏失）
        for phrase in _FORBIDDEN_PHRASES:
            if phrase in raw_text:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"匯入內容違反醫療廣告合規限制，包含禁用之誇大或保證療效詞彙: '{phrase}'",
                )

        for phrase in _POLITICAL_STANCE_PHRASES:
            if phrase in raw_text:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"匯入內容包含政治立場爭議詞彙: '{phrase}'",
                )

        if auto_convert_simplified:
            text = to_traditional(raw_text)
        else:
            simplified_hits = [c for c in raw_text if c in _SIMPLIFIED_CHAR_SAMPLE]
            if simplified_hits:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"匯入內容包含簡體中文字元: {''.join(set(simplified_hits))}，違反繁體中文專用規範",
                )
            text = raw_text

        # 轉換後再次雙重檢查
        for phrase in _FORBIDDEN_PHRASES:
            if phrase in text:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"匯入內容違反醫療廣告合規限制，包含禁用之誇大或保證療效詞彙: '{phrase}'",
                )

        for phrase in _POLITICAL_STANCE_PHRASES:
            if phrase in text:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"匯入內容包含政治立場爭議詞彙: '{phrase}'",
                )

        return mask_prices(text)

    elif isinstance(data, dict):
        return {k: sanitize_and_validate_import_data(v, auto_convert_simplified) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_and_validate_import_data(item, auto_convert_simplified) for item in data]
    return data


@router.post(
    "/export",
    response_model=SyncExportResponse,
    summary="匯出診所資料至雲端 (doctor-toolbox.com 契約)",
)
def export_sync_data(
    request: SyncExportRequest,
    _authorized: bool = Depends(verify_admin_key),
    conn: sqlite3.Connection = Depends(get_write_db),
) -> SyncExportResponse:
    """增量匯出診所臨床推理樹、衛教 FAQ、通用備註與門診時間。
    所有病患可見文字一律經由 deep_mask_prices() 二次遮蔽，保證零價格洩漏。
    """
    _ensure_sync_logs_table(conn)

    cursor = conn.cursor()
    exported_data: Dict[str, Any] = {}
    counts: Dict[str, int] = {}

    # 1. 臨床推理樹 (page_index_trees)
    if "trees" in request.entities:
        cursor.execute(
            """
            SELECT id, doc_id, clinic_id, category, pre_op, pre_op_physician_notes,
                   procedure, procedure_physician_notes, post_op_short,
                   post_op_short_physician_notes, maintenance,
                   maintenance_physician_notes, summary_text, version,
                   source_type, content_version, needs_regeneration, indexed_at,
                   created_at, updated_at
            FROM page_index_trees
            WHERE clinic_id = ? AND content_version >= ?
            ORDER BY id ASC
            """,
            (request.clinic_id, request.since_version),
        )
        tree_rows = [dict(row) for row in cursor.fetchall()]
        exported_data["trees"] = tree_rows
        counts["trees"] = len(tree_rows)

    # 2. 常見問答 (faq_cache)
    # 未核准 LLM FAQ 不外送雲端（Phase 09 BATCH-01）
    if "faqs" in request.entities:
        cursor.execute(
            f"""
            SELECT id, clinic_id, topic_key, question, answer, category,
                   source_type, content_version, needs_regeneration,
                   created_at, updated_at
            FROM faq_cache
            WHERE (clinic_id = ? OR (clinic_id IS NULL AND category = 'general'))
              AND content_version >= ?
              AND {visible_faq_sql(conn)}
            ORDER BY id ASC
            """,
            (request.clinic_id, request.since_version),
        )
        faq_rows = [dict(row) for row in cursor.fetchall()]
        exported_data["faqs"] = faq_rows
        counts["faqs"] = len(faq_rows)

    # 3. 診所通用備註 (clinic_custom_notes)
    if "notes" in request.entities:
        notes = get_clinic_custom_notes(conn, request.clinic_id)
        exported_data["notes"] = notes
        counts["notes"] = len(notes)

    # 4. 門診時間表 (clinic_hours)
    if "hours" in request.entities:
        hours = get_clinic_hours(conn, request.clinic_id)
        exported_data["hours"] = hours
        counts["hours"] = len(hours)

    # 安全防禦：匯出前全面遮蔽具體金額
    safe_data = deep_mask_prices(exported_data)
    total_records = sum(counts.values())
    summary_text = json.dumps(counts, ensure_ascii=False)

    # 寫入 sync_logs 審計紀錄
    cursor.execute(
        """
        INSERT INTO sync_logs (
            clinic_id, sync_type, direction, status, record_count,
            payload_summary, started_at, completed_at
        ) VALUES (?, 'export', 'pull', 'success', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (request.clinic_id, total_records, summary_text),
    )
    conn.commit()

    return SyncExportResponse(
        clinic_id=request.clinic_id,
        exported_at=datetime.now().isoformat(),
        counts=counts,
        data=safe_data,
    )


@router.post(
    "/import",
    response_model=SyncImportResponse,
    summary="自雲端匯入診所資料 (doctor-toolbox.com 契約)",
)
def import_sync_data(
    request: SyncImportRequest,
    _authorized: bool = Depends(verify_admin_key),
    conn: sqlite3.Connection = Depends(get_write_db),
) -> SyncImportResponse:
    """自雲端推播匯入更新資料。
    嚴格遵循單一權威寫入函式：
    - page_index_trees -> upsert_trees
    - faq_cache -> upsert_faqs
    - clinic_custom_notes -> upsert_clinic_note
    - clinic_hours -> 交易內比對更新
    """
    _ensure_sync_logs_table(conn)

    # 1. 遞迴驗證與清洗（繁中轉換、價格清洗、保證療效攔截）
    cleaned_data = sanitize_and_validate_import_data(
        request.data, auto_convert_simplified=request.auto_convert_simplified
    )

    summary: Dict[str, int] = {
        "trees_inserted": 0,
        "trees_updated": 0,
        "trees_unchanged": 0,
        "faqs_inserted": 0,
        "faqs_updated": 0,
        "faqs_unchanged": 0,
        "notes_updated": 0,
        "hours_updated": 0,
    }

    cursor = conn.cursor()

    try:
        # 2. 處理臨床推理樹 (trees)
        if "trees" in cleaned_data and isinstance(cleaned_data["trees"], list):
            trees_to_upsert = []
            for item in cleaned_data["trees"]:
                if not isinstance(item, dict):
                    continue
                doc_id = (item.get("doc_id") or "").strip()
                if not doc_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="匯入之 tree 項目缺少必填之 'doc_id'",
                    )

                target_clinic_id = item.get("clinic_id") or request.clinic_id

                # 查詢既有記錄以支援部分更新（如僅更新 physician_notes）
                cursor.execute(
                    f"SELECT {', '.join(CONTENT_FIELDS)} FROM page_index_trees WHERE doc_id = ?",
                    (doc_id,),
                )
                existing_row = cursor.fetchone()

                tree_entry: Dict[str, Any] = {
                    "doc_id": doc_id,
                    "clinic_id": target_clinic_id,
                }

                for field in CONTENT_FIELDS:
                    if field in item:
                        tree_entry[field] = item[field]
                    elif existing_row is not None:
                        tree_entry[field] = existing_row[field]
                    else:
                        tree_entry[field] = "療程" if field == "category" else ""

                trees_to_upsert.append(tree_entry)

            if trees_to_upsert:
                t_ins, t_upd, t_unc = upsert_trees(
                    conn, trees_to_upsert, source_type="clinic_upload"
                )
                summary["trees_inserted"] = t_ins
                summary["trees_updated"] = t_upd
                summary["trees_unchanged"] = t_unc

        # 3. 處理 FAQ 快取 (faqs)
        if "faqs" in cleaned_data and isinstance(cleaned_data["faqs"], list):
            faqs_to_upsert = []
            for item in cleaned_data["faqs"]:
                if not isinstance(item, dict):
                    continue
                q = (item.get("question") or "").strip()
                a = (item.get("answer") or "").strip()
                if not q or not a:
                    continue

                cat = item.get("category", "special")
                cid = item.get("clinic_id") or (request.clinic_id if cat == "special" else None)
                faqs_to_upsert.append(
                    {
                        "question": q,
                        "answer": a,
                        "category": cat,
                        "clinic_id": cid,
                        "topic_key": item.get("topic_key"),
                    }
                )

            if faqs_to_upsert:
                f_ins, f_upd, f_unc = upsert_faqs(
                    conn, faqs_to_upsert, source_type="clinic_upload"
                )
                summary["faqs_inserted"] = f_ins
                summary["faqs_updated"] = f_upd
                summary["faqs_unchanged"] = f_unc

        # 4. 處理診所自訂備註 (notes)
        if "notes" in cleaned_data:
            notes_input = cleaned_data["notes"]
            notes_items = []
            if isinstance(notes_input, dict):
                notes_items = list(notes_input.items())
            elif isinstance(notes_input, list):
                for n_elem in notes_input:
                    if isinstance(n_elem, dict) and "section" in n_elem and "note" in n_elem:
                        notes_items.append((n_elem["section"], n_elem["note"]))

            for section, note in notes_items:
                if section not in VALID_SECTIONS:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"無效的備註 section: '{section}'，必須為 {VALID_SECTIONS} 之一",
                    )
                upsert_clinic_note(conn, request.clinic_id, section, str(note))
                summary["notes_updated"] += 1

        # 5. 處理門診時間 (hours)
        if "hours" in cleaned_data and isinstance(cleaned_data["hours"], list):
            for h in cleaned_data["hours"]:
                if not isinstance(h, dict) or "day_of_week" not in h:
                    continue
                day_of_week = h["day_of_week"]
                morning_start = h.get("morning_start")
                morning_end = h.get("morning_end")
                afternoon_start = h.get("afternoon_start")
                afternoon_end = h.get("afternoon_end")
                evening_start = h.get("evening_start")
                evening_end = h.get("evening_end")
                is_open = int(bool(h.get("is_open", True)))

                cursor.execute(
                    "SELECT id FROM clinic_hours WHERE clinic_id = ? AND day_of_week = ?",
                    (request.clinic_id, day_of_week),
                )
                existing_h = cursor.fetchone()
                if existing_h:
                    cursor.execute(
                        """
                        UPDATE clinic_hours
                        SET morning_start = ?, morning_end = ?, afternoon_start = ?, afternoon_end = ?,
                            evening_start = ?, evening_end = ?, is_open = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            morning_start,
                            morning_end,
                            afternoon_start,
                            afternoon_end,
                            evening_start,
                            evening_end,
                            is_open,
                            existing_h[0],
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO clinic_hours (
                            clinic_id, day_of_week, morning_start, morning_end,
                            afternoon_start, afternoon_end, evening_start, evening_end,
                            is_open, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """,
                        (
                            request.clinic_id,
                            day_of_week,
                            morning_start,
                            morning_end,
                            afternoon_start,
                            afternoon_end,
                            evening_start,
                            evening_end,
                            is_open,
                        ),
                    )
                summary["hours_updated"] += 1

        total_processed = (
            summary["trees_inserted"]
            + summary["trees_updated"]
            + summary["faqs_inserted"]
            + summary["faqs_updated"]
            + summary["notes_updated"]
            + summary["hours_updated"]
        )

        cursor.execute(
            """
            INSERT INTO sync_logs (
                clinic_id, sync_type, direction, status, record_count,
                payload_summary, started_at, completed_at
            ) VALUES (?, 'import', 'push', 'success', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (request.clinic_id, total_processed, json.dumps(summary, ensure_ascii=False)),
        )
        sync_id = cursor.lastrowid
        conn.commit()

        return SyncImportResponse(
            success=True,
            sync_id=sync_id,
            summary=summary,
            message="資料同步匯入成功",
        )

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"同步匯入時發生未預期錯誤: {e}", exc_info=True)
        try:
            cursor.execute(
                """
                INSERT INTO sync_logs (
                    clinic_id, sync_type, direction, status, record_count,
                    payload_summary, error_message, started_at, completed_at
                ) VALUES (?, 'import', 'push', 'failed', 0, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (request.clinic_id, "匯入失敗", str(e)),
            )
            conn.commit()
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"資料匯入失敗: {e}",
        )


@router.get(
    "/logs",
    response_model=List[SyncLogItem],
    summary="取得同步審計紀錄",
)
def get_sync_logs(
    clinic_id: Optional[str] = Query(None, description="依診所代碼篩選"),
    limit: int = Query(20, ge=1, le=100, description="最多回傳筆數"),
    _authorized: bool = Depends(verify_admin_key),
    conn: sqlite3.Connection = Depends(get_read_db),
) -> List[SyncLogItem]:
    """查詢近期之資料同步匯出入紀錄。"""
    cursor = conn.cursor()
    try:
        if clinic_id:
            cursor.execute(
                """
                SELECT id, clinic_id, sync_type, direction, status, record_count,
                       payload_summary, error_message, started_at, completed_at
                FROM sync_logs
                WHERE clinic_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (clinic_id, limit),
            )
        else:
            cursor.execute(
                """
                SELECT id, clinic_id, sync_type, direction, status, record_count,
                       payload_summary, error_message, started_at, completed_at
                FROM sync_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
        rows = [dict(row) for row in cursor.fetchall()]
        return [SyncLogItem(**row) for row in rows]
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return []
