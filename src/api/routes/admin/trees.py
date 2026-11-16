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

class DistillTreeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(..., min_length=2, max_length=100)
    text: str = Field(..., min_length=20, max_length=10000)
    clinic_id: str = Field(..., min_length=1, max_length=32)
    doc_id: Optional[str] = Field(None, max_length=64, pattern=r"^[\w\-]{1,64}$")
    category: Literal["special", "general"] = "special"


class UpdateTreeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = Field(None, max_length=100)
    pre_op: Optional[str] = Field(None, max_length=2000)
    pre_op_physician_notes: Optional[str] = Field(None, max_length=2000)
    procedure: Optional[str] = Field(None, max_length=2000)
    procedure_physician_notes: Optional[str] = Field(None, max_length=2000)
    post_op_short: Optional[str] = Field(None, max_length=2000)
    post_op_short_physician_notes: Optional[str] = Field(None, max_length=2000)
    maintenance: Optional[str] = Field(None, max_length=2000)
    maintenance_physician_notes: Optional[str] = Field(None, max_length=2000)
    summary_text: Optional[str] = Field(None, max_length=2000)
    category: Optional[Literal["special", "general"]] = None


@router.get("/trees", summary="查詢臨床決策推理樹列表")
def list_admin_trees(
    status: Optional[str] = Query("pending"),
    clinic_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_read_db),
):
    from src.pageindex.tree_review import list_trees

    status_filter = status if status and status != "all" else None
    trees, total = list_trees(
        conn,
        status=status_filter,
        limit=limit,
        offset=offset,
        clinic_id=clinic_id,
        category=category,
    )
    return {"trees": trees, "total": total, "limit": limit, "offset": offset}


@router.get("/trees/{tree_id}", summary="取得單一臨床決策推理樹詳情")
def get_admin_tree(
    tree_id: int,
    conn: sqlite3.Connection = Depends(get_read_db),
):
    from src.pageindex.tree_review import get_tree

    tree = get_tree(conn, tree_id)
    if not tree:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到指定的推理樹")
    return tree


@router.post("/trees/distill", summary="自文字提煉臨床決策推理樹草稿")
def distill_admin_tree(
    req: DistillTreeRequest,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """提煉僅能建立「新」草稿（pending）；doc_id 已存在一律 409，絕不覆寫既有醫師樹。
    與單題生成共用 _GENERATION_LOCK（行程內）與夜間批次檔案鎖（跨行程）。"""
    import re
    from src.batch import db_lock
    from src.pageindex.llm_client import LLMEmptyOutputError, LocalLLMUnavailableError
    from src.pageindex.prompt_template import TreeValidationError
    from src.pageindex.tree_distiller import MAX_SOURCE_CHARS, TreeConflictError, distill_tree_from_text

    doc_id = req.doc_id
    if not doc_id:
        slug = re.sub(r"[^\w\-]+", "-", req.title.lower()).strip("-")
        doc_id = slug or f"tree-{int(time.time())}"

    if conn.execute("SELECT 1 FROM page_index_trees WHERE doc_id = ?", (doc_id,)).fetchone():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="此識別碼已存在，請改用其他 doc_id（提煉不會覆寫既有樹）")

    if not _GENERATION_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="系統目前正在執行另一個 AI 作業，請稍候重試")
    lock_fd = db_lock.try_acquire(config.db_path)
    if lock_fd is None:
        _GENERATION_LOCK.release()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="夜間批次或其他作業正在使用資料庫，請稍後再試")
    try:
        tree = distill_tree_from_text(
            conn,
            title=req.title,
            text=req.text,
            clinic_id=req.clinic_id,
            doc_id=doc_id,
            llm_call=__import__('src.api.routes.admin', fromlist=['_local_llm_call'])._local_llm_call,
            category=req.category,
            source_type="web_upload",
        )
        return {
            "status": "ok",
            "message": "成功提煉臨床決策推理樹草稿（待醫師簽核）",
            "truncated": len(req.text) > MAX_SOURCE_CHARS,
            "tree": tree,
        }
    except TreeConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except TreeValidationError as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve)) from ve
    except LLMEmptyOutputError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="模型回覆為空（可能因思考長度超限），請稍後重試") from e
    except LocalLLMUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="本機 LLM 服務目前無法使用，請確認 llama-server 已啟動後再試",
        ) from e
    except Exception as e:
        # 不回傳例外內容（可能含 SQL 或模型原文片段）；詳情僅記入伺服器日誌
        import logging
        logging.getLogger(__name__).exception("tree distill failed: %s", type(e).__name__)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="提煉失敗，請稍後再試") from e
    finally:
        db_lock.release(lock_fd)
        _GENERATION_LOCK.release()



@router.put("/trees/{tree_id}", summary="編輯臨床決策推理樹或填寫醫師權威醫囑")
def update_admin_tree(
    tree_id: int,
    req: UpdateTreeRequest,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """每個文字欄位都經與提煉／簽核相同的合規檢驗（價格遮蔽、簡體、禁詞、政治立場）。
    受控來源已核准之樹被修改後，自動回到 pending 重新簽核。"""
    from src.pageindex.prompt_template import TreeValidationError
    from src.pageindex.tree_distiller import TREE_TEXT_FIELDS, validate_tree_segment
    from src.pageindex.tree_review import get_tree, update_tree

    existing = get_tree(conn, tree_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到指定的推理樹")

    update_data = req.model_dump(exclude_unset=True)
    text_fields = set(TREE_TEXT_FIELDS) | {
        "pre_op_physician_notes", "procedure_physician_notes",
        "post_op_short_physician_notes", "maintenance_physician_notes", "title",
    }
    try:
        for k, v in list(update_data.items()):
            if k in text_fields and v is not None:
                update_data[k] = validate_tree_segment(k, v)
    except TreeValidationError as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve)) from ve

    updated = update_tree(conn, tree_id, update_data)
    return {"status": "ok", "message": "推理樹已更新", "tree": updated}



def _auto_draft_visual_in_background(tree_id: int, db_path: str) -> None:
    """背景非同步為已核准推理樹生成 3 幕視覺動畫草稿（狀態恆為 pending）。"""
    try:
        from src.visual.autodraft import autodraft_from_tree
        with sqlite3.connect(db_path, timeout=30.0) as bg_conn:
            bg_conn.execute("PRAGMA foreign_keys = ON;")
            autodraft_from_tree(
                bg_conn,
                tree_id,
                llm_call=__import__('src.api.routes.admin', fromlist=['_visual_llm_call'])._visual_llm_call,
                db_path=db_path,
            )
    except Exception:
        # 背景任務 Fail-Safe：不中斷主 API 流程
        pass


@router.post("/trees/{tree_id}/approve", summary="醫師簽核核准臨床決策推理樹")
def approve_admin_tree(
    tree_id: int,
    background_tasks: BackgroundTasks,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """核准前重跑完整合規檢驗（與 FAQ 核准一致）：四段必須齊全且通過檢驗；醫囑欄位若有內容亦須通過。
    核准成功後自動於背景觸發生成對應的 3 幕視覺解說卡草稿 (visual_assets pending)。
    """
    from src.pageindex.prompt_template import TreeValidationError
    from src.pageindex.tree_distiller import TREE_TEXT_FIELDS, validate_tree_segment
    from src.pageindex.tree_review import approve_tree, get_tree

    tree = get_tree(conn, tree_id)
    if tree is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到指定的推理樹")
    if tree.get("review_status") == "approved":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="該推理樹已為核准狀態")

    try:
        for f in TREE_TEXT_FIELDS:
            if not str(tree.get(f) or "").strip():
                raise TreeValidationError(f"核准前段落 {f} 不可為空")
            validate_tree_segment(f, tree[f])
        for f in ("pre_op_physician_notes", "procedure_physician_notes",
                  "post_op_short_physician_notes", "maintenance_physician_notes"):
            if tree.get(f):
                validate_tree_segment(f, tree[f])
    except TreeValidationError as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"無法核准：{ve}") from ve

    ok = approve_tree(conn, tree_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="無法核准該推理樹（狀態已變更）")

    # 自動觸發背景生成對應的 3 幕視覺解說卡草稿
    background_tasks.add_task(__import__('src.api.routes.admin', fromlist=['_auto_draft_visual_in_background'])._auto_draft_visual_in_background, tree_id, config.db_path)

    return {
        "status": "ok",
        "message": f"推理樹 {tree_id} 已核准發布，系統正於背景為您自動提煉視覺解說卡草稿",
        "id": tree_id,
        "auto_visual_drafting": True,
    }



@router.post("/trees/{tree_id}/reject", summary="醫師駁回臨床決策推理樹")
def reject_admin_tree(
    tree_id: int,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    from src.pageindex.tree_review import reject_tree

    ok = reject_tree(conn, tree_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="無法駁回該推理樹（不存在或已為駁回狀態）")
    return {"status": "ok", "message": f"推理樹 {tree_id} 已駁回", "id": tree_id}


@router.delete("/trees/{tree_id}", summary="刪除待審或駁回之臨床決策推理樹草稿")
def delete_admin_tree(
    tree_id: int,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    from src.pageindex.tree_review import delete_tree

    ok = delete_tree(conn, tree_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="無法刪除該推理樹（僅限非核准狀態之草稿）")
    return {"status": "ok", "message": f"推理樹 {tree_id} 草稿已刪除", "id": tree_id}




