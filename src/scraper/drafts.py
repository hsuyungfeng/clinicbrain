"""Phase 23 Task 2 & 3：FAQ 草稿建構、保證療效前置檢查、identity_leak 檢查與唯一寫入路徑。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import sqlite3
from typing import Sequence

from src.api.routes.query import deep_mask_prices
from src.ingestion.convert_chinese import to_traditional
from src.ingestion.generate_faq import validate_single_faq
from src.pageindex.faq_review import has_metadata_column, has_review_status
from src.pageindex.faq_writer import upsert_faqs
from src.scraper.extract import ExtractedClinicPage
from src.scraper.policy import PolicyError, strip_url_for_storage
from src.soap.deid import deidentify_text

# 保證療效禁詞完整表（來源：AGENTS §2.5 與 src/api/routes/sync.py:_FORBIDDEN_PHRASES）
GUARANTEE_PHRASES: tuple[str, ...] = (
    "保證有效",
    "保证有效",
    "保證根除",
    "保证根除",
    "百分之百有效",
    "100%有效",
    "徹底根除",
    "彻底根除",
    "一定有效",
    "一定能消除",
    "保證消除",
    "保证消除",
    "保證治癒",
    "保证治愈",
    "永久根除",
    "physician_notes",
)

PRICE_REGEX = re.compile(r"(?:NT\$|\$)\s*[\d,]+|[\d,]{3,}\s*(?:元|塊)|\b\d+\s*(?:元|塊)", re.IGNORECASE)


class ScraperDraftError(Exception):
    """草稿建置或寫入例外。"""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason


@dataclass
class DraftBuildResult:
    """草稿建置結果。"""

    drafts: list[dict]
    rejected: list[dict]


def build_faq_drafts(
    page: ExtractedClinicPage,
    *,
    clinic_id: str,
    source_url: str,
    fetched_at: str,
) -> DraftBuildResult:
    """將擷取頁面之有效服務轉換為待審核之 FAQ 草稿（記憶體純函式）。"""
    if not isinstance(clinic_id, str) or not re.match(r"^\d{10}$", clinic_id.strip()):
        raise ScraperDraftError("bad_clinic_id", f"診所代號必須為 10 碼數字: {clinic_id}")

    if not page.is_usable():
        raise ScraperDraftError("schema_drift", "頁面結構發生飄移或無有效服務項目")

    try:
        safe_url = strip_url_for_storage(source_url)
    except PolicyError as e:
        raise ScraperDraftError("bad_source_url", f"來源網址無效: {e}") from e

    drafts: list[dict] = []
    rejected: list[dict] = []

    # 準備比對用之機構與醫師身分文字（全部經繁體正規化）
    identities: list[str] = []
    if page.institution_name:
        identities.append(to_traditional(page.institution_name.strip()))
    if page.address:
        identities.append(to_traditional(page.address.strip()))
    if page.phone:
        identities.append(to_traditional(page.phone.strip()))
    for doc in page.doctors:
        d_name = doc.get("name", "").strip()
        if d_name:
            identities.append(to_traditional(d_name))

    for idx, svc in enumerate(page.services):
        raw_name = svc.get("name", "").strip()
        raw_desc = svc.get("description", "").strip()

        # 1. 繁簡轉換與清洗
        name_tw = to_traditional(raw_name)
        desc_tw = to_traditional(raw_desc)

        # 2. 去識別化與價格遮蔽
        name_clean = deep_mask_prices(deidentify_text(name_tw))
        desc_clean = deep_mask_prices(deidentify_text(desc_tw))

        # 3. 二次價格檢查（含未被遮蔽之殘餘價格模式）
        if PRICE_REGEX.search(desc_tw) or PRICE_REGEX.search(name_tw) or PRICE_REGEX.search(desc_clean):
            rejected.append({"service": raw_name, "reason": "price_pattern"})
            continue

        question = f"【{name_clean}】是什麼？"
        answer = desc_clean

        # 4. 前置保證療效檢查 (5a)
        q_lower = question.lower()
        a_lower = answer.lower()
        has_guarantee = any(phrase.lower() in q_lower or phrase.lower() in a_lower for phrase in GUARANTEE_PHRASES)
        if has_guarantee:
            rejected.append({"service": raw_name, "reason": "guarantee_phrase"})
            continue

        # 5. 身分洩漏檢查 (5b)
        has_leak = False
        for ident in identities:
            if not ident:
                continue
            if ident in to_traditional(question) or ident in to_traditional(answer):
                has_leak = True
                break
        if has_leak:
            rejected.append({"service": raw_name, "reason": "identity_leak"})
            continue

        # 6. validate_single_faq 醫療合規性驗證
        item = {"question": question, "answer": answer}
        is_valid, rej_reason = validate_single_faq(item, check_dosage=True, require_doctor_warning=False)
        if not is_valid:
            rejected.append({"service": raw_name, "reason": rej_reason or "invalid_faq"})
            continue

        # 7. 安全 slug 與 topic_key
        raw_slug = re.sub(r"[^\w]+", "-", name_clean.lower()).strip("-")
        if not raw_slug:
            raw_slug = f"svc-{idx+1}"
        topic_key = f"web-{raw_slug}"[:64]

        # 8. metadata（機構層級限定，絕不包含 doctors）
        extracted_meta = {
            "institution_name": deep_mask_prices(deidentify_text(to_traditional(page.institution_name))),
            "address": deep_mask_prices(deidentify_text(to_traditional(page.address))),
            "phone": deep_mask_prices(deidentify_text(to_traditional(page.phone))),
            "business_hours": deep_mask_prices(deidentify_text(to_traditional(page.business_hours))),
        }
        metadata_dict = {
            "origin": "web_scrape",
            "source_url": safe_url,
            "fetched_at": fetched_at,
            "schema_version": page.schema_version,
            "extracted": extracted_meta,
        }
        metadata_str = json.dumps(metadata_dict, ensure_ascii=False)

        drafts.append(
            {
                "question": question,
                "answer": answer,
                "category": "special",
                "clinic_id": clinic_id.strip(),
                "topic_key": topic_key,
                "metadata": metadata_str,
            }
        )

    return DraftBuildResult(drafts=drafts, rejected=rejected)


def write_faq_drafts(conn: sqlite3.Connection, drafts: list[dict]) -> tuple[int, int, int]:
    """將草稿經權威路徑寫入 faq_cache 表（source_type='web_upload'，review_status='pending'）。注意：本函式不自動 commit。"""
    if not has_metadata_column(conn):
        raise ScraperDraftError("metadata_column_missing", "資料庫缺少 faq_cache.metadata 欄位")

    if not has_review_status(conn):
        raise ScraperDraftError("review_column_missing", "資料庫缺少 faq_cache.review_status 欄位")

    for draft in drafts:
        cid = draft.get("clinic_id")
        cur = conn.execute("SELECT 1 FROM clinic_info WHERE clinic_id = ?", (cid,))
        if not cur.fetchone():
            raise ScraperDraftError("bad_clinic_id", f"診所代號 {cid} 不存在於 clinic_info")

    return upsert_faqs(conn, drafts, source_type="web_upload", commit=False)
