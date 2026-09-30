"""
handle_query 快取優先短路整合測試（Phase 07 CACHE-01, CACHE-04）。
驗證：
1. 高信心精確命中時短路回覆（source='cache'，附 cache_answer，清空其他結果）。
2. 低信心/釋義/歧義/跨診所時退回 PageIndex（source='pageindex'）。
3. 價格遮蔽在短路回覆中強制生效（CACHE-04）。
4. 醫療對抗性案例（否定、天數/單位、劑量、術前術後、人群體質）皆不短路，先有正向對照證明可短路。
5. 真實資料庫回歸測試（至少 20 筆真實 special FAQ 能自我命中短路）。
"""

import sqlite3
import pytest

from src.query.faq_shortcut import normalize_for_match
from src.query.router import (
    _STOPWORD_SPLIT_PATTERN,
    classify,
    handle_query,
)


def _insert_test_faq(
    conn: sqlite3.Connection,
    question: str,
    answer: str,
    topic_key: str,
    clinic_id: str | None = "3503190424",
    category: str = "special",
) -> int:
    """插入測試用 FAQ 並回傳 row_id。"""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type)
        VALUES (?, ?, ?, ?, ?, 'manual')
        """,
        (clinic_id, topic_key, question, answer, category),
    )
    conn.commit()
    return cur.lastrowid


# ==============================================================================
# 1. 核心短路與回傳欄位行為測試
# ==============================================================================

def test_handle_query_special_shortcut_success(isolated_conn):
    """測試 special 路由精確命中時短路回傳 FAQ 原文，其餘欄位清空。"""
    q = "皮秒雷射術後居家冰敷重點有哪些？"
    ans = "冰敷每次十分鐘，避免用力搓揉，間隔半小時一次。"
    r_id = _insert_test_faq(isolated_conn, q, ans, "t-cache-a")

    res = handle_query(isolated_conn, q, clinic_id="3503190424")

    assert res.source == "cache"
    assert res.cache_eligible is True
    assert res.cache_answer == ans
    assert len(res.faq_hits) == 1
    assert res.faq_hits[0].row_id == r_id
    assert res.page_index_hits == []
    assert res.drug_hits == []
    assert res.service_item_hits == []
    assert res.clinic_custom_notes == {}
    assert res.clinic_info is None
    assert res.clinic_hours == []


def test_handle_query_paraphrase_falls_back_to_pageindex(isolated_conn):
    """測試釋義問句（低覆蓋）不短路，退回 normal 流程，source='pageindex'。"""
    q_faq = "皮秒雷射術後居家冰敷重點有哪些？"
    ans = "冰敷每次十分鐘。"
    _insert_test_faq(isolated_conn, q_faq, ans, "t-cache-para")

    # 釋義查詢：詞彙覆蓋不足
    q_user = "皮秒雷射後臉部發紅怎麼辦？"
    res = handle_query(isolated_conn, q_user, clinic_id="3503190424")

    assert res.source == "pageindex"
    assert res.cache_answer is None
    assert res.cache_eligible is True


def test_handle_query_ambiguous_two_different_answers(isolated_conn):
    """測試相同問句但存在兩個不同答案時，因歧義不短路。"""
    q = "電波拉皮術後飲食禁忌有哪些？"
    _insert_test_faq(isolated_conn, q, "答案一：避免辛辣。", "t-cache-amb1")
    _insert_test_faq(isolated_conn, q, "答案二：請清淡飲食。", "t-cache-amb2")

    res = handle_query(isolated_conn, q, clinic_id="3503190424")
    assert res.source == "pageindex"


def test_handle_query_ambiguous_not_truncated_by_limit(isolated_conn):
    """測試呼叫端傳入 limit=1 時，仍由大候選集發現歧義而不誤短路。"""
    q = "電波拉皮術後飲食禁忌有哪些？"
    _insert_test_faq(isolated_conn, q, "答案X：避免刺激性食物。", "t-cache-amb3")
    _insert_test_faq(isolated_conn, q, "答案Y：不可飲酒吸菸。", "t-cache-amb4")

    res = handle_query(isolated_conn, q, clinic_id="3503190424", limit=1)
    assert res.source == "pageindex"
    assert len(res.faq_hits) <= 1


def test_handle_query_special_missing_clinic_id_raises_value_error(isolated_conn):
    """測試 special 路由缺少 clinic_id 時仍拋出 ValueError，短路不繞過必填檢查。"""
    q = "音波拉提術後照護重點有哪些？"
    _insert_test_faq(isolated_conn, q, "冰敷並保濕。", "t-cache-err")

    with pytest.raises(ValueError) as exc_info:
        handle_query(isolated_conn, q, clinic_id=None)
    assert "clinic_id" in str(exc_info.value)


def test_handle_query_other_clinic_not_shortcut(isolated_conn):
    """測試其他診所的 FAQ 即使完全同問句，查詢時不被短路回傳。"""
    q = "飛梭雷射術後防曬規定有哪些？"
    _insert_test_faq(isolated_conn, q, "他院防曬指引。", "t-cache-other", clinic_id="other-clinic-999")

    res = handle_query(isolated_conn, q, clinic_id="3503190424")
    assert res.source == "pageindex"


def test_handle_query_ops_keywords_not_shortcut(isolated_conn):
    """測試問及診所營運關鍵字時不短路，clinic_hours 正常回傳，cache_eligible=False。"""
    q = "診所營業時間是什麼？"
    _insert_test_faq(isolated_conn, q, "營業時間問答。", "t-cache-ops")

    res = handle_query(isolated_conn, q, clinic_id="3503190424")
    assert res.source == "pageindex"
    assert res.cache_eligible is False
    assert len(res.clinic_hours) >= 7


def test_handle_query_cache_shortcut_disabled(isolated_conn):
    """測試 cache_shortcut=False 時強制不短路，且 cache_eligible=False。"""
    q = "皮秒雷射術後居家冰敷重點有哪些？"
    ans = "冰敷每次十分鐘。"
    _insert_test_faq(isolated_conn, q, ans, "t-cache-dis")

    res = handle_query(isolated_conn, q, clinic_id="3503190424", cache_shortcut=False)
    assert res.source == "pageindex"
    assert res.cache_eligible is False
    assert res.cache_answer is None


def test_handle_query_general_route_shortcut(isolated_conn):
    """測試 general 路由 + general FAQ（clinic_id=None）順利短路。"""
    q = "感冒多喝水有用嗎？"
    ans = "多喝水有助於維持水分代謝並稀釋黏稠分泌物。"
    r_id = _insert_test_faq(isolated_conn, q, ans, "t-cache-gen", clinic_id=None, category="general")

    res = handle_query(isolated_conn, q, clinic_id=None)
    assert res.source == "cache"
    assert res.cache_answer == ans
    assert res.clinic_info is None
    assert res.clinic_hours == []
    assert len(res.faq_hits) == 1
    assert res.faq_hits[0].row_id == r_id


def test_handle_query_price_masking_in_shortcut(isolated_conn):
    """測試短路答案中若含有金額文字，強制經過 mask_prices 遮蔽。"""
    q = "肉毒桿菌除皺方案收費說明？"
    ans = "特惠只要 3000元，雙部位 5000塊，NT$8000 起。"
    _insert_test_faq(isolated_conn, q, ans, "t-cache-price")

    res = handle_query(isolated_conn, q, clinic_id="3503190424")
    assert res.source == "cache"

    # 斷言無價格數字，且含 [請致電診所確認]
    for sensitive in ("3000元", "5000塊", "NT$8000"):
        assert sensitive not in res.cache_answer
        assert sensitive not in res.faq_hits[0].fields["answer"]

    assert "[請致電診所確認]" in res.cache_answer
    assert "[請致電診所確認]" in res.faq_hits[0].fields["answer"]


def test_handle_query_source_domain(isolated_conn):
    """測試 handle_query 回傳之 source 欄位值僅可能是 'cache' 或 'pageindex'。"""
    res1 = handle_query(isolated_conn, "隨機一般查詢")
    assert res1.source in ("cache", "pageindex")


# ==============================================================================
# 2. 對抗性案例整合測試（正向對照 + 變形查詢防禦）
# ==============================================================================

def test_adversarial_integration_negation_bu(isolated_conn):
    """對抗性 (a)：否定字『不』——正向命中，加入不可以即不短路。"""
    q_faq = "肉毒桿菌注射完成後一週內的日常生活與飲食保養是否可以喝酒？"
    ans = "施作後一週內嚴禁飲酒。"
    _insert_test_faq(isolated_conn, q_faq, ans, "t-adv-neg")

    # 正向對照
    res_pos = handle_query(isolated_conn, q_faq, clinic_id="3503190424")
    assert res_pos.source == "cache"

    # 變形防禦
    q_adv = "肉毒桿菌注射完成後一週內的日常生活與飲食保養是否不可以喝酒？"
    res_adv = handle_query(isolated_conn, q_adv, clinic_id="3503190424")
    assert res_adv.source == "pageindex"


@pytest.mark.parametrize("q_adv", [
    "拆線後第7天的傷口照護與洗澡清潔是否可以使用一般肥皂？",
    "拆線後第三天的傷口照護與洗澡清潔是否可以使用一般肥皂？",
    "拆線後第3週的傷口照護與洗澡清潔是否可以使用一般肥皂？",
])
def test_adversarial_integration_numbers(isolated_conn, q_adv):
    """對抗性 (b)：數字不同（第7天、第三天、第3週）皆不短路。"""
    q_faq = "拆線後第3天的傷口照護與洗澡清潔是否可以使用一般肥皂？"
    ans = "前三天避免使用刺激性肥皂。"
    _insert_test_faq(isolated_conn, q_faq, ans, "t-adv-num")

    # 正向對照
    res_pos = handle_query(isolated_conn, q_faq, clinic_id="3503190424")
    assert res_pos.source == "cache"

    # 變形防禦
    res_adv = handle_query(isolated_conn, q_adv, clinic_id="3503190424")
    assert res_adv.source == "pageindex"


def test_adversarial_integration_dose_units(isolated_conn):
    """對抗性 (c)：劑量單位（5mg vs 5g）。"""
    q_faq = "止痛藥物術後每次服用5mg之後需要間隔多久再服用下一次並記錄症狀變化？"
    ans = "每次5mg，間隔四至六小時。"
    _insert_test_faq(isolated_conn, q_faq, ans, "t-adv-dose")

    # 正向對照
    res_pos = handle_query(isolated_conn, q_faq, clinic_id="3503190424")
    assert res_pos.source == "cache"

    # 變形防禦
    q_adv = "止痛藥物術後每次服用5g之後需要間隔多久再服用下一次並記錄症狀變化？"
    res_adv = handle_query(isolated_conn, q_adv, clinic_id="3503190424")
    assert res_adv.source == "pageindex"


def test_adversarial_integration_negation_wei(isolated_conn):
    """對抗性 (d)：否定字『未』（癒合前 vs 未癒合前）。"""
    q_faq = "拆線後傷口癒合完成前的日常清潔與洗澡是否可以使用一般肥皂？"
    ans = "傷口未癒合前請以生理食鹽水清潔。"
    _insert_test_faq(isolated_conn, q_faq, ans, "t-adv-wei")

    # 正向對照
    res_pos = handle_query(isolated_conn, q_faq, clinic_id="3503190424")
    assert res_pos.source == "cache"

    # 變形防禦
    q_adv = "拆線後傷口未癒合完成前的日常清潔與洗澡是否可以使用一般肥皂？"
    res_adv = handle_query(isolated_conn, q_adv, clinic_id="3503190424")
    assert res_adv.source == "pageindex"


def test_adversarial_integration_pre_vs_post(isolated_conn):
    """對抗性 (e)：時序字（注射前 vs 注射後）。"""
    q_faq = "肉毒桿菌注射前一週內的日常生活與飲食保養是否可以喝酒？"
    ans = "注射前一週請避免飲酒與抗凝血藥品。"
    _insert_test_faq(isolated_conn, q_faq, ans, "t-adv-pos")

    # 正向對照
    res_pos = handle_query(isolated_conn, q_faq, clinic_id="3503190424")
    assert res_pos.source == "cache"

    # 變形防禦
    q_adv = "肉毒桿菌注射後一週內的日常生活與飲食保養是否可以喝酒？"
    res_adv = handle_query(isolated_conn, q_adv, clinic_id="3503190424")
    assert res_adv.source == "pageindex"


def test_adversarial_integration_avoid_word(isolated_conn):
    """對抗性 (f)：禁忌字『避免』。"""
    q_faq = "肉毒桿菌注射完成後一週內的日常生活與飲食保養是否需要喝酒？"
    ans = "不需要，且應避免飲酒。"
    _insert_test_faq(isolated_conn, q_faq, ans, "t-adv-avoid")

    # 正向對照
    res_pos = handle_query(isolated_conn, q_faq, clinic_id="3503190424")
    assert res_pos.source == "cache"

    # 變形防禦
    q_adv = "肉毒桿菌注射完成後一週內的日常生活與飲食保養是否需要避免喝酒？"
    res_adv = handle_query(isolated_conn, q_adv, clinic_id="3503190424")
    assert res_adv.source == "pageindex"


def test_adversarial_integration_allergy_qualifier(isolated_conn):
    """對抗性 (g)：人群體質詞『過敏體質』。"""
    q_faq = "肉毒桿菌注射完成後一週內的日常生活與飲食保養是否可以喝酒？"
    ans = "無論體質皆請避免飲酒。"
    _insert_test_faq(isolated_conn, q_faq, ans, "t-adv-qual")

    # 正向對照
    res_pos = handle_query(isolated_conn, q_faq, clinic_id="3503190424")
    assert res_pos.source == "cache"

    # 變形防禦
    q_adv = "肉毒桿菌注射完成後一週內的日常生活與飲食保養是否過敏體質可以喝酒？"
    res_adv = handle_query(isolated_conn, q_adv, clinic_id="3503190424")
    assert res_adv.source == "pageindex"


def test_adversarial_integration_pregnant_qualifier(isolated_conn):
    """對抗性 (h)：限定詞『孕婦』。"""
    q_faq = "音波拉提術後照護重點有哪些？"
    ans = "加強保濕與防曬。"
    _insert_test_faq(isolated_conn, q_faq, ans, "t-adv-preg")

    # 正向對照
    res_pos = handle_query(isolated_conn, q_faq, clinic_id="3503190424")
    assert res_pos.source == "cache"

    # 變形防禦
    q_adv = "孕婦音波拉提術後照護重點有哪些？"
    res_adv = handle_query(isolated_conn, q_adv, clinic_id="3503190424")
    assert res_adv.source == "pageindex"


def test_adversarial_integration_topic_prefix_only(isolated_conn):
    """對抗性 (i)：僅有主題前綴。"""
    q_faq = "音波拉提術後照護重點有哪些？"
    _insert_test_faq(isolated_conn, q_faq, "照護指引。", "t-adv-prefix")

    res = handle_query(isolated_conn, "音波拉提", clinic_id="3503190424")
    assert res.source == "pageindex"


@pytest.mark.parametrize("q_broad", ["甲溝炎怎麼處理？", "甲溝炎"])
def test_adversarial_integration_broad_queries(conn, q_broad):
    """對抗性 (j)：以正式資料庫複本驗證寬泛問句不短路。"""
    res = handle_query(conn, q_broad, clinic_id="3503190424")
    assert res.source == "pageindex"


# ==============================================================================
# 3. 真實資料庫回歸測試
# ==============================================================================

def test_real_database_faq_self_hit_regression(conn):
    """真實資料回歸：正式庫中分類為 special 且標準化問句全庫唯一之 FAQ，自我查詢必須短路。"""
    cur = conn.cursor()
    cur.execute("SELECT id, question, answer, category FROM faq_cache WHERE category = 'special'")
    all_rows = cur.fetchall()

    # 計算標準化問句出現頻率以確保唯一性
    q_counts = {}
    for _, q, _, _ in all_rows:
        norm = normalize_for_match(q, _STOPWORD_SPLIT_PATTERN)
        q_counts[norm] = q_counts.get(norm, 0) + 1

    tested_count = 0
    passed_count = 0

    for row_id, question, _, _ in all_rows:
        route_res = classify(question)
        norm_q = normalize_for_match(question, _STOPWORD_SPLIT_PATTERN)

        # 僅檢驗符合 special 路由且問句唯一者
        if route_res.route == "special" and q_counts[norm_q] == 1:
            tested_count += 1
            res = handle_query(conn, question, clinic_id="3503190424", limit=5)
            if res.source == "cache" and res.faq_hits and res.faq_hits[0].row_id == row_id:
                passed_count += 1

    # 符合條件之筆數必須 >= 20
    assert tested_count >= 20
    assert passed_count == tested_count
