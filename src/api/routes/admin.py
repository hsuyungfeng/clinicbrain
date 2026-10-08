"""
診所 Web 管理與文件上傳 API 路由模組。
Phase 18 Plan 18-01: 提供文件上傳解析、待審衛教草稿檢索與簽核動作 API。
所有端點強制掛載 verify_admin_key 認證，唯讀查詢使用 PRAGMA query_only = ON，寫入操作走唯一權威路徑。
"""

import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from ...ingestion.convert_chinese import to_traditional
from ...ingestion.extract_text import extract_docx_text, extract_xlsx_text
from ...ingestion.generate_faq import validate_single_faq
from ...pageindex.faq_review import (
    get_faq,
    has_metadata_column,
    has_review_status,
    set_review_status,
)
from ...pageindex.faq_writer import upsert_faqs
from ...soap.deid import deidentify_text
from ..dependencies import get_read_db, get_write_db, verify_admin_key
from .query import deep_mask_prices

MAX_FILE_SIZE = 15 * 1024 * 1024  # 15MB
ALLOWED_EXTENSIONS = {".docx", ".xlsx", ".pdf"}
MAX_PARAGRAPHS = 200  # 單檔最多轉出的草稿段落數（過長請拆檔，保護醫師審核負擔）
MAX_ANSWER_CHARS = 3000
_ZIP_MAGIC = b"PK\x03\x04"
_PDF_MAGIC = b"%PDF-"
_Q_PREFIXES = ("問：", "問:", "Q:", "Q：", "q:", "q：")

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["診所管理端點 (Admin Only)"],
    dependencies=[Depends(verify_admin_key)],
)


@router.post("/upload", summary="診所衛教與項目文件上傳解析")
async def upload_admin_file(
    file: UploadFile = File(...),
    clinic_id: str = Form(...),
    preview_only: bool = Form(False),
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
        doc_topic = Path(filename).stem[:80]

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
                q_part = f"【診所文件】{doc_topic} - 指示 {idx + 1}"
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
                "topic_key": f"doc-{doc_topic}",
            })

        if preview_only:
            return {
                "status": "ok",
                "preview_only": True,
                "filename": filename,
                "clinic_id": clinic_id,
                "extracted_paragraphs_count": len(paragraphs),
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

    return {
        "pending_total": pending_total,
        "pending_special": pending_special,
        "pending_general": pending_general,
        "pending_soap_distilled": pending_soap_distilled,
        "approved_total": approved_total,
        "rejected_total": rejected_total,
        "soap_records_total": soap_records_total,
    }
