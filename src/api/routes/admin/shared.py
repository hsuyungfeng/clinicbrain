"""
診所 Web 管理與文件上傳 API 路由模組。
Phase 18 Plan 18-01: 提供文件上傳解析、待審衛教草稿檢索與簽核動作 API。
所有端點強制掛載 verify_admin_key 認證，唯讀查詢使用 PRAGMA query_only = ON，寫入操作走唯一權威路徑。
"""

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

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from src.ingestion.convert_chinese import to_traditional
from src.ingestion.extract_text import extract_docx_text, extract_xlsx_text
from src.ingestion.generate_faq import validate_single_faq
from src.ingestion.url_guard import UnsafeUrlError, validate_public_url
from src.pageindex import batch_answer_job
from src.pageindex.rag_ask import ask_with_data
from src.pageindex.answer_generator import GenerationError, generate_answer_for_faq, is_answer_thin
from src.pageindex.faq_review import (
    MAX_BATCH_SIZE,
    batch_review_faqs,
    get_faq,
    has_metadata_column,
    has_review_status,
    set_review_status,
    update_faq_content,
)
from src.pageindex.faq_writer import upsert_faqs
from src.pageindex.web_source_adapter import (
    UrlFetchDeps,
    UrlFetchError,
    build_service_text,
    fetch_clinic_page,
    get_shared_robots,
    get_shared_throttle,
    optional_missing_fields,
)
from src.scraper.fetch import build_user_agent
from src.scraper.policy import PolicyError, load_allowlist
from src.soap.deid import deidentify_text
from src.api.config import config
from src.api.dependencies import get_read_db, get_write_db, verify_admin_key
from src.api.routes.query import deep_mask_prices

MAX_FILE_SIZE = 15 * 1024 * 1024  # 15MB
ALLOWED_EXTENSIONS = {".docx", ".xlsx", ".pdf"}
MAX_PARAGRAPHS = 200  # 單檔最多轉出的草稿段落數（過長請拆檔，保護醫師審核負擔）
MAX_ANSWER_CHARS = 3000
_ZIP_MAGIC = b"PK\x03\x04"
_PDF_MAGIC = b"%PDF-"
_Q_PREFIXES = ("問：", "問:", "Q:", "Q：", "q:", "q：")

from src.pageindex.llm_lock import GENERATION_LOCK
from src.pageindex.llm_client import FAITHFUL_SAMPLING

# AI 生成：單一本機 llama-server 一次只服務一題，避免請求堆疊拖垮推論
_GENERATION_LOCK = GENERATION_LOCK
LLM_GENERATE_TIMEOUT_SECONDS = 480


def _local_llm_call(prompt: str) -> str:
    """呼叫本機 llama-server（測試時以 monkeypatch 替換）。"""
    from src.pageindex.llm_client import local_llm_call

    return local_llm_call(prompt, timeout=LLM_GENERATE_TIMEOUT_SECONDS)


# 忠實引用資料的任務（RAG 提問）：單次請求關閉重複懲罰並降低溫度，避免模型為了「不重複」而改字、掉字
LLM_ASK_TIMEOUT_SECONDS = 480
GENERAL_DRAFT_TIMEOUT_SECONDS = 900  # 一般草稿提示長、思考可能超過 480 秒（實測逾時）


def _local_llm_ask_call(prompt: str) -> str:
    """向本機 llama-server 提問（忠實引用取樣設定；測試時以 monkeypatch 替換）。"""
    from src.pageindex.llm_client import local_llm_call

    return local_llm_call(prompt, timeout=LLM_ASK_TIMEOUT_SECONDS, sampling=FAITHFUL_SAMPLING)


def _visual_llm_call(prompt: str) -> str:
    """呼叫本地 LLM 生成動畫草稿（使用 VISUAL_SAMPLING 並擴充 token 上限至 1800；測試時可由 monkeypatch 替換）。"""
    from src.pageindex.llm_client import VISUAL_SAMPLING, local_llm_call

    sampling = dict(VISUAL_SAMPLING)
    sampling["max_tokens"] = max(int(sampling.get("max_tokens", 900)), 1800)
    return local_llm_call(prompt, timeout=240, sampling=sampling)


class BatchReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "reject"]
    faq_ids: list[StrictInt] = Field(..., min_length=1, max_length=MAX_BATCH_SIZE)


class ClinicCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clinic_id: str = Field(..., pattern=r"^\d{10}$")  # 台灣健保特約醫事機構代碼（10 碼數字）
    name: str = Field(..., min_length=1, max_length=60)
    clinic_type: Optional[str] = Field(None, max_length=30)
    phone: Optional[str] = Field(None, max_length=30)
    address: Optional[str] = Field(None, max_length=120)
    website: Optional[str] = Field(None, max_length=200, pattern=r"^https://\S+$")


class UpdateFaqRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: Optional[str] = Field(None, max_length=200)
    answer: Optional[str] = Field(None, max_length=3000)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(..., min_length=1, max_length=300)
    clinic_id: Optional[str] = Field(None, max_length=40)


class GeneralDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(..., min_length=1, max_length=300)


class BatchGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    faq_ids: list[StrictInt] = Field(..., min_length=1, max_length=batch_answer_job.MAX_JOB_IDS)
    overwrite: bool = False


class GenerateAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overwrite: bool = False


class AutoFillAllRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clinic_id: Optional[str] = None


class VisualSceneUpdateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = None
    caption: Optional[str] = None
    labels: Optional[list[dict[str, str]]] = None


class UpdateVisualAssetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = None
    keywords: Optional[list[str]] = None
    scenes: Optional[list[VisualSceneUpdateItem]] = None


class TemplateOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: Optional[str] = None


class AutodraftVisualRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tree_id: StrictInt


class VisualBatchReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "reject"]
    asset_ids: list[StrictInt] = Field(..., min_length=1, max_length=200)



TOPIC_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
