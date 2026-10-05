#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - FAQ 自動生成與驗證模組 (generate_faq)
Phase 03 Document Ingestion Stage 1: TASK-03
Phase 12 General Content Generation: GC-02, GC-03

流程：
1. build_faq_prompt(): 組裝嚴格符合 AGENTS.md 準則之 prompt（價格屏蔽、繁體中文、立場中立）
2. local_llm_call(): 呼叫本地 LLM（Phase 02 llama-server adapter）
3. parse_and_validate_faq(): 解析 JSON 並逐項檢核，過濾違規項目，記錄剔除原因
   - 基礎四層（價格、簡體、政治、保證療效）常駐啟用
   - 第五層（用藥劑量與處方建議）與第六層（就醫警訊）為條件層，預設關閉
"""

import json
import logging
import re
from typing import Any, Optional, Tuple, Union

from src.ingestion.convert_chinese import to_traditional
from src.ingestion.medical_safety import check_dosage_prescription, has_doctor_warning

logger = logging.getLogger(__name__)

# 價格檢測：匹配包含 $、NT$、數字+元/塊、或健保點值計算
_PRICE_PATTERN = re.compile(r"\d+\s*[元塊]|NT\$\s*[\d,]+|\$\s*[\d,]+|點值\s*[xX*×]\s*[\d\.]+")
# 常見簡體字檢測樣本（含醫療常見字，確保雙重防禦）
_SIMPLIFIED_CHAR_SAMPLE = set("这个国实现们来对进为产时问题号线还没会说诊评体门医处术发区专护")
# 政治敏感與主權立場詞彙
_POLITICAL_STANCE_PHRASES = (
    "不可分割的一部分",
    "一個中國",
    "中國台灣",
    "台灣地區",
)
# 禁用保證療效與未授權醫囑詞彙
_FORBIDDEN_PHRASES = ("保證有效", "一定能消除", "保證消除", "保證治癒", "physician_notes")

FAQ_PROMPT_TEMPLATE = """你是台灣緻妍外科診所的專業醫療文案編輯。請將以下診所內部文件文字改寫為結構化的常見問答（Q&A）列表，供病患於診所系統查詢使用。請提煉 3 至 5 個最具代表性、病患最常關心之問答。

# 來源檔案：{source_filename}

# 來源內容：
{source_text}

# 嚴格生成規則（違反任何一條視為輸出無效）：
1. 【繁體中文專用】：全篇一律使用台灣正體中文，絕對禁止出現簡體中文字元。
2. 【嚴格價格屏蔽】：來源文件中可能包含自費金額、收費數字（如 $1500、$4500、收費$8000、健保點值計算等），你【絕對禁止】在問題或答案中輸出任何具體金額數字或收費計算！若問答涉及費用，答案中一律改寫為「請致電診所確認」或「費用需由醫師門診評估後確認」。
3. 【立場中立防禦】：禁止輸出任何政治、主權、國家定位、意識形態相關立場表述（如「一個中國」、「中國台灣」、「台灣地區」等），專注於醫療服務本身。
4. 【醫療責任分工】：不得輸出具體個別化醫療診斷或保證療效之語句（如「保證有效」、「一定能消除」）。
5. 【輸出格式規範】：僅輸出一個標準 JSON 陣列，每個元素包含 "question" 與 "answer" 兩個字串欄位，不要用 markdown 標記包裝，不要輸出任何額外解釋文字。

JSON 格式範例：
[
  {{
    "question": "甲溝炎手術如何安排？",
    "answer": "術前需經醫師門診評估指甲與甲床狀況，若有急性發炎需配合醫囑治療，相關費用請致電診所確認。"
  }}
]

請直接輸出 JSON 陣列："""


def build_faq_prompt(source_text: str, source_filename: str) -> str:
    """組裝將文件文字轉換為病患常見問答 (Q&A) 的 LLM prompt。

    參數:
        source_text: 來源文件擷取之純文字
        source_filename: 來源檔案名稱（如 '緻妍自費門診手術內容.docx'）
    回傳:
        組裝完成之 prompt 字串
    """
    clean_text = (source_text or "").strip()
    return FAQ_PROMPT_TEMPLATE.format(
        source_filename=source_filename,
        source_text=clean_text,
    )


def validate_single_faq(
    item: dict[str, Any],
    *,
    check_dosage: bool = False,
    require_doctor_warning: bool = False,
) -> Tuple[bool, Optional[str]]:
    """驗證單一 Q&A 項目是否合規。
    
    回傳: (is_valid, reason_if_invalid)
    """
    if not isinstance(item, dict):
        return False, "項目非 dict 格式"

    q = item.get("question")
    a = item.get("answer")

    if not q or not isinstance(q, str) or not q.strip():
        return False, "question 為空或非字串"
    if not a or not isinstance(a, str) or not a.strip():
        return False, "answer 為空或非字串"

    combined = f"{q} {a}"

    # 1. 價格洩漏檢測
    if _PRICE_PATTERN.search(combined):
        return False, f"檢出具體金額或價格數字 (命中: {_PRICE_PATTERN.findall(combined)})"

    # 2. 簡體中文檢測
    simplified_hits = [c for c in combined if c in _SIMPLIFIED_CHAR_SAMPLE]
    if simplified_hits:
        return False, f"檢出簡體中文字符: {''.join(set(simplified_hits))}"

    # 3. 政治敏感立場檢測
    for phrase in _POLITICAL_STANCE_PHRASES:
        if phrase in combined:
            return False, f"檢出政治立場詞彙: '{phrase}'"

    # 4. 保證療效禁詞檢測
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in combined:
            return False, f"檢出違規禁詞: '{phrase}'"

    # 5. 用藥劑量與處方建議檢測（僅對 answer 檢查）
    if check_dosage:
        rule_id = check_dosage_prescription(a)
        if rule_id is not None:
            return False, f"檢出用藥劑量或處方建議 (規則: {rule_id})"

    # 6. 何時該就醫警訊檢測（僅對 answer 檢查）
    if require_doctor_warning:
        if not has_doctor_warning(a):
            return False, "缺少「何時該就醫」警訊（需具體症狀或數值條件加就醫動作）"

    return True, None


def parse_and_validate_faq(
    raw_output: str,
    return_rejected: bool = False,
    *,
    check_dosage: bool = False,
    require_doctor_warning: bool = False,
) -> Union[list[dict[str, str]], Tuple[list[dict[str, str]], list[dict[str, Any]]]]:
    """解析 LLM 輸出之 JSON 陣列，並逐筆執行嚴格驗證。

    驗證規則：
    - question / answer 非空字串
    - 無價格洩漏（_PRICE_PATTERN）
    - 無簡體中文字元（_SIMPLIFIED_CHAR_SAMPLE）
    - 無政治立場用語（_POLITICAL_STANCE_PHRASES）
    - 無保證療效用語（_FORBIDDEN_PHRASES）
    - 條件啟用：劑量處方檢測（check_dosage=True）、就醫警訊檢測（require_doctor_warning=True）

    參數:
        raw_output: LLM 原始回傳字串
        return_rejected: 若為 True，回傳 (valid_faqs, rejected_faqs)；預設 False 僅回傳 valid_faqs
        check_dosage: 是否啟用第五層劑量與處方建議攔截（預設 False）
        require_doctor_warning: 是否啟用第六層「何時該就醫」警訊檢核（預設 False）
    回傳:
        符合規範之 Q&A 列表（或與被剔除項目的 tuple）
    """
    if not raw_output or not raw_output.strip():
        logger.warning("LLM 輸出為空")
        return ([], []) if return_rejected else []

    text = raw_output.strip()
    # 去除 Markdown 程式碼區塊標記
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            text = match.group(1).strip()

    # 尋找最外層的 JSON 陣列 [ ... ]
    start_idx = text.find("[")
    end_idx = text.rfind("]")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        text = text[start_idx : end_idx + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"FAQ JSON 解析失敗: {e}\n原始輸出: {raw_output[:200]}")
        return ([], [{"error": f"JSONDecodeError: {e}", "raw": raw_output}]) if return_rejected else []

    if not isinstance(data, list):
        logger.error(f"FAQ JSON 頂層非陣列: {type(data)}")
        return ([], [{"error": "頂層結構非陣列", "raw": raw_output}]) if return_rejected else []

    valid_faqs: list[dict[str, str]] = []
    rejected_faqs: list[dict[str, Any]] = []

    for idx, item in enumerate(data):
        is_valid, reason = validate_single_faq(
            item,
            check_dosage=check_dosage,
            require_doctor_warning=require_doctor_warning,
        )
        if is_valid:
            valid_faqs.append({
                "question": item["question"].strip(),
                "answer": item["answer"].strip(),
            })
        else:
            logger.warning(f"剔除違規 FAQ 項目 [{idx}]: {reason}")
            rejected_faqs.append({
                "index": idx,
                "item": item,
                "reason": reason,
            })

    if return_rejected:
        return valid_faqs, rejected_faqs
    return valid_faqs
