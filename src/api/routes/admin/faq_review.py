from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, StrictInt
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
from threading import Lock
import time
from typing import Any, Literal, Optional
import unicodedata
from src.ingestion.convert_chinese import to_traditional
from src.ingestion.extract_text import extract_docx_text, extract_xlsx_text
from src.ingestion.generate_faq import validate_single_faq
from src.ingestion.url_guard import UnsafeUrlError, validate_public_url
from src.pageindex import batch_answer_job
from src.pageindex.rag_ask import ask_with_data
from src.pageindex.answer_generator import GenerationError, generate_answer_for_faq, is_answer_thin
from src.pageindex.faq_review import MAX_BATCH_SIZE, batch_review_faqs, get_faq, has_metadata_column, has_review_status, set_review_status, update_faq_content
from src.pageindex.faq_writer import upsert_faqs
from src.pageindex.web_source_adapter import UrlFetchDeps, UrlFetchError, build_service_text, fetch_clinic_page, get_shared_robots, get_shared_throttle, optional_missing_fields
from src.scraper.fetch import build_user_agent
from src.scraper.policy import PolicyError, load_allowlist
from src.soap.deid import deidentify_text
from src.api.config import config
from src.api.dependencies import get_read_db, get_write_db, verify_admin_key
from src.api.routes.query import deep_mask_prices
from .shared import (
    ALLOWED_EXTENSIONS, LLM_ASK_TIMEOUT_SECONDS, LLM_GENERATE_TIMEOUT_SECONDS,
    MAX_ANSWER_CHARS, MAX_FILE_SIZE, MAX_PARAGRAPHS, _GENERATION_LOCK,
    _PDF_MAGIC, _Q_PREFIXES, _ZIP_MAGIC,
    AskRequest, AutoFillAllRequest, AutodraftVisualRequest, BatchGenerateRequest,
    BatchReviewRequest, ClinicCreateRequest, GeneralDraftRequest, GenerateAnswerRequest,
    TemplateOverrideRequest, UpdateFaqRequest, UpdateVisualAssetRequest,
    VisualBatchReviewRequest, VisualSceneUpdateItem,
    _local_llm_ask_call, _local_llm_call, _visual_llm_call,
)

router = APIRouter()

@router.get("/review/faqs", summary="檢索待審或已審衛教問答列表")
def get_admin_review_faqs(
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(pending|approved|rejected)$", description="pending/approved/rejected"),
    category: Optional[str] = Query(None, pattern="^(special|general)$", description="special/general"),
    clinic_id: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_read_db),
):
    """依據狀態、類別與診所代碼檢索 FAQ 列表，包含 metadata (SOAP 溯源資訊)。"""
    if not has_review_status(conn):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="資料庫尚未建立審核欄位",
        )

    where_clauses = []
    params = []

    if status_filter:
        where_clauses.append("review_status = ?")
        params.append(status_filter)

    if category:
        where_clauses.append("category = ?")
        params.append(category)

    if clinic_id:
        where_clauses.append("clinic_id = ?")
        params.append(clinic_id)

    if source_type:
        where_clauses.append("source_type = ?")
        params.append(source_type)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM faq_cache {where_sql}", tuple(params))
    total = cur.fetchone()[0]

    has_meta = has_metadata_column(conn)
    select_meta = ", metadata" if has_meta else ""

    query_sql = f"""
        SELECT id, clinic_id, topic_key, question, answer, category,
               source_type, content_version, needs_regeneration,
               review_status, reviewed_at, created_at, updated_at{select_meta}
        FROM faq_cache
        {where_sql}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """
    query_params = list(params) + [limit, offset]
    cur.execute(query_sql, tuple(query_params))
    rows = cur.fetchall()

    faqs = []
    for r in rows:
        item = dict(r)
        if has_meta and item.get("metadata"):
            try:
                if isinstance(item["metadata"], str):
                    item["metadata"] = json.loads(item["metadata"])
            except Exception:
                pass
        item["needs_answer"] = is_answer_thin(item.get("question"), item.get("answer"))
        faqs.append(item)

    return {
        "faqs": faqs,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/review/faqs/{faq_id}/approve", summary="核准指定 FAQ 發布")
def approve_admin_faq(
    faq_id: int,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """將指定 ID 之待審 FAQ 核准發布，使其在快取短路與自然語言查詢中生效。"""
    res = set_review_status(conn, [faq_id], "approved", enforce_general_warning=True)
    if faq_id in res.changed:
        return {"status": "ok", "message": f"FAQ {faq_id} 已核准發布", "id": faq_id}
    else:
        reason = "無效或無變更"
        if res.skipped:
            reason = res.skipped[0][1]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"無法核准 FAQ {faq_id}: {reason}",
        )


@router.post("/review/faqs/{faq_id}/reject", summary="駁回指定 FAQ 草稿")
def reject_admin_faq(
    faq_id: int,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """將指定 ID 之待審 FAQ 標記為駁回 (rejected)。"""
    res = set_review_status(conn, [faq_id], "rejected")
    if faq_id in res.changed:
        return {"status": "ok", "message": f"FAQ {faq_id} 已駁回", "id": faq_id}
    else:
        reason = "無效或無變更"
        if res.skipped:
            reason = res.skipped[0][1]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"無法駁回 FAQ {faq_id}: {reason}",
        )


@router.get("/review/summary", summary="醫師審核與系統儀表板摘要資訊")
def get_admin_review_summary(
    conn: sqlite3.Connection = Depends(get_read_db),
):
    """提供 Web 儀表板關鍵指標數字。"""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM faq_cache WHERE review_status = 'pending'")
    pending_total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM faq_cache WHERE review_status = 'pending' AND category = 'special'")
    pending_special = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM faq_cache WHERE review_status = 'pending' AND category = 'general'")
    pending_general = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM faq_cache WHERE review_status = 'pending' AND source_type = 'soap_distilled'")
    pending_soap_distilled = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM faq_cache WHERE review_status = 'approved'")
    approved_total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM faq_cache WHERE review_status = 'rejected'")
    rejected_total = cur.fetchone()[0]

    soap_records_total = 0
    try:
        cur.execute("SELECT COUNT(*) FROM soap_records")
        soap_records_total = cur.fetchone()[0]
    except Exception:
        pass

    trees_pending_total = 0
    trees_approved_total = 0
    trees_rejected_total = 0
    try:
        cur.execute("SELECT COUNT(*) FROM page_index_trees WHERE review_status = 'pending'")
        trees_pending_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM page_index_trees WHERE review_status = 'approved'")
        trees_approved_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM page_index_trees WHERE review_status = 'rejected'")
        trees_rejected_total = cur.fetchone()[0]
    except Exception:
        pass

    visuals_pending_total = 0
    visuals_approved_total = 0
    visuals_rejected_total = 0
    visuals_clinic_total = 0
    visuals_general_total = 0
    try:
        cur.execute("SELECT COUNT(*) FROM visual_assets WHERE review_status = 'pending'")
        visuals_pending_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM visual_assets WHERE review_status = 'approved'")
        visuals_approved_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM visual_assets WHERE review_status = 'rejected'")
        visuals_rejected_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM visual_assets WHERE clinic_id IS NOT NULL")
        visuals_clinic_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM visual_assets WHERE clinic_id IS NULL")
        visuals_general_total = cur.fetchone()[0]
    except Exception:
        pass

    visuals_videos_rendered_total = 0
    from src.visual.video_queue import DEFAULT_VIDEO_DIR
    if DEFAULT_VIDEO_DIR.exists():
        try:
            visuals_videos_rendered_total = len(list(DEFAULT_VIDEO_DIR.glob("*_landscape.mp4")))
        except Exception:
            pass

    total_pending = pending_total + trees_pending_total + visuals_pending_total
    total_approved = approved_total + trees_approved_total + visuals_approved_total
    total_rejected = rejected_total + trees_rejected_total + visuals_rejected_total
    total_assets = total_pending + total_approved + total_rejected

    return {
        "pending_total": pending_total,
        "pending_special": pending_special,
        "pending_general": pending_general,
        "pending_soap_distilled": pending_soap_distilled,
        "approved_total": approved_total,
        "rejected_total": rejected_total,
        "soap_records_total": soap_records_total,
        "trees_pending_total": trees_pending_total,
        "trees_approved_total": trees_approved_total,
        "trees_rejected_total": trees_rejected_total,
        "visuals_pending_total": visuals_pending_total,
        "visuals_approved_total": visuals_approved_total,
        "visuals_rejected_total": visuals_rejected_total,
        "visuals_clinic_total": visuals_clinic_total,
        "visuals_general_total": visuals_general_total,
        "visuals_videos_rendered_total": visuals_videos_rendered_total,
        "total_pending": total_pending,
        "total_approved": total_approved,
        "total_rejected": total_rejected,
        "total_assets": total_assets,
    }


@router.post("/review/batch", summary="批量核准／駁回待審草稿（單一交易）")
def batch_admin_review(
    req: BatchReviewRequest,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """單次最多 100 筆；核准前逐筆重跑合規檢驗，未通過者列入 failed_ids，其餘同一交易生效。"""
    if not has_review_status(conn):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="資料庫尚未建立審核欄位")
    try:
        result = batch_review_faqs(conn, req.faq_ids, req.action)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return {"status": "ok", "action": req.action, **result}


@router.patch("/review/faqs/{faq_id}", summary="內聯修訂待審草稿的題目／答案")
def patch_admin_faq(
    faq_id: int,
    req: UpdateFaqRequest,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    try:
        update_faq_content(conn, faq_id, question=req.question, answer=req.answer)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
    faq = get_faq(conn, faq_id)
    return {"status": "ok", "id": faq_id, "faq": faq}


@router.post("/review/faqs/{faq_id}/generate-answer", summary="以本機 LLM 為待審草稿生成衛教答案")
def generate_admin_faq_answer(
    faq_id: int,
    req: GenerateAnswerRequest = GenerateAnswerRequest(),
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """走本機 llama-server；生成內容須通過價格屏蔽、四層合規、劑量與就醫警訊檢驗才寫入，狀態維持 pending。"""
    from src.pageindex.llm_client import LLMEmptyOutputError, LocalLLMUnavailableError

    if not _GENERATION_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="已有一筆答案正在生成，請稍後再試")
    try:
        try:
            return {
                "status": "ok",
                **generate_answer_for_faq(
                    conn, faq_id, __import__('src.api.routes.admin', fromlist=['_local_llm_call'])._local_llm_call, overwrite=req.overwrite, grounded_llm_call=__import__('src.api.routes.admin', fromlist=['_local_llm_ask_call'])._local_llm_ask_call
                ),
            }
        except GenerationError as e:
            raise HTTPException(status_code=e.http_status, detail=str(e)) from e
        except LLMEmptyOutputError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="模型回覆為空（可能因思考長度超限），請稍後重試") from e
        except LocalLLMUnavailableError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="本機 LLM 服務目前無法使用，請確認 llama-server 已啟動後再試",
            ) from e
    finally:
        _GENERATION_LOCK.release()


GENERAL_DRAFT_TIMEOUT_SECONDS = 900  # 一般草稿提示長、思考可能超過 480 秒（實測逾時）



@router.post("/review/batch-generate", summary="啟動背景批次補齊答案（本機 LLM 逐題處理，完成後再一起審核）")
def start_batch_generate(req: BatchGenerateRequest):
    """同時只允許一個作業；每題結果一律 pending。進度以 GET /review/batch-generate/status 查詢。"""
    try:
        return batch_answer_job.start(
            config.db_path,
            req.faq_ids,
            __import__('src.api.routes.admin', fromlist=['_local_llm_call'])._local_llm_call,
            __import__('src.api.routes.admin', fromlist=['_local_llm_ask_call'])._local_llm_ask_call,
            _GENERATION_LOCK,
            overwrite=req.overwrite,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/review/batch-generate/status", summary="查詢批次補齊作業進度")
def batch_generate_status():
    return batch_answer_job.snapshot()


@router.post("/review/batch-generate/cancel", summary="取消批次補齊作業（目前題目完成後停止）")
def cancel_batch_generate():
    return {"status": "ok", "cancelling": batch_answer_job.cancel()}


@router.post("/review/autofill/all", summary="一鍵背景自動補齊所有待審題目之答案")
def autofill_all_unanswered(
    req: Optional[AutoFillAllRequest] = None,
    clinic_id: Optional[str] = Query(None),
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """
    一鍵啟動背景作業，自動補齊所有待審題目之答案。
    - 查詢 review_status='pending' 且 (answer IS NULL OR length(trim(answer)) < 15) 之項目。
    - 若無任何待補齊項目，回傳 {"status": "noop", "message": "目前無待補齊答案之草稿", "scheduled_count": 0}。
    - 若已有批次作業執行中，回傳 HTTP 409 Conflict。
    - 排入背景逐題生成，回傳 {"status": "started", "scheduled_count": len(ids), "faq_ids": ids}。
    """
    target_clinic_id = req.clinic_id if req and req.clinic_id is not None else clinic_id
    if target_clinic_id is not None:
        target_clinic_id = target_clinic_id.strip() or None

    if batch_answer_job.is_running():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已有批次補齊作業進行中")

    ids = batch_answer_job.get_pending_unanswered_ids(
        conn, clinic_id=target_clinic_id, limit=batch_answer_job.MAX_JOB_IDS
    )
    if not ids:
        return {"status": "noop", "message": "目前無待補齊答案之草稿", "scheduled_count": 0}

    try:
        batch_answer_job.start(
            config.db_path, ids, __import__('src.api.routes.admin', fromlist=['_local_llm_call'])._local_llm_call, __import__('src.api.routes.admin', fromlist=['_local_llm_ask_call'])._local_llm_ask_call, _GENERATION_LOCK
        )
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return {"status": "started", "scheduled_count": len(ids), "faq_ids": ids}


# =============================================================================
# Phase 21: 臨床決策推理樹 (PageIndex Trees) 審核與提煉端點
# =============================================================================

