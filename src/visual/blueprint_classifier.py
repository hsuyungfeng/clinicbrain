"""
Phase 57: LLM 動畫第一幕藍圖分類器模組 (src/visual/blueprint_classifier.py).

設計原則：
1. 藍圖列舉限制：從 VALID_SCENE1_BLUEPRINTS (定義於 src.visual.autodraft_ir) 加上 'other' 選一個。
2. 證據片段檢驗：依據 agy D1，比對前執行空白與全半形標點正規化，確保模型不是無中生有。
3. 嚴謹可信度門檻：若 blueprint 為 'other'、confidence < 0.6 或 evidence 無效，標記為 needs_review 或 invalid_evidence，不進自動發布。
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Optional, Tuple

from src.visual.autodraft_ir import VALID_SCENE1_BLUEPRINTS

CLASSIFIER_ALLOWED_BLUEPRINTS: tuple[str, ...] = VALID_SCENE1_BLUEPRINTS + ("other",)
DEFAULT_CONFIDENCE_THRESHOLD = 0.6

# 正規化正則：去除空白字元與常見中英文全半形標點符號
_PUNCT_AND_SPACE_RE = re.compile(
    r"[\s\r\n\t\u3000-\u303f\uff00-\uffef!\"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~]"
)


def normalize_text_for_comparison(text: str) -> str:
    """去除所有空白字元與全半形標點，供證據片段子字串容錯比對。"""
    if not text:
        return ""
    return _PUNCT_AND_SPACE_RE.sub("", text)


def is_evidence_in_source(source_text: str, evidence_span: str) -> bool:
    """檢驗 evidence_span 是否為 source_text 之子字串（正規化比對）。"""
    if not source_text or not evidence_span:
        return False
    norm_source = normalize_text_for_comparison(source_text)
    norm_evidence = normalize_text_for_comparison(evidence_span)
    if not norm_evidence:
        return False
    return norm_evidence in norm_source


def build_classification_prompt(source_text: str, title: str = "") -> str:
    """建構提供給 LLM 的結構化分類 Prompt。"""
    allowed_list_str = "\n".join(f"- {bp}" for bp in CLASSIFIER_ALLOWED_BLUEPRINTS)
    return f"""你是一位專業的臨床醫學與衛教動畫藍圖分類專家。
請依據下方提供的疾病／處置衛教來源文本，為該主題的「第一幕解說（Scene 1）」選擇最合適的動畫藍圖。

【可用藍圖清單（必須且只能從中選擇一個）】：
{allowed_list_str}

【分類說明與規則】：
1. 若主題著重於病理受損、發炎、感染等疾病機轉，請選 pathology_mechanism。
2. 若為能量裝置作用於皮膚或皮下組織的療程，請選 skin_energy；若為雷射或光能作用於色素或組織，請選 laser_action。
3. 若為神經肌肉作用的注射治療（神經調節類），請選 neuromuscular；若為填充物注射、補充容積，請選 dermal_support。
4. 若為囊腫或粉瘤的完整切除或剝離，請選 cyst_excision；若為嵌甲或甲床相關處置，請選 nail_matrix。
5. 若為皮下組織的微創旋轉刮除，請選 subdermal_curettage；若為臉部深層平面（SMAS／韌帶）提拉，請選 deep_plane_facelift；若為頸部闊頸肌對縫或束帶式整形，請選 corset_platysmaplasty。
6. 若為需要截骨、骨骼固定或保護神經的手術，請選 surgical_action。
7. 若主題為一般流程或概念說明，且無特定機轉、器械或手術動作，請選 process_diagram。
8. 若原文資訊不足，或與以上所有藍圖都不符，請務必選擇 other，絕不可強行歸類。
注意：process_diagram 僅為通用流程圖，若原文有明確機轉、器械或手術動作，應優先選擇對應藍圖。
5. 必須提供 evidence_span（原文中支持此選擇的文字片段，10至40字，必須存在於原文）。
6. confidence 為 0.0 至 1.0 的浮點數。

【衛教標題】：{title}
【來源文本】：
{source_text[:1200]}

【請直接輸出合法單一 JSON 物件，不含額外文字或 Markdown】：
{{
  "blueprint": "<選擇的藍圖名稱或 other>",
  "confidence": 0.85,
  "evidence_span": "<原文直接支持的文字片段>",
  "reason": "<簡短繁體中文理由（20字內）>"
}}"""


def parse_llm_json(raw_output: str) -> Dict[str, Any]:
    """清洗並解析 LLM 輸出的 JSON 字串。"""
    if not raw_output or not raw_output.strip():
        raise ValueError("LLM 輸出為空")

    # 去除 <think>...</think> 區塊
    cleaned = re.sub(r"<think>.*?</think>", "", raw_output, flags=re.DOTALL).strip()

    # 擷取 ```json ... ``` 或 ``` ... ```
    code_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if code_match:
        cleaned = code_match.group(1).strip()
    else:
        # 嘗試尋找最外層的 { ... }
        brace_match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if brace_match:
            cleaned = brace_match.group(1).strip()

    return json.loads(cleaned)


def classify_scene1_blueprint(
    source_text: str,
    llm_call: Callable[[str], str],
    title: str = "",
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> Dict[str, Any]:
    """執行第一幕藍圖分類核心入口。

    回傳字典結構：
    {
        "blueprint": str,             # 藍圖名稱或 'other'
        "confidence": float,          # 信心度
        "evidence_span": str,         # 證據子字串
        "status": str,                # 'ok' | 'needs_review' | 'invalid_evidence' | 'unknown_blueprint'
        "is_valid_evidence": bool,    # 證據是否在原文
        "needs_review": bool,         # 是否需人工審核（不進自動佇列）
        "reason": str,                # 判定原因
    }
    """
    prompt = build_classification_prompt(source_text, title=title)

    try:
        raw_res = llm_call(prompt)
        parsed = parse_llm_json(raw_res)
    except Exception as e:
        return {
            "blueprint": "other",
            "confidence": 0.0,
            "evidence_span": "",
            "status": "needs_review",
            "is_valid_evidence": False,
            "needs_review": True,
            "reason": f"LLM 輸出解析失敗: {str(e)}",
        }

    bp = str(parsed.get("blueprint", "")).strip()
    conf = float(parsed.get("confidence", 0.0))
    evidence = str(parsed.get("evidence_span", "")).strip()
    reason = str(parsed.get("reason", "")).strip()

    # 1. 檢驗 enum 合法性
    if bp not in CLASSIFIER_ALLOWED_BLUEPRINTS:
        return {
            "blueprint": bp,
            "confidence": conf,
            "evidence_span": evidence,
            "status": "unknown_blueprint",
            "is_valid_evidence": False,
            "needs_review": True,
            "reason": f"未知的藍圖類別: '{bp}'",
        }

    # 2. 檢驗證據片段子字串（正規化容錯）
    valid_evidence = is_evidence_in_source(source_text, evidence)
    if not valid_evidence:
        return {
            "blueprint": bp,
            "confidence": conf,
            "evidence_span": evidence,
            "status": "invalid_evidence",
            "is_valid_evidence": False,
            "needs_review": True,
            "reason": "證據片段不在來源文字內 (invalid_evidence)",
        }

    # 3. 檢查 other 與低信心
    needs_review = False
    status = "ok"

    if bp == "other":
        status = "needs_review"
        needs_review = True
        reason = reason or "分類為 other，需醫師審核建立新模板"
    elif conf < confidence_threshold:
        status = "needs_review"
        needs_review = True
        prefix = f"信心度 {conf:.2f} 低於門檻 {confidence_threshold}"
        reason = f"{prefix}: {reason}" if reason else prefix

    return {
        "blueprint": bp,
        "confidence": conf,
        "evidence_span": evidence,
        "status": status,
        "is_valid_evidence": True,
        "needs_review": needs_review,
        "reason": reason,
    }
