"""
高信心 FAQ 短路判定模組（Phase 07 CACHE-01, CACHE-04）。
純函式實作，無資料庫存取、不呼叫 LLM、不依賴 router。

設計原則：
1. 誤短路（答非所問、甚至肯定/否定相反或數字單位錯置的醫療誤答）的代價遠高於不短路。
2. 判定條件為保守可測量的常數規則：查詢覆蓋率 >= 0.9、FAQ 問句覆蓋率 >= 0.7、
   標準化查詢長度 >= 4、與次佳覆蓋率差距 >= 0.1、且通過「風險特徵殘餘檢查」。
3. 風險特徵檢查於去語助詞之前以原文（僅 NFKC 歸一化轉小寫）進行對稱比對，
   確保數字帶單位、否定/禁忌字、時序/方位字、人群/體質限定詞完全一致。
"""

import collections
from dataclasses import dataclass
import re
from typing import Counter, Optional, Pattern
import unicodedata

try:
    from .search import SearchHit
except ImportError:
    from search import SearchHit


# 判定規則常數
MIN_QUERY_CHARS: int = 4
MIN_QUERY_COVERAGE: float = 0.9
MIN_QUESTION_COVERAGE: float = 0.7
MIN_MARGIN: float = 0.1
SHORTCUT_CANDIDATE_LIMIT: int = 50  # 短路判定用獨立較大候選集上限，避免 limit 截斷導致漏看歧義

# 非文字過濾正規表達式（保留英數字與中日韓統一表意文字）
_NON_TEXT_PATTERN: Pattern = re.compile(r"[^0-9a-zA-Z\u4e00-\u9fff]+")

# 風險特徵偵測正則與字集
# 阿拉伯數字帶單位（單位依長到短排列避免貪婪誤配）
_NUMBER_WITH_UNIT_PATTERN: Pattern = re.compile(
    r"(\d+(?:\.\d+)?)\s*(個月|小時|分鐘|毫克|天|日|週|周|月|年|次|顆|片|mg|ml|cc|g|%)?"
)
# 中文數字加量詞
_CJK_NUMBER_UNIT_PATTERN: Pattern = re.compile(
    r"([一二三四五六七八九十兩半]+)(天|日|週|周|個月|月|年|次|小時|分鐘|顆|片|毫克)"
)
# 否定與禁忌單字
_NEGATION_CHARS: str = "不無沒別勿禁未非免避忌否戒停"
# 時序與方位字
_POSITION_CHARS: str = "前後內外"
# 人群與體質限定詞
_QUALIFIER_WORDS: tuple[str, ...] = (
    "懷孕", "孕", "哺乳", "嬰", "兒", "童", "老", "糖尿",
    "男", "女", "過敏", "高血壓", "抗凝血", "服藥", "成人", "長者",
)


@dataclass(frozen=True)
class ShortcutDecision:
    """高信心 FAQ 短路決策結果。"""
    hit: Optional[SearchHit]
    reason: str
    query_coverage: float = 0.0
    question_coverage: float = 0.0
    margin: float = 0.0


def normalize_for_match(text: str, stopword_pattern: Optional[Pattern] = None) -> str:
    """標準化字串以供字元 bigram 快取匹配。

    步驟：
    1. Unicode NFKC 規範化（全形轉半形等）。
    2. 若提供 stopword_pattern，以其切割後拼合（去除語助詞）。
    3. 英文轉小寫。
    4. 移除標點符號與特殊字元。
    """
    normalized = unicodedata.normalize("NFKC", text)
    if stopword_pattern is not None:
        normalized = "".join(stopword_pattern.split(normalized))
    normalized = normalized.lower()
    return _NON_TEXT_PATTERN.sub("", normalized)


def char_bigrams(text: str) -> set[str]:
    """取得字串的相鄰雙字元集合（Bigram Set）。若長度小於 2 則回傳空集合。"""
    if len(text) < 2:
        return set()
    return {text[i:i + 2] for i in range(len(text) - 1)}


def score_hit(query_norm: str, question_norm: str) -> tuple[float, float]:
    """計算標準化查詢與標準化問句之雙向 Bigram 覆蓋率。

    回傳：(query_coverage, question_coverage)
    任一字串 Bigram 為空則回傳 (0.0, 0.0)。
    """
    q_bg = char_bigrams(query_norm)
    ans_bg = char_bigrams(question_norm)
    if not q_bg or not ans_bg:
        return 0.0, 0.0
    intersection_len = len(q_bg & ans_bg)
    return intersection_len / len(q_bg), intersection_len / len(ans_bg)


def extract_risk_features(text: str) -> Counter[str]:
    """自原文擷取風險特徵集合與次數。

    直接對原文（NFKC 規範化並轉小寫，不去語助詞、不去標點）進行偵測，
    比對以下五大風險維度：
    1. 阿拉伯數字帶單位：key = 'd' + 數字 + 單位（例如 'd3天', 'd5mg'）
    2. 中文數字加量詞：key = 'n' + 詞（例如 'n三天'）
    3. 否定/禁忌單字：key = 'neg' + 字（例如 'neg不', 'neg未'）
    4. 時序/方位字：key = 'p' + 字（例如 'p前', 'p後'）
    5. 人群/體質限定詞：key = 'q' + 詞（例如 'q過敏', 'q孕'）
    """
    norm_text = unicodedata.normalize("NFKC", text).lower()
    counter: Counter[str] = collections.Counter()

    # 1. 阿拉伯數字帶單位
    for m in _NUMBER_WITH_UNIT_PATTERN.finditer(norm_text):
        num = m.group(1)
        if num:
            unit = m.group(2) or ""
            counter["d" + num + unit] += 1

    # 2. 中文數字加量詞
    for m in _CJK_NUMBER_UNIT_PATTERN.finditer(norm_text):
        counter["n" + m.group(0)] += 1

    # 3. 否定/禁忌單字
    for ch in norm_text:
        if ch in _NEGATION_CHARS:
            counter["neg" + ch] += 1

    # 4. 時序/方位字
    for ch in norm_text:
        if ch in _POSITION_CHARS:
            counter["p" + ch] += 1

    # 5. 人群/體質限定詞
    for word in _QUALIFIER_WORDS:
        cnt = norm_text.count(word)
        if cnt > 0:
            counter["q" + word] += cnt

    return counter


def risk_mismatch(query: str, question: str) -> bool:
    """檢查查詢與 FAQ 問句原文之風險特徵是否不一致（對稱比對）。"""
    return extract_risk_features(query) != extract_risk_features(question)


def select_confident_faq(
    query: str,
    faq_hits: list[SearchHit],
    route: str,
    clinic_id: Optional[str],
    stopword_pattern: Optional[Pattern] = None,
) -> ShortcutDecision:
    """自 FAQ 搜尋結果中評估並選出高信心短路項目。

    檢查順序：
    (a) special 路由且 clinic_id 為空 -> reason='no_clinic'
    (b) 依 route 篩選合格候選，若無合格項 -> reason='no_eligible'
    (c) 標準化後查詢長度 < MIN_QUERY_CHARS -> reason='query_too_short'
    (d) 對各候選計分；合併「標準化問句相同且答案相同」的重複項目（保留最小 row_id）；
        依 (query_coverage 降冪, question_coverage 降冪, row_id 升冪) 排序
    (e) 最佳候選覆蓋率未達門檻 -> reason='low_coverage'
    (f) 最佳候選與查詢之風險特徵不一致 -> reason='risk_mismatch'
    (g) 最佳與次佳覆蓋率差距 < MIN_MARGIN -> reason='ambiguous'
    (h) 通過所有門檻 -> reason='confident'，回傳 hit
    """
    # (a) special 路由必填 clinic_id
    if route == "special" and (not clinic_id or not clinic_id.strip()):
        return ShortcutDecision(hit=None, reason="no_clinic")

    # (b) 依路由篩選合格候選
    eligible_hits: list[SearchHit] = []
    for h in faq_hits:
        ans = h.fields.get("answer", "")
        if not ans or not ans.strip():
            continue
        cat = h.fields.get("category")
        c_id = h.fields.get("clinic_id")
        if route == "special":
            if cat == "special" and c_id == clinic_id:
                eligible_hits.append(h)
        elif route == "general":
            if cat == "general" and c_id is None:
                eligible_hits.append(h)

    if not eligible_hits:
        return ShortcutDecision(hit=None, reason="no_eligible")

    # (c) 查詢字數檢查
    query_norm = normalize_for_match(query, stopword_pattern=stopword_pattern)
    if len(query_norm) < MIN_QUERY_CHARS:
        return ShortcutDecision(hit=None, reason="query_too_short")

    # (d) 合併相同問句與答案的項目（保留最小 row_id），並計算分數
    candidate_map: dict[tuple[str, str], SearchHit] = {}
    for h in eligible_hits:
        q_raw = h.fields.get("question", "")
        ans_raw = h.fields.get("answer", "").strip()
        q_norm = normalize_for_match(q_raw, stopword_pattern=stopword_pattern)
        key = (q_norm, ans_raw)
        if key not in candidate_map or h.row_id < candidate_map[key].row_id:
            candidate_map[key] = h

    scored_candidates: list[dict] = []
    for (q_norm, _), h in candidate_map.items():
        q_cov, question_cov = score_hit(query_norm, q_norm)
        scored_candidates.append({
            "hit": h,
            "query_coverage": q_cov,
            "question_coverage": question_cov,
            "row_id": h.row_id,
        })

    # 排序：覆蓋率降冪、row_id 升冪
    scored_candidates.sort(
        key=lambda x: (-x["query_coverage"], -x["question_coverage"], x["row_id"])
    )

    best = scored_candidates[0]
    b_q_cov = best["query_coverage"]
    b_question_cov = best["question_coverage"]

    # (e) 覆蓋率門檻檢查
    if b_q_cov < MIN_QUERY_COVERAGE or b_question_cov < MIN_QUESTION_COVERAGE:
        return ShortcutDecision(
            hit=None,
            reason="low_coverage",
            query_coverage=b_q_cov,
            question_coverage=b_question_cov,
        )

    # (f) 風險特徵比對（以原文檢查）
    best_raw_question = best["hit"].fields.get("question", "")
    if risk_mismatch(query, best_raw_question):
        return ShortcutDecision(
            hit=None,
            reason="risk_mismatch",
            query_coverage=b_q_cov,
            question_coverage=b_question_cov,
        )

    # (g) 差距檢查（Margin）
    if len(scored_candidates) == 1:
        margin = b_q_cov
    else:
        second = scored_candidates[1]
        margin = b_q_cov - second["query_coverage"]

    if margin < MIN_MARGIN:
        return ShortcutDecision(
            hit=None,
            reason="ambiguous",
            query_coverage=b_q_cov,
            question_coverage=b_question_cov,
            margin=margin,
        )

    # (h) 通過所有門檻
    return ShortcutDecision(
        hit=best["hit"],
        reason="confident",
        query_coverage=b_q_cov,
        question_coverage=b_question_cov,
        margin=margin,
    )
