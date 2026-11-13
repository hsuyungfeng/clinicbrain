"""
src/api/routes/visual.py - 3D 臨床解剖與視覺資源 API 路由

提供：
1. GET /api/v1/visual/anatomy/{doc_id}：取得特定療程之 3D 解剖中繼資料與互動步驟設定
2. GET /api/v1/visual/anatomy/catalog：取得所有支援 3D 解剖定位之療程清單
3. 嚴格法規防線：強制經過 deep_mask_prices() 遞迴清洗、法定免責聲明、台灣標準繁體名詞
"""

from typing import Any, Dict
from fastapi import APIRouter, HTTPException, status
from src.visual.anatomy_catalog import (
    ANATOMY_CATALOG,
    DEFAULT_ANATOMY_METADATA,
    STATUTORY_ANATOMY_DISCLAIMER_ZH_TW,
    get_anatomy_metadata,
)
from src.api.routes.query import deep_mask_prices

router = APIRouter(prefix="/api/v1/visual", tags=["3D 臨床解剖與視覺服務"])


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
