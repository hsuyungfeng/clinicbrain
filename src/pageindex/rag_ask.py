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

from ..general.answer_compose import clip_at_sentence
from ..general.disclaimer import message_for_red_flag
from ..general.red_flags import detect_red_flag
from ..query.router import handle_query
from .faq_review import sanitize_faq_text

MAX_QUESTION_CHARS = 300
MAX_FAQ = 8
MAX_TREES = 2
CONTEXT_TOTAL_CHARS = 2400
MIN_ITEM_CHARS = 120
DEFAULT_FAQ_ANSWER_BUDGET = 500
DEFAULT_TREE_BUDGET = 300
DEFAULT_SUMMARY_BUDGET = 200
DEFAULT_NOTE_BUDGET = 300
NO_EVIDENCE_MESSAGE = "目前系統資料中沒有與此問題相關的已核准內容，因此不作答（避免憑空編造）。建議洽詢診所醫師。"

_TREE_FIELDS = (("pre_op", "術前"), ("procedure", "療程"), ("post_op_short", "術後短期"), ("maintenance", "長期維持"))


def _render_evidence(
    faq_hits: list,
    tree_hits: list,
    notes: list[tuple[str, str]],
    clinic_info: Optional[dict],
    budget_ratio: float = 1.0,
) -> tuple[str, list[dict]]:
    faq_ans_budget = max(MIN_ITEM_CHARS, int(DEFAULT_FAQ_ANSWER_BUDGET * budget_ratio))
    tree_budget = max(MIN_ITEM_CHARS, int(DEFAULT_TREE_BUDGET * budget_ratio))
    summary_budget = max(MIN_ITEM_CHARS, int(DEFAULT_SUMMARY_BUDGET * budget_ratio))
    note_budget = max(MIN_ITEM_CHARS, int(DEFAULT_NOTE_BUDGET * budget_ratio))

    blocks: list[str] = []
    sources: list[dict] = []

    for i, h in enumerate(faq_hits, 1):
        f = h.fields
        ref = f"F{i}"
        level = "診所" if f.get("clinic_id") else "通用"
        q_text = clip_at_sentence(f.get("question") or "", 200)
        a_text = clip_at_sentence(f.get("answer") or "", faq_ans_budget)
        blocks.append(f"[{ref}]（{level}常見問答）問：{q_text}\n答：{a_text}")
        sources.append({
            "ref": ref,
            "type": "faq",
            "id": h.row_id,
            "level": level,
            "title": clip_at_sentence(f.get("question") or "", 80),
        })

    for i, h in enumerate(tree_hits, 1):
        f = h.fields
        ref = f"T{i}"
        parts = [
            f"{label}：{clip_at_sentence(f.get(key) or '', tree_budget)}"
            for key, label in _TREE_FIELDS
            if (f.get(key) or "").strip()
        ]
        summary_raw = (f.get("summary_text") or "").strip()
        summary = clip_at_sentence(summary_raw, summary_budget) if summary_raw else ""
        body = (f"摘要：{summary}\n" if summary else "") + "\n".join(parts)
        if body.strip():
            blocks.append(f"[{ref}]（臨床推理樹：{f.get('doc_id')}）\n{body}")
            sources.append({
                "ref": ref,
                "type": "tree",
                "id": h.row_id,
                "level": "診所",
                "title": str(f.get("doc_id")),
            })

    for i, (section, note) in enumerate(notes, 1):
        ref = f"N{i}"
        blocks.append(f"[{ref}]（診所備註：{section}）{clip_at_sentence(note or '', note_budget)}")
        sources.append({"ref": ref, "type": "note", "id": None, "level": "診所", "title": section})

    if clinic_info:
        line = "、".join(f"{k}：{v}" for k, v in clinic_info.items() if v and k in ("name", "address", "phone"))
        if line:
            blocks.append(f"[C1]（診所基本資料）{line}")
            sources.append({"ref": "C1", "type": "clinic_info", "id": None, "level": "診所", "title": "診所基本資料"})

    return "\n\n".join(blocks), sources


def retrieve_evidence(conn: sqlite3.Connection, question: str, clinic_id: str) -> tuple[str, list[dict]]:
    """回傳 (給 LLM 的資料文字, 來源清單)。僅含對外可見（已核准）資料。"""
    resp = handle_query(conn, question, clinic_id, limit=MAX_FAQ, cache_shortcut=False)

    faq_candidates = list(resp.faq_hits[:MAX_FAQ])
    tree_candidates = list(resp.page_index_hits[:MAX_TREES])
    note_candidates = list(resp.clinic_custom_notes.items())[:3]
    clinic_info = resp.clinic_info

    # 1. 嘗試以標準預算渲染 (budget_ratio = 1.0)
    context, sources = _render_evidence(faq_candidates, tree_candidates, note_candidates, clinic_info, budget_ratio=1.0)
    if len(context) <= CONTEXT_TOTAL_CHARS:
        return context, sources

    # 2. 若超出預算，嘗試縮減每項預算至 MIN_ITEM_CHARS；若在 MIN_ITEM_CHARS 下仍超標，逐一從後方剔除 FAQ
    while len(faq_candidates) > 1:
        min_ctx, _ = _render_evidence(faq_candidates, tree_candidates, note_candidates, clinic_info, budget_ratio=0.0)
        if len(min_ctx) <= CONTEXT_TOTAL_CHARS:
            break
        faq_candidates.pop()

    # 3. 在當前候選集下，在 [0.0, 1.0] 間二分搜尋最佳預算比率，盡可能充分利用 CONTEXT_TOTAL_CHARS
    low, high = 0.0, 1.0
    best_context, best_sources = _render_evidence(faq_candidates, tree_candidates, note_candidates, clinic_info, budget_ratio=0.0)
    for _ in range(8):
        mid = (low + high) / 2
        ctx, srcs = _render_evidence(faq_candidates, tree_candidates, note_candidates, clinic_info, budget_ratio=mid)
        if len(ctx) <= CONTEXT_TOTAL_CHARS:
            best_context, best_sources = ctx, srcs
            low = mid
        else:
            high = mid

    return best_context, best_sources


def build_ask_prompt(question: str, context: str) -> str:
    return (
        "你是台灣診所的衛教問答助理。你只能根據下方「資料」回答，不可使用資料以外的醫學知識，也不可臆測。\n"
        "規則（必須全部遵守）：\n"
        "1. 若資料不足以回答，請直接回答：目前資料中沒有足夠資訊回答這個問題，建議洽詢診所醫師。\n"
        "2. 回答以繁體中文（台灣用語）撰寫，長度約 250～400 字。在資料充足時，請依主題結構化條列分段說明（例如【門診處置】、【日常照護】、【就醫提醒】），提升病患閱讀易讀性。\n"
        "3. 引用資料時在句末標示來源編號，例如 [F1]、[T1]。\n"
        "4. 嚴格禁止出現任何金額、價格、折扣或費用。\n"
        "5. 嚴格禁止出現具體藥品名稱與劑量，不下診斷、不開處方。\n"
        "6. 嚴格禁止使用「保證」「根治」「百分之百」等療效保證用語。\n"
        "7. 若問題涉及身體不適，結尾必須以具體症狀警訊提醒何時應儘速就醫。\n"
        "8. 只輸出答案本文，不輸出多餘開場白或問候語。\n\n"
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
