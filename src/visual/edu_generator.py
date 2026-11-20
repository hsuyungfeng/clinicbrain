"""Phase 53-02: Local LLM 7 段結構化衛教生成器、合規過濾與 3 幕 IR 升級器。"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Callable

from src.api.routes.query import deep_mask_prices
from src.ingestion.convert_chinese import to_traditional
from src.pageindex.llm_client import VISUAL_SAMPLING, local_llm_call
from src.pageindex.prompt_template import _FORBIDDEN_PHRASES, _POLITICAL_STANCE_PHRASES
from src.visual.blueprints import default_params
from src.visual.edu_schema import EduContent
from src.visual.ir import VISUAL_EXTRA_FORBIDDEN, validate_ir, validate_visual_text

_DIGIT_MAP = str.maketrans("0123456789０１２３４５６７８９", "零一二三四五六七八九零一二三四五六七八九")
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _default_edu_llm(prompt: str) -> str:
    sampling = dict(VISUAL_SAMPLING)
    sampling["max_tokens"] = max(int(sampling.get("max_tokens", 1200)), 2400)
    sampling["temperature"] = 0.25
    return local_llm_call(prompt, timeout=240, sampling=sampling)


def _recursive_traditional(obj: Any) -> Any:
    if isinstance(obj, str):
        return to_traditional(obj.strip())
    if isinstance(obj, list):
        return [_recursive_traditional(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _recursive_traditional(v) for k, v in obj.items()}
    return obj


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>", 1)[1].strip()
    text = _CODE_FENCE_RE.sub("", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("LLM 回傳內容未包含合法 JSON 物件")
    return json.loads(text[start : end + 1])


def _check_edu_compliance(obj: Any) -> None:
    if isinstance(obj, str):
        for kw in _FORBIDDEN_PHRASES:
            if kw in obj:
                raise ValueError(f"衛教內容含保證療效禁詞: {kw}")
        for kw in _POLITICAL_STANCE_PHRASES:
            if kw in obj:
                raise ValueError(f"衛教內容含政治敏感詞彙: {kw}")
        return
    if isinstance(obj, list):
        for item in obj:
            _check_edu_compliance(item)
    elif isinstance(obj, dict):
        for v in obj.values():
            _check_edu_compliance(v)


def sanitize_ir_text(text: str, max_len: int | None = None) -> str:
    """將衛教文字轉為符合動畫 IR 規範之純繁體文字（無阿拉伯數字、無 %）。"""
    clean = to_traditional(str(text or "").strip())
    clean = clean.replace("%", "百分比").replace("％", "百分比")
    clean = clean.translate(_DIGIT_MAP)
    clean = re.sub(r"[<>]", "", clean)
    for kw in (*_FORBIDDEN_PHRASES, *VISUAL_EXTRA_FORBIDDEN, *_POLITICAL_STANCE_PHRASES):
        clean = clean.replace(kw, "")
    if max_len is not None and len(clean) > max_len:
        clean = clean[:max_len]
    return clean.strip()


def _clamp_ir_caption(text: str, fallback: str) -> str:
    c = sanitize_ir_text(text, max_len=118)
    if len(c) < 20:
        c = sanitize_ir_text(fallback, max_len=118)
    ok, _ = validate_visual_text(c)
    if not ok or len(c) < 20:
        return sanitize_ir_text(fallback, max_len=118)
    return c


def build_edu_prompt(topic_key: str, title: str, existing_ir: dict[str, Any]) -> str:
    """組裝 7 段結構化衛教 JSON + 3 幕動畫提示詞。"""
    s0_params = (existing_ir.get("scenes") or [{}])[0].get("params") or {}
    organ_system = s0_params.get("organ_system", "")
    anatomy_target = s0_params.get("anatomy_target") or s0_params.get("organ_label") or title
    return (
        f"你是台灣資深臨床衛教編輯醫師。請針對主題「{title}」（topic_key={topic_key}，"
        f"解剖系統={organ_system}，目標構造={anatomy_target}）生成一份給民眾閱讀的 7 段結構化衛教 JSON。\n"
        "【嚴格要求】\n"
        "1. 全程使用台灣繁體中文，語氣親切專業，絕不可出現簡體字、價格金額、或「保證有效/根治/百分之百/永久」等誇大詞彙。\n"
        "2. 僅輸出單一合法 JSON 物件，不要加任何說明文字或 Markdown。\n"
        "3. `animation_hints` 內所有文字不得包含阿拉伯數字或 % 符號（數字請改寫國字，如「三」「六」），且必須嚴格遵守字數上限：\n"
        "   - s1_trigger_label / s1_lesion_label / s1_defense_label：各 2~8 字\n"
        "   - s1_step_labels：恰好 3 項，每項 2~10 字\n"
        "   - s2_left_title / s2_right_title：各 2~8 字；s2_left_note / s2_right_note：各 2~14 字\n"
        "   - s3_care_items：3~4 項，每項 2~12 字；s3_red_flags：2~4 項，每項 2~12 字\n"
        "   - s3_myth_note：2~24 字；s3_takeaway：6~36 字\n"
        "   - s1_caption / s2_caption / s3_caption：各 22~90 字，且 s3_caption 勿與 s3_takeaway 逐字重複\n"
        "4. JSON 結構範本：\n"
        "{\n"
        f'  "topic_key": "{topic_key}",\n'
        f'  "title": "{title}",\n'
        '  "definition": {"summary": "白話定義與比喻", "anatomy_note": "解剖位置與構造說明", "key_point": "核心重點一句話"},\n'
        '  "comparison": {"left_title": "概念A/輕症/傳統", "right_title": "概念B/發炎/進階", "rows": [{"aspect": "定義", "left_value": "...", "right_value": "..."}, {"aspect": "處理", "left_value": "...", "right_value": "..."}]},\n'
        '  "causes_risks": {"flow_steps": ["誘因", "機轉變化", "結果"], "risk_factors": ["高風險族群1", "高風險因子2", "高風險因子3"]},\n'
        '  "symptoms_complications": {"symptoms": ["常見症狀1", "症狀2"], "complications": [{"name": "併發症1", "description": "簡要說明"}, {"name": "併發症2", "description": "簡要說明"}]},\n'
        '  "diagnosis": {"methods": [{"method": "檢查1", "purpose": "用途說明"}, {"method": "檢查2", "purpose": "用途說明"}]},\n'
        '  "prevention_myth": {"tips": ["衛教重點1", "衛教重點2", "衛教重點3"], "myth_buster": "破解一個常見錯誤迷思"},\n'
        '  "red_flags_takeaway": {"red_flags": ["急診警訊1", "急診警訊2"], "takeaway": "朗朗上口的一句話記牢"},\n'
        '  "animation_hints": {\n'
        '    "s1_trigger_label": "...", "s1_lesion_label": "...", "s1_defense_label": "...",\n'
        '    "s1_step_labels": ["...", "...", "..."], "s1_caption": "...",\n'
        '    "s2_left_title": "...", "s2_left_note": "...", "s2_right_title": "...", "s2_right_note": "...", "s2_caption": "...",\n'
        '    "s3_care_items": ["...", "...", "..."], "s3_red_flags": ["...", "..."],\n'
        '    "s3_myth_note": "...", "s3_takeaway": "...", "s3_caption": "..."\n'
        "  }\n"
        "}\n"
    )


def generate_edu_content(
    topic_key: str,
    title: str,
    existing_ir: dict[str, Any],
    llm_call: Callable[[str], str] | None = None,
) -> EduContent:
    """呼叫 Local LLM 生成並驗證 7 段結構化衛教資料。"""
    caller = llm_call or _default_edu_llm
    prompt = build_edu_prompt(topic_key, title, existing_ir)
    raw = caller(prompt)
    parsed = _extract_json_object(raw)
    parsed["topic_key"] = topic_key
    parsed["title"] = title
    parsed = _recursive_traditional(parsed)
    parsed = deep_mask_prices(parsed)
    _check_edu_compliance(parsed)
    return EduContent.model_validate(parsed)


def build_upgraded_ir(existing_ir: dict[str, Any], edu: EduContent) -> dict[str, Any]:
    """依 `EduContent` 升級 3 幕 IR，並強制鎖定既有 `organ_system` 與 `anatomy_target`。"""
    upgraded = copy.deepcopy(existing_ir)
    scenes = list(upgraded.get("scenes") or [])
    while len(scenes) < 3:
        scenes.append({})

    hints = edu.animation_hints

    # Scene 1: 若原為 pathology_mechanism 則精準化標籤並鎖定解剖；若為醫美/手術專用藍圖則完整保留原藍圖與參數
    s1 = copy.deepcopy(scenes[0]) if isinstance(scenes[0], dict) else {}
    orig_bp1 = s1.get("blueprint") or "pathology_mechanism"
    if orig_bp1 == "pathology_mechanism":
        s1_def = default_params("pathology_mechanism")
        old_p1 = s1.get("params") if isinstance(s1.get("params"), dict) else {}
        p1 = {**s1_def, **old_p1}
        p1["trigger_label"] = sanitize_ir_text(hints.s1_trigger_label, 8) or s1_def["trigger_label"]
        p1["lesion_label"] = sanitize_ir_text(hints.s1_lesion_label, 8) or s1_def["lesion_label"]
        p1["defense_label"] = sanitize_ir_text(hints.s1_defense_label, 8) or s1_def["defense_label"]
        steps = [sanitize_ir_text(x, 10) or d for x, d in zip(hints.s1_step_labels, s1_def["step_labels"])]
        p1["step_labels"] = steps
        # 鎖定 Phase 52 已核定解剖欄位
        if "organ_system" in old_p1:
            p1["organ_system"] = old_p1["organ_system"]
        if "anatomy_target" in old_p1:
            p1["anatomy_target"] = old_p1["anatomy_target"]
        if "organ_label" in old_p1:
            p1["organ_label"] = old_p1["organ_label"]

        s1["blueprint"] = "pathology_mechanism"
        s1["title"] = sanitize_ir_text(s1.get("title") or "病理機轉與成因", 16) or "病理機轉與成因"
        s1["caption"] = _clamp_ir_caption(
            hints.s1_caption,
            f"{sanitize_ir_text(edu.title, 14)}涉及局部組織受損與發炎反應，建議及早就醫檢查。",
        )
        s1["labels"] = [
            {"text": sanitize_ir_text(p1["trigger_label"], 12) or "致病誘因", "tone": "warning"},
            {"text": sanitize_ir_text(p1["defense_label"], 12) or "組織修復", "tone": "optimal"},
        ]
        s1["duration_sec"] = s1.get("duration_sec", 8.0)
        s1["params"] = p1

    # Scene 2: contrast（呈現病症／處置對照，保留既有 mode 與版面設定）
    s2 = copy.deepcopy(scenes[1]) if isinstance(scenes[1], dict) else {}
    p2 = default_params("contrast")
    old_p2 = s2.get("params") if isinstance(s2.get("params"), dict) else {}
    for k in ("left", "right"):
        if isinstance(old_p2.get(k), dict):
            p2[k].update(old_p2[k])
    if "contrast_layout" in old_p2:
        p2["contrast_layout"] = old_p2["contrast_layout"]
    p2["left"]["title"] = sanitize_ir_text(hints.s2_left_title, 8) or p2["left"]["title"]
    p2["left"]["note"] = sanitize_ir_text(hints.s2_left_note, 14) or p2["left"]["note"]
    p2["right"]["title"] = sanitize_ir_text(hints.s2_right_title, 8) or p2["right"]["title"]
    p2["right"]["note"] = sanitize_ir_text(hints.s2_right_note, 14) or p2["right"]["note"]

    s2["blueprint"] = "contrast"
    s2["title"] = sanitize_ir_text("病症與處置對照", 16)
    s2["caption"] = _clamp_ir_caption(
        hints.s2_caption,
        "不同階段或處置方式各有重點，早期辨識差異有助與醫師共同擬定合適照護。",
    )
    s2["labels"] = [
        {"text": sanitize_ir_text(p2["left"]["title"], 12) or "初期觀察", "tone": "neutral"},
        {"text": sanitize_ir_text(p2["right"]["title"], 12) or "進階評估", "tone": "warning"},
    ]
    s2["duration_sec"] = s2.get("duration_sec", 8.0)
    s2["params"] = p2

    # Scene 3: care_redflag（衛教行動與急診紅旗警訊）
    s3_def = default_params("care_redflag")

    def _safe_ir_item(raw: str, max_len: int, fallback: str) -> str:
        txt = sanitize_ir_text(raw, max_len)
        if not txt:
            return fallback
        ok, _ = validate_visual_text(txt)
        return txt if ok else fallback

    care_items = [
        _safe_ir_item(x, 12, s3_def["care_items"][i % len(s3_def["care_items"])])
        for i, x in enumerate(hints.s3_care_items[:4])
    ]
    while len(care_items) < 3:
        care_items.append(s3_def["care_items"][len(care_items)])

    red_flags = [
        _safe_ir_item(x, 12, s3_def["red_flags"][i % len(s3_def["red_flags"])])
        for i, x in enumerate(hints.s3_red_flags[:4])
    ]
    while len(red_flags) < 2:
        red_flags.append(s3_def["red_flags"][len(red_flags)])

    p3 = {
        "care_items": care_items,
        "red_flags": red_flags,
        "myth_note": _safe_ir_item(hints.s3_myth_note, 24, s3_def["myth_note"]),
        "takeaway": _safe_ir_item(hints.s3_takeaway, 36, s3_def["takeaway"]),
        "urgency_level": 4,
    }
    s3 = {
        "blueprint": "care_redflag",
        "title": "日常衛教與急診紅旗",
        "caption": _clamp_ir_caption(
            hints.s3_caption,
            "落實日常保養有助降低復發風險，若出現異常紅旗症狀請立即就醫檢查。",
        ),
        "labels": [
            {"text": "日常預防", "tone": "optimal"},
            {"text": "急診紅旗", "tone": "warning"},
        ],
        "duration_sec": 8.0,
        "params": p3,
    }

    upgraded["scenes"] = [s1, s2, s3]
    ok, err = validate_ir(upgraded)
    if not ok:
        raise ValueError(f"升級後 IR 未通過 validate_ir(): {err}")
    return upgraded
