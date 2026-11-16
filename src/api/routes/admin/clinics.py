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

@router.get("/clinics", summary="列出已建檔診所（上傳中心下拉選單用）")
def list_admin_clinics(conn: sqlite3.Connection = Depends(get_read_db)):
    """回傳 clinic_info 全部診所的代碼、名稱與類型。"""
    rows = conn.execute(
        "SELECT clinic_id, name, clinic_type FROM clinic_info ORDER BY clinic_id"
    ).fetchall()
    return {
        "clinics": [
            {"clinic_id": r["clinic_id"], "name": r["name"], "clinic_type": r["clinic_type"]}
            for r in rows
        ]
    }


@router.post("/clinics", status_code=status.HTTP_201_CREATED, summary="新增已建檔診所")
def create_admin_clinic(
    req: ClinicCreateRequest,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """新增一筆 clinic_info（僅新增，不覆寫既有診所）。代碼重複回 409。"""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="診所名稱不可為空白")
    try:
        conn.execute(
            "INSERT INTO clinic_info (clinic_id, name, phone, address, website, clinic_type, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (
                req.clinic_id,
                name,
                (req.phone or "").strip() or None,
                (req.address or "").strip() or None,
                (req.website or "").strip() or None,
                (req.clinic_type or "").strip() or None,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"診所代碼 {req.clinic_id} 已存在",
        ) from e
    return {"clinic_id": req.clinic_id, "name": name}


# ============================================================================
# Phase 31 P31-API: 視覺解說卡管理審核與自動生成端點
# ============================================================================


