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

_ALLOWED_NAME_PATTERN = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9 \-_·（）\(\)\[\]]+$")
_NAME_VALIDATION_ERROR_MSG = "名稱格式不符：僅允許中英文、數字與基本符號，長度 1–80 字，且不得含個資或金額"


def validate_display_name(raw: Optional[str]) -> Optional[str]:
    """驗證與清理使用者自訂名稱（D-01、D-02）。

    - raw 為 None 或 strip 後為空字串時回傳 None。
    - 先以 NFKC 正規化再去除頭尾空白。
    - 長度限制 1–80 字元。
    - 允許字元：中英文（\u4e00-\u9fff）、英數、空白、以及 -_·（）()[]。
    - 不得包含個資或電話（deidentify_text 不變）。
    - 不得包含金額或價格（deep_mask_prices 不變）。
    - 違規時統一拋出 HTTP 400，錯誤訊息為固定字串，絕不包含輸入值。
    """
    if raw is None:
        return None
    trimmed = raw.strip()
    if not trimmed:
        return None

    normalized = unicodedata.normalize("NFKC", trimmed).strip()
    if not normalized:
        return None

    if len(normalized) > 80:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_NAME_VALIDATION_ERROR_MSG,
        )

    if not _ALLOWED_NAME_PATTERN.match(normalized):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_NAME_VALIDATION_ERROR_MSG,
        )

    if deidentify_text(normalized) != normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_NAME_VALIDATION_ERROR_MSG,
        )

    masked = deep_mask_prices(normalized)
    if isinstance(masked, dict):
        masked = str(masked)
    if masked != normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_NAME_VALIDATION_ERROR_MSG,
        )

    return normalized


def _text_to_faq_drafts(
    raw_text: str,
    topic: str,
    clinic_id: Optional[str],
) -> tuple[list[dict[str, Any]], int, int]:
    """將純文字/Markdown/萃取內文清洗、切分並轉換為 FAQ 草稿清單（D-11）。
    若 clinic_id 為空字串或 None，則 category 設為 'general'（一般醫學共用）。
    回傳: (faqs_to_insert, extracted_paragraphs_count, rejected_paragraphs)
    """
    # 4. 簡轉繁、去識別化與價格數字遮蔽
    trad_text = to_traditional(raw_text)
    deid_text = deidentify_text(trad_text)
    clean_text = deep_mask_prices(deid_text)
    if isinstance(clean_text, dict):
        clean_text = str(clean_text)

    # 5. 段落切分與 Q&A 轉換
    paragraphs = [p.strip() for p in clean_text.split("\n\n") if p.strip()]
    if len(paragraphs) > MAX_PARAGRAPHS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件段落過多（{len(paragraphs)} > {MAX_PARAGRAPHS}），請拆分為較小的檔案後再上傳",
        )
    faqs_to_insert = []
    rejected_paragraphs = 0

    clean_cid = str(clinic_id).strip() if clinic_id and str(clinic_id).strip() else None
    cat = "general" if not clean_cid else "special"

    for idx, p in enumerate(paragraphs):
        lines = p.splitlines()
        first = lines[0].strip() if lines else ""
        if len(lines) >= 2 and (first.startswith(_Q_PREFIXES) or first.endswith(("？", "?"))):
            q_part = first
            for pre in _Q_PREFIXES:
                if q_part.startswith(pre):
                    q_part = q_part[len(pre):]
                    break
            q_part = q_part.strip()
            a_part = "\n".join(lines[1:]).strip()
            for pre in ("答：", "答:", "A:", "A：", "a:", "a："):
                if a_part.startswith(pre):
                    a_part = a_part[len(pre):].strip()
                    break
        else:
            q_prefix = "【一般醫學】" if not clean_cid else "【診所文件】"
            q_part = f"{q_prefix}{topic} - 指示 {idx + 1}"
            a_part = p

        a_part = a_part[:MAX_ANSWER_CHARS]
        if not q_part or not a_part:
            rejected_paragraphs += 1
            continue

        # 四層驗證（簡體字／政治立場／保證療效／價格洩漏）：違規段落單筆剔除，不影響其他段落
        ok, _reason = validate_single_faq({"question": q_part, "answer": a_part})
        if not ok:
            rejected_paragraphs += 1
            continue

        faqs_to_insert.append({
            "question": q_part,
            "answer": a_part,
            "category": cat,
            "clinic_id": clean_cid,
            "topic_key": f"doc-{topic}",
        })

    return faqs_to_insert, len(paragraphs), rejected_paragraphs


def _process_admin_upload_sync(
    tmp_path: Path,
    filename: str,
    ext: str,
    clean_clinic_id: Optional[str],
    name: Optional[str],
    preview_only: bool,
    conn: sqlite3.Connection,
) -> dict:
    """在 threadpool 中同步處理檔案解析、文本萃取與資料庫寫入，不阻塞 FastAPI 事件迴圈。"""
    raw_text = ""
    # 優先嘗試 markitdown 轉 Markdown
    try:
        from src.ingestion.markdown_convert import convert_to_markdown
        raw_text = convert_to_markdown(tmp_path)
    except Exception:
        raw_text = ""

    # Fallback 萃取
    if not raw_text:
        if ext == ".docx":
            try:
                raw_text = extract_docx_text(tmp_path)
            except Exception as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"無法解析 {filename}") from e
        elif ext == ".xlsx":
            try:
                data_dict = extract_xlsx_text(tmp_path)
            except Exception as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"無法解析 {filename}") from e
            lines = []
            for sheet, rows in data_dict.items():
                lines.append(f"【工作表: {sheet}】")
                for row in rows:
                    row_str = " ; ".join(f"{k}: {v}" for k, v in row.items())
                    lines.append(row_str)
            raw_text = "\n".join(lines)
        elif ext == ".pdf":
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(str(tmp_path))
                pdf_lines = []
                for page in doc:
                    pdf_lines.append(page.get_text())
                raw_text = "\n".join(pdf_lines)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"PDF 內文萃取失敗 ({filename}): 無法讀取文字層",
                ) from e

    if not raw_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"未能在檔案 {filename} 中萃取到有效文字內容",
        )

    name_clean = validate_display_name(name)
    doc_topic = name_clean if name_clean else Path(filename).stem[:80]

    faqs_to_insert, extracted_paragraphs_count, rejected_paragraphs = __import__('src.api.routes.admin', fromlist=['_text_to_faq_drafts'])._text_to_faq_drafts(
        raw_text=raw_text,
        topic=doc_topic,
        clinic_id=clean_clinic_id,
    )

    if preview_only:
        return {
            "status": "ok",
            "preview_only": True,
            "filename": filename,
            "clinic_id": clean_clinic_id,
            "extracted_paragraphs_count": extracted_paragraphs_count,
            "rejected_paragraphs": rejected_paragraphs,
            "faqs_preview": faqs_to_insert,
        }

    # 6. 寫入 faq_cache：web_upload 為審核閘門來源，唯一權威寫入路徑直接以 pending 寫入
    try:
        inserted, updated, unchanged = upsert_faqs(conn, faqs_to_insert, source_type="web_upload")
    except RuntimeError as e:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="資料庫尚未完成審核欄位遷移，暫無法接收上傳",
        ) from e

    return {
        "status": "ok",
        "preview_only": False,
        "filename": filename,
        "clinic_id": clean_clinic_id,
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "total_faqs": len(faqs_to_insert),
        "rejected_paragraphs": rejected_paragraphs,
        "review_status": "pending",
    }


@router.post("/upload", summary="診所衛教與項目文件上傳解析")
async def upload_admin_file(
    file: UploadFile = File(...),
    clinic_id: Optional[str] = Form(None),
    preview_only: bool = Form(False),
    name: Optional[str] = Form(None),
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """
    接收診所人員上傳之衛教或項目文件（.docx, .xlsx, .pdf），進行安全防禦、內文解析、去識別化與價格遮蔽。
    若 clinic_id 為空，則自動歸類為一般醫學共用文件（category='general'）。
    若 preview_only=False，將合格問答段落寫入 faq_cache（source_type='web_upload'，review_status 恆為 'pending'）。
    """
    clean_clinic_id = (clinic_id or "").strip()
    if clean_clinic_id:
        if conn.execute("SELECT 1 FROM clinic_info WHERE clinic_id = ?", (clean_clinic_id,)).fetchone() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="找不到指定的診所代碼",
            )
    else:
        clean_clinic_id = None

    # 1. 安全防禦：檔名路徑穿越過濾與副檔名檢查
    filename = Path(file.filename or "uploaded_file").name
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支援的檔案格式 '{ext}'，僅接受 .docx, .xlsx, .pdf",
        )

    # 2. 檔案大小限制（15MB）
    content = await file.read(MAX_FILE_SIZE + 1)  # 最多多讀 1 byte 判斷超限，避免整包載入記憶體
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="檔案大小超過上限 15MB",
        )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="上傳之檔案內容為空",
        )

    # 2b. 檔頭魔術位元組檢查（副檔名可偽造；亦避免 markitdown 對格式不符檔案退回純文字吐亂碼）
    expected_magic = _PDF_MAGIC if ext == ".pdf" else _ZIP_MAGIC
    if not content.startswith(expected_magic):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"檔案內容與副檔名 '{ext}' 不符或已損毀",
        )

    # 3. 寫入臨時檔並處理（例外時在 finally 區塊刪除）
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        return await run_in_threadpool(
            _process_admin_upload_sync,
            tmp_path,
            filename,
            ext,
            clean_clinic_id,
            name,
            preview_only,
            conn,
        )
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

DEFAULT_SOURCES_PATH = Path(__file__).resolve().parents[4] / "data" / "scraper" / "sources.json"
_URL_FETCH_LOCK = Lock()


def get_url_fetch_deps() -> UrlFetchDeps:
    """取得網址擷取依賴項（唯一的依賴注入點，D-23）。"""
    try:
        allowlist = __import__('src.api.routes.admin', fromlist=['load_allowlist']).load_allowlist(DEFAULT_SOURCES_PATH)
    except PolicyError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="網站擷取器白名單設定無法讀取",
        ) from e

    return UrlFetchDeps(
        allowlist=allowlist,
        throttle=get_shared_throttle(),
        robots=get_shared_robots(),
        user_agent=build_user_agent(),
        resolver=None,  # None → policy 內建解析（回傳 IP 字串）；勿傳 socket.getaddrinfo（回傳 5-tuple）
        http_get=None,
    )


@router.post("/upload-url", summary="網站解析（網址）上傳草稿")
def upload_admin_url(
    url: str = Form(""),
    clinic_id: Optional[str] = Form(None),
    name: str = Form(""),
    target: str = Form("faq"),
    preview_only: bool = Form(False),
    conn: sqlite3.Connection = Depends(get_write_db),
    deps: UrlFetchDeps = Depends(get_url_fetch_deps),
):
    """
    接收公開已授權之 HTTPS 網址，經由 Phase 23 擷取器與結構化抽取，轉換為待審核之 FAQ 草稿。
    若 clinic_id 為空，則自動歸類為一般醫學共用文件（category='general'）。
    """
    # a. clinic_id 去空白；clinic_info 不存在 → 404
    clean_clinic_id = (clinic_id or "").strip()
    clinic_name = "一般醫學"
    if clean_clinic_id:
        clinic_row = conn.execute(
            "SELECT clinic_id, name FROM clinic_info WHERE clinic_id = ?",
            (clean_clinic_id,),
        ).fetchone()
        if not clinic_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到指定的診所代碼: {clean_clinic_id}",
            )
        clinic_name = clinic_row[1]
    else:
        clean_clinic_id = None

    # b. target 非 "faq" → 400
    if (target or "").strip() != "faq":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="網址解析目前僅支援常見問答 FAQ 草稿",
        )

    # c. name_clean = validate_display_name(name)；None → 400（網址模式名稱必填）
    name_clean = validate_display_name(name)
    if not name_clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_NAME_VALIDATION_ERROR_MSG,
        )

    # d. 若 not preview_only：__import__('src.api.routes.admin', fromlist=['has_metadata_column']).has_metadata_column(conn) 為假 → 503（早於擷取中止）
    if not preview_only and not __import__('src.api.routes.admin', fromlist=['has_metadata_column']).has_metadata_column(conn):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="資料庫尚未完成 metadata 欄位遷移，暫無法寫入網址來源草稿",
        )

    # e. validated = validate_public_url(url, resolver=deps.resolver)；UnsafeUrlError → 400
    try:
        validated = validate_public_url(url, resolver=deps.resolver)
    except UnsafeUrlError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    # f. 取得 _URL_FETCH_LOCK（非阻塞）；失敗 → 429
    acquired = _URL_FETCH_LOCK.acquire(blocking=False)
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="網站擷取進行中，請稍後再試",
        )

    try:
        # g. page_result = __import__('src.api.routes.admin', fromlist=['fetch_clinic_page']).fetch_clinic_page(...)
        try:
            page_result = __import__('src.api.routes.admin', fromlist=['fetch_clinic_page']).fetch_clinic_page(
                validated.url,
                deps=deps,
                pinned_addresses=validated.addresses,
                institution_name=clinic_name,
            )
        except UrlFetchError as e:
            if e.reason in {
                "not_allowlisted",
                "scheme",
                "port",
                "credentials",
                "private_address",
                "bad_url",
                "too_many_redirects",
            }:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="網址不允許解析（僅接受已授權之公開 https 網址）",
                ) from e
            elif e.reason == "bot_challenge":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="目標網站要求人工驗證（機器人防護），本系統不會嘗試繞過，請改由診所提供內容或更換來源",
                ) from e
            elif e.reason == "robots_denied":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="該網站之 robots.txt 不允許擷取",
                ) from e
            elif e.reason == "bad_allowlist":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="網站擷取器白名單設定無法讀取",
                ) from e
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="網站擷取失敗，請稍後再試",
                ) from e
        except (NotImplementedError, ImportError) as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="網站擷取器尚未就緒",
            ) from e
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="網站擷取失敗，請稍後再試",
            ) from e

        # h. page = page_result.page；若 not page.is_usable() → 422
        page = page_result.page
        if not page.is_usable():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="網站內容無法解析（必要欄位缺失，疑似網站改版），未產生草稿",
            )

        # i. raw_text = build_service_text(page)；若為空字串 → 400
        raw_text = build_service_text(page)
        if not raw_text or not raw_text.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="網站未解析出可用內容",
            )

        # j. faqs, paragraphs_count, rejected = __import__('src.api.routes.admin', fromlist=['_text_to_faq_drafts'])._text_to_faq_drafts(raw_text, name_clean, clean_clinic_id)
        faqs, paragraphs_count, rejected = __import__('src.api.routes.admin', fromlist=['_text_to_faq_drafts'])._text_to_faq_drafts(
            raw_text=raw_text,
            topic=name_clean,
            clinic_id=clean_clinic_id,
        )

        # k. 身分洩漏檢查（縱深防禦）：
        # 對 institution_name、address、phone 之原始值與其 to_traditional 版本，
        # 若出現於任一 faq 的 question 或 answer → 該 faq 剔除，rejected += 1
        identity_terms: set[str] = set()
        for raw_val in (page.institution_name, page.address, page.phone):
            if raw_val and isinstance(raw_val, str) and len(raw_val.strip()) >= 2:
                v = raw_val.strip()
                identity_terms.add(v)
                identity_terms.add(to_traditional(v).strip())

        filtered_faqs = []
        for faq in faqs:
            q_text = faq.get("question", "")
            a_text = faq.get("answer", "")
            leaked = any(term in q_text or term in a_text for term in identity_terms if term)
            if leaked:
                rejected += 1
            else:
                filtered_faqs.append(faq)
        faqs = filtered_faqs

        # l. 溯源 metadata（僅寫入 faq["metadata"]，JSON 字串）
        def _clean_s(x: Optional[str]) -> str:
            if not x:
                return ""
            trad = to_traditional(x)
            deid = deidentify_text(trad)
            masked = deep_mask_prices(deid)
            return str(masked) if isinstance(masked, dict) else str(masked)

        metadata_dict = {
            "origin": "web_scrape",
            "source_url": page_result.source_url,
            "fetched_at": page_result.fetched_at,
            "schema_version": page.schema_version,
            "extracted": {
                "institution_name": _clean_s(page.institution_name),
                "address": _clean_s(page.address),
                "phone": _clean_s(page.phone),
                "business_hours": _clean_s(page.business_hours),
            },
        }
        metadata_str = json.dumps(metadata_dict, ensure_ascii=False)
        for faq in faqs:
            faq["metadata"] = metadata_str

        missing_fields = optional_missing_fields(page)

        # m. 預覽或寫入回應
        if preview_only:
            return {
                "status": "ok",
                "preview_only": True,
                "clinic_id": clean_clinic_id,
                "name": name_clean,
                "source_url": page_result.source_url,
                "missing_fields": missing_fields,
                "extracted_paragraphs_count": paragraphs_count,
                "rejected_paragraphs": rejected,
                "faqs_preview": [
                    {
                        "question": f["question"],
                        "answer": f["answer"],
                        "topic_key": f["topic_key"],
                    }
                    for f in faqs
                ],
            }

        if not faqs:
            # 全部段落已被合規或身分檢查剔除：明確回報，不得回傳 OK 卻未寫入任何草稿
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="網站內容經合規與身分檢查後無可寫入之草稿（未寫入任何資料）",
            )

        try:
            inserted, updated, unchanged = upsert_faqs(conn, faqs, source_type="web_upload")
            conn.commit()
        except RuntimeError as e:
            conn.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="資料庫尚未完成審核欄位遷移，暫無法接收上傳",
            ) from e

        return {
            "status": "ok",
            "preview_only": False,
            "source_url": page_result.source_url,
            "missing_fields": missing_fields,
            "inserted": inserted,
            "updated": updated,
            "unchanged": unchanged,
            "total_faqs": len(faqs),
            "rejected_paragraphs": rejected,
            "review_status": "pending",
        }
    finally:
        _URL_FETCH_LOCK.release()


