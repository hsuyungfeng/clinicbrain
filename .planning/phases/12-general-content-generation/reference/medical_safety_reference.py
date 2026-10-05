"""GC-02 / GC-03 原型（最終實作將落在 src/ingestion/medical_safety.py）。"""
import re
import unicodedata
from typing import Optional

_NUM = r"(?:\d+(?:\.\d+)?|[零〇一二三四五六七八九十百千半兩]+)"
_RANGE = rf"{_NUM}(?:\s*(?:~|-|至|到|或)\s*{_NUM})?"

_UNIT_STRICT = r"(?:mg|mcg|μg|ug|iu|毫克|微克|公絲|國際單位)(?![a-z])"
_UNIT_AMOUNT = r"(?:片|顆|錠|粒|包|膠囊|湯匙|茶匙|匙|滴|支|貼|公克|毫升|ml|cc|g)(?![a-z])"

DX1 = re.compile(rf"{_RANGE}\s*{_UNIT_STRICT}")
DX2_VERB_ALL = re.compile(
    rf"(?:服用|吞服|口服|塗抹|滴入|注射|吸入)\s*(?:約|大約|至少|至多|最多|每次|一次)?\s*{_RANGE}\s*{_UNIT_AMOUNT}"
)
DX2_VERB_EAT = re.compile(
    rf"吃\s*(?:約|大約|至少|至多|最多|每次|一次)?\s*{_RANGE}\s*(?:錠|膠囊|湯匙|茶匙|匙|滴)"
)
DX6 = re.compile(r"(?<![a-z])(?:q\d{1,2}h|qd|bid|tid|qid|prn|hs|qhs)(?![a-z])")

_DW_SPECIFIC = (
    "抗生素|止痛藥|止痛劑|止痛貼|退燒藥|退燒劑|退燒栓劑|消炎藥|消炎劑|類固醇|抗組織胺|抗過敏藥|制酸|胃藥|"
    "感冒藥|咳嗽藥|止咳藥|止瀉藥|止吐藥|化痰藥|鼻噴劑|鼻用噴劑|去充血劑|抗病毒|克流感|奧司他韋|瑞樂沙|"
    "普拿疼|阿斯匹靈|阿司匹林|布洛芬|乙醯胺酚|撲熱息痛"
)
DW_SPECIFIC = re.compile(f"(?:{_DW_SPECIFIC})")
DW_GENERIC = re.compile(r"藥")
FREQ = re.compile(
    rf"(?:(?:每|一)(?:天|日)\s*{_RANGE}\s*次|每(?:隔)?\s*{_RANGE}\s*小時|飯前|飯後|睡前|空腹)"
)
AMOUNT = re.compile(rf"{_RANGE}\s*{_UNIT_AMOUNT}")

_V_FWD = "服用|吃|使用|塗抹|塗|擦|貼|施打|注射|開立|開|處方|購買|買|口服|吞服|噴|點|搭配"
_V_REV = "服用|吃|使用|塗抹|口服|吞服|即可"
DX4_FWD = re.compile(rf"(?:{_V_FWD})[^,，。；;、：:！!？?\n]{{0,4}}?(?:{_DW_SPECIFIC})")
DX4_REV = re.compile(rf"(?:{_DW_SPECIFIC})[^,，。；;、：:！!？?\n]{{0,4}}?(?:{_V_REV})")
DX5 = re.compile(r"(?:服用|服藥|吞服|吃藥|口服藥)|吃[^,，。；;、：:！!？?\n]{0,3}藥")

_NEG = re.compile(r"(?:請勿|切勿|勿|不要|不可|不宜|不建議|避免|禁止|不得|不應|不能|別)")
_STATE = re.compile(r"(?:正在|目前|曾經|曾|長期|已經|有在|在)(?:服用|服藥|使用|吃)")
_DOCTOR = re.compile(r"(?:依|遵|按|照)(?:照|從)?(?:醫囑|(?:醫師|藥師)(?:的)?(?:指示|處方|囑咐|建議|評估|診斷)?)")
_CLAUSE = re.compile(r"[,，。；;、：:！!？?\n]")
_SENT = re.compile(r"[。；;！!？?\n]")


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").lower()


def check_dosage_prescription(answer: str) -> Optional[str]:
    t = _norm(answer)
    if DX6.search(t):
        return "DX-6"
    if DX1.search(t):
        return "DX-1"
    for sent in _SENT.split(t):
        has_specific = bool(DW_SPECIFIC.search(sent))
        has_any = has_specific or bool(DW_GENERIC.search(sent))
        if has_any and AMOUNT.search(sent):
            return "DX-3"
        if has_specific and FREQ.search(sent):
            return "DX-3"
    if DX2_VERB_ALL.search(t) or DX2_VERB_EAT.search(t):
        return "DX-2"
    for clause in _CLAUSE.split(t):
        if _NEG.search(clause) or _STATE.search(clause) or _DOCTOR.search(clause):
            continue
        if DX4_FWD.search(clause) or DX4_REV.search(clause):
            return "DX-4"
        if DX5.search(clause):
            return "DX-5"
    return None


# ---- GC-03 ----
_ACTION = re.compile(r"就醫|就診|看診|回診|急診|醫院|門診|掛號|119|送醫|求醫|諮詢醫師|醫療院所|聯絡醫師")
_NEG_ACTION = re.compile(r"(?:不用|不需要?|無須|無需|不必|毋須|毋需)(?:特別|再|要)?(?:就醫|就診|看診|回診|急診|去醫院|到醫院|至醫院|送醫)")
_SYMPTOM = re.compile(
    "胸痛|呼吸急促|呼吸困難|喘鳴|血便|黑便|嘔血|意識不清|意識改變|昏迷|抽搐|痙攣|頸部僵硬|脫水|尿量(?:明顯)?減少|"
    "口乾|嘴唇乾裂|嘴唇發紫|無法進食|嘔吐不止|持續嘔吐|反覆嘔吐|高燒|高熱|發燒不退|劇烈頭痛|劇烈腹痛|嚴重腹痛|"
    "腹痛加劇|精神萎靡|嗜睡|臉色蒼白|喉嚨腫脹|臉部腫脹|嘴唇腫脹|血尿|耳痛|胸悶|心悸|無法吞嚥|吞嚥困難"
)
_SYM_NEG_PREFIX = re.compile(r"(?:沒有|無|未|不會|並無)$")
_THRESH_NUM = re.compile(
    rf"(?:超過|逾|達到?|大於|多於|至少|連續|持續|滿|>|≥)\s*{_RANGE}\s*(?:度|°c|℃|天|日|小時|次|週|周|個月|mmhg|%)"
    rf"|{_RANGE}\s*(?:度|°c|℃|天|日|小時|次|週|周|個月)\s*(?:以上|以內仍|仍未|未退|不退)"
)


def _has_concrete_condition(sent: str) -> bool:
    if _THRESH_NUM.search(sent):
        return True
    for m in _SYMPTOM.finditer(sent):
        if not _SYM_NEG_PREFIX.search(sent[max(0, m.start() - 3):m.start()]):
            return True
    return False


def has_doctor_warning(answer: str) -> bool:
    t = _norm(answer)
    for sent in _SENT.split(t):
        if not sent.strip():
            continue
        if _NEG_ACTION.search(sent):
            continue
        if _ACTION.search(sent) and _has_concrete_condition(sent):
            return True
    return False
