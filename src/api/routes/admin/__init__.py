"""
診所 Web 管理與文件上傳 API 路由子套件（Phase 47 拆分）。
所有端點強制掛載 verify_admin_key 認證，對外維持 `from src.api.routes.admin import router` 介面。
"""

from fastapi import APIRouter, Depends

from src.api.dependencies import verify_admin_key
from .shared import (  # noqa: F401
    ALLOWED_EXTENSIONS,
    LLM_ASK_TIMEOUT_SECONDS,
    LLM_GENERATE_TIMEOUT_SECONDS,
    MAX_ANSWER_CHARS,
    MAX_FILE_SIZE,
    MAX_PARAGRAPHS,
    _GENERATION_LOCK,
    AskRequest,
    AutoFillAllRequest,
    AutodraftVisualRequest,
    BatchGenerateRequest,
    BatchReviewRequest,
    ClinicCreateRequest,
    GeneralDraftRequest,
    GenerateAnswerRequest,
    TemplateOverrideRequest,
    UpdateFaqRequest,
    UpdateVisualAssetRequest,
    VisualBatchReviewRequest,
    VisualSceneUpdateItem,
    _local_llm_ask_call,
    _local_llm_call,
    _visual_llm_call,
)
from .upload import (  # noqa: F401
    _NAME_VALIDATION_ERROR_MSG,
    _URL_FETCH_LOCK,
    _process_admin_upload_sync,
    _text_to_faq_drafts,
    fetch_clinic_page,
    get_url_fetch_deps,
    has_metadata_column,
    load_allowlist,
    router as upload_router,
    upload_admin_file,
    upload_admin_url,
    validate_display_name,
)
from .faq_review import router as faq_review_router  # noqa: F401
from .ask import _general_draft_llm_call, router as ask_router  # noqa: F401
from .trees import (  # noqa: F401
    DistillTreeRequest,
    UpdateTreeRequest,
    _auto_draft_visual_in_background,
    router as trees_router,
)
from .clinics import router as clinics_router  # noqa: F401
from .visuals import router as visuals_router  # noqa: F401
from .videos import _render_video_in_background, router as videos_router  # noqa: F401
from .refresh import router as refresh_router  # noqa: F401

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["診所管理端點 (Admin Only)"],
    dependencies=[Depends(verify_admin_key)],
)

router.include_router(upload_router)
router.include_router(faq_review_router)
router.include_router(ask_router)
router.include_router(trees_router)
router.include_router(clinics_router)
router.include_router(visuals_router)
router.include_router(videos_router)
router.include_router(refresh_router)
