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

from dataclasses import dataclass, field
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
from ..query.router import (
    _CLINIC_OPS_KEYWORDS,
    STOPWORD_SPLIT_PATTERN,
    extract_search_terms,
    mask_prices,
)
from ..query.search import search_faq_cache, search_page_index_trees
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


class InsufficientEvidenceError(RuntimeError):
    """模型輸出表示參考資料不足以回答問句。"""
    pass


GENERIC_TERMS: frozenset[str] = frozenset({
    "照顧", "注意", "事項", "方法", "怎麼", "可以", "在家", "平常",
    "哪些", "什麼", "如何", "自己", "時候", "需要", "問題", "內容",
    "包含", "處理", "門診", "術後", "術前", "風險", "照護", "有沒有", "要不要",
    "手術", "療程", "治療", "項目",
})


def _build_generic_bigrams(terms: frozenset[str]) -> frozenset[str]:
    bg: set[str] = set()
    for t in terms:
        for i in range(len(t) - 1):
            pair = t[i : i + 2]
            if len(pair) == 2 and "\u4e00" <= pair[0] <= "\u9fff" and "\u4e00" <= pair[1] <= "\u9fff":
                bg.add(pair)
    return frozenset(bg)


_GENERIC_BIGRAMS: frozenset[str] = _build_generic_bigrams(GENERIC_TERMS)


def _extract_cjk_bigrams(text: str) -> set[str]:
    """取得字串中所有相鄰中文字元形成的 bigram 集合。"""
    bg: set[str] = set()
    for i in range(len(text) - 1):
        c1, c2 = text[i], text[i + 1]
        if "\u4e00" <= c1 <= "\u9fff" and "\u4e00" <= c2 <= "\u9fff":
            bg.add(c1 + c2)
    return bg


def is_relevant_evidence(query: str, hit: dict) -> bool:
    """判斷單筆已核准資料是否與問句具備足夠主題相關性（相鄰 2-gram 交集）。"""
    topic_text = normalize_for_match(query, stopword_pattern=STOPWORD_SPLIT_PATTERN)
    # 按長度降序逐一剔除泛用詞彙
    sorted_generic = sorted(GENERIC_TERMS, key=len, reverse=True)
    for term in sorted_generic:
        topic_text = topic_text.replace(term, "")

    topic_bigrams = _extract_cjk_bigrams(topic_text) - _GENERIC_BIGRAMS
    if not topic_bigrams:
        return False

    # 提取候選資料文字
    if "question" in hit or "answer" in hit:
        target_text = (hit.get("question") or "") + (hit.get("answer") or "")
    else:
        target_text = (
            (hit.get("doc_id") or "")
            + (hit.get("category") or "")
            + (hit.get("summary_text") or "")
            + (hit.get("pre_op") or "")
            + (hit.get("procedure") or "")
            + (hit.get("post_op_short") or "")
            + (hit.get("maintenance") or "")
        )

    target_bigrams = _extract_cjk_bigrams(target_text)
    return bool(target_bigrams & topic_bigrams)


def filter_relevant(query: str, *args):
    """過濾出與問句具備足夠相關性之已核准資料。

    支援兩種呼叫型式：
    1. filter_relevant(query, hits: list[dict]) -> list[dict]
    2. filter_relevant(query, clinic_ev: Optional[ClinicEvidence], found: GeneralConsultResult) -> tuple[Optional[ClinicEvidence], GeneralConsultResult]
    """
    if not args:
        return []

    if len(args) == 1 and isinstance(args[0], list):
        hits = args[0]
        if not query or not hits:
            return []
        return [h for h in hits if is_relevant_evidence(query, h)]

    if len(args) == 2:
        clinic_ev, found = args[0], args[1]
        new_clinic_ev = None
        if clinic_ev is not None:
            new_faqs = [h for h in clinic_ev.faq_hits if is_relevant_evidence(query, h)]
            new_guides = [h for h in clinic_ev.guide_hits if is_relevant_evidence(query, h)]
            new_clinic_ev = ClinicEvidence(faq_hits=new_faqs, guide_hits=new_guides)

        new_general_faqs = [h for h in found.faq_hits if is_relevant_evidence(query, h)]
        new_general_guides = [h for h in found.guide_hits if is_relevant_evidence(query, h)]
        has_any = bool(new_general_faqs or new_general_guides)
        new_found = GeneralConsultResult(
            status=found.status if has_any else "no_match",
            red_flag_level=found.red_flag_level,
            message=found.message if has_any else "",
            disclaimer=found.disclaimer,
            faq_hits=new_general_faqs,
            guide_hits=new_general_guides,
        )
        return new_clinic_ev, new_found

    raise ValueError("Invalid arguments for filter_relevant")


def looks_insufficient(text: str) -> bool:
    """檢查模型輸出是否表明現有參考資料不足以回答。"""
    t = (text or "").strip()
    if not t:
        return False
    if "資料不足" in t:
        return True
    data_indicators = ("參考資料", "提供的資料", "現有資料")
    lack_indicators = ("無法", "不足", "未提及", "並未", "僅涵蓋", "沒有")
    if any(d in t for d in data_indicators) and any(l in t for l in lack_indicators):
        return True
    return False


@dataclass
class ClinicEvidence:
    """診所已核准證據資料（含常見問答與衛教指引樹）。"""
    faq_hits: list[dict] = field(default_factory=list)
    guide_hits: list[dict] = field(default_factory=list)


def retrieve_clinic_evidence(
    conn: sqlite3.Connection,
    query: str,
    clinic_id: Optional[str],
    limit: int = 5,
) -> ClinicEvidence:
    """檢索指定診所已核准之 special FAQ 與推理指引樹。

    安全與邊界規範：
    1. clinic_id 為空時立即回傳空結構。
    2. 問句含營運關鍵字（如營業時間、地址、電話）時回傳空結構（不由此匿名端點提供營運資訊）。
    3. 僅經 search_faq_cache 與 search_page_index_trees 內建之可見性閘門檢索。
    4. Python 層雙重保險防禦性檢查：排除任何非指定 clinic_id 之資料，絕不跨診所。
    5. 內容經由 mask_prices 清洗。
    """
    if not clinic_id:
        return ClinicEvidence()

    q = (query or "").strip()
    if not q:
        return ClinicEvidence()

    # 問句含診所營運關鍵字時不提供診所證據（回歸一般路徑）
    if any(kw in q for kw in _CLINIC_OPS_KEYWORDS):
        return ClinicEvidence()

    terms = extract_search_terms(q) or [q]

    seen_faq_ids: set[int] = set()
    clinic_faqs: list[dict] = []

    seen_tree_ids: set[int] = set()
    clinic_trees: list[dict] = []

    for term in terms:
        # 1. 檢索該診所 special FAQ
        try:
            hits = search_faq_cache(
                conn,
                query=term,
                limit=limit,
                clinic_id=clinic_id,
                category="special",
            )
            for h in hits:
                # 雙重防禦檢查：確保 row.clinic_id 與 clinic_id 完全一致
                row_clinic_id = h.fields.get("clinic_id")
                if not (row_clinic_id == clinic_id):
                    continue
                if h.row_id not in seen_faq_ids:
                    seen_faq_ids.add(h.row_id)
                    clinic_faqs.append({
                        "topic_key": h.fields.get("topic_key"),
                        "question": mask_prices(h.fields.get("question") or ""),
                        "answer": mask_prices(h.fields.get("answer") or ""),
                        "clinic_id": clinic_id,
                        "level": "診所",
                    })
        except sqlite3.OperationalError:
            pass

        # 2. 檢索該診所已核准之推理指引樹
        try:
            tree_hits = search_page_index_trees(
                conn,
                query=term,
                limit=limit,
                clinic_id=clinic_id,
            )
            for th in tree_hits:
                # 雙重防禦檢查：確保 row.clinic_id 與 clinic_id 完全一致
                row_clinic_id = th.fields.get("clinic_id")
                if not (row_clinic_id == clinic_id):
                    continue
                if th.row_id not in seen_tree_ids:
                    seen_tree_ids.add(th.row_id)
                    clinic_trees.append({
                        "doc_id": th.fields.get("doc_id"),
                        "category": th.fields.get("category"),
                        "clinic_id": clinic_id,
                        "pre_op": mask_prices(th.fields.get("pre_op") or ""),
                        "procedure": mask_prices(th.fields.get("procedure") or ""),
                        "post_op_short": mask_prices(th.fields.get("post_op_short") or ""),
                        "maintenance": mask_prices(th.fields.get("maintenance") or ""),
                        "summary_text": mask_prices(th.fields.get("summary_text") or ""),
                        "level": "診所",
                    })
        except sqlite3.OperationalError:
            pass

    return ClinicEvidence(faq_hits=clinic_faqs, guide_hits=clinic_trees)


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


def _deterministic_fallback(
    found: GeneralConsultResult,
    intent: str,
    extra_faqs: Optional[list[dict]] = None,
    extra_guides: Optional[list[dict]] = None,
    scope: str = "procedure",
) -> Optional[str]:
    """從已核准資料萃取確定性回答，確保結構為 2～4 句並附加追問與 CTA。"""
    faqs = (extra_faqs or []) + found.faq_hits
    guides = (extra_guides or []) + found.guide_hits

    # 優先從 FAQ 答案萃取
    for h in faqs:
        ans = (h.get("answer") or "").strip()
        if not ans:
            continue

        # 1. 嘗試以句界截斷 400 字
        clipped = clip_at_sentence(ans, 400)
        assembled = assemble_answer(value=clipped, followup=None, intent=intent, scope=scope)
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
            assembled = assemble_answer(value=fallback_val, followup=None, intent=intent, scope=scope)
            if assembled:
                return sanitize_faq_text(assembled)

    # 次選從推理樹 guide_hits 萃取
    for g in guides:
        summary = (g.get("summary_text") or "").strip()
        post_op = (g.get("post_op_short") or "").strip()
        combined = f"{summary}。{post_op}" if summary and post_op else (summary or post_op)
        if combined:
            clipped = clip_at_sentence(combined, 400)
            assembled = assemble_answer(value=clipped, followup=None, intent=intent, scope=scope)
            if assembled:
                return sanitize_faq_text(assembled)

    return None


def compose_from_approved(
    conn: sqlite3.Connection,
    query: str,
    found: GeneralConsultResult,
    llm_call: Callable[[str], str],
    clinic_evidence: Optional[ClinicEvidence] = None,
) -> Optional[str]:
    """依已核准資料進行組稿，包含命中直答、LLM 組稿與確定性降級。

    回傳：符合「價值回答 2～4 句 ＋ 單一追問 ＋ 預約邀請」之完整字串，失敗時回傳 None。
    """
    q = (query or "").strip()
    if not q:
        return None

    intent = classify_intent(q)

    clinic_faqs = clinic_evidence.faq_hits if clinic_evidence else []
    clinic_guides = clinic_evidence.guide_hits if clinic_evidence else []
    all_faqs = clinic_faqs + found.faq_hits
    all_guides = clinic_guides + found.guide_hits

    # 僅在具備診所專屬證據（FAQ 或衛教指引樹）時使用 procedure 療程追問，否則走 general 中性通用追問
    scope = "procedure" if (clinic_evidence and (clinic_evidence.faq_hits or clinic_evidence.guide_hits)) else "general"

    # 1. 嘗試高信心直答（預生成核准後或既有 FAQ 命中即回，診所優先，不呼叫 LLM）
    best_faq = _evaluate_direct_shortcut(q, all_faqs)
    if best_faq is not None:
        best_ans = best_faq.get("answer") or ""
        clipped_val = clip_at_sentence(best_ans, 400)
        assembled = assemble_answer(value=clipped_val, followup=None, intent=intent, scope=scope)
        if assembled:
            return sanitize_faq_text(assembled)

    # 2. 否則建立 evidence blocks 嘗試 LLM 組稿（診所證據在前、通用證據在後）
    blocks: list[str] = []
    for i, h in enumerate(all_faqs[:5], 1):
        faq_q = clip_at_sentence(h.get("question") or "", 200)
        faq_a = clip_at_sentence(h.get("answer") or "", 400)
        lvl = f"（{h.get('level')}常見問答）" if h.get("level") else "（常見問答）"
        blocks.append(f"[F{i}]{lvl}問：{faq_q}\n答：{faq_a}")

    for i, g in enumerate(all_guides[:2], 1):
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
            lvl = f"（{g.get('level')}衛教指引：{doc_id}）" if g.get("level") else f"（衛教指引：{doc_id}）"
            blocks.append(f"[T{i}]{lvl}\n{body}")

    if not blocks:
        return _deterministic_fallback(found, intent, clinic_faqs, clinic_guides, scope=scope)

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
        return _deterministic_fallback(found, intent, clinic_faqs, clinic_guides, scope=scope)

    if not GENERATION_LOCK.acquire(blocking=False):
        return _deterministic_fallback(found, intent, clinic_faqs, clinic_guides, scope=scope)

    try:
        prompt = build_compose_prompt(q, filtered_blocks, intent)
        raw_output = llm_call(prompt)
    except Exception:
        return _deterministic_fallback(found, intent, clinic_faqs, clinic_guides, scope=scope)
    finally:
        GENERATION_LOCK.release()

    value, followup = parse_model_output(raw_output)
    if looks_insufficient(value):
        raise InsufficientEvidenceError("Model indicated insufficient evidence")
    if not is_complete_ending(value):
        return _deterministic_fallback(found, intent, clinic_faqs, clinic_guides, scope=scope)
    if followup and not is_complete_ending(followup):
        return _deterministic_fallback(found, intent, clinic_faqs, clinic_guides, scope=scope)

    ok, _ = validate_composed(value, followup)
    if not ok:
        return _deterministic_fallback(found, intent, clinic_faqs, clinic_guides, scope=scope)

    assembled = assemble_answer(value, followup, intent, scope=scope)
    if not assembled:
        return _deterministic_fallback(found, intent, clinic_faqs, clinic_guides, scope=scope)

    return sanitize_faq_text(assembled)


def decorate_general_answer(answer: str, query: str) -> str:
    """為 2.24 未審一般說明附單一追問與預約邀請，原答案少於 2 句時安全退回原 answer。"""
    intent = classify_intent(query)
    assembled = assemble_answer(value=answer, followup=None, intent=intent, scope="general")
    return assembled if assembled else answer

