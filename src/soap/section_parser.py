"""
Taiwan Clinic Medical PageIndex RAG System - 臨床文字 S/O/A/P 結構切分與一般醫學資料分析模組
Phase 14: 臨床語音與 SOAP 紀錄擷取 (D-05)

提供確定性段落標記切分器與一般醫學衛教資料擷取工具，將原始語音轉錄臨床文字
解析為結構化之 S/O/A/P 欄位，並萃取可用於一般醫學諮詢之症狀、診斷標籤與照護指引。
"""

import re
from typing import Any, Dict, List, Optional, Tuple

# 臨床常見段落標記正規表示式字典
_MARKER_PATTERNS: List[Tuple[str, re.Pattern]] = [
    (
        "subjective",
        re.compile(
            r"^(?:[#*\s-]*)(?:S(?:ubjective)?|主訴(?:問題)?|病人主訴|病患主訴|自覺症狀|現病史|過去病史|病史)[:：\s-]\s*(.*)$",
            re.IGNORECASE,
        ),
    ),
    (
        "objective",
        re.compile(
            r"^(?:[#*\s-]*)(?:O(?:bjective)?|客觀(?:檢查|發現)?|理學檢查|身體檢查|檢驗|檢查|體檢|生命徵象)[:：\s-]\s*(.*)$",
            re.IGNORECASE,
        ),
    ),
    (
        "assessment",
        re.compile(
            r"^(?:[#*\s-]*)(?:A(?:ssessment)?|評估|診斷|鑑別診斷|臨床診斷|初步診斷|醫師評估)[:：\s-]\s*(.*)$",
            re.IGNORECASE,
        ),
    ),
    (
        "plan",
        re.compile(
            r"^(?:[#*\s-]*)(?:P(?:lan)?|計畫|處置|治療計畫|醫囑|用藥|處方|衛教(?:指導|事項)?|衛教|追蹤計畫)[:：\s-]\s*(.*)$",
            re.IGNORECASE,
        ),
    ),
]

# 常見一般醫學疾病與症狀關鍵詞典（供 SOAP text 分析萃取至一般醫學）
_GENERAL_CONDITION_KEYWORDS = (
    "感冒", "流感", "急性咽喉炎", "咽喉炎", "急性支氣管炎", "支氣管炎",
    "急性腸胃炎", "腸胃炎", "過敏性鼻炎", "鼻竇炎", "扁桃腺炎", "中耳炎",
    "偏頭痛", "緊張型頭痛", "胃食道逆流", "蕁麻疹", "濕疹", "甲溝炎",
)

_GENERAL_SYMPTOM_KEYWORDS = (
    "發燒", "咳嗽", "喉嚨痛", "咽喉痛", "鼻塞", "流鼻水", "打噴嚏",
    "頭痛", "頭暈", "腹瀉", "拉肚子", "噁心", "嘔吐", "腹痛", "胃痛",
    "肌肉痠痛", "發冷", "畏寒", "胸悶", "呼吸急促", "皮膚搔癢",
)


def parse_soap_text(text: str) -> Dict[str, str]:
    """將臨床語音或文本切分為 S/O/A/P 四個區塊。

    演算法：
    1. 逐行掃描臨床段落前綴標記（繁中或英文縮寫）。
    2. 若偵測到標記，將後續文字累積至該區塊，直到遇到下一個段落標記。
    3. 若全文完全無任何段落標記，全數歸入 subjective，其他三段留空（安全 fallback）。
    4. 保留 raw_text 欄位儲存原始字串。
    """
    raw_clean = (text or "").strip()
    if not raw_clean:
        return {
            "subjective": "",
            "objective": "",
            "assessment": "",
            "plan": "",
            "raw_text": "",
        }

    lines = raw_clean.splitlines()
    sections: Dict[str, List[str]] = {
        "subjective": [],
        "objective": [],
        "assessment": [],
        "plan": [],
    }

    current_section: Optional[str] = None
    has_any_marker = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        matched_section: Optional[str] = None
        content_after_marker: str = ""

        # 比對段落標記
        for sec_name, pattern in _MARKER_PATTERNS:
            match = pattern.match(stripped)
            if match:
                matched_section = sec_name
                content_after_marker = match.group(1).strip()
                break

        if matched_section:
            current_section = matched_section
            has_any_marker = True
            if content_after_marker:
                sections[current_section].append(content_after_marker)
        elif current_section is not None:
            # 延續前一個段落之多行內容
            sections[current_section].append(stripped)
        else:
            # 尚未遇到任何標記前的文字，預設累積至 subjective
            sections["subjective"].append(stripped)

    # 若全程無任何標記，整個 raw_clean 歸入 subjective
    if not has_any_marker:
        return {
            "subjective": raw_clean,
            "objective": "",
            "assessment": "",
            "plan": "",
            "raw_text": raw_clean,
        }

    return {
        "subjective": "\n".join(sections["subjective"]).strip(),
        "objective": "\n".join(sections["objective"]).strip(),
        "assessment": "\n".join(sections["assessment"]).strip(),
        "plan": "\n".join(sections["plan"]).strip(),
        "raw_text": raw_clean,
    }


def extract_general_medical_insights(parsed_soap: Dict[str, str]) -> Dict[str, Any]:
    """從已剖析之 SOAP 內容中萃取可用於一般醫學（衛教與知識庫）之特徵標籤。

    使用者明確指示：「soap text 中資料擷取分析使用到一般醫學中」
    本函式從 Assessment、Subjective 與 Plan 中識別：
    - conditions: 潛在匹配之常見一般疾病名稱（例如感冒、急性腸胃炎等）
    - symptoms: 提及之臨床常見症狀關鍵字
    - home_care: Plan 中包含之生活與居家照護建議
    - suggested_tags: 綜合建議標籤清單（供 soap_records.tags 使用）
    """
    subjective = parsed_soap.get("subjective", "")
    assessment = parsed_soap.get("assessment", "")
    plan = parsed_soap.get("plan", "")
    full_search_text = f"{subjective} {assessment} {plan}"

    matched_conditions: List[str] = []
    for cond in _GENERAL_CONDITION_KEYWORDS:
        if cond in full_search_text and cond not in matched_conditions:
            matched_conditions.append(cond)

    matched_symptoms: List[str] = []
    for sym in _GENERAL_SYMPTOM_KEYWORDS:
        if sym in full_search_text and sym not in matched_symptoms:
            matched_symptoms.append(sym)

    # 擷取居家照護或衛教要點（若 Plan 中有相關字句）
    home_care_points: List[str] = []
    for line in plan.splitlines():
        clean_l = line.strip()
        if any(kw in clean_l for kw in ("衛教", "多喝水", "休息", "飲食", "清淡", "熱敷", "冰敷", "保養", "戒菸", "避免")):
            home_care_points.append(clean_l)

    # 組裝標籤
    suggested_tags = list(matched_conditions)
    for sym in matched_symptoms[:3]:  # 取前3個主要症狀
        if sym not in suggested_tags:
            suggested_tags.append(sym)

    return {
        "conditions": matched_conditions,
        "symptoms": matched_symptoms,
        "home_care": home_care_points,
        "suggested_tags": suggested_tags,
        "is_general_relevant": bool(matched_conditions or matched_symptoms),
    }
