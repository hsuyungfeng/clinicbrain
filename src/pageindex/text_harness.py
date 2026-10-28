"""Text Native Harness²：將雙層遞迴馬具擴展至 FAQ 答案生成與臨床推理樹提煉 (Phase 37 選項 B)。

與視覺版（src/visual/harness_optimizer.py）共用同一份治理教訓庫 data/visual/harness_lessons.json，
但文字版不注入 preferred_blueprint（純文字生成不涉及藍圖）。

設計原則：
1. 純本地、無外部依賴：不呼叫 LLM、不寫資料庫；評分與提示詞皆為純函式。
2. 教訓合規共用：FAQ 與推理樹評分共用 _lesson_compliance，禁用詞誤觸扣分、正向詞涵蓋加分只定義一次。
3. 所有扣分理由與建議皆為繁體中文。
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Optional

from src.visual.harness_optimizer import load_harness_lessons

TEXT_ALIGNMENT_THRESHOLD = 0.85
EXCELLENT_THRESHOLD = 0.88

_CJK_BIGRAM_RE = re.compile(r"[一-鿿]{2}")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?]+")
_DIGIT_RE = re.compile(r"\d")

# 二字詞停用集合（與視覺版一致的衛教通用詞，另補充 FAQ 常見口語詞）
_STOP_BIGRAMS: frozenset[str] = frozenset({
    "治療", "手術", "患者", "醫師", "照護", "術後", "術前", "注意", "方法", "可以", "需要", "進行",
    "過程", "效果", "因人", "評估", "說明", "身體", "時間", "實際", "維持", "進程", "定期", "調整",
    "建議", "方式", "問題", "使用", "作用", "狀態", "改善", "提供", "相關", "包括", "其中", "以及",
    "並且", "透過", "避免", "加強", "結果", "醫療", "專業", "診所", "醫生", "當面", "個人", "階段",
    "標籤", "步驟", "重要", "項目", "內容", "完成", "過後", "之後", "期間", "情況", "變化", "發生",
    "什麼", "如何", "哪些", "是否", "會有", "還是", "一般", "常見", "出現", "或是", "如果", "就是",
})

FAQ_LENGTH_MIN = 150
FAQ_LENGTH_MAX = 350
FAQ_MIN_SENTENCES = 3
TREE_SEGMENT_MIN_CHARS = 45
TREE_SEGMENT_SIMILARITY_CAP = 0.75
TREE_SEGMENT_KEYS = ("pre_op", "procedure", "post_op_short", "maintenance")


# ---------------------------------------------------------------------------
# 教訓匹配與提示詞注入
# ---------------------------------------------------------------------------

def select_text_lessons(
    text: str,
    lessons: Optional[list[dict[str, Any]]] = None,
    max_lessons: int = 2,
) -> list[dict[str, Any]]:
    """依輸入文字（問題+主題 或 標題+內文）命中 match_terms 的數量，回傳最相關的教訓。"""
    pool = lessons if lessons is not None else load_harness_lessons()
    haystack = (text or "").lower()
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for lesson in pool:
        hits = sum(1 for term in lesson.get("match_terms") or [] if term and term.lower() in haystack)
        if hits > 0:
            scored.append((hits, str(lesson.get("lesson_id")), lesson))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[: max(0, max_lessons)]]


def format_text_lessons_for_prompt(lessons: list[dict[str, Any]]) -> str:
    """產出純文字生成用防護欄（含 rule、建議詞彙、禁用詞；不含藍圖欄位）。無教訓時回傳空字串。"""
    if not lessons:
        return ""
    lines = ["【跨任務治理經驗防護欄（請嚴格遵守）】"]
    for idx, lesson in enumerate(lessons, start=1):
        lines.append(f"經驗{_cn_index(idx)}：{lesson.get('rule', '')}")
        pos = lesson.get("positive_terms") or []
        if pos:
            lines.append("  建議詞彙：" + "、".join(pos))
        neg = lesson.get("negative_terms") or []
        if neg:
            lines.append("  禁用跨科別錯置詞彙：" + "、".join(neg))
    return "\n".join(lines)


def _cn_index(n: int) -> str:
    return {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}.get(n, str(n))


# ---------------------------------------------------------------------------
# 共用評分組件
# ---------------------------------------------------------------------------

def _top_bigrams(text: str, limit: int) -> list[str]:
    counts: dict[str, int] = {}
    for gram in _CJK_BIGRAM_RE.findall(text or ""):
        if gram in _STOP_BIGRAMS:
            continue
        counts[gram] = counts.get(gram, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [gram for gram, _ in ranked[:limit]]


def _lesson_compliance(
    lessons: list[dict[str, Any]],
    body: str,
    penalties: list[str],
    suggestions: list[str],
) -> float:
    """誤觸 negative_terms 扣分、涵蓋 positive_terms 加分；無命中教訓則滿分。"""
    if not lessons:
        return 1.0
    neg_hits: list[tuple[str, str]] = []
    pos_union: list[str] = []
    for lesson in lessons:
        lid = str(lesson.get("lesson_id"))
        for term in lesson.get("negative_terms") or []:
            if term and term in body:
                neg_hits.append((lid, term))
        for term in lesson.get("positive_terms") or []:
            if term and term not in pos_union:
                pos_union.append(term)
    for lid, term in neg_hits:
        penalties.append(f"誤觸教訓禁用詞「{term}」（{lid}）")
    pos_hits = [t for t in pos_union if t in body]
    pos_cov = len(pos_hits) / len(pos_union) if pos_union else 1.0
    missing = [t for t in pos_union if t not in pos_hits]
    if missing:
        suggestions.append("建議補入教訓重點詞彙：" + "、".join(missing[:3]))
    neg_factor = max(0.0, 1.0 - 0.3 * len(neg_hits))
    return 0.6 * neg_factor + 0.4 * pos_cov


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text or "") if s.strip()]


# ---------------------------------------------------------------------------
# FAQ 答案對齊評分與精煉
# ---------------------------------------------------------------------------

def score_faq_answer_alignment(
    question: str,
    topic: str,
    answer: str,
    lessons: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """對已通過合規檢驗的 FAQ 答案評分（0.0～1.0）。

    lesson_compliance (0.40) ＋ question_relevance (0.35) ＋ structure_quality (0.25)。
    """
    penalties: list[str] = []
    suggestions: list[str] = []
    body = answer or ""
    matched = lessons if lessons is not None else select_text_lessons(f"{question}\n{topic}")

    compliance = _lesson_compliance(matched, body, penalties, suggestions)

    # question_relevance：問題與主題的二字詞，在答案中的覆蓋率
    q_terms = _top_bigrams(f"{question} {topic}", 12)
    if q_terms:
        coverage = sum(1 for t in q_terms if t in body) / len(q_terms)
        relevance = min(1.0, coverage / 0.5)
        if coverage < 0.5:
            suggestions.append("建議答案直接回應問題中的核心詞彙")
    else:
        relevance = 1.0

    # structure_quality：長度落在 150～350 字、至少三句、無重複句
    length = len(body)
    if FAQ_LENGTH_MIN <= length <= FAQ_LENGTH_MAX:
        len_factor = 1.0
    else:
        dist = FAQ_LENGTH_MIN - length if length < FAQ_LENGTH_MIN else length - FAQ_LENGTH_MAX
        len_factor = max(0.0, 1.0 - dist / 150.0)
        penalties.append(f"答案長度 {length} 字，超出建議範圍（150～350 字）")
        suggestions.append("建議答案長度落在 150～350 字之間")
    sentences = _split_sentences(body)
    sent_factor = min(1.0, len(sentences) / FAQ_MIN_SENTENCES)
    if len(sentences) < FAQ_MIN_SENTENCES:
        penalties.append("答案句子數不足（少於三句）")
        suggestions.append("建議以三句以上完整敘述說明重點")
    seen: set[str] = set()
    has_dup = False
    for sent in sentences:
        if len(sent) > 4 and sent in seen:
            has_dup = True
        seen.add(sent)
    if has_dup:
        penalties.append("答案含重複句")
        suggestions.append("請刪除重複句並改寫為不同內容")
    structure = 0.5 * len_factor + 0.3 * sent_factor + 0.2 * (0.0 if has_dup else 1.0)

    score = round(min(1.0, max(0.0, 0.40 * compliance + 0.35 * relevance + 0.25 * structure)), 4)
    return {
        "score": score,
        "passed_threshold": score >= TEXT_ALIGNMENT_THRESHOLD,
        "penalties": penalties,
        "suggestions": suggestions,
        "breakdown": {
            "lesson_compliance": round(compliance, 4),
            "question_relevance": round(relevance, 4),
            "structure_quality": round(structure, 4),
        },
    }


def build_faq_critique_prompt(base_prompt: str, candidate_answer: str, score_report: dict[str, Any]) -> str:
    """將上一輪合法但分數未達標的答案，轉為針對弱點的任務級精煉提示詞。"""
    score = float(score_report.get("score", 0.0))
    lines = [
        f"【任務級遞迴精煉】上一輪答案通過合規檢驗，但對齊分數為 {score:.2f}"
        f"（優異門檻 {EXCELLENT_THRESHOLD}），請針對下列落差重新撰寫。",
        f"上一輪答案摘要：{(candidate_answer or '')[:80]}",
    ]
    penalties = score_report.get("penalties") or []
    if penalties:
        lines.append("具體扣分原因：")
        lines.extend(f"- {p}" for p in penalties)
    suggestions = score_report.get("suggestions") or []
    if suggestions:
        lines.append("改進建議：")
        lines.extend(f"- {s}" for s in suggestions)
    lines.append("請維持所有合規限制（不得出現金額、藥品劑量、保證療效用語與阿拉伯數字），並保留最後一句就醫警訊。")
    return base_prompt + "\n\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# 推理樹四段式提煉對齊評分與精煉
# ---------------------------------------------------------------------------

def score_tree_distillation_alignment(
    title: str,
    source_text: str,
    tree_data: dict[str, Any],
    lessons: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """對已通過 validate_tree_segment 的四段式推理樹評分（0.0～1.0）。

    lesson_compliance (0.35) ＋ source_specificity (0.30) ＋ stage_diversity (0.35)。
    """
    penalties: list[str] = []
    suggestions: list[str] = []
    segments = {k: str(tree_data.get(k) or "") for k in TREE_SEGMENT_KEYS}
    body = "\n".join(segments.values())
    matched = lessons if lessons is not None else select_text_lessons(f"{title}\n{source_text}")

    compliance = _lesson_compliance(matched, body, penalties, suggestions)

    # source_specificity：來源文字核心二字詞在四段中的覆蓋率
    src_terms = _top_bigrams(source_text, 15)
    if src_terms:
        coverage = sum(1 for t in src_terms if t in body) / len(src_terms)
        specificity = min(1.0, coverage / 0.4)
        if coverage < 0.4:
            penalties.append("四段內容對來源文字的臨床詞彙覆蓋不足")
            suggestions.append("建議四段中引用來源文件的具體臨床詞彙")
    else:
        specificity = 1.0

    # stage_diversity：四段兩兩相似度（>= 0.75 扣分）與各段字數充實度（>= 45 字）
    keys = list(TREE_SEGMENT_KEYS)
    similar_pairs = 0
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            ratio = difflib.SequenceMatcher(None, segments[keys[i]], segments[keys[j]]).ratio()
            if ratio >= TREE_SEGMENT_SIMILARITY_CAP:
                similar_pairs += 1
                penalties.append(f"「{keys[i]}」與「{keys[j]}」內容高度相似（相似度過高）")
    if similar_pairs:
        suggestions.append("請讓四個臨床階段各自描述不同重點，避免複製貼上")
    len_factor = sum(min(1.0, len(segments[k]) / TREE_SEGMENT_MIN_CHARS) for k in keys) / len(keys)
    for k in keys:
        if len(segments[k]) < TREE_SEGMENT_MIN_CHARS:
            penalties.append(f"「{k}」字數不足（少於 {TREE_SEGMENT_MIN_CHARS} 字）")
    if len_factor < 1.0:
        suggestions.append(f"建議每段至少 {TREE_SEGMENT_MIN_CHARS} 字，寫出具體內容")
    dup_factor = 1.0 - similar_pairs / 6.0
    diversity = max(0.0, 0.5 * dup_factor + 0.5 * len_factor)

    score = round(min(1.0, max(0.0, 0.35 * compliance + 0.30 * specificity + 0.35 * diversity)), 4)
    return {
        "score": score,
        "passed_threshold": score >= TEXT_ALIGNMENT_THRESHOLD,
        "penalties": penalties,
        "suggestions": suggestions,
        "breakdown": {
            "lesson_compliance": round(compliance, 4),
            "source_specificity": round(specificity, 4),
            "stage_diversity": round(diversity, 4),
        },
    }


def build_tree_critique_prompt(base_prompt: str, candidate_tree: dict[str, Any], score_report: dict[str, Any]) -> str:
    """將上一輪合法但分數未達標的推理樹，轉為針對弱點的任務級精煉提示詞。"""
    score = float(score_report.get("score", 0.0))
    lines = [
        f"【任務級遞迴精煉】上一輪推理樹通過結構驗證，但提煉對齊分數為 {score:.2f}"
        f"（優異門檻 {EXCELLENT_THRESHOLD}），請針對下列落差重新提煉。",
        "上一輪四段摘要（僅供參考，請勿照抄）：",
    ]
    for key in TREE_SEGMENT_KEYS:
        val = str(candidate_tree.get(key) or "")
        lines.append(f"- {key}：{val[:40]}")
    penalties = score_report.get("penalties") or []
    if penalties:
        lines.append("具體扣分原因：")
        lines.extend(f"- {p}" for p in penalties)
    suggestions = score_report.get("suggestions") or []
    if suggestions:
        lines.append("改進建議：")
        lines.extend(f"- {s}" for s in suggestions)
    lines.append("請維持 JSON 格式與合規限制，讓四個階段各自獨立且不重複，並引用來源文件的具體臨床詞彙。")
    return base_prompt + "\n\n" + "\n".join(lines)
