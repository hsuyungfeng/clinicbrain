"""病人端「已核准資料組稿」模組（Phase 28 P28-TPL, P28-LAT, P28-TRUNC）。

設計原則：
1. 先提供價值、後獲取資訊：回答恆為「價值段 2～4 句（含警訊句）＋ 單一追問 ＋ 預約邀請」。
2. 高度吻合直答：符合 AGENTS 2.8 雙門檻（>=0.9 / >=0.7）、風險特徵對稱、歧義邊界（>=0.1）與最小長度時，
   直接由已核准 FAQ 原文組裝，不呼叫 LLM（預生成 QA 經醫師核准後命中即回）。
3. 確定性降級：LLM 忙碌、離線、截斷、逾時或輸出合規檢驗失敗時，安全降級為由已核准資料
   萃取之確定性回答，不拋出例外、不回傳 busy、不外露未核准或未通過檢驗之內容。
4. 隱私與守門：純函式／唯讀流程，不寫入問句、不記錄日誌、不進行任何資料庫寫入操作。
"""

from __future__ import annotations

import sqlite3
from typing import Callable, Optional

from ..ingestion.medical_safety import has_doctor_warning
from ..pageindex.faq_review import sanitize_faq_text
from ..pageindex.llm_lock import GENERATION_LOCK, nightly_batch_running
from ..query.faq_shortcut import (
    MIN_MARGIN,
    MIN_QUERY_CHARS,
    MIN_QUERY_COVERAGE,
    MIN_QUESTION_COVERAGE,
    normalize_for_match,
    risk_mismatch,
    score_hit,
)
from ..query.router import STOPWORD_SPLIT_PATTERN
from .answer_compose import (
    assemble_answer,
    build_compose_prompt,
    classify_intent,
    clip_at_sentence,
    is_complete_ending,
    parse_model_output,
    split_sentences,
    validate_composed,
)
from .consult import GeneralConsultResult


def _get_db_path(conn: sqlite3.Connection) -> str:
    """自連線取得主資料庫檔案路徑（純 SELECT 語法以符合隱私 AST 檢核）。"""
    try:
        row = conn.execute("SELECT file FROM pragma_database_list WHERE name = 'main'").fetchone()
        if row and row[0]:
            return str(row[0])
    except Exception:
        pass
    return ""


def _evaluate_direct_shortcut(
    query: str,
    faq_hits: list[dict],
) -> Optional[dict]:
    """評估已核准 FAQ 是否符合 AGENTS 2.8 高信心直答標準。

    符合標準：
    1. 標準化查詢長度 >= MIN_QUERY_CHARS (4)。
    2. 最佳候選覆蓋率雙門檻：query_coverage >= 0.9 且 question_coverage >= 0.7。
    3. 風險特徵完全對稱：not risk_mismatch(query, best_faq_question)。
    4. 歧義邊界：若有多於 1 筆候選，best_query_cov - second_query_cov >= 0.1。
    """
    if not faq_hits:
        return None

    query_norm = normalize_for_match(query, stopword_pattern=STOPWORD_SPLIT_PATTERN)
    if len(query_norm) < MIN_QUERY_CHARS:
        return None

    # 合併相同標準化問句與答案的候選（保留第一個）
    candidate_map: dict[tuple[str, str], dict] = {}
    for h in faq_hits:
        q_raw = h.get("question") or ""
        ans_raw = (h.get("answer") or "").strip()
        if not ans_raw:
            continue
        q_norm = normalize_for_match(q_raw, stopword_pattern=STOPWORD_SPLIT_PATTERN)
        key = (q_norm, ans_raw)
        if key not in candidate_map:
            candidate_map[key] = h

    if not candidate_map:
        return None

    scored = []
    for (q_norm, _), h in candidate_map.items():
        q_cov, question_cov = score_hit(query_norm, q_norm)
        scored.append({
            "item": h,
            "q_cov": q_cov,
            "question_cov": question_cov,
        })

    # 排序：覆蓋率降冪
    scored.sort(key=lambda x: (-x["q_cov"], -x["question_cov"]))

    best = scored[0]
    if best["q_cov"] < MIN_QUERY_COVERAGE or best["question_cov"] < MIN_QUESTION_COVERAGE:
        return None

    best_q_raw = best["item"].get("question") or ""
    if risk_mismatch(query, best_q_raw):
        return None

    if len(scored) > 1:
        margin = best["q_cov"] - scored[1]["q_cov"]
        if margin < MIN_MARGIN:
            return None

    return best["item"]


def _deterministic_fallback(found: GeneralConsultResult, intent: str) -> Optional[str]:
    """從已核准資料萃取確定性回答，確保結構為 2～4 句並附加追問與 CTA。"""
    # 優先從 FAQ 答案萃取
    for h in found.faq_hits:
        ans = (h.get("answer") or "").strip()
        if not ans:
            continue

        # 1. 嘗試以句界截斷 400 字
        clipped = clip_at_sentence(ans, 400)
        assembled = assemble_answer(value=clipped, followup=None, intent=intent)
        if assembled:
            return sanitize_faq_text(assembled)

        # 2. 若 400 字截斷無法組裝，檢查原始句子，若有警訊句，挑選前幾句加上警訊句
        sents = split_sentences(ans)
        warn_indices = [i for i, s in enumerate(sents) if has_doctor_warning(s)]
        if len(sents) >= 2 and warn_indices:
            w_idx = warn_indices[-1]
            chosen_sents = []
            for i, s in enumerate(sents):
                if i != w_idx:
                    chosen_sents.append(s)
                if len(chosen_sents) >= 3:
                    break
            chosen_sents.append(sents[w_idx])
            fallback_val = "".join(chosen_sents)
            assembled = assemble_answer(value=fallback_val, followup=None, intent=intent)
            if assembled:
                return sanitize_faq_text(assembled)

    # 次選從推理樹 guide_hits 萃取
    for g in found.guide_hits:
        summary = (g.get("summary_text") or "").strip()
        post_op = (g.get("post_op_short") or "").strip()
        combined = f"{summary}。{post_op}" if summary and post_op else (summary or post_op)
        if combined:
            clipped = clip_at_sentence(combined, 400)
            assembled = assemble_answer(value=clipped, followup=None, intent=intent)
            if assembled:
                return sanitize_faq_text(assembled)

    return None


def compose_from_approved(
    conn: sqlite3.Connection,
    query: str,
    found: GeneralConsultResult,
    llm_call: Callable[[str], str],
) -> Optional[str]:
    """依已核准資料進行組稿，包含命中直答、LLM 組稿與確定性降級。

    回傳：符合「價值回答 2～4 句 ＋ 單一追問 ＋ 預約邀請」之完整字串，失敗時回傳 None。
    """
    q = (query or "").strip()
    if not q:
        return None

    intent = classify_intent(q)

    # 1. 嘗試高信心直答（預生成核准後或既有 FAQ 命中即回，不呼叫 LLM）
    best_faq = _evaluate_direct_shortcut(q, found.faq_hits)
    if best_faq is not None:
        best_ans = best_faq.get("answer") or ""
        clipped_val = clip_at_sentence(best_ans, 400)
        assembled = assemble_answer(value=clipped_val, followup=None, intent=intent)
        if assembled:
            return sanitize_faq_text(assembled)

    # 2. 否則建立 evidence blocks 嘗試 LLM 組稿
    blocks: list[str] = []
    for i, h in enumerate(found.faq_hits[:5], 1):
        faq_q = clip_at_sentence(h.get("question") or "", 200)
        faq_a = clip_at_sentence(h.get("answer") or "", 400)
        blocks.append(f"[F{i}]（常見問答）問：{faq_q}\n答：{faq_a}")

    for i, g in enumerate(found.guide_hits[:2], 1):
        doc_id = g.get("doc_id") or ""
        summary_raw = (g.get("summary_text") or "").strip()
        summary = clip_at_sentence(summary_raw, 200) if summary_raw else ""
        parts = []
        for key, label in (("pre_op", "處置前"), ("procedure", "處置過程"), ("post_op_short", "短期照護"), ("maintenance", "長期維持")):
            val = (g.get(key) or "").strip()
            if val:
                parts.append(f"{label}：{clip_at_sentence(val, 250)}")
        body = (f"摘要：{summary}\n" if summary else "") + "\n".join(parts)
        if body.strip():
            blocks.append(f"[T{i}]（衛教指引：{doc_id}）\n{body}")

    if not blocks:
        return _deterministic_fallback(found, intent)

    # 總長限制 2000 字
    total_len = 0
    filtered_blocks = []
    for b in blocks:
        if total_len + len(b) > 2000 and filtered_blocks:
            break
        filtered_blocks.append(b)
        total_len += len(b)

    # 鎖探測：非阻塞取得 GENERATION_LOCK 且 nightly_batch_running 為 False
    db_path = _get_db_path(conn)
    if nightly_batch_running(db_path):
        return _deterministic_fallback(found, intent)

    if not GENERATION_LOCK.acquire(blocking=False):
        return _deterministic_fallback(found, intent)

    try:
        prompt = build_compose_prompt(q, filtered_blocks, intent)
        raw_output = llm_call(prompt)
    except Exception:
        return _deterministic_fallback(found, intent)
    finally:
        GENERATION_LOCK.release()

    value, followup = parse_model_output(raw_output)
    if not is_complete_ending(value):
        return _deterministic_fallback(found, intent)
    if followup and not is_complete_ending(followup):
        return _deterministic_fallback(found, intent)

    ok, _ = validate_composed(value, followup)
    if not ok:
        return _deterministic_fallback(found, intent)

    assembled = assemble_answer(value, followup, intent)
    if not assembled:
        return _deterministic_fallback(found, intent)

    return sanitize_faq_text(assembled)


def decorate_general_answer(answer: str, query: str) -> str:
    """為 2.24 未審一般說明附單一追問與預約邀請，原答案少於 2 句時安全退回原 answer。"""
    intent = classify_intent(query)
    assembled = assemble_answer(value=answer, followup=None, intent=intent)
    return assembled if assembled else answer
