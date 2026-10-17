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
from .consult import consult_general
from .disclaimer import message_for_red_flag, RED_FLAG_DISCLAIMER_TEXT
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


def patient_consult(
    conn: sqlite3.Connection,
    query: str,
    llm_call: Callable[[str], str],
) -> PatientConsultResult:
    """依固定順序回覆病人問句。llm_call 僅在沒有已核准資料時使用。"""
    rf = detect_red_flag(query)
    if rf is not None:
        return PatientConsultResult(
            status="red_flag",
            message=message_for_red_flag(rf.level, rf.rule_id),
            disclaimer=RED_FLAG_DISCLAIMER_TEXT,
            label=None,
            booking_url=BOOKING_URL,
        )

    found = consult_general(conn, query)
    if found.status == "answered":
        return PatientConsultResult(
            status="answered",
            message=found.message,
            disclaimer=found.disclaimer,
            label=None,
            booking_url=BOOKING_URL,
        )

    # 同一題已有一般草稿：直接沿用，不再呼叫模型（待審重用答案，駁回則回固定文字）
    existing = find_existing_general_draft(conn, query)
    if existing is not None:
        status, answer = existing
        if status == "pending" and answer:
            return PatientConsultResult(
                status="llm_general", message=answer, disclaimer=LLM_DISCLAIMER,
                label=LLM_LABEL, booking_url=BOOKING_URL,
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
            message=draft["answer"],
            disclaimer=LLM_DISCLAIMER,
            label=LLM_LABEL,
            booking_url=BOOKING_URL,
        )
    except (GeneralDraftError, LLMEmptyOutputError, LLMTruncatedError, LocalLLMUnavailableError, RuntimeError):
        # 驗證未通過、輸出截斷、LLM 離線或資料庫未遷移：回固定文字，不外露內部細節
        return PatientConsultResult(
            status="no_match", message=NO_DATA_TEXT, disclaimer=LLM_DISCLAIMER,
            label=None, booking_url=BOOKING_URL,
        )
    finally:
        GENERATION_LOCK.release()


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
