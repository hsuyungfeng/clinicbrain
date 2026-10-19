"""病人「先答後導」諮詢（Phase 26，階段一）。

路由順序（固定）：
1. 急重症紅旗：固定就醫指示，不查資料、不呼叫模型。
2. 已核准的一般衛教資料（consult_general）：有命中則回答並附免責聲明。
3. 沒有已核准資料：由本機 LLM 生成一般醫學說明（標示「尚未經醫師審核」），
   同時以 generate_general_draft 存入一般草稿佇列（pending，醫師核准前不對外）。
   生成失敗時回固定文字，不回傳未通過檢驗的內容。
4. 每個回覆都附預約方式：https://doctor-toolbox.com/（留資與預約由該平台承接）。

隱私：不要求姓名、電話、身分證；不記錄問句原文或對話；草稿佇列僅存去識別化後的問題文字。
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from typing import Callable

from ..pageindex.general_fallback import GeneralDraftError, generate_general_draft, find_existing_general_draft
from ..pageindex.llm_client import (
    LLMEmptyOutputError,
    LLMTruncatedError,
    LocalLLMUnavailableError,
    PATIENT_COMPOSE_SAMPLING,
    PATIENT_GENERAL_SAMPLING,
)
from ..pageindex.llm_lock import GENERATION_LOCK, nightly_batch_running
from ..visual.match import find_visual
from .consult import GeneralConsultResult, consult_general
from .disclaimer import message_for_red_flag, RED_FLAG_DISCLAIMER_TEXT
from .patient_compose import (
    ClinicEvidence,
    InsufficientEvidenceError,
    compose_from_approved,
    decorate_general_answer,
    filter_relevant,
    retrieve_clinic_evidence,
)
from .red_flags import detect_red_flag

BOOKING_URL = "https://doctor-toolbox.com/"
LLM_LABEL = "以下為一般醫學知識說明，並非本診所醫師意見，尚未經醫師審核。"
LLM_DISCLAIMER = "本說明無法取代醫師面對面診察。請洽合作診所或醫師評估，勿自行用藥。"
NO_DATA_TEXT = "目前沒有已核准的相關資料，無法提供說明。建議您洽詢合作診所或醫師評估。"
BUSY_TEXT = "目前諮詢人數較多，請稍後再試。"

# 病人端與管理端共用唯一模型生成鎖；保留 _PATIENT_LLM_LOCK 別名以相容既有引用
_PATIENT_LLM_LOCK = GENERATION_LOCK


def _get_db_path(conn: sqlite3.Connection) -> str:
    """自 SQLite 連線取得主資料庫檔案路徑。"""
    try:
        row = conn.execute("SELECT file FROM pragma_database_list WHERE name = 'main'").fetchone()
        if row and row[0]:
            return str(row[0])
    except Exception:
        pass
    return ""


@dataclass
class PatientConsultResult:
    status: str  # red_flag | answered | llm_general | no_match | busy
    message: str
    disclaimer: str
    label: str | None
    booking_url: str
    visual: dict | None = None


def _safe_find_visual(conn: sqlite3.Connection, query: str) -> dict | None:
    """安全呼叫 find_visual，任何例外皆視為 None（Fail-Closed）。"""
    try:
        return find_visual(conn, query)
    except Exception:
        return None


PATIENT_LLM_TIMEOUT_SECONDS = 240  # 限制單題上限 4 分鐘內，避免公開端點無限懸掛


def default_patient_llm(prompt: str) -> str:
    """病人端預設 LLM 呼叫（未審草稿路徑）：使用 PATIENT_GENERAL_SAMPLING，timeout 240 秒。"""
    from ..pageindex.llm_client import local_llm_call

    return local_llm_call(
        prompt,
        timeout=PATIENT_LLM_TIMEOUT_SECONDS,
        sampling=dict(PATIENT_GENERAL_SAMPLING),
    )


def default_patient_compose_llm(prompt: str) -> str:
    """病人端即時組稿預設 LLM 呼叫：使用 PATIENT_COMPOSE_SAMPLING，timeout 240 秒。"""
    from ..pageindex.llm_client import local_llm_call

    return local_llm_call(
        prompt,
        timeout=PATIENT_LLM_TIMEOUT_SECONDS,
        sampling=dict(PATIENT_COMPOSE_SAMPLING),
    )


def patient_consult(
    conn: sqlite3.Connection,
    query: str,
    llm_call: Callable[[str], str] = default_patient_llm,
    compose_llm_call: Callable[[str], str] | None = None,
    clinic_id: str | None = None,
) -> PatientConsultResult:
    """依固定順序回覆病人問句。

    診所範圍規範：
    - clinic_id 僅由呼叫端傳入伺服器固定解析之代碼（由伺服器決定，不讀請求主體或標頭）。
    - clinic_id 為 None 時維持純一般醫療衛教行為。
    - clinic_id 有效時，可檢索該診所已核准之 special FAQ 與指引樹，絕不跨診所。

    路由順序：
    1. 急重症紅旗：固定就醫指示，不查資料、不呼叫模型。
    2. 已核准資料直答／組稿（診所證據 + 通用證據 + compose_from_approved）：有命中則回答並附免責聲明。
    3. 同題草稿重用（find_existing_general_draft）：待審重用裝飾答案，駁回則回固定文字。
    4. 2.24 未審一般說明（generate_general_draft）：本機 LLM 生成、存入草稿佇列（pending），裝飾回傳並標示未審。
    5. 固定文字（no_match）。
    """
    rf = detect_red_flag(query)
    if rf is not None:
        return PatientConsultResult(
            status="red_flag",
            message=message_for_red_flag(rf.level, rf.rule_id),
            disclaimer=RED_FLAG_DISCLAIMER_TEXT,
            label=None,
            booking_url=BOOKING_URL,
        )

    raw_clinic_ev = retrieve_clinic_evidence(conn, query, clinic_id) if clinic_id else None
    found = consult_general(conn, query)

    # 過濾不相關的已核准資料並取得乾淨複本
    clinic_ev, filtered_found = filter_relevant(query, raw_clinic_ev, found)

    has_clinic_evidence = bool(clinic_ev and (clinic_ev.faq_hits or clinic_ev.guide_hits))
    has_general_evidence = filtered_found.status == "answered"

    if has_clinic_evidence or has_general_evidence:
        actual_compose_llm = compose_llm_call or llm_call
        try:
            composed_msg = compose_from_approved(
                conn, query, filtered_found, actual_compose_llm, clinic_evidence=clinic_ev
            )
        except InsufficientEvidenceError:
            composed_msg = None
            has_general_evidence = False

        if composed_msg:
            return PatientConsultResult(
                status="answered",
                message=composed_msg,
                disclaimer=found.disclaimer,
                label=None,
                booking_url=BOOKING_URL,
                visual=_safe_find_visual(conn, query),
            )
        elif has_general_evidence and filtered_found.message:
            return PatientConsultResult(
                status="answered",
                message=filtered_found.message,
                disclaimer=found.disclaimer,
                label=None,
                booking_url=BOOKING_URL,
                visual=_safe_find_visual(conn, query),
            )

    # 同一題已有一般草稿：直接沿用，不再呼叫模型（待審重用答案，駁回則回固定文字）
    existing = find_existing_general_draft(conn, query)
    if existing is not None:
        status, answer = existing
        if status == "pending" and answer:
            return PatientConsultResult(
                status="llm_general",
                message=decorate_general_answer(answer, query),
                disclaimer=LLM_DISCLAIMER,
                label=LLM_LABEL,
                booking_url=BOOKING_URL,
                visual=_safe_find_visual(conn, query),
            )
        return PatientConsultResult(
            status="no_match", message=NO_DATA_TEXT, disclaimer=LLM_DISCLAIMER,
            label=None, booking_url=BOOKING_URL,
        )

    # 檢查夜間批次是否正在執行（跨行程檔案鎖探測）
    db_path = _get_db_path(conn)
    if nightly_batch_running(db_path):
        return PatientConsultResult(
            status="busy", message=BUSY_TEXT, disclaimer=LLM_DISCLAIMER,
            label=None, booking_url=BOOKING_URL,
        )

    if not GENERATION_LOCK.acquire(blocking=False):
        return PatientConsultResult(
            status="busy", message=BUSY_TEXT, disclaimer=LLM_DISCLAIMER,
            label=None, booking_url=BOOKING_URL,
        )
    try:
        draft = generate_general_draft(conn, query, llm_call, retry_on_empty=False)
        return PatientConsultResult(
            status="llm_general",
            message=decorate_general_answer(draft["answer"], query),
            disclaimer=LLM_DISCLAIMER,
            label=LLM_LABEL,
            booking_url=BOOKING_URL,
            visual=_safe_find_visual(conn, query),
        )
    except (GeneralDraftError, LLMEmptyOutputError, LLMTruncatedError, LocalLLMUnavailableError, RuntimeError):
        # 驗證未通過、輸出截斷、LLM 離線或資料庫未遷移：回固定文字，不外露內部細節
        return PatientConsultResult(
            status="no_match", message=NO_DATA_TEXT, disclaimer=LLM_DISCLAIMER,
            label=None, booking_url=BOOKING_URL,
        )
    finally:
        GENERATION_LOCK.release()
