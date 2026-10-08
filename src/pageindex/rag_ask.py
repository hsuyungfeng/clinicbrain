"""
Taiwan Clinic Medical PageIndex RAG System - 管理端「向 LLM 提問」檢驗模組
Phase 20: 讓醫師／管理者實際對本機 LLM 提問，觀察它如何「只根據系統資料」回答。

設計原則：
- 檢索沿用 handle_query（cache_shortcut=False），因此只會取得「對外可見」的資料：
  已核准的 FAQ、推理樹、診所備註——與公開端點相同的審核閘門，未核准草稿絕不入 context。
- 紅旗急重症問句不呼叫 LLM，直接回固定就醫指示（與 /api/v1/general/query 一致）。
- 找不到任何相關資料時不呼叫 LLM、不憑空作答，誠實回報「資料中沒有」。
- LLM 輸出一律價格屏蔽並檢驗合規；本模組只供管理端檢視，不寫入資料庫。
"""

import sqlite3
from typing import Callable, Optional

from ..general.disclaimer import message_for_red_flag
from ..general.red_flags import detect_red_flag
from ..query.router import handle_query
from .faq_review import sanitize_faq_text

MAX_QUESTION_CHARS = 300
MAX_FAQ = 4
MAX_TREES = 2
SNIPPET_CHARS = 500
NO_EVIDENCE_MESSAGE = "目前系統資料中沒有與此問題相關的已核准內容，因此不作答（避免憑空編造）。建議洽詢診所醫師。"

_TREE_FIELDS = (("pre_op", "術前"), ("procedure", "療程"), ("post_op_short", "術後短期"), ("maintenance", "長期維持"))


def _clip(text: Optional[str], n: int = SNIPPET_CHARS) -> str:
    t = (text or "").strip()
    return t if len(t) <= n else t[:n] + "…"


def retrieve_evidence(conn: sqlite3.Connection, question: str, clinic_id: str) -> tuple[str, list[dict]]:
    """回傳 (給 LLM 的資料文字, 來源清單)。僅含對外可見（已核准）資料。"""
    resp = handle_query(conn, question, clinic_id, limit=MAX_FAQ, cache_shortcut=False)
    blocks: list[str] = []
    sources: list[dict] = []

    for i, h in enumerate(resp.faq_hits[:MAX_FAQ], 1):
        f = h.fields
        ref = f"F{i}"
        level = "診所" if f.get("clinic_id") else "通用"
        blocks.append(f"[{ref}]（{level}常見問答）問：{_clip(f.get('question'), 200)}\n答：{_clip(f.get('answer'))}")
        sources.append({"ref": ref, "type": "faq", "id": h.row_id, "level": level, "title": _clip(f.get("question"), 80)})

    for i, h in enumerate(resp.page_index_hits[:MAX_TREES], 1):
        f = h.fields
        ref = f"T{i}"
        parts = [f"{label}：{_clip(f.get(key), 300)}" for key, label in _TREE_FIELDS if (f.get(key) or "").strip()]
        summary = _clip(f.get("summary_text"), 200)
        body = (f"摘要：{summary}\n" if summary else "") + "\n".join(parts)
        if body.strip():
            blocks.append(f"[{ref}]（臨床推理樹：{f.get('doc_id')}）\n{body}")
            sources.append({"ref": ref, "type": "tree", "id": h.row_id, "level": "診所", "title": str(f.get("doc_id"))})

    for i, (section, note) in enumerate(list(resp.clinic_custom_notes.items())[:3], 1):
        ref = f"N{i}"
        blocks.append(f"[{ref}]（診所備註：{section}）{_clip(note, 300)}")
        sources.append({"ref": ref, "type": "note", "id": None, "level": "診所", "title": section})

    if resp.clinic_info:
        info = resp.clinic_info
        line = "、".join(f"{k}：{v}" for k, v in info.items() if v and k in ("name", "address", "phone"))
        if line:
            blocks.append(f"[C1]（診所基本資料）{line}")
            sources.append({"ref": "C1", "type": "clinic_info", "id": None, "level": "診所", "title": "診所基本資料"})

    return "\n\n".join(blocks), sources


def build_ask_prompt(question: str, context: str) -> str:
    return (
        "你是台灣診所的衛教問答助理。你只能根據下方「資料」回答，不可使用資料以外的醫學知識，也不可臆測。\n"
        "規則（必須全部遵守）：\n"
        "1. 若資料不足以回答，請直接回答：目前資料中沒有足夠資訊回答這個問題，建議洽詢診所醫師。\n"
        "2. 回答以繁體中文（台灣用語）撰寫，約 100～250 字，引用資料時在句末標示編號，例如 [F1]。\n"
        "3. 不得出現任何金額、價格、折扣或優惠。\n"
        "4. 不得出現具體藥品名稱與劑量，不下診斷、不開處方。\n"
        "5. 不得使用「保證」「根治」「百分之百」等療效保證用語。\n"
        "6. 若問題涉及身體不適，結尾以具體症狀提醒何時應儘速就醫。\n"
        "7. 只輸出答案本文。\n\n"
        f"資料：\n{context}\n\n問題：{question}\n"
    )


def ask_with_data(
    conn: sqlite3.Connection,
    question: str,
    clinic_id: str,
    llm_call: Callable[[str], str],
) -> dict:
    """對本機 LLM 提問並回傳答案、使用的資料來源與合規檢視結果。"""
    from ..ingestion.generate_faq import validate_single_faq
    from .answer_generator import _clean_llm_output

    q = (question or "").strip()
    if not q:
        raise ValueError("問題不可為空")
    if len(q) > MAX_QUESTION_CHARS:
        raise ValueError(f"問題過長（上限 {MAX_QUESTION_CHARS} 字）")

    rf = detect_red_flag(q)
    if rf is not None:
        return {
            "mode": "red_flag", "answer": message_for_red_flag(rf.level, rf.rule_id), "sources": [],
            "red_flag_level": rf.level, "used_llm": False, "compliance": {"ok": True, "reason": ""},
        }

    context, sources = retrieve_evidence(conn, q, clinic_id)
    if not sources:
        return {
            "mode": "no_evidence", "answer": NO_EVIDENCE_MESSAGE, "sources": [],
            "red_flag_level": None, "used_llm": False, "compliance": {"ok": True, "reason": ""},
        }

    raw = llm_call(build_ask_prompt(q, context))
    answer = sanitize_faq_text(_clean_llm_output(raw))
    ok, reason = validate_single_faq({"question": q, "answer": answer}, check_dosage=True)
    return {
        "mode": "answered", "answer": answer, "sources": sources, "red_flag_level": None,
        "used_llm": True, "compliance": {"ok": bool(ok), "reason": "" if ok else str(reason)},
    }
