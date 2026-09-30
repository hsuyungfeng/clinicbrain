"""
高信心 FAQ 短路判定模組單元測試（Phase 07 CACHE-01, CACHE-04）。
涵蓋規則常數、標準化、Bigram 覆蓋率、風險特徵擷取、決策邏輯與醫療對抗性案例。
所有測試皆為純函式邏輯驗證，無需資料庫連線。
"""

import collections
import random
import pytest

from src.query.faq_shortcut import (
    MIN_MARGIN,
    MIN_QUERY_CHARS,
    MIN_QUERY_COVERAGE,
    MIN_QUESTION_COVERAGE,
    SHORTCUT_CANDIDATE_LIMIT,
    ShortcutDecision,
    char_bigrams,
    extract_risk_features,
    normalize_for_match,
    risk_mismatch,
    score_hit,
    select_confident_faq,
)
from src.query.router import _STOPWORD_SPLIT_PATTERN
from src.query.search import SearchHit


def _make_hit(
    row_id: int,
    question: str,
    answer: str = "標準衛教答案內容說明。",
    clinic_id: str | None = "3503190424",
    category: str = "special",
    topic_key: str = "test-topic",
) -> SearchHit:
    """建立 SearchHit 測試物件輔助函式。"""
    return SearchHit(
        table="faq_cache",
        row_id=row_id,
        fields={
            "id": row_id,
            "clinic_id": clinic_id,
            "category": category,
            "topic_key": topic_key,
            "question": question,
            "answer": answer,
        },
    )


# ==============================================================================
# 1. 規則常數與基礎工具驗證
# ==============================================================================

def test_constants_values():
    """驗證各項判定常數值符合設計規格。"""
    assert MIN_QUERY_CHARS == 4
    assert MIN_QUERY_COVERAGE == 0.9
    assert MIN_QUESTION_COVERAGE == 0.7
    assert MIN_MARGIN == 0.1
    assert SHORTCUT_CANDIDATE_LIMIT == 50


def test_normalize_for_match_basic():
    """測試 normalize_for_match 移除標點與轉小寫。"""
    assert normalize_for_match("甲溝炎，門診處理？") == "甲溝炎門診處理"
    assert normalize_for_match("HIFU 音波拉提！") == "hifu音波拉提"


def test_normalize_for_match_nfkc():
    """測試 NFKC 規範化轉換全形字元。"""
    assert normalize_for_match("第３天，５ｍｇ") == "第3天5mg"


def test_normalize_for_match_with_stopwords():
    """測試結合語助詞 pattern 移除語助詞。"""
    text = "音波拉提是什麼？有沒有效果呢？"
    norm = normalize_for_match(text, stopword_pattern=_STOPWORD_SPLIT_PATTERN)
    assert "是什麼" not in norm
    assert "有沒有" not in norm
    assert "呢" not in norm
    assert "音波拉提效果" in norm


def test_char_bigrams_and_score_hit():
    """測試 Bigram 計算與分數計算。"""
    assert char_bigrams("a") == set()
    assert char_bigrams("音波拉提") == {"音波", "波拉", "拉提"}

    # 完全相同
    q_cov, a_cov = score_hit("音波拉提", "音波拉提")
    assert q_cov == 1.0 and a_cov == 1.0

    # 空字串或過短字串
    assert score_hit("", "音波拉提") == (0.0, 0.0)
    assert score_hit("音", "音波拉提") == (0.0, 0.0)


# ==============================================================================
# 2. 風險特徵擷取與不匹配比對（Risk Features）
# ==============================================================================

def test_extract_risk_features_numbers_and_units():
    """測試阿拉伯數字帶單位之特徵辨識。"""
    c1 = extract_risk_features("術後第3天的照護")
    assert c1["d3天"] == 1

    c2 = extract_risk_features("術後第3週的照護")
    assert c2["d3週"] == 1
    assert c1 != c2

    c3 = extract_risk_features("每次服用 5mg 藥物")
    assert c3["d5mg"] == 1

    c4 = extract_risk_features("每次服用 5g 藥物")
    assert c4["d5g"] == 1
    assert c3 != c4

    c5 = extract_risk_features("施作 3 次療程")
    assert c5["d3次"] == 1


def test_extract_risk_features_cjk_numbers():
    """測試中文數字加量詞。"""
    c = extract_risk_features("拆線後第三天的護理")
    assert c["n三天"] == 1


def test_extract_risk_features_negations():
    """測試否定字詞計數與特定句型。"""
    c = extract_risk_features("會不會痛？有沒有副作用？")
    # '會不會' 貢獻 1 個 'neg不'，且無 '會' 相關 key
    assert c["neg不"] == 1
    assert not any("會" in k for k in c.keys())
    # '有沒有' 貢獻 1 個 'neg沒'
    assert c["neg沒"] == 1

    all_negs = "不無沒別勿禁未非免避忌否戒停"
    c_all = extract_risk_features(all_negs)
    for ch in all_negs:
        assert c_all["neg" + ch] == 1


def test_extract_risk_features_positions():
    """測試時序與方位字（前後內外）。"""
    c = extract_risk_features("術前評估與術後照護，體內與體外")
    assert c["p前"] == 1
    assert c["p後"] == 1
    assert c["p內"] == 1
    assert c["p外"] == 1


def test_extract_risk_features_qualifiers():
    """測試人群與體質限定詞計數。"""
    c = extract_risk_features("孕婦與哺乳期，幼兒與過敏體質患者")
    assert c["q孕"] == 1
    assert c["q哺乳"] == 1
    assert c["q兒"] == 1
    assert c["q過敏"] == 1


@pytest.mark.parametrize("word", [
    "男", "女", "高血壓", "抗凝血", "服藥", "成人", "長者", "糖尿",
])
def test_extract_risk_features_remaining_qualifiers(word):
    """測試其餘人群/體質詞之特徵存在與 mismatch 判定。"""
    q1 = f"音波拉提術後注意事項（{word}）"
    q2 = "音波拉提術後注意事項"
    assert extract_risk_features(q1)["q" + word] == 1
    assert risk_mismatch(q1, q2) is True


def test_risk_mismatch_symmetry():
    """測試風險特徵不匹配檢查之對稱性。"""
    t1 = "術後可以洗臉嗎"
    t2 = "術後不可以洗臉嗎"
    assert risk_mismatch(t1, t2) is True
    assert risk_mismatch(t2, t1) is True

    t3 = "完全相同的文字內容"
    assert risk_mismatch(t3, t3) is False


# ==============================================================================
# 3. select_confident_faq 流程與門檻驗證
# ==============================================================================

def test_select_confident_faq_exact_match():
    """測試完全相符問句順利通過並回傳 confident。"""
    hit = _make_hit(1, "音波拉提術後需要注意什麼？")
    decision = select_confident_faq(
        query="音波拉提術後需要注意什麼？",
        faq_hits=[hit],
        route="special",
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert decision.reason == "confident"
    assert decision.hit == hit
    assert decision.query_coverage == 1.0
    assert decision.question_coverage == 1.0


def test_select_confident_faq_no_clinic():
    """測試 special 路由缺少 clinic_id 時回傳 no_clinic。"""
    hit = _make_hit(1, "音波拉提術後注意事項？")
    decision = select_confident_faq(
        query="音波拉提術後注意事項？",
        faq_hits=[hit],
        route="special",
        clinic_id=None,
    )
    assert decision.reason == "no_clinic"
    assert decision.hit is None


def test_select_confident_faq_clinic_and_category_mismatch():
    """測試跨診所或 category 不符時判定為 no_eligible。"""
    # 1. special 路由但 clinic_id 不同
    hit_other = _make_hit(1, "音波拉提術後注意事項？", clinic_id="other-clinic")
    decision1 = select_confident_faq(
        query="音波拉提術後注意事項？",
        faq_hits=[hit_other],
        route="special",
        clinic_id="3503190424",
    )
    assert decision1.reason == "no_eligible"

    # 2. special 路由但 hit 是 general
    hit_general = _make_hit(2, "音波拉提術後注意事項？", category="general", clinic_id=None)
    decision2 = select_confident_faq(
        query="音波拉提術後注意事項？",
        faq_hits=[hit_general],
        route="special",
        clinic_id="3503190424",
    )
    assert decision2.reason == "no_eligible"


def test_select_confident_faq_general_route_eligible():
    """測試 general 路由要求 clinic_id 為 None 且 category='general'。"""
    hit_gen = _make_hit(1, "感冒多喝水有用嗎？", category="general", clinic_id=None)
    decision = select_confident_faq(
        query="感冒多喝水有用嗎？",
        faq_hits=[hit_gen],
        route="general",
        clinic_id=None,
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert decision.reason == "confident"
    assert decision.hit == hit_gen


def test_select_confident_faq_blank_answer():
    """測試空白答案之 hit 視為不合格。"""
    hit_blank = _make_hit(1, "音波拉提術後注意事項？", answer="   ")
    decision = select_confident_faq(
        query="音波拉提術後注意事項？",
        faq_hits=[hit_blank],
        route="special",
        clinic_id="3503190424",
    )
    assert decision.reason == "no_eligible"


def test_select_confident_faq_query_too_short():
    """測試標準化後長度小於 4 之查詢被擋下（query_too_short）。"""
    hit = _make_hit(1, "粉瘤手術如何處理？")
    decision = select_confident_faq(
        query="粉瘤？",
        faq_hits=[hit],
        route="special",
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert decision.reason == "query_too_short"


def test_select_confident_faq_low_coverage():
    """測試覆蓋率未達門檻回傳 low_coverage。"""
    hit = _make_hit(1, "皮秒雷射術後居家冰敷重點有哪些？")
    decision = select_confident_faq(
        query="皮秒雷射後臉部發紅怎麼辦？",
        faq_hits=[hit],
        route="special",
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert decision.reason == "low_coverage"
    assert decision.hit is None


def test_select_confident_faq_deduplication_same_answer():
    """測試多筆問句相同且答案相同之 hit 被合併，保留最小 row_id 且不因歧義被擋。"""
    hit_a = _make_hit(10, "肉毒桿菌除皺術後注意事項？", answer="答案相同")
    hit_b = _make_hit(5, "肉毒桿菌除皺術後注意事項？", answer="答案相同")
    decision = select_confident_faq(
        query="肉毒桿菌除皺術後注意事項？",
        faq_hits=[hit_a, hit_b],
        route="special",
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert decision.reason == "confident"
    assert decision.hit.row_id == 5  # 保留最小 row_id


def test_select_confident_faq_ambiguous_same_question_diff_answer():
    """測試同問句但答案不同時，margin=0 判定為 ambiguous。"""
    hit1 = _make_hit(1, "電波拉皮術後飲食禁忌有哪些？", answer="答案A：請多吃清淡。")
    hit2 = _make_hit(2, "電波拉皮術後飲食禁忌有哪些？", answer="答案B：完全不同的說明。")
    decision = select_confident_faq(
        query="電波拉皮術後飲食禁忌有哪些？",
        faq_hits=[hit1, hit2],
        route="special",
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert decision.reason == "ambiguous"
    assert decision.margin == 0.0
    assert decision.hit is None


def test_select_confident_faq_ambiguous_margin_insufficient():
    """測試次佳候選與最佳候選差距小於 0.1 時判定為 ambiguous。"""
    hit1 = _make_hit(1, "音波拉提術後照護重點須知")
    hit2 = _make_hit(2, "音波拉提術後照護重點指南")
    decision = select_confident_faq(
        query="音波拉提術後照護重點",
        faq_hits=[hit1, hit2],
        route="special",
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert decision.reason == "ambiguous"


def test_select_confident_faq_shuffle_invariance():
    """測試打亂輸入順序不影響最終判定結果。"""
    hits = [
        _make_hit(1, "音波拉提術後照護重點？"),
        _make_hit(2, "皮秒雷射術後照護重點？"),
        _make_hit(3, "玻尿酸注射術後照護重點？"),
    ]
    query = "音波拉提術後照護重點？"
    d1 = select_confident_faq(query, hits, "special", "3503190424", _STOPWORD_SPLIT_PATTERN)

    shuffled_hits = list(hits)
    random.shuffle(shuffled_hits)
    d2 = select_confident_faq(query, shuffled_hits, "special", "3503190424", _STOPWORD_SPLIT_PATTERN)

    assert d1.reason == d2.reason == "confident"
    assert d1.hit.row_id == d2.hit.row_id == 1


# ==============================================================================
# 4. 對抗性案例：隔離組（前置覆蓋率達標，全靠風險檢查擋下）
# ==============================================================================

def test_adversarial_isolated_negation_bu():
    """隔離組 (a)：否定『不』——前置覆蓋率達標，但因風險特徵不符擋下。"""
    faq_q = "肉毒桿菌注射完成後一週內的日常生活與飲食保養是否可以喝酒？"
    query = "肉毒桿菌注射完成後一週內的日常生活與飲食保養是否不可以喝酒？"

    q_norm = normalize_for_match(query, _STOPWORD_SPLIT_PATTERN)
    f_norm = normalize_for_match(faq_q, _STOPWORD_SPLIT_PATTERN)
    q_cov, f_cov = score_hit(q_norm, f_norm)
    # 證明若無風險檢查，此覆蓋率足以通過
    assert q_cov >= MIN_QUERY_COVERAGE
    assert f_cov >= MIN_QUESTION_COVERAGE

    hit = _make_hit(1, faq_q)
    decision = select_confident_faq(query, [hit], "special", "3503190424", _STOPWORD_SPLIT_PATTERN)
    assert decision.hit is None
    assert decision.reason == "risk_mismatch"


def test_adversarial_isolated_numbers_7th_and_cjk():
    """隔離組 (b)：數字不同（第3天 vs 第7天 vs 第三天）。"""
    faq_q = "拆線後第3天的傷口照護與洗澡清潔是否可以使用一般肥皂？"
    hit = _make_hit(1, faq_q)

    # 1. 第7天
    q_7 = "拆線後第7天的傷口照護與洗澡清潔是否可以使用一般肥皂？"
    q_norm = normalize_for_match(q_7, _STOPWORD_SPLIT_PATTERN)
    f_norm = normalize_for_match(faq_q, _STOPWORD_SPLIT_PATTERN)
    q_cov, f_cov = score_hit(q_norm, f_norm)
    assert q_cov >= MIN_QUERY_COVERAGE and f_cov >= MIN_QUESTION_COVERAGE
    d_7 = select_confident_faq(q_7, [hit], "special", "3503190424", _STOPWORD_SPLIT_PATTERN)
    assert d_7.reason == "risk_mismatch" and d_7.hit is None

    # 2. 第三天
    q_cjk = "拆線後第三天的傷口照護與洗澡清潔是否可以使用一般肥皂？"
    q_cjk_norm = normalize_for_match(q_cjk, _STOPWORD_SPLIT_PATTERN)
    q_cov_c, f_cov_c = score_hit(q_cjk_norm, f_norm)
    assert q_cov_c >= MIN_QUERY_COVERAGE and f_cov_c >= MIN_QUESTION_COVERAGE
    d_cjk = select_confident_faq(q_cjk, [hit], "special", "3503190424", _STOPWORD_SPLIT_PATTERN)
    assert d_cjk.reason == "risk_mismatch" and d_cjk.hit is None


def test_adversarial_isolated_numbers_unit_week():
    """隔離組 (c)：數字單位不同（第3天 vs 第3週）。"""
    faq_q = "拆線後第3天的傷口照護與洗澡清潔是否可以使用一般肥皂？"
    query = "拆線後第3週的傷口照護與洗澡清潔是否可以使用一般肥皂？"

    q_norm = normalize_for_match(query, _STOPWORD_SPLIT_PATTERN)
    f_norm = normalize_for_match(faq_q, _STOPWORD_SPLIT_PATTERN)
    q_cov, f_cov = score_hit(q_norm, f_norm)
    assert q_cov >= MIN_QUERY_COVERAGE and f_cov >= MIN_QUESTION_COVERAGE

    hit = _make_hit(1, faq_q)
    decision = select_confident_faq(query, [hit], "special", "3503190424", _STOPWORD_SPLIT_PATTERN)
    assert decision.reason == "risk_mismatch"
    assert decision.hit is None


def test_adversarial_isolated_dose_unit_mg_vs_g():
    """隔離組 (d)：劑量單位不同（5mg vs 5g）。"""
    faq_q = "止痛藥物術後每次服用5mg之後需要間隔多久再服用下一次並記錄症狀變化？"
    query = "止痛藥物術後每次服用5g之後需要間隔多久再服用下一次並記錄症狀變化？"

    q_norm = normalize_for_match(query, _STOPWORD_SPLIT_PATTERN)
    f_norm = normalize_for_match(faq_q, _STOPWORD_SPLIT_PATTERN)
    q_cov, f_cov = score_hit(q_norm, f_norm)
    assert q_cov >= MIN_QUERY_COVERAGE and f_cov >= MIN_QUESTION_COVERAGE

    hit = _make_hit(1, faq_q)
    decision = select_confident_faq(query, [hit], "special", "3503190424", _STOPWORD_SPLIT_PATTERN)
    assert decision.reason == "risk_mismatch"
    assert decision.hit is None


def test_adversarial_isolated_negation_wei():
    """隔離組 (e)：否定字『未』（癒合完成前 vs 未癒合完成前）。"""
    faq_q = "拆線後傷口癒合完成前的日常清潔與洗澡是否可以使用一般肥皂？"
    query = "拆線後傷口未癒合完成前的日常清潔與洗澡是否可以使用一般肥皂？"

    q_norm = normalize_for_match(query, _STOPWORD_SPLIT_PATTERN)
    f_norm = normalize_for_match(faq_q, _STOPWORD_SPLIT_PATTERN)
    q_cov, f_cov = score_hit(q_norm, f_norm)
    assert q_cov >= MIN_QUERY_COVERAGE and f_cov >= MIN_QUESTION_COVERAGE

    hit = _make_hit(1, faq_q)
    decision = select_confident_faq(query, [hit], "special", "3503190424", _STOPWORD_SPLIT_PATTERN)
    assert decision.reason == "risk_mismatch"
    assert decision.hit is None


def test_adversarial_isolated_temporal_qian_vs_hou():
    """隔離組 (f)：時序字（注射前 vs 注射後）。"""
    faq_q = "肉毒桿菌注射前一週內的日常生活與飲食保養是否可以喝酒？"
    query = "肉毒桿菌注射後一週內的日常生活與飲食保養是否可以喝酒？"

    q_norm = normalize_for_match(query, _STOPWORD_SPLIT_PATTERN)
    f_norm = normalize_for_match(faq_q, _STOPWORD_SPLIT_PATTERN)
    q_cov, f_cov = score_hit(q_norm, f_norm)
    assert q_cov >= MIN_QUERY_COVERAGE and f_cov >= MIN_QUESTION_COVERAGE

    hit = _make_hit(1, faq_q)
    decision = select_confident_faq(query, [hit], "special", "3503190424", _STOPWORD_SPLIT_PATTERN)
    assert decision.reason == "risk_mismatch"
    assert decision.hit is None


# ==============================================================================
# 5. 對抗性案例：非隔離組（綜合防禦）
# ==============================================================================

def test_adversarial_avoid_word():
    """非隔離組 (g)：避免（長句與短句）。"""
    faq_q = "肉毒桿菌注射完成後一週內的日常生活與飲食保養是否需要喝酒？"
    q_avoid = "肉毒桿菌注射完成後一週內的日常生活與飲食保養是否需要避免喝酒？"
    assert risk_mismatch(q_avoid, faq_q) is True

    hit = _make_hit(1, faq_q)
    decision = select_confident_faq(q_avoid, [hit], "special", "3503190424", _STOPWORD_SPLIT_PATTERN)
    assert decision.hit is None

    # 短句
    faq_short = "術後需要喝酒嗎？"
    q_short_avoid = "術後需要避免喝酒"
    assert risk_mismatch(q_short_avoid, faq_short) is True
    hit_short = _make_hit(2, faq_short)
    decision_short = select_confident_faq(q_short_avoid, [hit_short], "special", "3503190424", _STOPWORD_SPLIT_PATTERN)
    assert decision_short.hit is None


def test_adversarial_allergy_qualifier():
    """非隔離組 (h)：過敏體質限定詞。"""
    faq_q = "肉毒桿菌注射完成後一週內的日常生活與飲食保養是否可以喝酒？"
    query = "肉毒桿菌注射完成後一週內的日常生活與飲食保養是否過敏體質可以喝酒？"
    assert "q過敏" in extract_risk_features(query)
    assert risk_mismatch(query, faq_q) is True

    hit = _make_hit(1, faq_q)
    decision = select_confident_faq(query, [hit], "special", "3503190424", _STOPWORD_SPLIT_PATTERN)
    assert decision.hit is None


def test_adversarial_pre_vs_post_short():
    """非隔離組 (i)：術前 vs 術後短句。"""
    faq_q = "術前可以喝酒嗎？"
    query = "術後可以喝酒嗎？"
    assert risk_mismatch(query, faq_q) is True

    hit = _make_hit(1, faq_q)
    decision = select_confident_faq(query, [hit], "special", "3503190424", _STOPWORD_SPLIT_PATTERN)
    assert decision.hit is None


def test_adversarial_pregnant_qualifier():
    """非隔離組 (j)：孕婦限定詞。"""
    faq_q = "音波拉提術後照護重點有哪些？"
    query = "孕婦音波拉提術後照護重點有哪些？"
    assert "q孕" in extract_risk_features(query)
    assert risk_mismatch(query, faq_q) is True

    hit = _make_hit(1, faq_q)
    decision = select_confident_faq(query, [hit], "special", "3503190424", _STOPWORD_SPLIT_PATTERN)
    assert decision.hit is None


def test_adversarial_topic_prefix_only():
    """非隔離組 (k)：只有主題前綴。"""
    hit = _make_hit(1, "音波拉提術後照護重點有哪些？")
    decision = select_confident_faq("音波拉提", [hit], "special", "3503190424", _STOPWORD_SPLIT_PATTERN)
    assert decision.hit is None


def test_adversarial_broad_query():
    """非隔離組 (l)：寬泛查詢（low_coverage 擋下）。"""
    hit = _make_hit(1, "甲溝炎門診處理包含哪些內容？")
    decision = select_confident_faq("甲溝炎怎麼處理？", [hit], "special", "3503190424", _STOPWORD_SPLIT_PATTERN)
    assert decision.hit is None
    assert decision.reason == "low_coverage"


def test_adversarial_short_negation():
    """非隔離組 (m)：可以 vs 不可以短句。"""
    faq_q = "術後可以喝酒嗎？"
    query = "術後不可以喝酒嗎？"
    assert risk_mismatch(query, faq_q) is True

    hit = _make_hit(1, faq_q)
    decision = select_confident_faq(query, [hit], "special", "3503190424", _STOPWORD_SPLIT_PATTERN)
    assert decision.hit is None
