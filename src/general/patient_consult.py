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

from ..pageindex.general_fallback import GeneralDraftError, generate_general_draft
from ..pageindex.llm_client import LLMEmptyOutputError, LocalLLMUnavailableError
from .consult import consult_general
from .disclaimer import message_for_red_flag, RED_FLAG_DISCLAIMER_TEXT
from .red_flags import detect_red_flag

BOOKING_URL = "https://doctor-toolbox.com/"
LLM_LABEL = "以下為一般醫學知識說明，並非本診所醫師意見，尚未經醫師審核。"
LLM_DISCLAIMER = "本說明無法取代醫師面對面診察。請洽合作診所或醫師評估，勿自行用藥。"
NO_DATA_TEXT = "目前沒有已核准的相關資料，無法提供說明。建議您洽詢合作診所或醫師評估。"
BUSY_TEXT = "目前諮詢人數較多，請稍後再試。"

# 病人端只允許一次生成（本機 LLM 單一 slot）；忙碌時直接回覆，不排隊
_PATIENT_LLM_LOCK = threading.Lock()


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

    if not _PATIENT_LLM_LOCK.acquire(blocking=False):
        return PatientConsultResult(
            status="busy", message=BUSY_TEXT, disclaimer=LLM_DISCLAIMER,
            label=None, booking_url=BOOKING_URL,
        )
    try:
        draft = generate_general_draft(conn, query, llm_call)
        return PatientConsultResult(
            status="llm_general",
            message=draft["answer"],
            disclaimer=LLM_DISCLAIMER,
            label=LLM_LABEL,
            booking_url=BOOKING_URL,
        )
    except (GeneralDraftError, LLMEmptyOutputError, LocalLLMUnavailableError, RuntimeError):
        # 驗證未通過、LLM 離線或資料庫未遷移：回固定文字，不外露內部細節
        return PatientConsultResult(
            status="no_match", message=NO_DATA_TEXT, disclaimer=LLM_DISCLAIMER,
            label=None, booking_url=BOOKING_URL,
        )
    finally:
        _PATIENT_LLM_LOCK.release()


GENERAL_LLM_TIMEOUT_SECONDS = 900  # 一般醫學說明提示較長，實測可能超過 480 秒
GENERAL_LLM_MAX_TOKENS = 12288


def default_patient_llm(prompt: str) -> str:
    """病人端預設 LLM 呼叫：本機 llama-server，放寬 token 與逾時（與管理端一般草稿一致）。"""
    from ..pageindex.llm_client import local_llm_call

    return local_llm_call(
        prompt,
        timeout=GENERAL_LLM_TIMEOUT_SECONDS,
        sampling={"max_tokens": GENERAL_LLM_MAX_TOKENS},
    )
