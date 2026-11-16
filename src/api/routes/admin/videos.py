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
    TOPIC_KEY_RE,
    _local_llm_ask_call, _local_llm_call, _visual_llm_call,
)

router = APIRouter()

def _render_video_in_background(topic_key: str, aspect: str, force: bool, db_path: str) -> None:
    """背景非同步執行影片逐格錄製與 H.264 合成。"""
    import sqlite3
    from src.visual.video_queue import render_asset_to_video

    conn = sqlite3.connect(db_path)
    try:
        aspects = ["landscape", "portrait"] if aspect == "both" else [aspect]
        for asp in aspects:
            render_asset_to_video(conn, topic_key=topic_key, aspect=asp, force=force)
    except Exception as e:
        logger.error(f"背景渲染影片失敗 {topic_key} ({aspect}): {e}")
    finally:
        conn.close()


@router.get("/visuals/videos/{topic_key}", summary="查詢指定主題的 MP4 影片狀態與資訊")
def get_admin_visual_video_status(
    topic_key: str,
    conn: sqlite3.Connection = Depends(get_read_db),
):
    """查詢該主題 16:9 橫屏與 9:16 豎屏 MP4 影片是否已生成、檔案大小與時長。"""
    if not TOPIC_KEY_RE.match(topic_key) or ".." in topic_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="無效的主題代碼格式")

    from src.visual.video_queue import DEFAULT_VIDEO_DIR

    cursor = conn.cursor()
    cursor.execute("SELECT title, review_status FROM visual_assets WHERE topic_key = ?", (topic_key,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到視覺資產：{topic_key}")

    title, review_status = row

    res = {
        "topic_key": topic_key,
        "title": title,
        "review_status": review_status,
        "landscape": {"available": False},
        "portrait": {"available": False},
    }

    for asp in ("landscape", "portrait"):
        mp4_path = DEFAULT_VIDEO_DIR / f"{topic_key}_{asp}.mp4"
        meta_path = DEFAULT_VIDEO_DIR / f"{topic_key}_{asp}.meta.json"
        if mp4_path.exists() and mp4_path.stat().st_size > 0:
            meta = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            res[asp] = {
                "available": True,
                "size_bytes": mp4_path.stat().st_size,
                "duration_sec": meta.get("duration_sec"),
                "fps": meta.get("fps", 24),
                "download_url": f"/api/v1/admin/visuals/videos/{topic_key}/download?aspect={asp}",
            }

    return res


@router.post("/visuals/videos/{topic_key}/render", summary="手動觸發指定主題之影片背景渲染")
def trigger_admin_visual_video_render(
    topic_key: str,
    background_tasks: BackgroundTasks,
    aspect: str = Query("landscape", pattern="^(landscape|portrait|both)$", description="規格：landscape, portrait, 或 both"),
    force: bool = Query(False, description="是否強制重新渲染 (略過快取)"),
    conn: sqlite3.Connection = Depends(get_read_db),
):
    """將指定視覺解說動畫送入背景渲染佇列。"""
    if not TOPIC_KEY_RE.match(topic_key) or ".." in topic_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="無效的主題代碼格式")

    cursor = conn.cursor()
    cursor.execute("SELECT review_status FROM visual_assets WHERE topic_key = ?", (topic_key,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到視覺資產：{topic_key}")

    review_status = row[0]
    if review_status != "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"該資產審核狀態為 '{review_status}'，僅已核准 (approved) 的資產可渲染為影片",
        )

    background_tasks.add_task(__import__('src.api.routes.admin', fromlist=['_render_video_in_background'])._render_video_in_background, topic_key, aspect, force, config.db_path)

    return {
        "status": "queued",
        "topic_key": topic_key,
        "aspect": aspect,
        "force": force,
        "message": "影片渲染任務已加入背景佇列",
    }


@router.get("/visuals/videos/{topic_key}/download", summary="下載或在線播放已渲染之 MP4 影片")
def download_admin_visual_video(
    topic_key: str,
    aspect: str = Query("landscape", pattern="^(landscape|portrait)$", description="規格：landscape 或 portrait"),
):
    """以串流方式回傳 H.264 MP4 影片檔案，支援在線播放或下載。"""
    if not TOPIC_KEY_RE.match(topic_key) or ".." in topic_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="無效的主題代碼格式")

    from fastapi.responses import FileResponse
    from src.visual.video_queue import DEFAULT_VIDEO_DIR

    mp4_path = DEFAULT_VIDEO_DIR / f"{topic_key}_{aspect}.mp4"
    if not mp4_path.exists() or mp4_path.stat().st_size == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"主題 '{topic_key}' 之 {aspect} 影片尚未生成，請先觸發渲染",
        )

    return FileResponse(
        path=str(mp4_path),
        media_type="video/mp4",
        filename=f"{topic_key}_{aspect}.mp4",
    )

