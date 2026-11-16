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
    ALLOWED_EXTENSIONS, GENERAL_DRAFT_TIMEOUT_SECONDS, LLM_ASK_TIMEOUT_SECONDS, LLM_GENERATE_TIMEOUT_SECONDS,
    MAX_ANSWER_CHARS, MAX_FILE_SIZE, MAX_PARAGRAPHS, _GENERATION_LOCK,
    _PDF_MAGIC, _Q_PREFIXES, _ZIP_MAGIC,
    AskRequest, AutoFillAllRequest, AutodraftVisualRequest, BatchGenerateRequest,
    BatchReviewRequest, ClinicCreateRequest, GeneralDraftRequest, GenerateAnswerRequest,
    TemplateOverrideRequest, UpdateFaqRequest, UpdateVisualAssetRequest,
    VisualBatchReviewRequest, VisualSceneUpdateItem,
    _local_llm_ask_call, _local_llm_call, _visual_llm_call,
)

router = APIRouter()

def _general_draft_llm_call(prompt: str) -> str:
    """一般草稿專用：提示較長，思考可能耗盡預設 6144 token，故放寬上限（呼叫端仍有空白重試）。"""
    from src.pageindex.llm_client import local_llm_call

    return local_llm_call(prompt, timeout=GENERAL_DRAFT_TIMEOUT_SECONDS, sampling={"max_tokens": 12288})


@router.post("/ask/general-draft", summary="無診所資料時改由本機 LLM 生成一般醫學草稿（待醫師審核）")
def admin_ask_general_draft(
    req: GeneralDraftRequest,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """寫入：將一般醫學草稿存為 general / llm_generated / pending，醫師核准前不對外可見。

    驗證未通過時不寫入任何資料（422）；與其他本機模型作業共用 _GENERATION_LOCK。
    """
    from src.pageindex.general_fallback import GeneralDraftError, generate_general_draft
    from src.pageindex.llm_client import LLMEmptyOutputError, LocalLLMUnavailableError

    if not _GENERATION_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="本機模型忙碌中，請稍後再試")
    try:
        try:
            return {"status": "ok", **generate_general_draft(conn, req.question, _general_draft_llm_call)}
        except GeneralDraftError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=e.reason) from e
        except LLMEmptyOutputError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="模型回覆為空（可能因思考長度超限），請稍後重試") from e
        except LocalLLMUnavailableError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="本機 LLM 服務目前無法使用，請確認 llama-server 已啟動後再試",
            ) from e
        except RuntimeError as e:
            # 資料庫尚未完成審核欄位遷移：Fail-Closed，拒絕寫入（不回顯內部訊息）
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="資料庫尚未完成審核欄位遷移，暫無法寫入一般草稿",
            ) from e
    finally:
        _GENERATION_LOCK.release()


@router.post("/ask", summary="向本機 LLM 提問（僅依系統內已核准資料作答，檢視回答與資料來源）")
def admin_ask_llm(
    req: AskRequest,
    conn: sqlite3.Connection = Depends(get_read_db),
):
    """唯讀：不寫入任何資料。紅旗問句與無資料問句不呼叫 LLM；其餘走本機 llama-server。"""
    from src.pageindex.llm_client import LLMEmptyOutputError, LocalLLMUnavailableError

    clinic_id = (req.clinic_id or "").strip()
    if clinic_id:
        if conn.execute("SELECT 1 FROM clinic_info WHERE clinic_id = ?", (clinic_id,)).fetchone() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到指定的診所代碼")
    else:
        clinic_id = None
    if not _GENERATION_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="本機模型忙碌中，請稍後再試")
    try:
        try:
            return {"status": "ok", "question": req.question.strip(),
                    **ask_with_data(conn, req.question, clinic_id, __import__('src.api.routes.admin', fromlist=['_local_llm_ask_call'])._local_llm_ask_call)}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
        except LLMEmptyOutputError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="模型回覆為空（可能因思考長度超限），請稍後重試") from e
        except LocalLLMUnavailableError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="本機 LLM 服務目前無法使用，請確認 llama-server 已啟動後再試",
            ) from e
    finally:
        _GENERATION_LOCK.release()


