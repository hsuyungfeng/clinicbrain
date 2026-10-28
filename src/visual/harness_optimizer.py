"""ClinicBrain Native Harness²：任務級與治理級雙層遞迴優化模組 (Phase 36)。

設計原則：
1. 任務級遞迴：`score_visual_ir_alignment` 在 `validate_ir` 硬防線通過後，針對教訓合規、臨床詞彙專一性、
   三幕敘事差異與醫師手札對齊度做 0.0～1.0 定量評分；`build_alignment_critique_prompt` 將落差轉為精煉提示。
2. 治理級遞迴：`data/visual/harness_lessons.json` 為跨任務經驗記憶庫；`select_lessons_for_tree` 依推理樹內容
   命中教訓並注入 Prompt；`record_review_lesson` 於 V2 取代 V1 時沉澱新教訓（同 lesson_id 冪等更新）。
3. 純本地、零外部依賴：本模組不呼叫 LLM、不連線資料庫；寫檔僅限 harness_lessons.json（可由參數指定路徑）。
4. 所有評分理由、建議與沉澱之教訓皆為繁體中文，教訓欄位不含阿拉伯數字。
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.visual.ir import validate_ir

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LESSONS_PATH = PROJECT_ROOT / "data" / "visual" / "harness_lessons.json"

ALIGNMENT_THRESHOLD = 0.85
EXCELLENT_THRESHOLD = 0.88
WEIGHTS = {
    "lesson_compliance": 0.35,
    "lexical_specificity": 0.30,
    "scene_diversity": 0.20,
    "physician_note_alignment": 0.15,
}

# 罐頭泛用詞：命中即扣分（模板殘留的典型特徵）
GENERIC_PHRASES: tuple[str, ...] = (
    "重要標籤", "標籤一", "標籤二", "標籤三",
    "步驟一", "步驟二", "步驟三",
    "第一階段", "第二階段", "第三階段",
    "問題狀態", "建議方案",
)

# 二字詞停用集合：不具臨床專一性的通用詞
_STOP_BIGRAMS: frozenset[str] = frozenset({
    "治療", "手術", "患者", "醫師", "照護", "術後", "術前", "注意", "方法", "可以", "需要", "進行",
    "過程", "效果", "因人", "評估", "說明", "身體", "時間", "實際", "維持", "進程", "定期", "調整",
    "建議", "方式", "問題", "使用", "作用", "狀態", "改善", "提供", "相關", "包括", "其中", "以及",
    "並且", "透過", "避免", "加強", "結果", "醫療", "專業", "診所", "醫生", "當面", "個人", "階段",
    "標籤", "步驟", "重要", "項目", "內容", "完成", "過後", "之後", "期間", "情況", "變化", "發生",
})

_CJK_BIGRAM_RE = re.compile(r"[一-鿿]{2}")
_DIGIT_RE = re.compile(r"\d")
_TREE_TEXT_FIELDS = ("title", "summary_text", "pre_op", "procedure", "post_op_short", "maintenance")
_NOTE_FIELDS = ("pre_op_physician_notes", "procedure_physician_notes",
                "post_op_short_physician_notes", "maintenance_physician_notes")


# ---------------------------------------------------------------------------
# 教訓載入與匹配
# ---------------------------------------------------------------------------

def _empty_store() -> dict[str, Any]:
    return {"version": 1, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "lessons": []}


def load_harness_lessons(path: Optional[Path] = None) -> list[dict[str, Any]]:
    """讀取治理教訓清單；檔案不存在或結構損毀時安全回傳空清單（不拋例外、不阻斷生成）。"""
    target = Path(path) if path is not None else DEFAULT_LESSONS_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    lessons = data.get("lessons") if isinstance(data, dict) else None
    if not isinstance(lessons, list):
        return []
    return [item for item in lessons if isinstance(item, dict) and item.get("lesson_id")]


def _tree_text(tree: dict[str, Any]) -> str:
    parts = []
    for key in _TREE_TEXT_FIELDS + _NOTE_FIELDS:
        val = tree.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    return "\n".join(parts)


def select_lessons_for_tree(
    tree: dict[str, Any],
    lessons: Optional[list[dict[str, Any]]] = None,
    max_lessons: int = 3,
) -> list[dict[str, Any]]:
    """依推理樹文字命中 match_terms 數量，回傳最相關的前 max_lessons 條教訓（命中數 0 者不回傳）。"""
    pool = lessons if lessons is not None else load_harness_lessons()
    text = _tree_text(tree) + "\n" + str(tree.get("doc_id") or "")
    text_lower = text.lower()
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for lesson in pool:
        hits = sum(1 for term in lesson.get("match_terms", []) if term and term.lower() in text_lower)
        if hits > 0:
            scored.append((hits, str(lesson.get("lesson_id")), lesson))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[: max(0, max_lessons)]]


def format_lessons_for_prompt(lessons: list[dict[str, Any]]) -> str:
    """將命中的治理教訓格式化為 Prompt 防護欄區塊；無教訓時回傳空字串。"""
    if not lessons:
        return ""
    lines = ["【Harness² 跨任務治理經驗防護欄（請嚴格遵守）】"]
    for idx, lesson in enumerate(lessons, start=1):
        lines.append(f"經驗{_cn_index(idx)}：{lesson.get('rule', '')}")
        pos = lesson.get("positive_terms") or []
        if pos:
            lines.append("  建議詞彙：" + "、".join(pos))
        neg = lesson.get("negative_terms") or []
        if neg:
            lines.append("  禁用跨科別錯置詞彙：" + "、".join(neg))
        bp = lesson.get("preferred_blueprint")
        if bp:
            lines.append(f"  第一幕建議藍圖：{bp}")
    return "\n".join(lines)


def _cn_index(n: int) -> str:
    return {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}.get(n, str(n))


# ---------------------------------------------------------------------------
# 臨床對齊評分器
# ---------------------------------------------------------------------------

def _ir_visible_text(ir: dict[str, Any]) -> str:
    """串接 IR 中所有可見文字（不含 topic_key 等機器識別碼）。"""
    parts: list[str] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, str):
            parts.append(obj)
        elif isinstance(obj, dict):
            for key, value in obj.items():
                if key != "topic_key":
                    walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk({k: v for k, v in ir.items() if k != "topic_key"})
    return "\n".join(parts)


def _top_bigrams(text: str, limit: int) -> list[str]:
    counts: dict[str, int] = {}
    for gram in _CJK_BIGRAM_RE.findall(text):
        if gram in _STOP_BIGRAMS:
            continue
        counts[gram] = counts.get(gram, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [gram for gram, _ in ranked[:limit]]


def _scene1_blueprint(ir: dict[str, Any]) -> str:
    scenes = ir.get("scenes") or []
    return str(scenes[0].get("blueprint")) if scenes and isinstance(scenes[0], dict) else ""


def score_visual_ir_alignment(
    tree: dict[str, Any],
    ir: dict[str, Any],
    lessons: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """對已通過 validate_ir 的 IR 做臨床語意與視覺品質評分（0.0～1.0）。"""
    penalties: list[str] = []
    suggestions: list[str] = []

    ok, code = validate_ir(ir)
    if not ok:
        penalties.append(f"未通過 validate_ir（{code}），不予評分")
        return {
            "score": 0.0,
            "passed_threshold": False,
            "penalties": penalties,
            "suggestions": ["請先修正結構與合規錯誤後再評分"],
            "breakdown": {k: 0.0 for k in WEIGHTS},
        }

    ir_text = _ir_visible_text(ir)
    matched = lessons if lessons is not None else select_lessons_for_tree(tree)

    # A. 教訓合規度
    neg_hits: list[tuple[str, str]] = []
    pos_union: list[str] = []
    for lesson in matched:
        lid = str(lesson.get("lesson_id"))
        for term in lesson.get("negative_terms") or []:
            if term and term in ir_text:
                neg_hits.append((lid, term))
        for term in lesson.get("positive_terms") or []:
            if term and term not in pos_union:
                pos_union.append(term)
    for lid, term in neg_hits:
        penalties.append(f"誤觸教訓禁用詞「{term}」（{lid}）")
    if matched:
        neg_factor = max(0.0, 1.0 - 0.3 * len(neg_hits))
        pos_hits = [t for t in pos_union if t in ir_text]
        pos_cov = len(pos_hits) / len(pos_union) if pos_union else 1.0
        compliance = 0.6 * neg_factor + 0.4 * pos_cov
        missing = [t for t in pos_union if t not in pos_hits]
        if missing:
            suggestions.append("建議補入教訓重點詞彙：" + "、".join(missing[:3]))
        preferred = {str(l.get("preferred_blueprint")) for l in matched if l.get("preferred_blueprint")}
        if preferred and _scene1_blueprint(ir) not in preferred:
            suggestions.append("建議第一幕改用教訓指定藍圖：" + "、".join(sorted(preferred)))
    else:
        compliance = 1.0

    # B. 臨床詞彙專一性
    tree_core = " ".join(str(tree.get(k) or "") for k in _TREE_TEXT_FIELDS)
    tree_terms = _top_bigrams(tree_core, 12)
    if tree_terms:
        coverage = sum(1 for t in tree_terms if t in ir_text) / len(tree_terms)
        lexical = min(1.0, coverage / 0.6)
        if coverage < 0.6:
            suggestions.append("建議於標題、說明與標籤中引用推理樹的具體臨床詞彙")
    else:
        lexical = 1.0
    generic_found = [p for p in GENERIC_PHRASES if p in ir_text]
    for phrase in generic_found:
        penalties.append(f"出現罐頭泛用詞「{phrase}」")
    if generic_found:
        suggestions.append("請以具體臨床用語取代罐頭標籤（如「重要標籤」「步驟一」「第一階段」）")
    lexical = max(0.0, lexical - 0.25 * len(generic_found))

    # C. 三幕敘事差異與豐富度
    scenes = ir["scenes"]
    titles = [s["title"] for s in scenes]
    distinct = len(set(titles)) / len(scenes)
    len_factor = sum(min(1.0, len(s["caption"]) / 32.0) for s in scenes) / len(scenes)
    for idx, s in enumerate(scenes, start=1):
        if len(s["caption"]) < 32:
            penalties.append(f"第{_cn_index(idx)}幕說明文字過短（不足三十二字）")
    label_factor = sum(min(1.0, len(s["labels"]) / 2.0) for s in scenes) / len(scenes)
    sim_penalty = 0.0
    for i in range(len(scenes)):
        for j in range(i + 1, len(scenes)):
            ratio = difflib.SequenceMatcher(None, scenes[i]["caption"], scenes[j]["caption"]).ratio()
            if ratio >= 0.8:
                sim_penalty += 0.2
                penalties.append(f"第{_cn_index(i + 1)}幕與第{_cn_index(j + 1)}幕說明高度重複")
    diversity = max(0.0, 0.4 * distinct + 0.4 * len_factor + 0.2 * label_factor - sim_penalty)
    if len_factor < 1.0:
        suggestions.append("建議各幕說明至少三十二字，寫出具體的機轉或照護差異")

    # D. 醫師手札對齊度
    note_text = "\n".join(str(tree.get(k) or "") for k in _NOTE_FIELDS)
    note_terms = _top_bigrams(note_text, 15) if note_text.strip() else []
    if note_terms:
        note_cov = sum(1 for t in note_terms if t in ir_text) / len(note_terms)
        physician = min(1.0, note_cov / 0.5)
        if note_cov < 0.3:
            penalties.append("醫師手札重點覆蓋不足")
            suggestions.append("建議將醫師手札的核心詞彙反映於視覺解說卡的說明或標籤")
    else:
        physician = 1.0

    breakdown = {
        "lesson_compliance": round(compliance, 4),
        "lexical_specificity": round(lexical, 4),
        "scene_diversity": round(diversity, 4),
        "physician_note_alignment": round(physician, 4),
    }
    score = sum(WEIGHTS[k] * breakdown[k] for k in WEIGHTS)
    score = round(min(1.0, max(0.0, score)), 4)
    return {
        "score": score,
        "passed_threshold": score >= ALIGNMENT_THRESHOLD,
        "penalties": penalties,
        "suggestions": suggestions,
        "breakdown": breakdown,
    }


# ---------------------------------------------------------------------------
# 任務級精煉提示詞
# ---------------------------------------------------------------------------

def build_alignment_critique_prompt(
    base_prompt: str,
    candidate_ir: dict[str, Any],
    score_report: dict[str, Any],
) -> str:
    """將上一輪合法但分數未達標的候選，轉為針對弱點的繁體中文重繪提示詞。"""
    score = float(score_report.get("score", 0.0))
    lines = [
        "【任務級遞迴精煉】上一輪候選通過結構驗證，但臨床對齊分數為 "
        f"{score:.2f}（優異門檻 {EXCELLENT_THRESHOLD}），請針對下列落差重新生成。",
        f"上一輪標題：{candidate_ir.get('title', '')}",
        f"上一輪第一幕藍圖：{_scene1_blueprint(candidate_ir)}",
    ]
    penalties = score_report.get("penalties") or []
    if penalties:
        lines.append("具體扣分原因：")
        lines.extend(f"- {p}" for p in penalties)
    suggestions = score_report.get("suggestions") or []
    if suggestions:
        lines.append("改進建議：")
        lines.extend(f"- {s}" for s in suggestions)
    lines.append(
        "請維持相同的 JSON 結構與所有合規限制（零阿拉伯數字、字數上限、禁用保證療效詞彙），"
        "並讓標題、說明與標籤直接引用推理樹的具體臨床詞彙，不得使用罐頭標籤。"
    )
    return base_prompt + "\n\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# 治理級經驗沉澱
# ---------------------------------------------------------------------------

def _step_labels(ir: dict[str, Any]) -> list[str]:
    scenes = ir.get("scenes") or []
    if not scenes or not isinstance(scenes[0], dict):
        return []
    params = scenes[0].get("params") or {}
    steps = params.get("step_labels") if isinstance(params, dict) else None
    return [s for s in steps or [] if isinstance(s, str)]


def _clean_terms(items: list[str], limit: int) -> list[str]:
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        term = item.strip()
        if 2 <= len(term) <= 12 and not _DIGIT_RE.search(term) and term not in out:
            out.append(term)
        if len(out) >= limit:
            break
    return out


def record_review_lesson(
    rejected_ir: dict[str, Any],
    approved_ir: dict[str, Any],
    *,
    topic_key: str,
    title: str = "",
    path: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """V2 取代 V1 且第一幕藍圖或關鍵詞／步驟用語有實質差異時，提煉並冪等寫入一條治理教訓。

    無實質差異回傳 None（不寫檔）。同一 (topic_key, 舊藍圖, 新藍圖) 組合固定 lesson_id，重跑為冪等更新。
    """
    old_bp = _scene1_blueprint(rejected_ir)
    new_bp = _scene1_blueprint(approved_ir)
    old_kw = [k for k in rejected_ir.get("keywords") or [] if isinstance(k, str)]
    new_kw = [k for k in approved_ir.get("keywords") or [] if isinstance(k, str)]
    old_steps = _step_labels(rejected_ir)
    new_steps = _step_labels(approved_ir)

    bp_changed = old_bp != new_bp
    kw_changed = set(old_kw) != set(new_kw)
    steps_changed = set(old_steps) != set(new_steps)
    if not (bp_changed or kw_changed or steps_changed):
        return None

    digest = hashlib.sha1(f"{topic_key}|{old_bp}|{new_bp}".encode("utf-8")).hexdigest()[:12]
    lesson_id = f"lesson-review-{digest}"

    if bp_changed:
        rule = (f"經醫師審核，本主題第一幕由 {old_bp} 改為 {new_bp}，同類主題應優先沿用審核後的器官結構與用語。")
    else:
        rule = "經醫師審核修訂用語，同類主題應優先沿用審核後的關鍵詞與步驟用語，避免沿用被取代的表述。"

    lesson = {
        "lesson_id": lesson_id,
        "scope": "review_promotion",
        "match_terms": _clean_terms(new_kw, 6) or _clean_terms([title], 1),
        "preferred_blueprint": new_bp,
        "rule": rule,
        "negative_terms": _clean_terms([k for k in old_kw if k not in new_kw], 4),
        "positive_terms": _clean_terms(new_steps + [k for k in new_kw if k not in old_kw], 6),
        "origin": "review_promotion",
        "topic_key": topic_key,
    }

    target = Path(path) if path is not None else DEFAULT_LESSONS_PATH
    try:
        store = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(store, dict) or not isinstance(store.get("lessons"), list):
            store = _empty_store()
    except (OSError, ValueError):
        store = _empty_store()

    lessons = [item for item in store["lessons"] if item.get("lesson_id") != lesson_id]
    lessons.append(lesson)
    store["lessons"] = lessons
    store["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return lesson
