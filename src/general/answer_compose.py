"""純函式組稿與截斷防護模組 (answer_compose)。

設計原則：
1. 純函式架構：無資料庫連線、無網路呼叫、無日誌副作用，可完全在記憶體中單元測試。
2. 句界截斷防護：永不輸出機械硬切半句（如「若出現胸…」），警訊句優先保留於 context 預算中。
3. 程式保證結構：回答恆為「價值回答 2～4 句（含警訊句）+ 恰一個追問（以？結尾）+ 固定預約邀請 CTA」。
4. 隱私與合規：不記錄問句，嚴禁金額與劑量處方，追問含合理時間數字不誤攔。
"""

from __future__ import annotations

import re
from typing import Tuple, Optional

from src.ingestion.generate_faq import (
    _FORBIDDEN_PHRASES,
    _POLITICAL_STANCE_PHRASES,
    _PRICE_PATTERN,
    _SIMPLIFIED_CHAR_SAMPLE,
    validate_single_faq,
)
from src.ingestion.medical_safety import has_doctor_warning

# 斷句正則：以中文常見句末標點或換行進行正向回顧切分，保留標點
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？；\n])")

# 句末標點白名單
VALID_ENDINGS = ("。", "！", "？", "」", "）", ")")

MAX_VALUE_SENTENCES = 4
MIN_VALUE_SENTENCES = 2

CTA_TEXT = "若想進一步評估，可使用下方的預約連結，由醫師親自了解您的狀況。"

# 六大類意圖之預設追問常數表（皆以？結尾、恰一個？、無網址、無數字與用藥）
DEFAULT_FOLLOWUPS = {
    "what": "您是希望先了解整體治療方式，還是想知道適合的評估指標呢？",
    "recovery": "您比較在意術後照護的休息時間，還是日常生活的活動限制呢？",
    "risk": "您主要想了解常見的暫時性反應，還是少數需要留意的併發症呢？",
    "suitable": "您目前是否有正在關注的身體狀況或慢性體質想先與醫師確認呢？",
    "when_to_see_doctor": "您目前是否已有特定不適症狀需要醫師協助評估呢？",
    "other": "您目前是否有特定的困擾部位，或想先了解哪方面的照護方式？",
}

# 追問中禁止出現的用藥動詞/關鍵字
_FOLLOWUP_FORBIDDEN_MED = ("服藥", "吃藥", "服用", "劑量", "處方", "開立", "買藥")

# 療程專用術語：通用衛教追問中絕不可出現
PROCEDURE_ONLY_TERMS: tuple[str, ...] = ("術後", "療程", "手術", "治療", "施作")

# 通用衛教中性追問常數表（無療程術語、皆以？結尾、恰一個？、無網址、無數字與用藥）
GENERAL_FOLLOWUPS: dict[str, str] = {
    "what": "您是希望先了解整體概念，還是想知道日常上怎麼留意呢？",
    "recovery": "您比較在意休息與恢復的安排，還是日常活動上的限制呢？",
    "risk": "您主要想了解常見的暫時性狀況，還是需要留意的少數情形呢？",
    "suitable": "您目前是否有正在關注的身體狀況或體質想先與醫師確認呢？",
    "when_to_see_doctor": "您目前是否已有特定不適症狀需要醫師協助評估呢？",
    "other": "您目前是否有特定的困擾部位，或想先了解哪方面的照護方式？",
}



def split_sentences(text: str) -> list[str]:
    """將文字依句末標點切分，保留標點；空字串回空清單。"""
    if not text:
        return []
    raw_sents = _SENT_SPLIT_RE.split(text)
    return [s for s in raw_sents if s.strip()]


def is_complete_ending(text: str) -> bool:
    """檢查文字結尾是否為合法的句末完整標點（防半句截斷）。"""
    t = (text or "").strip()
    if not t:
        return False
    return t.endswith(VALID_ENDINGS)


def clip_at_sentence(text: str, limit: int) -> str:
    """以句界進行截斷，長度內原文不變，超出時只輸出完整句。

    若原文含「何時該就醫」警訊句，警訊句優先保留於預算內，
    其餘句子依原文順序填入，永不輸出半句或省略號。
    """
    t = (text or "").strip()
    if not t or limit <= 0:
        return ""
    if len(t) <= limit:
        return t

    sents = split_sentences(t)
    if not sents:
        return ""

    # 檢查是否有就醫警訊句
    warn_indices = [i for i, s in enumerate(sents) if has_doctor_warning(s)]

    if warn_indices:
        w_idx = warn_indices[-1]  # 實務上警訊句多在段落結尾
        warn_sent = sents[w_idx]
        if len(warn_sent) > limit:
            return ""

        chosen_indices = {w_idx}
        rem = limit - len(warn_sent)

        for i, s in enumerate(sents):
            if i == w_idx:
                continue
            if len(s) <= rem:
                chosen_indices.add(i)
                rem -= len(s)
            else:
                break

        out = "".join(sents[i] for i in range(len(sents)) if i in chosen_indices)
        return out
    else:
        out = ""
        for s in sents:
            if len(out) + len(s) > limit:
                break
            out += s
        return out


def classify_intent(query: str) -> str:
    """以關鍵字分類病患問句意圖（6 類）。"""
    q = (query or "").lower().strip()
    if any(k in q for k in ("何時就醫", "要不要就醫", "何時看醫生", "需要就醫", "需要看醫生", "就醫", "急診", "掛號")):
        return "when_to_see_doctor"
    if any(k in q for k in ("恢復", "傷口", "拆線", "消腫", "休養", "照顧", "護理", "多久好", "多久能")):
        return "recovery"
    if any(k in q for k in ("風險", "後遺症", "副作用", "危險", "失敗", "感染", "發炎", "併發症")):
        return "risk"
    if any(k in q for k in ("適合", "對象", "條件", "禁忌", "體質", "懷孕", "年齡", "可以做嗎", "能做嗎")):
        return "suitable"
    if any(k in q for k in ("是什麼", "介紹", "原理", "種類", "差別", "比較", "效果", "作用", "項目", "方式", "優缺點")):
        return "what"
    return "other"


_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)


def parse_model_output(raw_output: str) -> tuple[str, str | None]:
    """解析模型純文字輸出（答：／追問：兩段），並清理 think 標籤。"""
    t = raw_output or ""
    t = _THINK_BLOCK_RE.sub("", t)
    t = _THINK_OPEN_RE.sub("", t)
    t = t.strip()

    match_val = re.search(r"(?:^|\n)\s*答\s*[:：]\s*(.*?)(?=\n\s*追問\s*[:：]|$)", t, re.DOTALL)
    match_fol = re.search(r"(?:^|\n)\s*追問\s*[:：]\s*(.*)$", t, re.DOTALL)

    if match_val:
        val = match_val.group(1).strip()
        fol = match_fol.group(1).strip() if match_fol else None
        return val, fol or None
    elif match_fol:
        val = t[:match_fol.start()].strip()
        fol = match_fol.group(1).strip()
        return val, fol or None
    else:
        return t, None


def _validate_followup_text(followup: str) -> Tuple[bool, Optional[str]]:
    """獨立檢核追問句合規性（價格、簡體、政治、保證療效、用藥禁詞）。

    追問句若含「3天」「2週」等時間數字不走劑量處方檢核，避免被 DX 規則誤攔。
    """
    f = (followup or "").strip()
    if not f:
        return False, "追問為空"

    if _PRICE_PATTERN.search(f):
        return False, f"追問檢出具體金額或價格數字 (命中: {_PRICE_PATTERN.findall(f)})"

    simplified_hits = [c for c in f if c in _SIMPLIFIED_CHAR_SAMPLE]
    if simplified_hits:
        return False, f"追問檢出簡體中文: {''.join(set(simplified_hits))}"

    for phrase in _POLITICAL_STANCE_PHRASES:
        if phrase in f:
            return False, f"追問檢出政治立場詞彙: '{phrase}'"

    for phrase in _FORBIDDEN_PHRASES:
        if phrase in f:
            return False, f"追問檢出違規禁詞: '{phrase}'"

    for med_word in _FOLLOWUP_FORBIDDEN_MED:
        if med_word in f:
            return False, f"追問檢出用藥相關詞彙: '{med_word}'"

    return True, None


def validate_composed(value: str, followup: str | None) -> tuple[bool, str | None]:
    """檢驗價值回答段（六層）與追問段（獨立規則）是否合規。"""
    v = (value or "").strip()
    if not v:
        return False, "價值段為空"

    # 價值段需包含完整六層（含劑量處方與就醫警訊）
    val_ok, reason = validate_single_faq(
        {"question": "病患諮詢問題", "answer": v},
        check_dosage=True,
        require_doctor_warning=True,
    )
    if not val_ok:
        return False, reason

    if followup is not None and followup.strip():
        fol_ok, fol_reason = _validate_followup_text(followup.strip())
        if not fol_ok:
            return False, fol_reason

    return True, None


def assemble_answer(value: str, followup: str | None, intent: str, scope: str = "procedure") -> str | None:
    """將價值段、追問句與預約邀請組裝為固定結構。

    規則：
    1. 價值段 2～4 句，超長時取「警訊句加前面句子」湊足 4 句並維持原相對順序。
    2. 少於 2 句時回傳 None（由呼叫端降級）。
    3. 追問取第一個「？」結尾的句子，缺少或不合規時退回預設追問。
       - 若 scope == "general"，候選追問不得包含 PROCEDURE_ONLY_TERMS，否則退回通用中性追問。
       - 預設追問在 scope == "general" 時取 GENERAL_FOLLOWUPS，其餘（procedure 或未知）取 DEFAULT_FOLLOWUPS。
    4. 最終整體回答恰好包含一個「？」，結尾附加固定 CTA_TEXT。
    """
    v = (value or "").strip()
    if not v:
        return None

    sents = split_sentences(v)
    if len(sents) < MIN_VALUE_SENTENCES:
        return None

    # 分離警訊句與非警訊句
    warn_indices = [i for i, s in enumerate(sents) if has_doctor_warning(s)]

    if len(sents) > MAX_VALUE_SENTENCES:
        if warn_indices:
            w_idx = warn_indices[-1]
            chosen = {w_idx}
            # 從前面依序選取非警訊句，湊滿 MAX_VALUE_SENTENCES (4 句)
            for i, s in enumerate(sents):
                if len(chosen) >= MAX_VALUE_SENTENCES:
                    break
                if i != w_idx:
                    chosen.add(i)
            selected_sents = [sents[i] for i in range(len(sents)) if i in chosen]
        else:
            selected_sents = sents[:MAX_VALUE_SENTENCES]
    else:
        selected_sents = sents

    if len(selected_sents) < MIN_VALUE_SENTENCES:
        return None

    value_body = "".join(selected_sents)

    # 處理追問
    chosen_followup = None
    if followup and followup.strip():
        candidate = followup.strip()
        # 取第一個以「？」結尾的句子
        if "？" in candidate:
            first_q = candidate.split("？")[0].strip() + "？"
            ok, _ = _validate_followup_text(first_q)
            if ok and is_complete_ending(first_q) and first_q.count("？") == 1:
                if scope == "general" and any(term in first_q for term in PROCEDURE_ONLY_TERMS):
                    chosen_followup = None
                else:
                    chosen_followup = first_q

    if not chosen_followup:
        if scope == "general":
            chosen_followup = GENERAL_FOLLOWUPS.get(intent, GENERAL_FOLLOWUPS["other"])
        else:
            chosen_followup = DEFAULT_FOLLOWUPS.get(intent, DEFAULT_FOLLOWUPS["other"])

    # 確保價值段內沒有「？」避免出現多個問號
    # 衛教說明通常為陳述句，若價值段含有「？」，替換為「。」以保證全篇恰一個問號
    clean_value_body = value_body.replace("？", "。").replace("?", "。")

    final_text = f"{clean_value_body}\n{chosen_followup}\n{CTA_TEXT}"
    return final_text


# 各意圖之互補追問意圖優先順序表（供前端互動追問膠囊或延伸詢問使用）
_COMPLEMENTARY_INTENT_MAP: dict[str, tuple[str, str]] = {
    "what": ("recovery", "suitable"),
    "recovery": ("risk", "when_to_see_doctor"),
    "risk": ("suitable", "recovery"),
    "suitable": ("what", "recovery"),
    "when_to_see_doctor": ("recovery", "risk"),
    "other": ("what", "recovery"),
}


def suggest_followup_chips(intent: str, scope: str = "procedure") -> list[str]:
    """依當前意圖回傳 2 個互補意圖的簡短合規追問句（純函式）。

    規則：
    - 嚴格取自經合規檢驗的 DEFAULT_FOLLOWUPS 或 GENERAL_FOLLOWUPS。
    - 不包含當前 intent 本身，引導病患從「了解原理」自然推進至「恢復期／自身評估」。
    """
    norm_intent = (intent or "other").strip()
    if norm_intent not in _COMPLEMENTARY_INTENT_MAP:
        norm_intent = "other"
    pair = _COMPLEMENTARY_INTENT_MAP[norm_intent]
    table = GENERAL_FOLLOWUPS if scope == "general" else DEFAULT_FOLLOWUPS
    chips: list[str] = []
    for key in pair:
        if key != norm_intent and key in table:
            chips.append(table[key])
    return chips


def build_compose_prompt(query: str, evidence_blocks: list[str], intent: str) -> str:
    """組裝即時組稿之 LLM 提示詞（純文字兩段輸出，不要 JSON）。"""
    ev_text = "\n\n".join(evidence_blocks) if evidence_blocks else "（目前無特定資料）"
    return f"""你是台灣緻妍外科診所的專業醫療顧問。請根據以下參考資料，針對病人的問題提供專業、簡潔且具同理心的衛教回答。

【參考資料】：
{ev_text}

【病患問題】：
{query}

【生成規則】：
1. 思考過程請保持簡潔（不超過 100 字），直接輸出答案本文。
2. 繁體中文專用：輸出必須全為台灣正體中文，嚴禁使用簡體字。
3. 嚴格依據資料：只依據上方參考資料作答，資料未提及之處請明確告知資料不足，絕不憑空捏造。
4. 回答長度與警訊句：回答正文需介於 2 至 4 句完整句子，且【必須包含一句具體症狀或數值條件之就醫警訊句】。
   - 警訊句必須包含具體症狀（如紅腫、發燒、疼痛、化膿、出血等）與就醫動作（如回診、就醫、就診）。
   - 合法示範句：「若傷口出現持續紅腫或化膿，請盡速回診尋求醫師評估。」
5. 嚴格價格與劑量屏蔽：絕對不得輸出任何具體金額數字、費用、收費方案或用藥劑量處方。
6. 單一延伸追問：結尾必須提出一個關心病患狀況或評估考量的單一問句（以？結尾）。
7. 輸出格式規範：僅輸出純文字兩段（不要輸出 JSON、不要 markdown 標題），格式嚴格如下：
答：(2至4句衛教回答本文，含就醫警訊)
追問：(單一延伸問句，以？結尾)
"""


# 模組載入時自我驗證預設追問常數表
for _intent_key, _f_text in DEFAULT_FOLLOWUPS.items():
    assert _f_text.count("？") == 1, f"DEFAULT_FOLLOWUPS[{_intent_key}] 必須恰包含一個問號"
    assert is_complete_ending(_f_text), f"DEFAULT_FOLLOWUPS[{_intent_key}] 必須為完整句結尾"
    _ok, _err = _validate_followup_text(_f_text)
    assert _ok, f"DEFAULT_FOLLOWUPS[{_intent_key}] 未通過合規檢查: {_err}"

for _intent_key, _f_text in GENERAL_FOLLOWUPS.items():
    assert _f_text.count("？") == 1, f"GENERAL_FOLLOWUPS[{_intent_key}] 必須恰包含一個問號"
    assert is_complete_ending(_f_text), f"GENERAL_FOLLOWUPS[{_intent_key}] 必須為完整句結尾"
    _ok, _err = _validate_followup_text(_f_text)
    assert _ok, f"GENERAL_FOLLOWUPS[{_intent_key}] 未通過合規檢查: {_err}"
    for _term in PROCEDURE_ONLY_TERMS:
        assert _term not in _f_text, f"GENERAL_FOLLOWUPS[{_intent_key}] 包含療程專用詞: {_term}"
