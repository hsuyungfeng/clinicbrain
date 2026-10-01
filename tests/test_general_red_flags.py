"""測試 src/general/red_flags.py 紅旗偵測器。"""

from dataclasses import fields, is_dataclass
import logging
import re
import sqlite3
import pytest

from src.general.red_flags import (
    RedFlagMatch,
    RedFlagRule,
    RED_FLAG_RULES,
    detect_red_flag,
    light_normalize,
    normalize_for_match,
)


POSITIVE_CASES: list[tuple[str, str, str]] = [
    # E01
    ("我胸口好痛", "emergency", "E01"),
    ("胸口悶悶的", "emergency", "E01"),
    ("心臟痛", "emergency", "E01"),
    ("心臟好痛", "emergency", "E01"),
    ("心悸", "emergency", "E01"),
    ("胸口像被壓住", "emergency", "E01"),
    ("隆乳後胸口好痛", "emergency", "E01"),
    ("chest pain", "emergency", "E01"),
    ("heart attack", "emergency", "E01"),
    ("胸,痛", "emergency", "E01"),
    ("胸　痛", "emergency", "E01"),
    ("沒有胸痛但還是想問", "emergency", "E01"),
    # E02
    ("最近常常喘不過氣", "emergency", "E02"),
    ("喘不過來", "emergency", "E02"),
    ("我喘不过来", "emergency", "E02"),
    ("最近常常喘不過來", "emergency", "E02"),
    ("呼吸有點困难", "emergency", "E02"),
    ("吸不到氣", "emergency", "E02"),
    ("透不過氣", "emergency", "E02"),
    ("喘不氣", "emergency", "E02"),
    ("上不了氣", "emergency", "E02"),
    ("呼吸不到空氣", "emergency", "E02"),
    ("被噎到", "emergency", "E02"),
    ("嗆到", "emergency", "E02"),
    ("喉嚨卡住", "emergency", "E02"),
    ("喉嚨腫而且呼吸困難", "emergency", "E02"),
    ("I can't breathe", "emergency", "E02"),
    ("發燒不退而且喘不過氣", "emergency", "E02"),
    # E03
    ("我爸昏倒了", "emergency", "E03"),
    ("他意識不清", "emergency", "E03"),
    ("暈過去", "emergency", "E03"),
    ("昏厥", "emergency", "E03"),
    ("叫不起來", "emergency", "E03"),
    ("昏睡", "emergency", "E03"),
    ("小孩發燒抽筋", "emergency", "E03"),
    # E04
    ("咳出大量血", "emergency", "E04"),
    ("咳大量血", "emergency", "E04"),
    ("咳出血絲", "emergency", "E04"),
    ("咳了很多血", "emergency", "E04"),
    ("傷口一直流血止不住", "emergency", "E04"),
    ("血一直流", "emergency", "E04"),
    ("流很多血", "emergency", "E04"),
    ("血流不停", "emergency", "E04"),
    ("出血不停", "emergency", "E04"),
    ("傷口一直流血", "emergency", "E04"),
    ("血流不止怎麼辦", "emergency", "E04"),
    ("吐血了", "emergency", "E04"),
    # E05
    ("喉頭水腫", "emergency", "E05"),
    ("打完針喉嚨腫起來", "emergency", "E05"),
    ("过敏性休克", "emergency", "E05"),
    ("全身起紅疹還有點喘", "emergency", "E05"),
    # E06
    ("突然嘴歪", "emergency", "E06"),
    ("嘴歪而且說話不清", "emergency", "E06"),
    ("半身不遂", "emergency", "E06"),
    ("手腳麻痺無力", "emergency", "E06"),
    ("一邊手沒力", "emergency", "E06"),
    ("口齒不清", "emergency", "E06"),
    ("stroke", "emergency", "E06"),
    # E07
    ("吞了整瓶藥", "emergency", "E07"),
    ("吞下電池", "emergency", "E07"),
    ("吞了異物", "emergency", "E07"),
    ("喝了農藥", "emergency", "E07"),
    ("食物中毒", "emergency", "E07"),
    ("overdose", "emergency", "E07"),
    # E08
    ("打完玻尿酸眼睛看不見", "emergency", "E08"),
    ("注射後視力突然模糊", "emergency", "E08"),
    ("打了水光後眼睛變黑", "emergency", "E08"),
    ("填充後右眼看不清", "emergency", "E08"),
    ("打完針後視力模糊", "emergency", "E08"),
    ("打完玻尿酸鼻頭發黑", "emergency", "E08"),
    ("打了水光後嘴唇發紫", "emergency", "E08"),
    ("注射後皮膚變得蒼白", "emergency", "E08"),
    ("填充後鼻翼突然變白", "emergency", "E08"),
    # U01
    ("痛到受不了", "urgent", "U01"),
    ("劇烈疼痛", "urgent", "U01"),
    # U02
    ("嬰兒發燒", "urgent", "U02"),
    ("小孩發燒", "urgent", "U02"),
    ("39.5度", "urgent", "U02"),
    ("體溫39.5", "urgent", "U02"),
    ("體溫量到40度", "urgent", "U02"),
    ("燒了三天", "urgent", "U02"),
    ("發燒一週", "urgent", "U02"),
    ("發燒不退", "urgent", "U02"),
    ("高燒", "urgent", "U02"),
    # U03
    ("傷口紅腫熱痛還化膿", "urgent", "U03"),
    ("傷口流膿", "urgent", "U03"),
    ("術後發燒", "urgent", "U03"),
    # U04
    ("嘴唇腫", "urgent", "U04"),
    ("臉腫起來", "urgent", "U04"),
    ("视力模糊", "urgent", "U04"),
    # U05
    ("肚子好痛", "urgent", "U05"),
    ("右下腹痛", "urgent", "U05"),
    ("腹痛如絞", "urgent", "U05"),
]

NEGATIVE_CASES: list[str] = [
    "玻尿酸要打幾次",
    "痛風可以喝酒嗎",
    "肉毒桿菌多久見效",
    "發燒的原因有哪些",
    "如何預防感冒",
    "胸腔外科在哪",
    "40度的熱水可以洗臉嗎",
    "雷射後要防曬嗎",
    "保濕怎麼做",
    "音波拉提會痛嗎",
    "疼痛指數是什麼",
    "過敏原檢測是什麼",
    "高血壓飲食",
    "肉毒桿菌會中毒嗎",
    "肉毒中毒的風險",
    "喉嚨腫痛怎麼辦",
    "扁桃腺發炎喉嚨腫",
    "怎麼讓臉變白",
    "皮膚變白的方法",
    "鼻頭發黑是粉刺嗎",
    "血壓量到140",
    "血糖量到140",
    "體重量到40公斤",
    "洗臉水溫度40度",
    "電波拉提溫度40度",
    "痘痘有膿包",
    "青春痘有膿怎麼處理",
    "臉歪了怎麼矯正",
    "口罩歪掉",
    "隆胸後會痛嗎",
    "孩子一直吐奶",
    "水光針可以讓臉變白嗎",
    "水光針會讓皮膚變白嗎",
    "打玻尿酸鼻頭會變黑嗎",
    "小腿抽筋怎麼辦",
    "請問可以過來看診嗎",
    "眼睛看不清楚是近視嗎",
    "眼睛周圍打玻尿酸會變黑嗎",
    "玻尿酸可以填眼袋嗎",
    "眼睛模糊怎麼辦",
    "咳出痰有黃色怎麼辦",
    "高血壓患者咳嗽可以吃藥嗎",
    "咳嗽有痰怎麼辦",
]

KNOWN_ACCEPTED_OVERTRIGGERS: list[tuple[str, str, str]] = [
    ("胸。痛風", "emergency", "E01"),
    ("運動後心跳很快", "emergency", "E01"),
    ("忙到喘不過來", "emergency", "E02"),
    ("打完針淤青發紫", "emergency", "E08"),
    ("鼻子填充後變蒼白", "emergency", "E08"),
    ("咳出血絲", "emergency", "E04"),
]


@pytest.mark.parametrize("query, expected_level, expected_rule_id", POSITIVE_CASES)
def test_positive_cases_hit_expected_rule(query: str, expected_level: str, expected_rule_id: str):
    """漏報導向正例測試：每一句都必須命中預期的等級與規則。"""
    match = detect_red_flag(query)
    assert match is not None, f"正例未能命中紅旗: '{query}'"
    assert match.level == expected_level, f"等級不符: {match.level} != {expected_level} for '{query}'"
    assert match.rule_id == expected_rule_id, f"規則不符: {match.rule_id} != {expected_rule_id} for '{query}'"


def test_all_13_rules_covered_in_positive_cases():
    """確保 13 個 rule_id 至少在正例測試中各出現一次。"""
    covered_rules = {expected_rule_id for _, _, expected_rule_id in POSITIVE_CASES}
    all_rules = {r.rule_id for r in RED_FLAG_RULES}
    assert covered_rules == all_rules


def test_negation_context_still_triggers():
    """測試否定語境（沒有胸痛）仍保守觸發。"""
    match1 = detect_red_flag("沒有胸痛但還是想問")
    assert match1 is not None and match1.rule_id == "E01"

    match2 = detect_red_flag("没有胸痛但是还是想問")
    assert match2 is not None and match2.rule_id == "E01"


def test_formatting_and_variant_robustness():
    """測試格式變體：全形、大小寫、標點插入等皆能命中。"""
    # 大小寫與撇號
    assert detect_red_flag("Chest Pain") is not None
    assert detect_red_flag("CAN'T BREATHE") is not None
    assert detect_red_flag("can’t breathe") is not None  # 弧形撇號

    # 標點插入與空白
    assert detect_red_flag("胸,痛") is not None
    assert detect_red_flag("胸 痛") is not None
    assert detect_red_flag("胸　痛") is not None  # 全形空白


def test_emergency_priority_over_urgent():
    """測試優先序：同時含發燒（urgent）與呼吸困難（emergency）時回傳 emergency。"""
    match = detect_red_flag("發燒不退而且喘不過氣")
    assert match is not None
    assert match.level == "emergency"
    assert match.rule_id == "E02"


@pytest.mark.parametrize("query", NEGATIVE_CASES)
def test_negative_cases_return_none(query: str):
    """誤觸發控制：負例清單每一句都必須回傳 None。"""
    match = detect_red_flag(query)
    assert match is None, f"負例不應命中紅旗卻命中了: '{query}' -> {match}"


@pytest.mark.parametrize("query, expected_level, expected_rule_id", KNOWN_ACCEPTED_OVERTRIGGERS)
def test_known_accepted_overtrigger(query: str, expected_level: str, expected_rule_id: str):
    """測試已知並接受的過度觸發案例，證明符合保守安全預期。"""
    match = detect_red_flag(query)
    assert match is not None, f"已知過度觸發未命中: '{query}'"
    assert match.level == expected_level
    assert match.rule_id == expected_rule_id


def test_red_flag_rules_structure():
    """測試規則結構完整性。"""
    assert len(RED_FLAG_RULES) == 13
    expected_ids = [
        "E01", "E02", "E03", "E04", "E05", "E06", "E07", "E08",
        "U01", "U02", "U03", "U04", "U05",
    ]
    actual_ids = [r.rule_id for r in RED_FLAG_RULES]
    assert actual_ids == expected_ids

    # rule_id 唯一性
    assert len(set(actual_ids)) == 13

    # level 只能是 emergency 或 urgent
    for r in RED_FLAG_RULES:
        assert r.level in ("emergency", "urgent")
        for p in r.patterns:
            re.compile(p)
        for rp in r.raw_patterns:
            re.compile(rp)


def test_red_flag_match_dataclass_fields():
    """測試 RedFlagMatch 為 frozen dataclass 且欄位恰為 {level, rule_id, label}。"""
    assert is_dataclass(RedFlagMatch)
    field_names = {f.name for f in fields(RedFlagMatch)}
    assert field_names == {"level", "rule_id", "label"}

    match = RedFlagMatch(level="emergency", rule_id="E01", label="測試")
    with pytest.raises(Exception):
        match.level = "urgent"  # frozen


def test_empty_input_returns_none():
    """空字串與純空白應回傳 None。"""
    assert detect_red_flag("") is None
    assert detect_red_flag("   ") is None
    assert detect_red_flag("\n\t") is None
    assert detect_red_flag("!@#$%^&*()") is None


def test_detect_red_flag_purity(monkeypatch):
    """測試純函式性：不得呼叫 sqlite3 或 logging。"""
    def fail_sqlite(*args, **kwargs):
        raise AssertionError("不得呼叫 sqlite3")

    def fail_log(*args, **kwargs):
        raise AssertionError("不得呼叫 logging")

    monkeypatch.setattr(sqlite3, "connect", fail_sqlite)
    monkeypatch.setattr(logging.Logger, "_log", fail_log)

    # 執行偵測，確認不拋出 AssertionError
    detect_red_flag("胸痛")
    detect_red_flag("玻尿酸幾次")
