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

@router.get("/visuals", summary="查詢視覺解說卡列表與總數")
def list_admin_visuals(
    status: Literal["pending", "approved", "rejected", "all"] = "pending",
    clinic_id: Optional[str] = Query(None, description="診所代碼篩選"),
    scope: Literal["all", "clinic", "general"] = "all",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_read_db),
):
    from src.visual.review import list_visual_assets

    items, total = list_visual_assets(
        conn,
        status=status,
        clinic_id=clinic_id,
        scope=scope,
        limit=limit,
        offset=offset,
    )
    return {
        "visuals": items,
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/visuals/{asset_id}", summary="查詢單一視覺解說卡詳情")
def get_admin_visual(
    asset_id: int,
    conn: sqlite3.Connection = Depends(get_read_db),
):
    from src.visual.review import get_visual_asset_by_id

    asset = get_visual_asset_by_id(conn, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到指定的視覺資產")
    return {"asset": asset, **asset}


@router.patch("/visuals/{asset_id}", summary="修訂視覺解說卡內容")
def patch_admin_visual(
    asset_id: int,
    req: UpdateVisualAssetRequest,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    from src.visual.review import update_visual_asset_by_id
    from src.visual.writer import has_visual_assets_table

    if not has_visual_assets_table(conn):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="資料庫尚未建立 visual_assets 資料表",
        )

    scenes_data = (
        [s.model_dump(exclude_unset=True) for s in req.scenes]
        if req.scenes is not None
        else None
    )

    try:
        updated = update_visual_asset_by_id(
            conn,
            asset_id,
            title=req.title,
            keywords=req.keywords,
            scenes=scenes_data,
        )
    except ValueError as e:
        code = str(e)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"動畫內容驗證未通過: {code}",
        ) from e

    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到指定的視覺資產")

    return {"status": "ok", "asset": updated, **updated}


@router.get("/visual-blueprints", summary="列出可指定為草稿場景 1 模板的已註冊模板")
def list_visual_blueprints():
    from src.visual.blueprints import BLUEPRINTS

    return {"blueprints": sorted(BLUEPRINTS.keys())}


@router.put("/visuals/{asset_id}/template-override", summary="設定草稿的醫師指定場景 1 模板")
def put_visual_template_override(
    asset_id: int,
    req: TemplateOverrideRequest,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    from src.visual.review import set_template_override
    from src.visual.writer import has_visual_assets_table

    if not has_visual_assets_table(conn):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="資料庫尚未建立 visual_assets 資料表")
    try:
        res = set_template_override(conn, asset_id, req.template)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"模板不合法: {e}") from e
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
    if res["status"] == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到指定的視覺資產")
    return res


@router.post("/visuals/{asset_id}/approve", summary="醫師簽核核准視覺解說卡")
def approve_admin_visual(
    asset_id: int,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    from src.visual.review import adopt_v2_candidate, set_review_status
    from src.visual.writer import has_visual_assets_table

    if not has_visual_assets_table(conn):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="資料庫尚未建立 visual_assets 資料表",
        )

    # 若核准目標為 -v2 平行候選列，一鍵晉升取代 V1 並清理 -v2 暫存列
    row = conn.execute("SELECT topic_key FROM visual_assets WHERE id = ?", (asset_id,)).fetchone()
    if row is not None and str(row[0] or "").endswith("-v2"):
        res = adopt_v2_candidate(conn, str(row[0]), asset_id=asset_id)
    else:
        res = set_review_status(conn, "", "approved", asset_id=asset_id)

    if res.get("status") == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到指定的視覺資產")
    if res.get("status") == "validation_failed":
        code = res.get("code")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"動畫內容驗證未通過: {code}",
        )

    return {
        "status": "ok",
        "id": asset_id,
        "review_status": "approved",
        "promoted_v2_to": res.get("base_topic_key"),
    }


@router.post("/visuals/{asset_id}/reject", summary="醫師駁回視覺解說卡")
def reject_admin_visual(
    asset_id: int,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    from src.visual.review import set_review_status
    from src.visual.writer import has_visual_assets_table

    if not has_visual_assets_table(conn):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="資料庫尚未建立 visual_assets 資料表",
        )

    res = set_review_status(conn, "", "rejected", asset_id=asset_id)
    if res.get("status") == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到指定的視覺資產")

    return {"status": "ok", "id": asset_id, "review_status": "rejected"}


@router.post("/visuals/batch", summary="批量核准／駁回視覺解說卡（單一交易）")
def batch_admin_visuals_review(
    req: VisualBatchReviewRequest,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """單次最多 200 筆；在單一交易中逐筆核准或駁回視覺動畫資產。"""
    from src.visual.review import adopt_v2_candidate, set_review_status
    from src.visual.writer import has_visual_assets_table

    if not has_visual_assets_table(conn):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="資料庫尚未建立 visual_assets 資料表",
        )

    processed_ids = []
    failed_reasons = {}

    for asset_id in req.asset_ids:
        try:
            if req.action == "approve":
                row = conn.execute("SELECT topic_key FROM visual_assets WHERE id = ?", (asset_id,)).fetchone()
                if row is not None and str(row[0] or "").endswith("-v2"):
                    res = adopt_v2_candidate(conn, str(row[0]), asset_id=asset_id, commit=False)
                else:
                    res = set_review_status(conn, "", "approved", asset_id=asset_id, commit=False)
            else:
                res = set_review_status(conn, "", "rejected", asset_id=asset_id, commit=False)

            if res.get("status") == "ok":
                processed_ids.append(asset_id)
            else:
                failed_reasons[str(asset_id)] = res.get("code") or res.get("status") or "failed"
        except Exception as e:
            failed_reasons[str(asset_id)] = str(e)

    conn.commit()

    # 若有成功核准，同步更新 nhi_catalog_1_400 中的 visual_available 標記
    if req.action == "approve" and processed_ids:
        try:
            conn.execute(
                "UPDATE nhi_catalog_1_400 SET visual_available = 1 WHERE topic_key IN (SELECT topic_key FROM visual_assets WHERE review_status = 'approved')"
            )
            conn.commit()
        except Exception:
            pass

    return {
        "status": "ok",
        "action": req.action,
        "success_count": len(processed_ids),
        "failed_count": len(failed_reasons),
        "processed_ids": processed_ids,
        "failed_reasons": failed_reasons,
    }


@router.post("/visuals/autodraft", summary="自已核准臨床推理樹自動生成視覺解說卡草稿")
def autodraft_admin_visual(
    req: AutodraftVisualRequest,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    from src.visual.autodraft import autodraft_from_tree
    from src.visual.review import get_visual_asset_by_id

    res = autodraft_from_tree(
        conn,
        req.tree_id,
        llm_call=__import__('src.api.routes.admin', fromlist=['_visual_llm_call'])._visual_llm_call,
        db_path=config.db_path,
    )
    st = res.get("status")
    code = res.get("code")

    if st == "not_found" or code == "tree_not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到指定的推理樹")
    if code == "tree_not_approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="該推理樹尚未核准，無法生成動畫草稿",
        )
    if st == "busy" or code == "busy":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="系統正忙或夜間批次執行中，請稍後再試",
        )
    if code == "llm_unavailable":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="本地 LLM 服務暫不可用",
        )
    if st != "ok":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"動畫草稿生成失敗: {code}",
        )

    # 查回完整格式之資產
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM visual_assets WHERE clinic_id IS ? AND topic_key = ?",
        (res.get("clinic_id"), res.get("topic_key")),
    )
    r = cur.fetchone()
    if r:
        asset_id = r[0]
        full_asset = get_visual_asset_by_id(conn, asset_id)
        if full_asset:
            return {"status": "ok", "asset": full_asset, **full_asset}

    return {"status": "ok", "asset": res, **res}


# =============================================================================
# Phase 43: 自動化動態解說動畫影片佇列 API
# =============================================================================



