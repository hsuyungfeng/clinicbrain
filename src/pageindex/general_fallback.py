"""無診所資料時，改由本機 LLM 生成「一般醫學」衛教草稿（待醫師審核，核准前不對外可見）。

- 題目沒有診所已核准內容時才使用（呼叫端負責判斷）。
- 生成沿用批次一般題目的提示與驗證：價格屏蔽、禁詞、劑量／處方攔截、就醫警訊強制收尾。
- 寫入 category='general'、clinic_id=NULL、source_type='llm_generated'，review_status 由
  faq_writer 強制為 'pending'（Fail-Closed）。批次與本函式都不會核准任何草稿。
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Callable

from ..batch.faq_generator import build_seed_faq_prompt
from .llm_client import LLMEmptyOutputError
from ..ingestion.generate_faq import parse_and_validate_faq
from ..soap.deid import deidentify_text
from .answer_generator import _clean_llm_output
from .faq_writer import upsert_faqs

MAX_QUESTION_CHARS = 300


class GeneralDraftError(Exception):
    """無法產生可寫入之一般草稿（驗證未通過或格式錯誤）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _topic_key(question: str) -> str:
    slug = re.sub(r"[^\w]+", "-", question.lower()).strip("-")
    return f"general-{slug}"[:64] or "general-misc"


_NO_THINK_SUFFIX = "\n/no_think\n請跳過思考過程，直接輸出 JSON 陣列，不要任何說明文字。"


def _call_no_think_first(llm_call: Callable[[str], str], prompt: str) -> str:
    """JSON 生成任務預設關閉思考（思考過長會耗盡 token 或逾時，實測多次回傳空白）。

    仍保留一次空白重試作為保險；僅限本一般草稿路徑，RAG 與其他任務不受影響。
    """
    try:
        return llm_call(prompt + _NO_THINK_SUFFIX)
    except LLMEmptyOutputError:
        return llm_call(prompt + _NO_THINK_SUFFIX)


def generate_general_draft(
    conn: sqlite3.Connection,
    question: str,
    llm_call: Callable[[str], str],
) -> dict:
    """生成一般醫學草稿並寫入 faq_cache（pending）。回傳寫入結果與待審草稿摘要。

    驗證失敗時拋出 GeneralDraftError，且**不寫入任何資料**。
    """
    q = (question or "").strip()
    if not q:
        raise GeneralDraftError("問題不可為空")
    if len(q) > MAX_QUESTION_CHARS:
        raise GeneralDraftError(f"問題過長（上限 {MAX_QUESTION_CHARS} 字）")

    # 問句可能含個人資訊，寫入資料庫前先去識別化
    q_store = deidentify_text(q).strip()

    prompt = build_seed_faq_prompt(
        title=f"一般醫學衛教：{q_store}",
        questions=[q_store],
        reference_context=None,
        require_doctor_warning=True,
    )
    raw = _clean_llm_output(_call_no_think_first(llm_call, prompt))
    valid, rejected = parse_and_validate_faq(
        raw, return_rejected=True, check_dosage=True, require_doctor_warning=True,
    )
    if not valid:
        reasons = [str(r.get("reason", r.get("code", ""))) for r in rejected] or ["模型輸出無法解析"]
        raise GeneralDraftError("生成內容未通過合規檢驗：" + "；".join(reasons))

    item = valid[0]
    if item.get("question", "").strip() != q_store:
        raise GeneralDraftError("模型改寫了問題，未寫入")

    answer = item["answer"].strip()
    metadata = json.dumps(
        {
            "origin": "general_llm_fallback",
            "generated_from": "no_clinic_evidence",
            "requested_question": q_store,
        },
        ensure_ascii=False,
    )
    inserted, updated, unchanged = upsert_faqs(
        conn,
        [{
            "question": q_store,
            "answer": answer,
            "category": "general",
            "clinic_id": None,
            "topic_key": _topic_key(q_store),
            "metadata": metadata,
        }],
        source_type="llm_generated",
        commit=True,
    )
    return {
        "question": q_store,
        "answer": answer,
        "review_status": "pending",
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
    }
