"""
src/api/routes/visual.py - 3D 臨床解剖與視覺資源 API 路由

提供：
1. GET /api/v1/visual/anatomy/{doc_id}：取得特定療程之 3D 解剖中繼資料與互動步驟設定
2. GET /api/v1/visual/anatomy/catalog：取得所有支援 3D 解剖定位之療程清單
3. 嚴格法規防線：強制經過 deep_mask_prices() 遞迴清洗、法定免責聲明、台灣標準繁體名詞
"""

import re
import sqlite3
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from src.api.dependencies import get_read_db
from src.visual.anatomy_catalog import (
    ANATOMY_CATALOG,
    DEFAULT_ANATOMY_METADATA,
    STATUTORY_ANATOMY_DISCLAIMER_ZH_TW,
    get_anatomy_metadata,
)
from src.visual.match import get_public_video_info, search_public_visuals
from src.visual.video_queue import DEFAULT_VIDEO_DIR
from src.api.routes.query import deep_mask_prices

router = APIRouter(prefix="/api/v1/visual", tags=["3D 臨床解剖與視覺服務"])
_TOPIC_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@router.get(
    "/anatomy/catalog",
    summary="取得所有支援 3D 解剖定位之療程清單",
    response_model=Dict[str, Any],
)
def get_anatomy_catalog_list():
    """回傳所有已註冊 3D 解剖模型與專科映射之療程清單。"""
    items = []
    for doc_id, meta in ANATOMY_CATALOG.items():
        items.append({
            "doc_id": doc_id,
            "anatomy_target": meta.get("anatomy_target"),
            "specialty_zh": meta.get("specialty_zh"),
            "specialty": meta.get("specialty"),
            "model_src": meta.get("model_src"),
            "steps_count": len(meta.get("interactive_steps", [])),
        })

    response = {
        "total": len(items),
        "catalog": items,
        "disclaimer": STATUTORY_ANATOMY_DISCLAIMER_ZH_TW,
    }
    return deep_mask_prices(response)


@router.get(
    "/anatomy/{doc_id}",
    summary="取得特定療程之 3D 解剖中繼資料與互動步驟",
    response_model=Dict[str, Any],
)
def get_anatomy_by_doc_id(doc_id: str):
    """
    根據 doc_id 回傳 3D 解剖中繼資料，含：
    - 相機視角設定 (camera)
    - 臨床步驟聯動設定 (interactive_steps)
    - 嚴格價格遮蔽與常駐法定免責聲明
    """
    if not doc_id or not doc_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="療程代碼 doc_id 不得為空",
        )

    metadata = get_anatomy_metadata(doc_id.strip())
    return metadata


@router.get(
    "/search",
    summary="公開搜尋已核准視覺解說卡與 MP4 衛教影片",
    response_model=Dict[str, Any],
)
def search_public_visual_assets(
    query: str = Query(..., min_length=1, max_length=200, description="搜尋關鍵字或問句"),
    clinic_id: Optional[str] = Query(None, description="選填診所代碼（一併搜尋該診所專屬與一般醫學共用）"),
    limit: int = Query(5, ge=1, le=20),
    conn: sqlite3.Connection = Depends(get_read_db),
):
    """搜尋所有已核准（含一般醫學共用與指定診所）之視覺解說卡及對應 MP4 下載連結。"""
    clean_cid = clinic_id.strip() if clinic_id and clinic_id.strip() else None
    items = search_public_visuals(conn, query, clinic_id=clean_cid, limit=limit)
    return deep_mask_prices({"total": len(items), "items": items})


def _get_approved_visual_title(conn: sqlite3.Connection, topic_key: str) -> str:
    """確認 topic_key 存在於已核准之視覺資產中（Fail-Closed）。"""
    if not _TOPIC_KEY_RE.match(topic_key) or ".." in topic_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="無效的主題代碼格式")
    try:
        row = conn.execute(
            "SELECT title FROM visual_assets WHERE topic_key = ? AND review_status = 'approved' "
            "ORDER BY CASE WHEN clinic_id IS NULL THEN 0 ELSE 1 END LIMIT 1",
            (topic_key,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到已核准的視覺資產") from exc
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到已核准的視覺資產：{topic_key}")
    return str(row[0] or "")


@router.get(
    "/videos/{topic_key}",
    summary="查詢指定主題之公開 MP4 影片資訊",
    response_model=Dict[str, Any],
)
def get_public_visual_video_status(
    topic_key: str,
    conn: sqlite3.Connection = Depends(get_read_db),
):
    """查詢已核准主題的 16:9 橫屏與 9:16 豎屏 MP4 影片可用性與下載連結。"""
    title = _get_approved_visual_title(conn, topic_key)
    info = get_public_video_info(topic_key) or {
        "topic_key": topic_key,
        "landscape": {"available": False},
        "portrait": {"available": False},
    }
    return deep_mask_prices({"title": title, **info})


@router.get(
    "/videos/{topic_key}/download",
    summary="公開播放或下載已核准之 MP4 衛教影片",
)
def download_public_visual_video(
    topic_key: str,
    aspect: str = Query("landscape", pattern="^(landscape|portrait)$", description="規格：landscape 或 portrait"),
    conn: sqlite3.Connection = Depends(get_read_db),
):
    """以串流方式提供已核准視覺解說卡之 H.264 MP4 影片供病人播放或下載。"""
    _get_approved_visual_title(conn, topic_key)
    mp4_path = DEFAULT_VIDEO_DIR / f"{topic_key}_{aspect}.mp4"
    if not mp4_path.exists() or mp4_path.stat().st_size == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"主題 '{topic_key}' 之 {aspect} 影片尚未生成",
        )
    return FileResponse(
        path=str(mp4_path),
        media_type="video/mp4",
        filename=f"{topic_key}_{aspect}.mp4",
    )
