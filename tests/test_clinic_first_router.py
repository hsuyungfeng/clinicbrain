"""
診所資料優先檢索與跨層級路由測試（Phase 11 CF-01, CF-02, CF-03）。
涵蓋：
- 設計題 A: 隔離宣告局部放寬（僅放寬診所自己 category=special 的 FAQ）
- 設計題 B: 跨層級競爭規則（診所優先、歧義/風險不符不退 general）
- 設計題 D: 診所層對抗性變形防禦
- 設計題 E: 審核閘門貫徹（pending/rejected 永不外洩）
- 設計題 F: 快取統計資格與命中語意鎖定
- 設計題 G: 正式庫 40 筆真實 FAQ 複本量測（目標 >= 38/40）
- Blocker: 診所專屬規定 vs 一般通則衝突防護
- 決策 1: 無 clinic_id 跨診所外洩修復
- 決策 2: special 路由退 general 機制
"""

from typing import Optional
import pytest

from src.query.router import handle_query, classify
from src.query.faq_shortcut import select_confident_faq_tiered


def _insert_faq(
    conn,
    question: str,
    answer: str,
    topic_key: str,
    clinic_id: Optional[str] = "3503190424",
    category: str = "special",
    source_type: str = "manual",
    review_status: str = "approved",
) -> int:
    """測試輔助：在隔離連線直接插入測試用 FAQ。"""
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (clinic_id, topic_key, question, answer, category, source_type, review_status),
    )
    conn.commit()
    return cursor.lastrowid


L1 = "甲溝炎門診處理完成之後傷口敷料需要每天更換並且保持乾燥清潔"


def test_r1_cf01_clinic_special_faq_retrieved_in_general_route(isolated_conn):
    """R1: CF-01 診所 special FAQ 即使被 classify 分流為 general，仍能被帶 clinic_id 的查詢命中並短路。"""
    q = "做完特定照護後居家皮膚清潔如何進行？"
    a = "請保持皮膚乾燥，並依照指示進行溫和清潔。"
    assert classify(q).route == "general"

    _insert_faq(isolated_conn, q, a, topic_key="test_r1", clinic_id="3503190424", category="special")

    # 帶 clinic_id：應短路且 data_level 為 clinic
    resp = handle_query(isolated_conn, q, clinic_id="3503190424")
    assert resp.source == "cache"
    assert resp.cache_answer == a
    assert resp.data_level == "clinic"
    assert resp.route == "general"

    # 對照：不帶 clinic_id 不得命中診所 FAQ，且 data_level 不為 clinic
    resp_no_clinic = handle_query(isolated_conn, q, clinic_id=None)
    assert resp_no_clinic.source == "pageindex"
    assert resp_no_clinic.cache_answer is None
    assert getattr(resp_no_clinic, "data_level", None) != "clinic"


def test_r2_cf02_fallback_to_approved_general_faq(isolated_conn):
    """R2: CF-02 當診所無合格候選時，帶 clinic_id 查詢退到 approved general FAQ。"""
    q = "一般日常飲水量每日建議標準是多少毫升？"
    a = "成人每日建議飲水量約為體重乘以 30 毫升。"
    assert classify(q).route == "general"

    _insert_faq(isolated_conn, q, a, topic_key="test_r2", clinic_id=None, category="general")

    resp = handle_query(isolated_conn, q, clinic_id="3503190424")
    assert resp.source == "cache"
    assert resp.cache_answer == a
    assert resp.data_level == "general"


def test_r3_design_b_clinic_priority_over_general(isolated_conn):
    """R3: 設計題 B 診所優先——同問句兩層皆有時，診所答案勝出且 data_level 為 clinic。"""
    q = "一般臉部清潔保養方式該如何進行？"
    a_clinic = "緻妍診所專屬指示：前 3 天請使用無菌棉花棒與生理食鹽水擦拭。"
    a_general = "一般衛教建議：溫和洗面乳輕柔清洗即可。"
    assert classify(q).route == "general"

    _insert_faq(isolated_conn, q, a_clinic, topic_key="test_r3_c", clinic_id="3503190424", category="special")
    _insert_faq(isolated_conn, q, a_general, topic_key="test_r3_g", clinic_id=None, category="general")

    resp = handle_query(isolated_conn, q, clinic_id="3503190424")
    assert resp.source == "cache"
    assert resp.cache_answer == a_clinic
    assert resp.data_level == "clinic"


def test_r4_design_b_clinic_ambiguous_does_not_fallback_to_general(isolated_conn):
    """R4: 設計題 B 診所歧義不退 general——診所有兩筆相同問句不同答案時不短路，且非短路排序列出診所優先。"""
    q = L1
    a_c1 = "診所方案一：每天早晚各換一次。"
    a_c2 = "診所方案二：每天洗澡後更換一次。"
    a_gen = "一般建議：保持乾燥。"

    _insert_faq(isolated_conn, q, a_c1, topic_key="test_r4_c1", clinic_id="3503190424", category="special")
    _insert_faq(isolated_conn, q, a_c2, topic_key="test_r4_c2", clinic_id="3503190424", category="special")
    _insert_faq(isolated_conn, q, a_gen, topic_key="test_r4_g", clinic_id=None, category="general")

    resp = handle_query(isolated_conn, q, clinic_id="3503190424")
    assert resp.source == "pageindex"
    assert resp.cache_answer is None
    # 診所層級 FAQ 排序應在 general 之前
    assert len(resp.faq_hits) >= 2
    assert resp.faq_hits[0].fields.get("clinic_id") == "3503190424"


def test_r5_design_a_isolation_intact(isolated_conn):
    """R5: 設計題 A 隔離宣告局部放寬——僅放寬診所 FAQ，general 路由下 clinic_info/hours/notes 與 pageindex 隔離完全不動。"""
    q_gen = "一般皮膚紅腫癢該如何初步照護？"
    assert classify(q_gen).route == "general"

    # 1. 帶 clinic_id 查 general 路由，營運資訊仍強制隔離
    resp_gen = handle_query(isolated_conn, q_gen, clinic_id="3503190424", cache_shortcut=False)
    assert resp_gen.clinic_info is None
    assert resp_gen.clinic_hours == []
    assert resp_gen.clinic_custom_notes == {}
    for hit in resp_gen.page_index_hits:
        assert hit.fields.get("category") == "general"

    # 2. 營運問句走 special 路由正常取得營運資訊
    q_ops = "請問診所幾點開門？"
    resp_ops = handle_query(isolated_conn, q_ops, clinic_id="3503190424")
    assert len(resp_ops.clinic_hours) > 0
    assert resp_ops.source == "pageindex"

    # 3. 診所 FAQ 問句若剛好包含『地址』等營運字眼，不可短路
    q_with_ops = "診所地址附近有停車場可以停車嗎？"
    _insert_faq(isolated_conn, q_with_ops, "附近有收費停車場", topic_key="test_r5_ops", clinic_id="3503190424", category="special")
    resp_with_ops = handle_query(isolated_conn, q_with_ops, clinic_id="3503190424")
    assert resp_with_ops.cache_eligible is False
    assert resp_with_ops.source == "pageindex"


def test_r6_design_e_review_gate_enforcement(isolated_conn):
    """R6: 設計題 E 審核閘門——未核准（pending/rejected）的 llm_generated FAQ 絕不出現在 faq_hits 或短路。"""
    from src.pageindex.faq_writer import upsert_faqs
    from src.pageindex.faq_review import set_review_status

    q = "夜間生成特定保養衛教常見問題？"
    a = "建議諮詢專業醫師進行客製化評估。"

    # 1. 以 llm_generated 寫入（預設 pending）
    faq_dict = {
        "clinic_id": "3503190424",
        "topic_key": "test_r6_pending",
        "question": q,
        "answer": a,
        "category": "special",
    }
    upsert_faqs(isolated_conn, [faq_dict], source_type="llm_generated")

    resp_pending = handle_query(isolated_conn, q, clinic_id="3503190424")
    assert resp_pending.source != "cache"
    assert not any(h.fields.get("question") == q for h in resp_pending.faq_hits)

    # 2. 駁回 rejected 同樣不可見
    cur = isolated_conn.cursor()
    row_id = cur.execute("SELECT id FROM faq_cache WHERE topic_key='test_r6_pending'").fetchone()[0]
    set_review_status(isolated_conn, [row_id], "rejected")

    resp_rejected = handle_query(isolated_conn, q, clinic_id="3503190424")
    assert resp_rejected.source != "cache"
    assert not any(h.fields.get("question") == q for h in resp_rejected.faq_hits)

    # 3. 核准 approved 後立即可見並短路
    set_review_status(isolated_conn, [row_id], "approved")
    resp_approved = handle_query(isolated_conn, q, clinic_id="3503190424")
    assert resp_approved.source == "cache"
    assert resp_approved.data_level == "clinic"


@pytest.mark.parametrize(
    "variant_query",
    [
        "甲溝炎門診處理完成之後傷口敷料需要每3天更換並且保持乾燥清潔",
        "甲溝炎門診處理完成之前傷口敷料需要每天更換並且保持乾燥清潔",
        "甲溝炎門診處理完成之後不傷口敷料需要每天更換並且保持乾燥清潔",
        "甲溝炎門診處理完成之後傷口敷料需要每天更換並且保持乾燥清潔前",
        "甲溝炎門診處理完成之後傷口敷料需要每天不要更換並且保持乾燥清潔",
        "甲溝炎門診處理完成之後傷口敷料孕婦需要每天更換並且保持乾燥清潔",
    ],
)
def test_r7_design_d_clinic_adversarial_variants(isolated_conn, variant_query):
    """R7: 設計題 D 診所層對抗性變形防禦——變形問句皆不得短路，且 general 放入同句亦不得退回 general。"""
    a_clinic = "診所回答：每天更換保持乾燥。"
    a_gen = "一般回答：保持清潔。"
    _insert_faq(isolated_conn, L1, a_clinic, topic_key="test_r7_c", clinic_id="3503190424", category="special")
    _insert_faq(isolated_conn, variant_query, a_gen, topic_key="test_r7_g", clinic_id=None, category="general")

    resp = handle_query(isolated_conn, variant_query, clinic_id="3503190424")
    assert resp.source == "pageindex"
    assert resp.cache_answer is None
    assert getattr(resp, "data_level", None) != "general"


def test_r7_positive_control(isolated_conn):
    """R7 正向對照：L1 原句高信心命中診所。"""
    a_clinic = "診所回答：每天更換保持乾燥。"
    _insert_faq(isolated_conn, L1, a_clinic, topic_key="test_r7_pos", clinic_id="3503190424", category="special")

    resp = handle_query(isolated_conn, L1, clinic_id="3503190424")
    assert resp.source == "cache"
    assert resp.data_level == "clinic"


@pytest.mark.parametrize(
    "query",
    [
        "縫合後傷口可以洗澡嗎",
        "縫合後的傷口可以洗澡嗎？",
        "縫合後傷口多久可以洗澡？",
    ],
)
def test_r8_blocker_regression_wound_showering_conflict(isolated_conn, query):
    """R8: Blocker 回歸鎖定——診所專屬規定（不可碰水）與 general 通則（可淋浴）衝突時，短句變形不得短路為 general。"""
    q_c = "縫合後的傷口可以碰水洗澡嗎？"
    a_c = "本診所規定縫合後一週內不可碰水"
    q_g = "縫合後的傷口可以洗澡嗎？"
    a_g = "包覆防水敷料後可以淋浴"

    _insert_faq(isolated_conn, q_c, a_c, topic_key="test_r8_c", clinic_id="3503190424", category="special")
    _insert_faq(isolated_conn, q_g, a_g, topic_key="test_r8_g", clinic_id=None, category="general")

    resp = handle_query(isolated_conn, query, clinic_id="3503190424")
    assert resp.source == "pageindex"
    assert resp.cache_answer is None
    assert getattr(resp, "data_level", None) != "general"


def test_r8_positive_control(isolated_conn):
    """R8 正向對照：查詢完全吻合診所問句時命中診所。"""
    q_c = "縫合後的傷口可以碰水洗澡嗎？"
    _insert_faq(isolated_conn, q_c, "本診所規定縫合後一週內不可碰水", topic_key="test_r8_pos", clinic_id="3503190424", category="special")
    resp = handle_query(isolated_conn, q_c, clinic_id="3503190424")
    assert resp.source == "cache"
    assert resp.data_level == "clinic"


def test_r9_design_g_real_db_40_faqs_retrieval(isolated_conn):
    """R9: 設計題 G 正式庫 40 筆診所 FAQ 原文自查驗收：短路數 >= 38，未短路者僅限 id 4 與 id 19 歧義問句。"""
    from src.pageindex.faq_review import visible_faq_sql
    from src.query.router import mask_prices

    vis_sql = visible_faq_sql(isolated_conn)
    cur = isolated_conn.cursor()
    rows = cur.execute(
        f"""
        SELECT id, question, answer
        FROM faq_cache
        WHERE clinic_id = '3503190424' AND ({vis_sql})
        ORDER BY id
        """
    ).fetchall()

    assert len(rows) == 40, f"正式庫複本診所 FAQ 筆數預期 40，實得 {len(rows)}"

    miss_questions = set()
    hit_count = 0
    general_classified_hit_count = 0

    for row_id, question, answer in rows:
        resp = handle_query(isolated_conn, question, clinic_id="3503190424")
        if resp.source == "cache":
            hit_count += 1
            assert resp.data_level == "clinic"
            assert resp.cache_answer == mask_prices(answer)
            if classify(question).route == "general":
                general_classified_hit_count += 1
        else:
            miss_questions.add(question)

    assert hit_count >= 38, f"短路命中筆數預期 >= 38，實得 {hit_count}"
    assert miss_questions == {"痣、疣或皮膚小贅生物可以如何處理？"}, (
        f"未短路問句集合預期僅含痣疣歧義問句，實得 {miss_questions}"
    )
    # 原 16 筆 general 分流的 FAQ 扣除此 2 筆歧義，其餘 14 筆應全部命中
    assert general_classified_hit_count == 14


def test_r10_real_db_variant_safety_scan(isolated_conn):
    """R10: 真實庫 40 筆問句變形防禦掃描——附加語境詞後皆不得短路。"""
    cur = isolated_conn.cursor()
    questions = [r[0] for r in cur.execute("SELECT question FROM faq_cache WHERE clinic_id='3503190424'").fetchall()]

    suffixes = ["孕婦也一樣嗎", "不可以嗎", "術後第3天呢"]
    for q in questions[:10]:  # 取樣測試防拖慢
        for suffix in suffixes:
            variant = q.rstrip("？?") + suffix
            resp = handle_query(isolated_conn, variant, clinic_id="3503190424")
            assert resp.source != "cache", f"問句變形 '{variant}' 竟誤短路！"


def test_r11_price_masking_in_cache_answer(isolated_conn):
    """R11: 快取答案中之價格數字必須遮蔽為 [請致電診所確認]。"""
    q = "特定進階煥膚護理自費療程單次費用約多少？"
    a = "本自費療程單次費用約 1500 元，請向櫃檯洽詢。"
    _insert_faq(isolated_conn, q, a, topic_key="test_r11", clinic_id="3503190424", category="special")

    resp = handle_query(isolated_conn, q, clinic_id="3503190424")
    assert resp.source == "cache"
    assert "1500" not in resp.cache_answer
    assert "[請致電診所確認]" in resp.cache_answer


@pytest.mark.parametrize("invalid_id", [None, "", "   "])
def test_r12_clinic_id_normalization(isolated_conn, invalid_id):
    """R12: clinic_id 正規化——None、空字串與純空白等價；營運問句缺少 clinic_id 一律拋出 ValueError。"""
    q_gen = "做完特定照護後居家皮膚清潔如何進行？"
    assert classify(q_gen).route == "general"
    _insert_faq(isolated_conn, q_gen, "保持乾燥", topic_key="test_r12", clinic_id="3503190424", category="special")

    # general 問句：None / '' / '   ' 結果一致，不見診所 FAQ，data_level 不為 clinic
    resp = handle_query(isolated_conn, q_gen, clinic_id=invalid_id)
    assert resp.source == "pageindex"
    assert resp.cache_answer is None
    assert getattr(resp, "data_level", None) != "clinic"

    # 營運問句：三者皆拋出 ValueError
    q_ops = "請問診所幾點開門？"
    with pytest.raises(ValueError, match="clinic_id"):
        handle_query(isolated_conn, q_ops, clinic_id=invalid_id)


def test_r13_non_shortcut_ranking_and_level(isolated_conn):
    """R13: 非短路時的排序與 data_level 賦予。"""
    from src.query.router import faq_hit_level

    q = "非短路狀況下之術後衛教追蹤？"
    a_c = "診所衛教追蹤"
    a_g = "一般衛教追蹤"
    _insert_faq(isolated_conn, q, a_c, topic_key="test_r13_c", clinic_id="3503190424", category="special")
    _insert_faq(isolated_conn, q, a_g, topic_key="test_r13_g", clinic_id=None, category="general")

    resp = handle_query(isolated_conn, q, clinic_id="3503190424", cache_shortcut=False)
    assert resp.source == "pageindex"
    assert resp.cache_answer is None
    assert len(resp.faq_hits) >= 2
    # 診所層級在前
    assert faq_hit_level(resp.faq_hits[0]) == "clinic"
    assert resp.data_level == "clinic"


def test_r14_design_f_cache_eligible(isolated_conn):
    """R14: 設計題 F cache_eligible 語意鎖定——一般問句為 True，營運問句與關閉短路時為 False。"""
    q_normal = "做完療程回家後，若有不適或不清楚的地方該怎麼處理？"
    resp_hit = handle_query(isolated_conn, q_normal, clinic_id="3503190424")
    assert resp_hit.cache_eligible is True

    q_miss = "無關的皮膚衛教諮詢問答？"
    resp_miss = handle_query(isolated_conn, q_miss, clinic_id="3503190424")
    assert resp_miss.cache_eligible is True

    q_ops = "請問診所門診營業時間？"
    resp_ops = handle_query(isolated_conn, q_ops, clinic_id="3503190424")
    assert resp_ops.cache_eligible is False

    resp_disabled = handle_query(isolated_conn, q_normal, clinic_id="3503190424", cache_shortcut=False)
    assert resp_disabled.cache_eligible is False


def test_r15_static_no_from_faq_cache_in_router():
    """R15: 靜態檢查——src/query/router.py 整檔（含註解）嚴禁出現 'from faq_cache'。"""
    from pathlib import Path
    router_text = Path("src/query/router.py").read_text(encoding="utf-8")
    assert "from faq_cache" not in router_text.lower()


def test_r16_decision_1_cross_clinic_leak_fix(isolated_conn):
    """R16: 決策 1 外洩修復——無 clinic_id 查詢絕不列出他院 FAQ，帶自己 clinic_id 看不到他院列。"""
    q_drug = "這個藥有副作用嗎？"
    q_nhi = "健保給付範圍包含哪些？"
    a_other = "其他診所特定指示"
    a_self = "本院專屬藥物說明"

    # 插入他院 (9999999999) 的 FAQ
    _insert_faq(isolated_conn, q_drug, a_other, topic_key="test_r16_other", clinic_id="9999999999", category="special")
    _insert_faq(isolated_conn, q_drug, a_self, topic_key="test_r16_self", clinic_id="3503190424", category="special")

    # 1. 無 clinic_id 查詢：絕不可包含他院 FAQ
    resp_no_clinic = handle_query(isolated_conn, q_drug, clinic_id=None)
    for h in resp_no_clinic.faq_hits:
        assert h.fields.get("clinic_id") is None
    assert getattr(resp_no_clinic, "data_level", None) in ("general", None)
    assert resp_no_clinic.cache_answer != a_other

    # 2. 帶本院 clinic_id 查詢：看不到他院列
    resp_self = handle_query(isolated_conn, q_drug, clinic_id="3503190424")
    for h in resp_self.faq_hits:
        assert h.fields.get("clinic_id") != "9999999999"
    if resp_self.source == "cache":
        assert resp_self.cache_answer == a_self


def test_r17_decision_2_special_route_fallback_to_general(isolated_conn):
    """R17: 決策 2 special 路由退 general 機制。
    (a) 診所完全無相關 FAQ（query_coverage < 0.4）時退回 approved general。
    (b) 診所有相關但低覆蓋（query_coverage >= 0.4）時不短路。
    """
    # (a) 診所無相關 FAQ，special 路由問句退 general
    q_special_unrelated = "健保給付審查流程一般需要多少工作天？"
    assert classify(q_special_unrelated).route == "special"
    a_gen = "一般給付審查約需 7 至 14 個工作天。"
    _insert_faq(isolated_conn, q_special_unrelated, a_gen, topic_key="test_r17_gen", clinic_id=None, category="general")

    resp_a = handle_query(isolated_conn, q_special_unrelated, clinic_id="3503190424")
    assert resp_a.source == "cache"
    assert resp_a.data_level == "general"
    assert resp_a.cache_answer == a_gen

    # (b) 診所有相近內容（query_coverage >= 0.4）時不退 general
    q_clinic = "皮秒雷射除斑術後修復期需要幾天？"
    q_query = "皮秒雷射術後可以洗臉嗎？"
    assert classify(q_query).route == "special"
    _insert_faq(isolated_conn, q_clinic, "診所皮秒修復指示", topic_key="test_r17_c", clinic_id="3503190424", category="special")
    _insert_faq(isolated_conn, q_query, "一般皮秒修復指示", topic_key="test_r17_g", clinic_id=None, category="general")

    resp_b = handle_query(isolated_conn, q_query, clinic_id="3503190424")
    assert resp_b.source == "pageindex"
    assert resp_b.cache_answer is None
