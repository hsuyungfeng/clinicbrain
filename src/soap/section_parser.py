"""
Taiwan Clinic Medical PageIndex RAG System - 臨床文字 S/O/A/P 結構切分與一般醫學資料分析模組
Phase 14: 臨床語音與 SOAP 紀錄擷取 (D-05)

提供確定性段落標記切分器與一般醫學衛教資料擷取工具，將原始語音轉錄臨床文字
解析為結構化之 S/O/A/P 欄位，並萃取可用於一般醫學諮詢之症狀、診斷標籤與照護指引。
"""

import re
from typing import Any, Dict, List, Optional, Tuple

# 段落標記定義：(section_name, chinese_candidates, english_full_candidates, single_letter_char)
_SECTION_MARKER_DEFS = [
    (
        "subjective",
        ["病患主訴", "病人主訴", "主訴問題", "自覺症狀", "現病史", "過去病史", "主訴", "病史"],
        ["Subjective"],
        "S",
    ),
    (
        "objective",
        ["客觀檢查", "客觀發現", "理學檢查", "身體檢查", "生命徵象", "客觀", "檢驗", "檢查", "體檢"],
        ["Objective"],
        "O",
    ),
    (
        "assessment",
        ["鑑別診斷", "臨床診斷", "初步診斷", "醫師評估", "評估", "診斷"],
        ["Assessment"],
        "A",
    ),
    (
        "plan",
        ["治療計畫", "追蹤計畫", "衛教指導", "衛教事項", "計畫", "處置", "醫囑", "用藥", "處方", "衛教"],
        ["Plan"],
        "P",
    ),
]

# 常見一般醫學疾病與症狀關鍵詞典
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

# 前置否定與排除片語白名單（按長度降序）
_NEGATION_PREFIXES = [
    "鑑別診斷", "rule out", "未出現", "r/o", "疑似", "沒有", "否認",
    "排除", "不見", "未有", "不是", "無", "非",
]

# 後置否定片語白名單
_NEGATION_SUFFIXES = [
    "陰性", "未檢出",
]

# 排除黑名單（不可誤判為否定的詞彙）
_FALSE_NEGATION_EXCLUSIONS = [
    "非常", "無法", "未見好轉", "非但", "無特殊",
]


def _try_match_marker_at(text: str, i: int) -> Optional[Tuple[int, int, str]]:
    """嘗試在位置 i 匹配合格的 section 標記。

    返回 (marker_start, marker_end, section_name) 或 None。
    """
    n = len(text)
    if i >= n:
        return None

    # 前導邊界 (B1) 檢查：必須在 (1) 行首/全文起點, (2) 空白, (3) 標點, 或 (4) 成對括號起點
    b1_valid = (i == 0) or text[i] == "【" or (text[i - 1] in "\n\r\t 。；！？，、,;.!?【[(（#*-")
    if not b1_valid:
        return None

    # 1. 括號標記檢測 (e.g. 【主訴】, [S], (Objective), （診斷）)
    if text[i] in "【[(（":
        close_map = {"【": "】", "[": "]", "(": ")", "（": "）"}
        target_close = close_map.get(text[i])
        sub = text[i + 1 : min(n, i + 30)]
        close_pos = -1
        for idx, ch in enumerate(sub):
            if ch in "】])）":
                if target_close and ch == target_close:
                    close_pos = idx
                    break
                elif not target_close:
                    close_pos = idx
                    break
        if close_pos != -1:
            inside = sub[:close_pos].strip()
            for sec_name, cn_list, en_list, s_char in _SECTION_MARKER_DEFS:
                if (
                    inside.upper() == s_char
                    or inside.lower() in [e.lower() for e in en_list]
                    or inside in cn_list
                ):
                    return (i, i + 1 + close_pos + 1, sec_name)

    # 2. 無括號標記檢測
    for sec_name, cn_list, en_list, s_char in _SECTION_MARKER_DEFS:
        # 2a. 中文複合標記
        for cn in cn_list:
            if text[i:].startswith(cn):
                rem = text[i + len(cn) :]
                m = re.match(r"^\s*[:：]", rem)
                if m:
                    return (i, i + len(cn) + m.end(), sec_name)

        # 2b. 英文全稱標記 (Subjective, Objective, Assessment, Plan)
        for en in en_list:
            if text[i : i + len(en)].lower() == en.lower():
                if i + len(en) == n or not text[i + len(en)].isalnum():
                    rem = text[i + len(en) :]
                    m = re.match(r"^\s*(?:[:：.\-]|-\s)", rem)
                    if m:
                        return (i, i + len(en) + m.end(), sec_name)

        # 2c. 單字母標記 (S, O, A, P) - 強制僅限行首且必須帶標點 (Decision 4 & 5)
        if text[i].upper() == s_char:
            if i + 1 == n or not text[i + 1].isalnum():
                line_prefix = text[:i].split("\n")[-1]
                if line_prefix.strip("#*- ") == "":
                    rem = text[i + 1 :]
                    m = re.match(r"^\s*[:：.]", rem)
                    if m:
                        return (i, i + 1 + m.end(), sec_name)

    return None


def parse_soap_text(text: str) -> Dict[str, str]:
    """將臨床語音或文本切分為 S/O/A/P 四個區塊。"""
    raw_clean = (text or "").strip()
    if not raw_clean:
        return {
            "subjective": "",
            "objective": "",
            "assessment": "",
            "plan": "",
            "raw_text": "",
        }

    # 前置正規化：將 \r\n, \r, \t, 全形空白 (\u3000) 標準化
    normalized_text = (
        raw_clean.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\t", " ")
        .replace("\u3000", " ")
    )

    matches = []
    i = 0
    n = len(normalized_text)
    while i < n:
        m = _try_match_marker_at(normalized_text, i)
        if m:
            matches.append(m)
            i = m[1]
        else:
            i += 1

    if not matches:
        return {
            "subjective": raw_clean,
            "objective": "",
            "assessment": "",
            "plan": "",
            "raw_text": raw_clean,
        }

    sections: Dict[str, List[str]] = {
        "subjective": [],
        "objective": [],
        "assessment": [],
        "plan": [],
    }

    leading_text = normalized_text[: matches[0][0]].strip()
    if leading_text:
        sections["subjective"].append(leading_text)

    for idx, (m_start, m_end, sec_name) in enumerate(matches):
        next_start = matches[idx + 1][0] if idx + 1 < len(matches) else n
        content = normalized_text[m_end:next_start].strip()
        if content:
            sections[sec_name].append(content)

    return {
        "subjective": "\n".join(sections["subjective"]).strip(),
        "objective": "\n".join(sections["objective"]).strip(),
        "assessment": "\n".join(sections["assessment"]).strip(),
        "plan": "\n".join(sections["plan"]).strip(),
        "raw_text": raw_clean,
    }


def _is_term_negated(text: str, match_start: int, match_end: int) -> bool:
    """判斷 text[match_start:match_end] 處的關鍵字是否處於否定或排除語境中。"""
    # 1. 檢查後置否定 (如 流感快篩陰性、未檢出)
    after_text = text[match_end : match_end + 10]
    for suf in _NEGATION_SUFFIXES:
        if re.match(r"^[^。；！？，,、\n]{0,4}?" + re.escape(suf), after_text):
            return True

    # 2. 檢查前置否定與範圍
    prefix_window = text[max(0, match_start - 30) : match_start]

    # 檢查 prefix_window 尾端是否緊接 false negation 排除詞 (如 非常頭痛、未見好轉)
    for false_neg in _FALSE_NEGATION_EXCLUSIONS:
        if re.search(re.escape(false_neg) + r"[的之地\s]*$", prefix_window):
            return False

    # 掃描 prefix_window 內的否定片語
    last_neg = None
    for neg in _NEGATION_PREFIXES:
        pattern = re.compile(re.escape(neg), re.IGNORECASE)
        for m in pattern.finditer(prefix_window):
            m_start = m.start()
            m_end = m.end()
            # 確保該否定片語不是 false negation 的一部分 (例如 非常 中的 非)
            is_false = False
            for false_neg in _FALSE_NEGATION_EXCLUSIONS:
                fn_pattern = re.compile(re.escape(false_neg), re.IGNORECASE)
                for fn_m in fn_pattern.finditer(prefix_window):
                    if fn_m.start() <= m_start and fn_m.end() >= m_end:
                        is_false = True
                        break
                if is_false:
                    break
            if not is_false:
                if last_neg is None or m.start() > last_neg[0]:
                    last_neg = (m.start(), m.end(), neg)

    if last_neg is None:
        return False

    # 找到最近的否定片語後，檢查該否定片語與關鍵字之間是否有轉折詞或句號/確診詞斷開
    between = prefix_window[last_neg[1] :]

    breaker_pattern = re.compile(r"[。；！？，,\n]|但|然而|不過|伴隨|出現|伴有|合併|確診")
    if breaker_pattern.search(between):
        return False

    return True


def extract_general_medical_insights(parsed_soap: Dict[str, str]) -> Dict[str, Any]:
    """從已剖析之 SOAP 內容中萃取可用於一般醫學（衛教與知識庫）之特徵標籤。"""
    subjective = parsed_soap.get("subjective", "")
    objective = parsed_soap.get("objective", "")
    assessment = parsed_soap.get("assessment", "")
    plan = parsed_soap.get("plan", "")

    # 1. conditions: 僅從 assessment 擷取 (Decision 2)。若 assessment 為空，conditions 保持 []
    matched_conditions: List[str] = []
    if assessment.strip():
        sorted_cond_kws = sorted(_GENERAL_CONDITION_KEYWORDS, key=len, reverse=True)
        matched_spans: List[Tuple[int, int]] = []

        for cond in sorted_cond_kws:
            pattern = re.compile(re.escape(cond))
            for m in pattern.finditer(assessment):
                m_start, m_end = m.span()
                # 最長匹配去重
                if any(sp_start <= m_start and sp_end >= m_end for sp_start, sp_end in matched_spans):
                    continue
                if not _is_term_negated(assessment, m_start, m_end):
                    if cond not in matched_conditions:
                        matched_conditions.append(cond)
                    matched_spans.append((m_start, m_end))

    # 2. symptoms: 僅從 subjective 與 objective 擷取 (Decision 2)，嚴格排除 plan
    search_text_symptoms = f"{subjective} {objective}".strip()
    matched_symptoms: List[str] = []
    if search_text_symptoms:
        sorted_sym_kws = sorted(_GENERAL_SYMPTOM_KEYWORDS, key=len, reverse=True)
        matched_sym_spans: List[Tuple[int, int]] = []

        for sym in sorted_sym_kws:
            pattern = re.compile(re.escape(sym))
            for m in pattern.finditer(search_text_symptoms):
                m_start, m_end = m.span()
                if any(sp_start <= m_start and sp_end >= m_end for sp_start, sp_end in matched_sym_spans):
                    continue
                if not _is_term_negated(search_text_symptoms, m_start, m_end):
                    if sym not in matched_symptoms:
                        matched_symptoms.append(sym)
                    matched_sym_spans.append((m_start, m_end))

    # 3. 擷取居家照護或衛教要點 (從 Plan 中)
    home_care_points: List[str] = []
    for line in plan.splitlines():
        clean_l = line.strip()
        if any(kw in clean_l for kw in ("衛教", "多喝水", "休息", "飲食", "清淡", "熱敷", "冰敷", "保養", "戒菸", "避免")):
            home_care_points.append(clean_l)

    # 4. 組裝標籤
    suggested_tags = list(matched_conditions)
    for sym in matched_symptoms:
        if sym not in suggested_tags:
            suggested_tags.append(sym)

    return {
        "conditions": matched_conditions,
        "symptoms": matched_symptoms,
        "home_care": home_care_points,
        "suggested_tags": suggested_tags,
        "is_general_relevant": bool(matched_conditions or matched_symptoms),
    }
