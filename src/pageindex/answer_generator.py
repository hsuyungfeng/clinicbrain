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

    def __init__(self, message: str, http_status: int = 422, skippable: bool = False):
        super().__init__(message)
        self.http_status = http_status
        self.skippable = skippable   # 批次作業中視為「略過」而非「失敗」（例如已完整、已核准）


_BULLET_PREFIX = re.compile(r"^[\s\-\*•·●■□▪◆◇▶►\u2022]+")
MAX_TOPIC_FRAGMENT_CHARS = 40
CONTEXT_CHARS = 1500


def classify_draft(question: str, answer: str) -> tuple[str, Optional[str]]:
    """判斷草稿類型，回傳 (kind, text)：

    - ("question", 問句)：題目欄是實際問句，或佔位題下答案欄僅為單行問句（問題清單型文件）。
    - ("topic", 片段)：佔位題下答案欄僅為單行短片段（文章的標題／小標題，例如「- 常見疑難傷口型別」）；
      需要以同一份文件的內文為依據撰寫說明。
    - ("content", None)：佔位題但答案已是實質內容（多行或較長），不應被覆蓋。
    """
    q = (question or "").strip()
    if not q.startswith(PLACEHOLDER_QUESTION_PREFIX):
        return ("question", q) if q else ("content", None)
    a = (answer or "").strip()
    lines = [ln for ln in a.splitlines() if ln.strip()]
    if len(lines) != 1:
        return ("content", None)
    cand = _LEAD_NUMBERING.sub("", _BULLET_PREFIX.sub("", lines[0].strip())).strip()
    if 4 <= len(cand) <= 120 and cand.endswith(("？", "?")):
        return ("question", cand)
    cand = cand.strip("：:。；;、，, ")
    if 2 <= len(cand) <= MAX_TOPIC_FRAGMENT_CHARS:
        return ("topic", cand)
    return ("content", None)


def extract_question_text(question: str, answer: str) -> Optional[str]:
    """取得「真正要被回答的問題」（kind 為 question 時）；其餘回傳 None。"""
    kind, text = classify_draft(question, answer)
    return text if kind == "question" else None


def is_answer_thin(question: str, answer: str) -> bool:
    """答案是否尚待補齊。唯一來源：Web 介面旗標與批次補齊選取共用此判斷。

    - 空白：待補齊。
    - 佔位題：僅 question／topic 型態為待補齊（可由模型補）；多段或實質內容（content）不算待補齊，
      因為生成端會以「已有實質內容」拒絕覆蓋，顯示旗標只會造成誤會。
    - 非佔位題：答案不足 THIN_ANSWER_CHARS 字即待補齊。
    """
    a = (answer or "").strip()
    if not a:
        return True
    q = question or ""
    if q.startswith(PLACEHOLDER_QUESTION_PREFIX):
        return classify_draft(q, a)[0] in ("question", "topic")
    return len(a) < THIN_ANSWER_CHARS


def build_answer_prompt(question: str, topic: str) -> str:
    return (
        "你是台灣診所的衛教助理。請以繁體中文（台灣用語）回答下列問題，全文約 150～300 字。\n"
        "規則（必須全部遵守）：\n"
        "1. 思考過程請保持簡潔（不超過 100 字），直接輸出答案本文。\n"
        "2. 內容僅限一般性衛教，不下診斷、不開處方。\n"
        "3. 不得出現任何金額、價格、折扣或優惠。\n"
        "4. 不得出現具體藥品名稱與劑量。\n"
        "5. 不得使用「保證」「根治」「百分之百」「一定有效」等療效保證用語。\n"
        "6. 最後一句必須是就醫警訊：列出具體危險症狀或數值條件（例如：若傷口出現紅腫化膿、持續滲血或發燒，請儘速就醫回診。）。\n"
        "7. 只輸出答案本文，不要重複題目，不要加標題或 Markdown 符號。\n\n"
        f"主題背景：{topic}\n"
        f"問題：{question}\n"
    )


def build_topic_prompt(fragment: str, doc_title: str, outline: list[str], excerpts: list[str]) -> str:
    outline_txt = "\n".join(f"- {o}" for o in outline) or "（無）"
    excerpt_txt = "\n".join(f"{n}. {e}" for n, e in enumerate(excerpts, 1)) or "（無）"
    return (
        "你是台灣診所的衛教助理。下方「文件」是診所提供的衛教文章節錄；請只根據文件內容，"
        f"針對主題「{fragment}」撰寫一則衛教問答。\n"
        "規則（必須全部遵守）：\n"
        "1. 思考過程請保持簡潔（不超過 100 字），直接依規定格式輸出。\n"
        "2. 只能使用文件裡有的資訊，不可加入文件以外的醫學知識或臆測；文件資訊不足時，只輸出「資料不足」四個字。\n"
        "3. 先擬一個一般民眾會問的問題（以「？」結尾，30 字內），再回答，答案約 150～300 字，繁體中文（台灣用語）。\n"
        "4. 不得出現任何金額、價格、折扣或優惠；不得出現具體藥品名稱與劑量；不下診斷、不開處方。\n"
        "5. 不得使用「保證」「根治」「百分之百」「一定有效」等療效保證用語。\n"
        "6. 答案最後一句必須是就醫警訊：列出具體危險症狀或數值條件（例如：若傷口出現紅腫化膿、持續滲血或發燒，請儘速就醫回診。）。\n"
        "7. 嚴格依下列格式輸出兩段，不要加其他文字或符號：\n問題：<問題>\n答案：<答案>\n\n"
        f"文件標題：{doc_title}\n文件大綱：\n{outline_txt}\n文件內文節錄：\n{excerpt_txt}\n"
    )


_QA_PARSE = re.compile(r"問題\s*[:：]\s*(.+?)\s*\n+\s*答案\s*[:：]\s*(.+)", re.DOTALL)


def parse_topic_output(text: str, fragment: str) -> tuple[str, str]:
    """解析「問題：／答案：」兩段；問題不合格時以片段組出保底問句。"""
    m = _QA_PARSE.search(text or "")
    if not m:
        raise GenerationError("模型回覆格式不符或資料不足，已捨棄，請重試", 422)
    q, a = m.group(1).strip(), m.group(2).strip()
    if not (4 <= len(q) <= 80 and q.endswith(("？", "?"))):
        q = f"關於「{fragment}」有哪些重點？"
    return q, a


def _document_context(conn: sqlite3.Connection, faq_id: int, clinic_id, topic_key) -> tuple[list[str], list[str]]:
    """同一份文件的其他段落：短片段作大綱，實質段落作內文節錄（總量受限，避免 prompt 過長）。"""
    rows = conn.execute(
        "SELECT answer FROM faq_cache WHERE clinic_id IS ? AND topic_key IS ? AND id != ? ORDER BY id",
        (clinic_id, topic_key, faq_id),
    ).fetchall()
    outline: list[str] = []
    excerpts: list[str] = []
    budget = CONTEXT_CHARS
    for (ans,) in rows:
        t = (ans or "").strip()
        if not t:
            continue
        if len(t) < THIN_ANSWER_CHARS:
            frag = _BULLET_PREFIX.sub("", t).strip()
            if frag and len(outline) < 15 and frag not in outline:
                outline.append(frag)
        elif budget > 0:
            piece = t[:min(220, budget)]
            excerpts.append(piece)
            budget -= len(piece)
    return outline, excerpts


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
    grounded_llm_call: Optional[Callable[[str], str]] = None,
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
        raise GenerationError("僅限待審來源草稿可使用 AI 生成", 409, skippable=True)
    if review_status == "approved":
        raise GenerationError("已核准項目不可直接改寫，請先退回待審", 409, skippable=True)

    kind, frag = classify_draft(question, answer)
    if kind == "content":
        if not overwrite:
            raise GenerationError("此草稿已有實質內容，若要覆蓋請明確指定 overwrite", 409, skippable=True)
        kind, frag = "question", (question or "").strip()
    elif not overwrite and not is_answer_thin(question, answer):
        raise GenerationError("此草稿答案已完整，若要重新生成請明確指定 overwrite", 409, skippable=True)

    topic = re.sub(r"^doc-", "", topic_key or "") or "一般衛教"
    if kind == "topic":
        # 標題片段：以同一份文件內文為依據；模型自擬問句。使用「忠實引用」取樣的呼叫（若有提供）
        clinic_id = conn.execute("SELECT clinic_id FROM faq_cache WHERE id = ?", (faq_id,)).fetchone()[0]
        outline, excerpts = _document_context(conn, faq_id, clinic_id, topic_key)
        if not excerpts:
            raise GenerationError("同一份文件中沒有可作為依據的內文，無法針對此標題生成", 422)
        raw = (grounded_llm_call or llm_call)(build_topic_prompt(frag, topic, outline, excerpts))
        real_q, text = parse_topic_output(_clean_llm_output(raw), frag)
        text = sanitize_faq_text(text)
        real_q = sanitize_faq_text(real_q)
    else:
        real_q = frag
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
        if kind == "topic":
            meta["generated_from"] = "document_context"
        meta_sql, meta_params = ", metadata = ?", [json.dumps(meta, ensure_ascii=False)]

    update_sql = f"""
        UPDATE faq_cache
        SET question = ?, answer = ?, review_status = 'pending', reviewed_at = NULL,
            content_version = content_version + 1, updated_at = CURRENT_TIMESTAMP{meta_sql}
        WHERE id = ? AND answer IS ? AND review_status != 'approved'
    """
    try:
        cur = conn.execute(update_sql, [new_question, text, *meta_params, faq_id, answer])
    except sqlite3.IntegrityError as e:
        conn.rollback()
        if kind != "topic":
            raise GenerationError("同診所同主題已有相同題目，請先處理重複項目", 409) from e
        # 標題片段的問句由模型自擬，同一份文件內可能撞題：改用以片段組成的保底問句重試一次
        new_question = f"關於「{frag}」有哪些重點？"
        try:
            cur = conn.execute(update_sql, [new_question, text, *meta_params, faq_id, answer])
        except sqlite3.IntegrityError as e2:
            conn.rollback()
            raise GenerationError("同診所同主題已有相同題目，請先處理重複項目", 409) from e2
    if cur.rowcount != 1:
        conn.rollback()
        raise GenerationError("草稿在生成期間已被他人修改，請重新整理後再試", 409)
    conn.commit()
    return {"id": faq_id, "question": new_question, "answer": text, "review_status": "pending"}
