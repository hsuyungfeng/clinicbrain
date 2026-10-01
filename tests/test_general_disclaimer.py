"""測試 src/general/disclaimer.py 固定文字與提示函式。"""

import re
import pytest

from src.general.disclaimer import (
    DISCLAIMER_TEXT,
    RED_FLAG_DISCLAIMER_TEXT,
    EMERGENCY_MESSAGE,
    URGENT_MESSAGE,
    FILLER_OCCLUSION_ADDENDUM,
    ANSWERED_MESSAGE,
    NO_MATCH_MESSAGE,
    message_for_red_flag,
)
from src.ingestion.convert_chinese import to_traditional
from src.query.router import mask_prices


ALL_CONSTANTS = [
    DISCLAIMER_TEXT,
    RED_FLAG_DISCLAIMER_TEXT,
    EMERGENCY_MESSAGE,
    URGENT_MESSAGE,
    FILLER_OCCLUSION_ADDENDUM,
    ANSWERED_MESSAGE,
    NO_MATCH_MESSAGE,
]

PROHIBITED_WORDS = ["保證", "百分之百", "根治", "一定會好"]


def test_constants_are_non_empty_strings():
    """斷言七個常數皆為非空字串。"""
    assert len(ALL_CONSTANTS) == 7
    for item in ALL_CONSTANTS:
        assert isinstance(item, str)
        assert len(item.strip()) > 0


def test_constants_are_pure_traditional_chinese():
    """斷言每個常數皆為繁體中文（to_traditional 轉換後無變化）。"""
    for item in ALL_CONSTANTS:
        assert to_traditional(item) == item


def test_constants_contain_no_price_patterns():
    """斷言每個常數不含價格模式（mask_prices 轉換後無變化）。"""
    for item in ALL_CONSTANTS:
        assert mask_prices(item) == item


def test_constants_contain_no_guarantee_words():
    """斷言每個常數不含保證療效用語。"""
    for item in ALL_CONSTANTS:
        for word in PROHIBITED_WORDS:
            assert word not in item, f"常數中包含禁用字詞 {word}: {item}"


def test_disclaimer_text_contains_key_medical_terms():
    """斷言 DISCLAIMER_TEXT 同時包含『醫囑』與『就醫』。"""
    assert "醫囑" in DISCLAIMER_TEXT
    assert "就醫" in DISCLAIMER_TEXT
    assert "面對面" in DISCLAIMER_TEXT


def test_emergency_message_contains_119_and_er():
    """斷言 EMERGENCY_MESSAGE 含『119』與『急診』。"""
    assert "119" in EMERGENCY_MESSAGE
    assert "急診" in EMERGENCY_MESSAGE


def test_urgent_message_contains_119():
    """斷言 URGENT_MESSAGE 含『119』。"""
    assert "119" in URGENT_MESSAGE


def test_no_match_message_contains_honest_guidance():
    """斷言 NO_MATCH_MESSAGE 含『沒有』與『就醫』或『醫師』。"""
    assert "沒有" in NO_MATCH_MESSAGE
    assert "就醫" in NO_MATCH_MESSAGE or "醫師" in NO_MATCH_MESSAGE


def test_filler_occlusion_addendum_contains_clinic():
    """斷言 FILLER_OCCLUSION_ADDENDUM 含『診所』。"""
    assert "診所" in FILLER_OCCLUSION_ADDENDUM
    assert "注射" in FILLER_OCCLUSION_ADDENDUM


def test_message_for_red_flag_routing():
    """斷言 message_for_red_flag 各種分支表現正確。"""
    # Emergency E01 -> EMERGENCY_MESSAGE
    assert message_for_red_flag("emergency", "E01") == EMERGENCY_MESSAGE

    # Emergency E08 -> EMERGENCY_MESSAGE + "\n" + FILLER_OCCLUSION_ADDENDUM
    e08_msg = message_for_red_flag("emergency", "E08")
    assert e08_msg.startswith(EMERGENCY_MESSAGE)
    assert FILLER_OCCLUSION_ADDENDUM in e08_msg

    # Urgent U02 -> URGENT_MESSAGE
    assert message_for_red_flag("urgent", "U02") == URGENT_MESSAGE

    # Invalid level -> ValueError
    with pytest.raises(ValueError, match="不支援的紅旗等級"):
        message_for_red_flag("bogus", "E01")


def test_constants_only_contain_allowed_numbers():
    """斷言全部常數中的數字序列只有『119』（不含其他電話或專線）。"""
    for item in ALL_CONSTANTS:
        numbers = re.findall(r"\d+", item)
        for num in numbers:
            assert num == "119", f"常數中包含非 119 數字: {num} in {item}"
