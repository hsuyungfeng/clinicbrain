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
import time
from typing import Any, Literal, Optional
import unicodedata

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from ...ingestion.convert_chinese import to_traditional
from ...ingestion.extract_text import extract_docx_text, extract_xlsx_text
from ...ingestion.generate_faq import validate_single_faq
from ...ingestion.url_guard import UnsafeUrlError, validate_public_url
from ...pageindex import batch_answer_job
from ...pageindex.rag_ask import ask_with_data
from ...pageindex.answer_generator import GenerationError, generate_answer_for_faq, is_answer_thin
from ...pageindex.faq_review import (
    MAX_BATCH_SIZE,
    batch_review_faqs,
    get_faq,
    has_metadata_column,
    has_review_status,
    set_review_status,
    update_faq_content,
)
from ...pageindex.faq_writer import upsert_faqs
from ...pageindex.web_source_adapter import (
    UrlFetchDeps,
    UrlFetchError,
    build_service_text,
    fetch_clinic_page,
    get_shared_robots,
    get_shared_throttle,
    optional_missing_fields,
)
from ...scraper.fetch import build_user_agent
from ...scraper.policy import PolicyError, load_allowlist
from ...soap.deid import deidentify_text
from ..config import config
from ..dependencies import get_read_db, get_write_db, verify_admin_key
from .query import deep_mask_prices

MAX_FILE_SIZE = 15 * 1024 * 1024  # 15MB
ALLOWED_EXTENSIONS = {".docx", ".xlsx", ".pdf"}
MAX_PARAGRAPHS = 200  # 單檔最多轉出的草稿段落數（過長請拆檔，保護醫師審核負擔）
MAX_ANSWER_CHARS = 3000
_ZIP_MAGIC = b"PK\x03\x04"
_PDF_MAGIC = b"%PDF-"
_Q_PREFIXES = ("問：", "問:", "Q:", "Q：", "q:", "q：")

# AI 生成：單一本機 llama-server 一次只服務一題，避免請求堆疊拖垮推論
_GENERATION_LOCK = threading.Lock()
LLM_GENERATE_TIMEOUT_SECONDS = 480


def _local_llm_call(prompt: str) -> str:
    """呼叫本機 llama-server（測試時以 monkeypatch 替換）。"""
    from ...pageindex.llm_client import local_llm_call

    return local_llm_call(prompt, timeout=LLM_GENERATE_TIMEOUT_SECONDS)


# 忠實引用資料的任務（RAG 提問）：單次請求關閉重複懲罰並降低溫度，避免模型為了「不重複」而改字、掉字
FAITHFUL_SAMPLING = {"temperature": 0.1, "dry_multiplier": 0.0, "repeat_penalty": 1.0}
LLM_ASK_TIMEOUT_SECONDS = 480


def _local_llm_ask_call(prompt: str) -> str:
    """向本機 llama-server 提問（忠實引用取樣設定；測試時以 monkeypatch 替換）。"""
    from ...pageindex.llm_client import local_llm_call

    return local_llm_call(prompt, timeout=LLM_ASK_TIMEOUT_SECONDS, sampling=FAITHFUL_SAMPLING)


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
    clinic_id: str = Field(..., min_length=1, max_length=40)


class BatchGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    faq_ids: list[StrictInt] = Field(..., min_length=1, max_length=batch_answer_job.MAX_JOB_IDS)


class GenerateAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overwrite: bool = False


class AutoFillAllRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clinic_id: Optional[str] = None


router = APIRouter(
    prefix="/api/v1/admin",
    tags=["診所管理端點 (Admin Only)"],
    dependencies=[Depends(verify_admin_key)],
)

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
    clinic_id: str,
) -> tuple[list[dict[str, Any]], int, int]:
    """將純文字/Markdown/萃取內文清洗、切分並轉換為 FAQ 草稿清單（D-11）。

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
            q_part = f"【診所文件】{topic} - 指示 {idx + 1}"
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
            "category": "special",
            "clinic_id": clinic_id,
            "topic_key": f"doc-{topic}",
        })

    return faqs_to_insert, len(paragraphs), rejected_paragraphs


@router.post("/upload", summary="診所衛教與項目文件上傳解析")
async def upload_admin_file(
    file: UploadFile = File(...),
    clinic_id: str = Form(...),
    preview_only: bool = Form(False),
    name: Optional[str] = Form(None),
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """
    接收診所人員上傳之衛教或項目文件（.docx, .xlsx, .pdf），進行安全防禦、內文解析、去識別化與價格遮蔽。
    若 preview_only=False，將合格問答段落寫入 faq_cache（source_type='web_upload'，review_status 恆為 'pending'）。

    Fail-Closed：web_upload 屬審核閘門來源（REVIEW_GATED_SOURCES），由唯一權威寫入函式 upsert_faqs
    直接以 pending 寫入，經醫師 approve 前對所有公開端點與同步匯出完全隱蔽。
    """
    if not clinic_id or not clinic_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="必須提供非空之診所代碼 clinic_id",
        )
    clinic_id = clinic_id.strip()
    if conn.execute("SELECT 1 FROM clinic_info WHERE clinic_id = ?", (clinic_id,)).fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="找不到指定的診所代碼",
        )

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
        raw_text = ""
        # 優先嘗試 markitdown 轉 Markdown
        try:
            from ...ingestion.markdown_convert import convert_to_markdown
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

        faqs_to_insert, extracted_paragraphs_count, rejected_paragraphs = _text_to_faq_drafts(
            raw_text=raw_text,
            topic=doc_topic,
            clinic_id=clinic_id,
        )

        if preview_only:
            return {
                "status": "ok",
                "preview_only": True,
                "filename": filename,
                "clinic_id": clinic_id,
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
            "clinic_id": clinic_id,
            "inserted": inserted,
            "updated": updated,
            "unchanged": unchanged,
            "total_faqs": len(faqs_to_insert),
            "rejected_paragraphs": rejected_paragraphs,
            "review_status": "pending",
        }
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

DEFAULT_SOURCES_PATH = Path(__file__).resolve().parents[3] / "data" / "scraper" / "sources.json"
_URL_FETCH_LOCK = threading.Lock()


def get_url_fetch_deps() -> UrlFetchDeps:
    """取得網址擷取依賴項（唯一的依賴注入點，D-23）。"""
    try:
        allowlist = load_allowlist(DEFAULT_SOURCES_PATH)
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
    clinic_id: str = Form(...),
    name: str = Form(""),
    target: str = Form("faq"),
    preview_only: bool = Form(False),
    conn: sqlite3.Connection = Depends(get_write_db),
    deps: UrlFetchDeps = Depends(get_url_fetch_deps),
):
    """
    接收公開已授權之 HTTPS 網址，經由 Phase 23 擷取器與結構化抽取，轉換為待審核之 FAQ 草稿。
    """
    # a. clinic_id 去空白；clinic_info 不存在 → 404
    clean_clinic_id = (clinic_id or "").strip()
    clinic_row = conn.execute(
        "SELECT clinic_id, name FROM clinic_info WHERE clinic_id = ?",
        (clean_clinic_id,),
    ).fetchone()
    if not clinic_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到指定的診所代碼: {clean_clinic_id}",
        )

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

    # d. 若 not preview_only：has_metadata_column(conn) 為假 → 503（早於擷取中止）
    if not preview_only and not has_metadata_column(conn):
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
        # g. page_result = fetch_clinic_page(...)
        try:
            page_result = fetch_clinic_page(
                validated.url,
                deps=deps,
                pinned_addresses=validated.addresses,
                institution_name=clinic_row["name"],
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

        # j. faqs, paragraphs_count, rejected = _text_to_faq_drafts(raw_text, name_clean, clean_clinic_id)
        faqs, paragraphs_count, rejected = _text_to_faq_drafts(
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


@router.get("/review/faqs", summary="檢索待審或已審衛教問答列表")
def get_admin_review_faqs(
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(pending|approved|rejected)$", description="pending/approved/rejected"),
    category: Optional[str] = Query(None, pattern="^(special|general)$", description="special/general"),
    clinic_id: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_read_db),
):
    """依據狀態、類別與診所代碼檢索 FAQ 列表，包含 metadata (SOAP 溯源資訊)。"""
    if not has_review_status(conn):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="資料庫尚未建立審核欄位",
        )

    where_clauses = []
    params = []

    if status_filter:
        where_clauses.append("review_status = ?")
        params.append(status_filter)

    if category:
        where_clauses.append("category = ?")
        params.append(category)

    if clinic_id:
        where_clauses.append("clinic_id = ?")
        params.append(clinic_id)

    if source_type:
        where_clauses.append("source_type = ?")
        params.append(source_type)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM faq_cache {where_sql}", tuple(params))
    total = cur.fetchone()[0]

    has_meta = has_metadata_column(conn)
    select_meta = ", metadata" if has_meta else ""

    query_sql = f"""
        SELECT id, clinic_id, topic_key, question, answer, category,
               source_type, content_version, needs_regeneration,
               review_status, reviewed_at, created_at, updated_at{select_meta}
        FROM faq_cache
        {where_sql}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """
    query_params = list(params) + [limit, offset]
    cur.execute(query_sql, tuple(query_params))
    rows = cur.fetchall()

    faqs = []
    for r in rows:
        item = dict(r)
        if has_meta and item.get("metadata"):
            try:
                if isinstance(item["metadata"], str):
                    item["metadata"] = json.loads(item["metadata"])
            except Exception:
                pass
        item["needs_answer"] = is_answer_thin(item.get("question"), item.get("answer"))
        faqs.append(item)

    return {
        "faqs": faqs,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/review/faqs/{faq_id}/approve", summary="核准指定 FAQ 發布")
def approve_admin_faq(
    faq_id: int,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """將指定 ID 之待審 FAQ 核准發布，使其在快取短路與自然語言查詢中生效。"""
    res = set_review_status(conn, [faq_id], "approved", enforce_general_warning=True)
    if faq_id in res.changed:
        return {"status": "ok", "message": f"FAQ {faq_id} 已核准發布", "id": faq_id}
    else:
        reason = "無效或無變更"
        if res.skipped:
            reason = res.skipped[0][1]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"無法核准 FAQ {faq_id}: {reason}",
        )


@router.post("/review/faqs/{faq_id}/reject", summary="駁回指定 FAQ 草稿")
def reject_admin_faq(
    faq_id: int,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """將指定 ID 之待審 FAQ 標記為駁回 (rejected)。"""
    res = set_review_status(conn, [faq_id], "rejected")
    if faq_id in res.changed:
        return {"status": "ok", "message": f"FAQ {faq_id} 已駁回", "id": faq_id}
    else:
        reason = "無效或無變更"
        if res.skipped:
            reason = res.skipped[0][1]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"無法駁回 FAQ {faq_id}: {reason}",
        )


@router.get("/review/summary", summary="醫師審核與系統儀表板摘要資訊")
def get_admin_review_summary(
    conn: sqlite3.Connection = Depends(get_read_db),
):
    """提供 Web 儀表板關鍵指標數字。"""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM faq_cache WHERE review_status = 'pending'")
    pending_total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM faq_cache WHERE review_status = 'pending' AND category = 'special'")
    pending_special = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM faq_cache WHERE review_status = 'pending' AND category = 'general'")
    pending_general = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM faq_cache WHERE review_status = 'pending' AND source_type = 'soap_distilled'")
    pending_soap_distilled = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM faq_cache WHERE review_status = 'approved'")
    approved_total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM faq_cache WHERE review_status = 'rejected'")
    rejected_total = cur.fetchone()[0]

    soap_records_total = 0
    try:
        cur.execute("SELECT COUNT(*) FROM soap_records")
        soap_records_total = cur.fetchone()[0]
    except Exception:
        pass

    trees_pending_total = 0
    trees_approved_total = 0
    try:
        cur.execute("SELECT COUNT(*) FROM page_index_trees WHERE review_status = 'pending'")
        trees_pending_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM page_index_trees WHERE review_status = 'approved'")
        trees_approved_total = cur.fetchone()[0]
    except Exception:
        pass

    return {
        "pending_total": pending_total,
        "pending_special": pending_special,
        "pending_general": pending_general,
        "pending_soap_distilled": pending_soap_distilled,
        "approved_total": approved_total,
        "rejected_total": rejected_total,
        "soap_records_total": soap_records_total,
        "trees_pending_total": trees_pending_total,
        "trees_approved_total": trees_approved_total,
    }


@router.post("/review/batch", summary="批量核准／駁回待審草稿（單一交易）")
def batch_admin_review(
    req: BatchReviewRequest,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """單次最多 100 筆；核准前逐筆重跑合規檢驗，未通過者列入 failed_ids，其餘同一交易生效。"""
    if not has_review_status(conn):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="資料庫尚未建立審核欄位")
    try:
        result = batch_review_faqs(conn, req.faq_ids, req.action)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return {"status": "ok", "action": req.action, **result}


@router.patch("/review/faqs/{faq_id}", summary="內聯修訂待審草稿的題目／答案")
def patch_admin_faq(
    faq_id: int,
    req: UpdateFaqRequest,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    try:
        update_faq_content(conn, faq_id, question=req.question, answer=req.answer)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
    faq = get_faq(conn, faq_id)
    return {"status": "ok", "id": faq_id, "faq": faq}


@router.post("/review/faqs/{faq_id}/generate-answer", summary="以本機 LLM 為待審草稿生成衛教答案")
def generate_admin_faq_answer(
    faq_id: int,
    req: GenerateAnswerRequest = GenerateAnswerRequest(),
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """走本機 llama-server；生成內容須通過價格屏蔽、四層合規、劑量與就醫警訊檢驗才寫入，狀態維持 pending。"""
    from ...pageindex.llm_client import LLMEmptyOutputError, LocalLLMUnavailableError

    if not _GENERATION_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="已有一筆答案正在生成，請稍後再試")
    try:
        try:
            return {
                "status": "ok",
                **generate_answer_for_faq(
                    conn, faq_id, _local_llm_call, overwrite=req.overwrite, grounded_llm_call=_local_llm_ask_call
                ),
            }
        except GenerationError as e:
            raise HTTPException(status_code=e.http_status, detail=str(e)) from e
        except LLMEmptyOutputError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="模型回覆為空（可能因思考長度超限），請稍後重試") from e
        except LocalLLMUnavailableError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="本機 LLM 服務目前無法使用，請確認 llama-server 已啟動後再試",
            ) from e
    finally:
        _GENERATION_LOCK.release()


@router.post("/ask", summary="向本機 LLM 提問（僅依系統內已核准資料作答，檢視回答與資料來源）")
def admin_ask_llm(
    req: AskRequest,
    conn: sqlite3.Connection = Depends(get_read_db),
):
    """唯讀：不寫入任何資料。紅旗問句與無資料問句不呼叫 LLM；其餘走本機 llama-server。"""
    from ...pageindex.llm_client import LLMEmptyOutputError, LocalLLMUnavailableError

    clinic_id = req.clinic_id.strip()
    if conn.execute("SELECT 1 FROM clinic_info WHERE clinic_id = ?", (clinic_id,)).fetchone() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到指定的診所代碼")
    if not _GENERATION_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="本機模型忙碌中，請稍後再試")
    try:
        try:
            return {"status": "ok", "question": req.question.strip(),
                    **ask_with_data(conn, req.question, clinic_id, _local_llm_ask_call)}
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


@router.post("/review/batch-generate", summary="啟動背景批次補齊答案（本機 LLM 逐題處理，完成後再一起審核）")
def start_batch_generate(req: BatchGenerateRequest):
    """同時只允許一個作業；每題結果一律 pending。進度以 GET /review/batch-generate/status 查詢。"""
    try:
        return batch_answer_job.start(
            config.db_path, req.faq_ids, _local_llm_call, _local_llm_ask_call, _GENERATION_LOCK
        )
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/review/batch-generate/status", summary="查詢批次補齊作業進度")
def batch_generate_status():
    return batch_answer_job.snapshot()


@router.post("/review/batch-generate/cancel", summary="取消批次補齊作業（目前題目完成後停止）")
def cancel_batch_generate():
    return {"status": "ok", "cancelling": batch_answer_job.cancel()}


@router.post("/review/autofill/all", summary="一鍵背景自動補齊所有待審題目之答案")
def autofill_all_unanswered(
    req: Optional[AutoFillAllRequest] = None,
    clinic_id: Optional[str] = Query(None),
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """
    一鍵啟動背景作業，自動補齊所有待審題目之答案。
    - 查詢 review_status='pending' 且 (answer IS NULL OR length(trim(answer)) < 15) 之項目。
    - 若無任何待補齊項目，回傳 {"status": "noop", "message": "目前無待補齊答案之草稿", "scheduled_count": 0}。
    - 若已有批次作業執行中，回傳 HTTP 409 Conflict。
    - 排入背景逐題生成，回傳 {"status": "started", "scheduled_count": len(ids), "faq_ids": ids}。
    """
    target_clinic_id = req.clinic_id if req and req.clinic_id is not None else clinic_id
    if target_clinic_id is not None:
        target_clinic_id = target_clinic_id.strip() or None

    if batch_answer_job.is_running():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已有批次補齊作業進行中")

    ids = batch_answer_job.get_pending_unanswered_ids(
        conn, clinic_id=target_clinic_id, limit=batch_answer_job.MAX_JOB_IDS
    )
    if not ids:
        return {"status": "noop", "message": "目前無待補齊答案之草稿", "scheduled_count": 0}

    try:
        batch_answer_job.start(
            config.db_path, ids, _local_llm_call, _local_llm_ask_call, _GENERATION_LOCK
        )
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return {"status": "started", "scheduled_count": len(ids), "faq_ids": ids}


# =============================================================================
# Phase 21: 臨床決策推理樹 (PageIndex Trees) 審核與提煉端點
# =============================================================================

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
    from ...pageindex.tree_review import list_trees

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
    from ...pageindex.tree_review import get_tree

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
    from ...batch import db_lock
    from ...pageindex.llm_client import LLMEmptyOutputError, LocalLLMUnavailableError
    from ...pageindex.prompt_template import TreeValidationError
    from ...pageindex.tree_distiller import MAX_SOURCE_CHARS, TreeConflictError, distill_tree_from_text

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
            llm_call=_local_llm_call,
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
    from ...pageindex.prompt_template import TreeValidationError
    from ...pageindex.tree_distiller import TREE_TEXT_FIELDS, validate_tree_segment
    from ...pageindex.tree_review import get_tree, update_tree

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



@router.post("/trees/{tree_id}/approve", summary="醫師簽核核准臨床決策推理樹")
def approve_admin_tree(
    tree_id: int,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    """核准前重跑完整合規檢驗（與 FAQ 核准一致）：四段必須齊全且通過檢驗；醫囑欄位若有內容亦須通過。"""
    from ...pageindex.prompt_template import TreeValidationError
    from ...pageindex.tree_distiller import TREE_TEXT_FIELDS, validate_tree_segment
    from ...pageindex.tree_review import approve_tree, get_tree

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
    return {"status": "ok", "message": f"推理樹 {tree_id} 已核准發布", "id": tree_id}



@router.post("/trees/{tree_id}/reject", summary="醫師駁回臨床決策推理樹")
def reject_admin_tree(
    tree_id: int,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    from ...pageindex.tree_review import reject_tree

    ok = reject_tree(conn, tree_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="無法駁回該推理樹（不存在或已為駁回狀態）")
    return {"status": "ok", "message": f"推理樹 {tree_id} 已駁回", "id": tree_id}


@router.delete("/trees/{tree_id}", summary="刪除待審或駁回之臨床決策推理樹草稿")
def delete_admin_tree(
    tree_id: int,
    conn: sqlite3.Connection = Depends(get_write_db),
):
    from ...pageindex.tree_review import delete_tree

    ok = delete_tree(conn, tree_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="無法刪除該推理樹（僅限非核准狀態之草稿）")
    return {"status": "ok", "message": f"推理樹 {tree_id} 草稿已刪除", "id": tree_id}




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
