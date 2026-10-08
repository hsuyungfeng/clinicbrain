"""
Taiwan Clinic Medical PageIndex RAG System - 待審草稿 AI 輔助答案生成模組
Phase 19: Web 管理介面臨床體驗升級與 AI 輔助生成

僅供醫師在 Web 管理介面對「待審（pending/rejected）」草稿補齊答案：
- 一律走本機 llama-server（由呼叫端注入 llm_call），病患與診所文件不外流雲端。
- 生成結果必須先通過價格屏蔽與四層合規＋劑量＋就醫警訊檢驗才寫入；
- 寫入後狀態恆為 pending，仍須醫師核准後才對外生效（Fail-Closed）。
"""

import json
import re
import sqlite3
from typing import Callable, Optional

from .faq_review import REVIEW_GATED_SOURCES, has_metadata_column, has_review_status

PLACEHOLDER_QUESTION_PREFIX = "【診所文件】"
MIN_ANSWER_CHARS = 100
MAX_ANSWER_CHARS = 600
THIN_ANSWER_CHARS = 30  # 低於此長度視為「尚未補齊」

_LEAD_NUMBERING = re.compile(r"^\s*(?:\d+|[一二三四五六七八九十]+)\s*[\.、．)）:：]\s*")
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class GenerationError(Exception):
    """生成流程中可預期的失敗（含 http_status 供 API 對應）。"""

    def __init__(self, message: str, http_status: int = 422):
        super().__init__(message)
        self.http_status = http_status


def extract_question_text(question: str, answer: str) -> Optional[str]:
    """取得「真正要被回答的問題」。

    - 問題欄是實際問句：直接使用。
    - 問題欄是上傳文件的佔位題（【診所文件】… - 指示 N）且答案欄僅為單行問句
      （問題清單型文件）：以答案欄的那行問句為準。
    - 其餘（佔位題但答案是多行指示內容）：回傳 None，代表此列已有實質內容，不應被覆蓋。
    """
    q = (question or "").strip()
    if not q.startswith(PLACEHOLDER_QUESTION_PREFIX):
        return q or None
    a = (answer or "").strip()
    if not a:
        return None
    lines = [ln for ln in a.splitlines() if ln.strip()]
    if len(lines) != 1:
        return None
    cand = _LEAD_NUMBERING.sub("", lines[0].strip()).strip()
    if 4 <= len(cand) <= 120 and cand.endswith(("？", "?")):
        return cand
    return None


def is_answer_thin(question: str, answer: str) -> bool:
    """答案是否尚待補齊（空白、過短，或佔位題下僅為問題清單）。"""
    a = (answer or "").strip()
    if len(a) < THIN_ANSWER_CHARS:
        return True
    return (question or "").startswith(PLACEHOLDER_QUESTION_PREFIX) and extract_question_text(question, answer) is not None


def build_answer_prompt(question: str, topic: str) -> str:
    return (
        "你是台灣診所的衛教助理。請以繁體中文（台灣用語）回答下列問題，全文約 150～300 字。\n"
        "規則（必須全部遵守）：\n"
        "1. 內容僅限一般性衛教，不下診斷、不開處方。\n"
        "2. 不得出現任何金額、價格、折扣或優惠。\n"
        "3. 不得出現具體藥品名稱與劑量。\n"
        "4. 不得使用「保證」「根治」「百分之百」「一定有效」等療效保證用語。\n"
        "5. 最後一句必須是就醫警訊：列出具體症狀或數值條件（例如高燒超過3天、呼吸困難、傷口紅腫化膿），並說明應儘速就醫。\n"
        "6. 只輸出答案本文，不要重複題目，不要加標題或 Markdown 符號。\n\n"
        f"主題背景：{topic}\n"
        f"問題：{question}\n"
    )


def _clean_llm_output(raw: str) -> str:
    text = _THINK_BLOCK.sub("", raw or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    text = re.sub(r"^(?:答|答案|A)\s*[:：]\s*", "", text).strip()
    return text


def generate_answer_for_faq(
    conn: sqlite3.Connection,
    faq_id: int,
    llm_call: Callable[[str], str],
    *,
    overwrite: bool = False,
) -> dict:
    """為指定待審草稿生成答案並寫回（狀態維持 pending）。失敗拋 GenerationError。"""
    from .faq_review import sanitize_faq_text
    from ..ingestion.generate_faq import validate_single_faq

    if not has_review_status(conn):
        raise GenerationError("資料庫尚未完成審核欄位遷移", 503)

    row = conn.execute(
        "SELECT id, topic_key, question, answer, source_type, review_status, category "
        "FROM faq_cache WHERE id = ?",
        (faq_id,),
    ).fetchone()
    if row is None:
        raise GenerationError("找不到指定的 FAQ", 404)
    _, topic_key, question, answer, source_type, review_status, category = tuple(row)

    if source_type not in REVIEW_GATED_SOURCES:
        raise GenerationError("僅限待審來源草稿可使用 AI 生成", 409)
    if review_status == "approved":
        raise GenerationError("已核准項目不可直接改寫，請先退回待審", 409)

    real_q = extract_question_text(question, answer)
    if real_q is None:
        if not overwrite:
            raise GenerationError("此草稿已有實質內容，若要覆蓋請明確指定 overwrite", 409)
        real_q = (question or "").strip()
    elif not overwrite and not is_answer_thin(question, answer):
        raise GenerationError("此草稿答案已完整，若要重新生成請明確指定 overwrite", 409)

    topic = re.sub(r"^doc-", "", topic_key or "") or "一般衛教"
    raw = llm_call(build_answer_prompt(real_q, topic))
    text = sanitize_faq_text(_clean_llm_output(raw))

    if not (MIN_ANSWER_CHARS <= len(text) <= MAX_ANSWER_CHARS):
        raise GenerationError(f"模型回覆長度不符（{len(text)} 字），已捨棄，請重試", 422)
    ok, reason = validate_single_faq(
        {"question": real_q, "answer": text},
        check_dosage=True,
        require_doctor_warning=True,
    )
    if not ok:
        raise GenerationError(f"模型回覆未通過合規檢驗（{reason}），已捨棄，請重試", 422)

    new_question = real_q if real_q != (question or "").strip() else question
    meta_sql, meta_params = "", []
    if has_metadata_column(conn):
        old = conn.execute("SELECT metadata FROM faq_cache WHERE id = ?", (faq_id,)).fetchone()[0]
        try:
            meta = json.loads(old) if old else {}
            if not isinstance(meta, dict):
                meta = {}
        except (TypeError, ValueError):
            meta = {}
        meta["answer_source"] = "local_llm"
        meta_sql, meta_params = ", metadata = ?", [json.dumps(meta, ensure_ascii=False)]

    try:
        cur = conn.execute(
            f"""
            UPDATE faq_cache
            SET question = ?, answer = ?, review_status = 'pending', reviewed_at = NULL,
                content_version = content_version + 1, updated_at = CURRENT_TIMESTAMP{meta_sql}
            WHERE id = ? AND answer IS ? AND review_status != 'approved'
            """,
            [new_question, text, *meta_params, faq_id, answer],
        )
    except sqlite3.IntegrityError as e:
        conn.rollback()
        raise GenerationError("同診所同主題已有相同題目，請先處理重複項目", 409) from e
    if cur.rowcount != 1:
        conn.rollback()
        raise GenerationError("草稿在生成期間已被他人修改，請重新整理後再試", 409)
    conn.commit()
    return {"id": faq_id, "question": new_question, "answer": text, "review_status": "pending"}
