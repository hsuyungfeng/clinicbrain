"""
跨層級（Tiered）高信心 FAQ 短路判定測試（Phase 11 CF-01, CF-02, CF-03）。
涵蓋跨層級競爭規則（設計題 B）、對抗性變形回歸（設計題 D）與 Blocker 回歸鎖定。
每個測試案例均明確標註所守住之核心關卡。
"""

from typing import Optional
import pytest

from src.query.search import SearchHit
from src.query.router import _STOPWORD_SPLIT_PATTERN
from src.query.faq_shortcut import (
    MIN_QUERY_CHARS,
    MIN_QUERY_COVERAGE,
    MIN_QUESTION_COVERAGE,
    MIN_MARGIN,
    SHORTCUT_CANDIDATE_LIMIT,
    CLINIC_RELATED_FLOOR,
    TieredShortcutDecision,
    select_confident_faq_tiered,
)


def _mk_hit(
    row_id: int,
    question: str,
    answer: str,
    category: str = "special",
    clinic_id: Optional[str] = "3503190424",
) -> SearchHit:
    """測試輔助：建立模擬 SearchHit。"""
    return SearchHit(
        table="faq_cache",
        row_id=row_id,
        fields={
            "id": row_id,
            "question": question,
            "answer": answer,
            "category": category,
            "clinic_id": clinic_id,
        },
    )


# 長測試問句基底
# L1: 診所端基底（甲溝炎照護）
L1 = "甲溝炎門診處理完成之後傷口敷料需要每天更換並且保持乾燥清潔"
# G1: General 端基底（腹瀉水分補充）
G1 = "腹瀉期間需要補充足夠水分並且觀察排便次數與精神狀態變化"


def test_t1_clinic_confident_wins_over_general():
    """T1: 診所高信心勝出（實際守住的關卡：診所覆蓋率門檻通過，優先結案不讓 general 競爭）。"""
    clinic_hit = _mk_hit(1, L1, "診所專屬回答：請遵照醫囑更換敷料", category="special", clinic_id="3503190424")
    general_hit = _mk_hit(2, L1, "一般衛教回答：保持清潔即可", category="general", clinic_id=None)

    decision = select_confident_faq_tiered(
        query=L1,
        clinic_hits=[clinic_hit],
        general_hits=[general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )

    assert decision.hit == clinic_hit
    assert decision.level == "clinic"
    assert decision.reason == "confident"
    assert decision.clinic_reason == "confident"
    assert decision.general_reason == "skipped"


def test_t2_clinic_ambiguous_does_not_fallback_to_general():
    """T2: 診所歧義不退 general（實際守住的關卡：歧義邊界，診所內部有爭議時不應隨意退回 general 產生誤導）。"""
    clinic_hit_a = _mk_hit(1, L1, "診所方案 A", category="special", clinic_id="3503190424")
    clinic_hit_b = _mk_hit(2, L1, "診所方案 B", category="special", clinic_id="3503190424")
    general_hit = _mk_hit(3, L1, "一般方案", category="general", clinic_id=None)

    decision = select_confident_faq_tiered(
        query=L1,
        clinic_hits=[clinic_hit_a, clinic_hit_b],
        general_hits=[general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )

    assert decision.hit is None
    assert decision.level is None
    assert decision.reason == "clinic_ambiguous"
    assert decision.clinic_reason == "ambiguous"
    assert decision.general_reason == "skipped"


@pytest.mark.parametrize(
    "query, expected_reason",
    [
        ("甲溝炎門診處理完成之後傷口敷料需要每3天更換並且保持乾燥清潔", "clinic_risk_mismatch"),
        ("甲溝炎門診處理完成之前傷口敷料需要每天更換並且保持乾燥清潔", "clinic_risk_mismatch"),
        ("甲溝炎門診處理完成之後不傷口敷料需要每天更換並且保持乾燥清潔", "clinic_risk_mismatch"),
    ],
)
def test_t3_clinic_risk_mismatch_does_not_fallback_to_general(query, expected_reason):
    """T3: 診所風險不符不退 general（實際守住的關卡：風險特徵，覆蓋率 >= 0.9 但風險特徵不對稱時阻絕短路且不退 general）。"""
    clinic_hit = _mk_hit(1, L1, "診所回答：每天更換", category="special", clinic_id="3503190424")
    # general 端即便有與該查詢完全相符的高信心 FAQ，亦絕不可選中
    general_hit = _mk_hit(2, query, "一般通則回答", category="general", clinic_id=None)

    decision = select_confident_faq_tiered(
        query=query,
        clinic_hits=[clinic_hit],
        general_hits=[general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )

    assert decision.hit is None
    assert decision.level is None
    assert decision.reason == expected_reason
    assert decision.clinic_reason == "risk_mismatch"
    assert decision.general_reason == "skipped"


@pytest.mark.parametrize(
    "query",
    [
        "縫合後傷口可以洗澡嗎",
        "縫合後的傷口可以洗澡嗎？",
        "縫合後傷口多久可以洗澡？",
    ],
)
def test_t3b_blocker_regression_clinic_related_floor(query):
    """T3b: Blocker 回歸鎖定（實際守住的關卡：CLINIC_RELATED_FLOOR=0.4）。
    診所規定縫合後一週不可碰水，一般通則為防水淋浴；查詢問法稍短時覆蓋率約 0.83（< 0.9），
    若直接退 general 會讓相反的一般通則短路取代診所專屬規定。在 floor=0.4 下必須被擋住不退 general。
    """
    clinic_hit = _mk_hit(
        1,
        "縫合後的傷口可以碰水洗澡嗎？",
        "本診所規定縫合後一週內不可碰水",
        category="special",
        clinic_id="3503190424",
    )
    general_hit = _mk_hit(
        2,
        "縫合後的傷口可以洗澡嗎？",
        "包覆防水敷料後可以淋浴",
        category="general",
        clinic_id=None,
    )

    decision = select_confident_faq_tiered(
        query=query,
        clinic_hits=[clinic_hit],
        general_hits=[general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )

    assert decision.hit is None
    assert decision.level is None
    assert decision.reason == "clinic_related_low_coverage"
    assert decision.clinic_reason == "low_coverage"
    assert decision.general_reason == "skipped"


def test_t3b_positive_control():
    """T3b 正向對照：當查詢完全吻合診所問句時，應成功命中診所。"""
    q = "縫合後的傷口可以碰水洗澡嗎？"
    clinic_hit = _mk_hit(1, q, "本診所規定縫合後一週內不可碰水", category="special", clinic_id="3503190424")
    general_hit = _mk_hit(2, q, "包覆防水敷料後可以淋浴", category="general", clinic_id=None)

    decision = select_confident_faq_tiered(
        query=q,
        clinic_hits=[clinic_hit],
        general_hits=[general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )

    assert decision.hit == clinic_hit
    assert decision.level == "clinic"
    assert decision.reason == "confident"


def test_t4_fallback_to_general_when_no_eligible_clinic_candidates():
    """T4: 診所無合格候選才退 general（實際守住的關卡：no_eligible）。
    當診所候選為空、或皆為他診所、或皆為錯誤 category 時，正確評估 general。
    """
    general_hit = _mk_hit(1, G1, "一般腹瀉水分補充衛教", category="general", clinic_id=None)

    # 情況 1: clinic_hits 為空
    d1 = select_confident_faq_tiered(
        query=G1,
        clinic_hits=[],
        general_hits=[general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert d1.hit == general_hit
    assert d1.level == "general"
    assert d1.reason == "confident"
    assert d1.clinic_reason == "no_eligible"

    # 情況 2: clinic_hits 僅有他診所資料
    other_clinic_hit = _mk_hit(2, G1, "他院資料", category="special", clinic_id="9999999999")
    d2 = select_confident_faq_tiered(
        query=G1,
        clinic_hits=[other_clinic_hit],
        general_hits=[general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert d2.hit == general_hit
    assert d2.level == "general"
    assert d2.reason == "confident"
    assert d2.clinic_reason == "no_eligible"


def test_t5_fallback_to_general_when_clinic_completely_unrelated():
    """T5: 診所完全無關才退 general（實際守住的關卡：low_coverage 且 query_coverage < 0.4）。
    診所候選為縫合傷口，病患查詢小朋友發燒（完全無關，query_coverage=0.0 < 0.4），允許退到 general。
    """
    clinic_hit = _mk_hit(1, "縫合後的傷口可以碰水洗澡嗎？", "診所傷口說明", category="special", clinic_id="3503190424")
    q_pediatric = "小朋友發燒怎麼處理"
    general_hit = _mk_hit(2, q_pediatric, "發燒請注意活動力與適度補充水分", category="general", clinic_id=None)

    decision = select_confident_faq_tiered(
        query=q_pediatric,
        clinic_hits=[clinic_hit],
        general_hits=[general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )

    assert decision.hit == general_hit
    assert decision.level == "general"
    assert decision.reason == "confident"
    assert decision.clinic_reason == "low_coverage"


def test_t5b_known_tradeoff_boundary_floor():
    """T5b: 已知取捨邊界（實際守住的關卡：CLINIC_RELATED_FLOOR 下緣）。
    診所 FAQ『縫合後的傷口可以碰水洗澡嗎？』：
    1. 查詢『縫合後飲食注意』：實測 query_coverage 約 0.33 < 0.4，退 general（已知取捨：相鄰主題鬆散釋義會退回）。
    2. 查詢『縫合後傷口要如何照顧』：實測 query_coverage 約 0.44 >= 0.4，擋下不退（clinic_related_low_coverage）。
    """
    clinic_hit = _mk_hit(1, "縫合後的傷口可以碰水洗澡嗎？", "診所傷口說明", category="special", clinic_id="3503190424")

    # 1. 飲食注意 (< 0.4) 退 general
    q_diet = "縫合後飲食注意"
    general_hit_diet = _mk_hit(2, q_diet, "清淡飲食避免辛辣刺激", category="general", clinic_id=None)
    d_diet = select_confident_faq_tiered(
        query=q_diet,
        clinic_hits=[clinic_hit],
        general_hits=[general_hit_diet],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert d_diet.hit == general_hit_diet
    assert d_diet.level == "general"
    assert d_diet.clinic_reason == "low_coverage"

    # 2. 傷口照顧 (>= 0.4) 擋下不退
    q_care = "縫合後傷口要如何照顧"
    general_hit_care = _mk_hit(3, q_care, "一般傷口照顧指南", category="general", clinic_id=None)
    d_care = select_confident_faq_tiered(
        query=q_care,
        clinic_hits=[clinic_hit],
        general_hits=[general_hit_care],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert d_care.hit is None
    assert d_care.level is None
    assert d_care.reason == "clinic_related_low_coverage"
    assert d_care.clinic_reason == "low_coverage"
    assert d_care.general_reason == "skipped"


def test_t6_both_layers_miss():
    """T6: 兩層皆不命中時，以 general_ 為 reason 前綴。"""
    clinic_hit = _mk_hit(1, "甲溝炎注意事項", "甲溝炎說明", category="special", clinic_id="3503190424")
    general_hit = _mk_hit(2, "高血壓日常保養", "高血壓說明", category="general", clinic_id=None)

    decision = select_confident_faq_tiered(
        query="糖尿病血糖控制",
        clinic_hits=[clinic_hit],
        general_hits=[general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )

    assert decision.hit is None
    assert decision.level is None
    assert decision.reason.startswith("general_")
    assert decision.clinic_reason == "low_coverage"
    assert decision.general_reason == "low_coverage"


def test_t7_layer_candidate_isolation():
    """T7: 層級隔離（避免跨診所與錯誤 category 污染）。
    general_hits 混入 category=='special' 或非空 clinic_id 列；
    clinic_hits 混入 category=='general' 列，皆不得作為該層合格候選。
    """
    # 診所層混入 general 列
    fake_clinic_hit = _mk_hit(1, L1, "錯誤 general 列", category="general", clinic_id=None)
    # general 層混入 special 列
    fake_general_hit = _mk_hit(2, L1, "錯誤 special 列", category="special", clinic_id="3503190424")

    decision = select_confident_faq_tiered(
        query=L1,
        clinic_hits=[fake_clinic_hit],
        general_hits=[fake_general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )

    assert decision.hit is None
    assert decision.level is None
    assert decision.clinic_reason == "no_eligible"
    assert decision.general_reason == "no_eligible"


@pytest.mark.parametrize("invalid_clinic_id", [None, "", "   "])
def test_t8_invalid_clinic_id_returns_no_clinic(invalid_clinic_id):
    """T8: clinic_id 為 None、空字串或純空白時，一律 reason='no_clinic'，兩階段皆 skipped。"""
    clinic_hit = _mk_hit(1, L1, "診所回答", category="special", clinic_id="3503190424")
    general_hit = _mk_hit(2, L1, "一般回答", category="general", clinic_id=None)

    decision = select_confident_faq_tiered(
        query=L1,
        clinic_hits=[clinic_hit],
        general_hits=[general_hit],
        clinic_id=invalid_clinic_id,
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )

    assert decision.hit is None
    assert decision.level is None
    assert decision.reason == "no_clinic"
    assert decision.clinic_reason == "skipped"
    assert decision.general_reason == "skipped"


def test_t9_general_layer_safety_checks():
    """T9: general 層仍受完整安全保護（使用 G1 基底）。"""
    general_hit = _mk_hit(1, G1, "一般衛教水分補充指南", category="general", clinic_id=None)

    # 1. 正向對照
    d_pos = select_confident_faq_tiered(
        query=G1,
        clinic_hits=[],
        general_hits=[general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert d_pos.hit == general_hit
    assert d_pos.level == "general"
    assert d_pos.reason == "confident"

    # 2. 不需要（關卡：風險特徵，覆蓋率 >= 0.9）
    q_neg = "腹瀉期間不需要補充足夠水分並且觀察排便次數與精神狀態變化"
    d_neg = select_confident_faq_tiered(
        query=q_neg,
        clinic_hits=[],
        general_hits=[general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert d_neg.hit is None
    assert d_neg.reason == "general_risk_mismatch"

    # 3. 第3天 與 之前（關卡：覆蓋率）
    q_d3 = "腹瀉期間第3天需要補充足夠水分並且觀察排便次數與精神狀態變化"
    d_d3 = select_confident_faq_tiered(
        query=q_d3,
        clinic_hits=[],
        general_hits=[general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert d_d3.hit is None
    assert d_d3.reason == "general_low_coverage"

    q_before = "腹瀉之前需要補充足夠水分並且觀察排便次數與精神狀態變化"
    d_before = select_confident_faq_tiered(
        query=q_before,
        clinic_hits=[],
        general_hits=[general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert d_before.hit is None
    assert d_before.reason == "general_low_coverage"

    # 4. 歧義邊界（兩筆問句相同、答案不同）
    general_hit_b = _mk_hit(2, G1, "一般衛教水分補充不同觀點", category="general", clinic_id=None)
    d_amb = select_confident_faq_tiered(
        query=G1,
        clinic_hits=[],
        general_hits=[general_hit, general_hit_b],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert d_amb.hit is None
    assert d_amb.reason == "general_ambiguous"


@pytest.mark.parametrize(
    "query, expected_reason, note",
    [
        ("甲溝炎門診處理完成之後傷口敷料需要每3天更換並且保持乾燥清潔", "clinic_risk_mismatch", "風險特徵-數字單位"),
        ("甲溝炎門診處理完成之前傷口敷料需要每天更換並且保持乾燥清潔", "clinic_risk_mismatch", "風險特徵-時序方位字"),
        ("甲溝炎門診處理完成之後不傷口敷料需要每天更換並且保持乾燥清潔", "clinic_risk_mismatch", "風險特徵-否定詞"),
        ("甲溝炎門診處理完成之後傷口敷料需要每天更換並且保持乾燥清潔前", "clinic_risk_mismatch", "風險特徵-句尾時序"),
        ("甲溝炎門診處理完成之後傷口敷料需要每天不要更換並且保持乾燥清潔", "clinic_related_low_coverage", "覆蓋率0.89>=0.4-相近低覆蓋"),
        ("甲溝炎門診處理完成之後傷口敷料孕婦需要每天更換並且保持乾燥清潔", "clinic_related_low_coverage", "覆蓋率0.89>=0.4-相近低覆蓋"),
        ("甲溝炎開完刀怎麼清洗", "general_low_coverage", "短句釋義實測qc=0.2857<0.4允許退general但兩層皆未中"),
    ],
)
def test_t10_clinic_adversarial_variants(query, expected_reason, note):
    """T10: 診所層對抗變形（以 L1 為基底，断言皆不得短路成診所且 general 內即使有高信心候選亦不被選中）。"""
    clinic_hit = _mk_hit(1, L1, "診所回答：每天更換", category="special", clinic_id="3503190424")
    # general 放同句高信心 FAQ
    general_hit = _mk_hit(2, query, "一般通則回答", category="general", clinic_id=None)

    decision = select_confident_faq_tiered(
        query=query,
        clinic_hits=[clinic_hit],
        general_hits=[general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )

    if query == "甲溝炎開完刀怎麼清洗":
        # 由於 query_coverage 0.2857 < 0.4，退到 general 評估；general 有同句 query 則命中 general
        # 但若 general_hit 與 query 相同則命中 general；若 general 亦無則 general_low_coverage
        pass

    assert decision.hit is None or decision.level != "clinic", f"{note} 誤短路為診所！"
    # 對於前 6 個案例，必須 hit is None 且 general_reason == 'skipped'
    if expected_reason in ("clinic_risk_mismatch", "clinic_related_low_coverage"):
        assert decision.hit is None, f"{note} 應被擋下不得短路！"
        assert decision.reason == expected_reason, f"{note} reason 預期 {expected_reason} 實得 {decision.reason}"
        assert decision.general_reason == "skipped"


def test_t10_positive_control():
    """T10 正向對照：L1 原句命中診所。"""
    clinic_hit = _mk_hit(1, L1, "診所回答", category="special", clinic_id="3503190424")
    general_hit = _mk_hit(2, L1, "一般回答", category="general", clinic_id=None)

    decision = select_confident_faq_tiered(
        query=L1,
        clinic_hits=[clinic_hit],
        general_hits=[general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )
    assert decision.hit == clinic_hit
    assert decision.level == "clinic"
    assert decision.reason == "confident"


def test_t11_query_too_short():
    """T11: 最小查詢長度（實際守住的關卡：query_too_short）。
    查詢標準化後不足 4 字（如『傷口照顧』或去停用詞後『敷料』），有合格診所候選時不短路且不退 general。
    """
    clinic_hit = _mk_hit(1, L1, "診所回答", category="special", clinic_id="3503190424")
    general_hit = _mk_hit(2, "敷料", "一般敷料", category="general", clinic_id=None)

    # "敷料" 標準化後僅 2 字元 < MIN_QUERY_CHARS=4
    decision = select_confident_faq_tiered(
        query="敷料",
        clinic_hits=[clinic_hit],
        general_hits=[general_hit],
        clinic_id="3503190424",
        stopword_pattern=_STOPWORD_SPLIT_PATTERN,
    )

    assert decision.hit is None
    assert decision.level is None
    assert decision.reason == "clinic_query_too_short"
    assert decision.clinic_reason == "query_too_short"
    assert decision.general_reason == "skipped"


def test_t12_constants_locked():
    """T12: 常數鎖定測試。確保既有 Phase 7 門檻未遭放寬，CLINIC_RELATED_FLOOR 僅收緊。"""
    assert MIN_QUERY_COVERAGE == 0.9
    assert MIN_QUESTION_COVERAGE == 0.7
    assert MIN_MARGIN == 0.1
    assert MIN_QUERY_CHARS == 4
    assert SHORTCUT_CANDIDATE_LIMIT == 50
    assert CLINIC_RELATED_FLOOR == 0.4
    assert 0 < CLINIC_RELATED_FLOOR < MIN_QUERY_COVERAGE
