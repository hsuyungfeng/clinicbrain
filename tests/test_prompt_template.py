"""
Taiwan Clinic Medical PageIndex RAG System - LLM 推理樹生成與驗證器測試
涵蓋 TASK-008 選擇性項目（TASK-004 驗證器 7 種核心情境正式化）：
- 情境 1：合法繁體中文 JSON 正確解析為 GeneratedTree
- 情境 2：價格洩漏拒絕（1500元 / NT$500 等）
- 情境 3：簡體字拒絕（違反繁體中文專用 CONSTRAINT）
- 情境 4：缺少必要欄位拒絕
- 情境 5：禁用詞彙與保證療效用語拒絕（保證有效 / 一定能消除 / physician_notes）
- 情境 6：Markdown code fence 格式容錯
- 情境 7：非法 JSON 語法拒絕
- 額外：build_prompt() 組裝驗證與欄位長度過短警告機制
"""

import json
import pytest
from src.pageindex.prompt_template import (
    parse_and_validate,
    build_prompt,
    GeneratedTree,
    TreeValidationError,
)

VALID_TREE_DATA = {
    "pre_op": "術前一週請停用阿斯匹靈及抗凝血藥物，避免劇烈日曬與酸類換膚，施作當日請著寬鬆衣物。",
    "procedure": "清潔臉部後塗抹外用麻膏30分鐘，醫師使用聚焦超音波探頭分層施打，過程中可能有微熱酸麻感。",
    "post_op_short": "術後肌膚可能輕微發紅水腫，屬正常反應通常於數小時至兩天內消退，加強保濕與物理性防曬。",
    "maintenance": "效果於施作後1至3個月隨膠原蛋白新生逐步顯現，建議每12至18個月由醫師評估回診施作以維持輪廓。",
    "summary_text": "音波拉提透過聚焦超音波刺激肌膚深層筋膜層緊實，術前停用酸類，術後加強保濕防曬，效果約可維持一年以上。",
}


def test_validator_scenario_1_valid_json():
    """情境 1：合法繁體中文 JSON 正確解析為 GeneratedTree 物件。"""
    raw = json.dumps(VALID_TREE_DATA, ensure_ascii=False)
    tree = parse_and_validate(raw)
    assert isinstance(tree, GeneratedTree)
    assert tree.pre_op == VALID_TREE_DATA["pre_op"]
    assert tree.procedure == VALID_TREE_DATA["procedure"]
    assert tree.post_op_short == VALID_TREE_DATA["post_op_short"]
    assert tree.maintenance == VALID_TREE_DATA["maintenance"]
    assert tree.summary_text == VALID_TREE_DATA["summary_text"]
    assert tree.warnings == []


@pytest.mark.parametrize("price_phrase", ["1500元", "NT$500", "費用NT$ 800", "$3000", "200塊"])
def test_validator_scenario_2_price_leakage_rejected(price_phrase: str):
    """情境 2：價格洩漏拒絕，任何具體金額均引發 TreeValidationError。"""
    data = dict(VALID_TREE_DATA)
    data["pre_op"] = f"本療程需預收訂金{price_phrase}。"
    raw = json.dumps(data, ensure_ascii=False)
    with pytest.raises(TreeValidationError, match="價格資訊洩漏"):
        parse_and_validate(raw)


@pytest.mark.parametrize("simplified_word", ["这个问题", "实现理想", "我们的服务", "这个療程"])
def test_validator_scenario_3_simplified_chinese_rejected(simplified_word: str):
    """情境 3：簡體字拒絕，違反繁體中文專用 CONSTRAINT。"""
    data = dict(VALID_TREE_DATA)
    data["post_op_short"] = f"術後請注意，{simplified_word}需要密切追蹤。"
    raw = json.dumps(data, ensure_ascii=False)
    with pytest.raises(TreeValidationError, match="疑似簡體字"):
        parse_and_validate(raw)


@pytest.mark.parametrize("missing_field", ["pre_op", "procedure", "post_op_short", "maintenance", "summary_text"])
def test_validator_scenario_4_missing_required_field_rejected(missing_field: str):
    """情境 4：缺少任一必要欄位或欄位為空時拋出 TreeValidationError。"""
    data = dict(VALID_TREE_DATA)
    del data[missing_field]
    raw = json.dumps(data, ensure_ascii=False)
    with pytest.raises(TreeValidationError, match="缺少必要欄位"):
        parse_and_validate(raw)

    # 空字串亦視為缺少
    data_empty = dict(VALID_TREE_DATA)
    data_empty[missing_field] = "   "
    raw_empty = json.dumps(data_empty, ensure_ascii=False)
    with pytest.raises(TreeValidationError, match="缺少必要欄位"):
        parse_and_validate(raw_empty)


@pytest.mark.parametrize("forbidden", ["保證有效", "一定能消除", "保證消除", "physician_notes"])
def test_validator_scenario_5_forbidden_phrases_rejected(forbidden: str):
    """情境 5：保證療效違規用語或誤填醫師備註欄位名時拒絕。"""
    data = dict(VALID_TREE_DATA)
    data["procedure"] = f"本技術{forbidden}，讓肌膚煥然一新。"
    raw = json.dumps(data, ensure_ascii=False)
    with pytest.raises(TreeValidationError, match="禁用詞彙"):
        parse_and_validate(raw)


def test_validator_scenario_6_code_fence_tolerance():
    """情境 6：容錯處理 LLM 偶爾使用 markdown ```json ... ``` code fence 包裹的情況。"""
    raw_json = json.dumps(VALID_TREE_DATA, ensure_ascii=False)
    fenced_1 = f"```json\n{raw_json}\n```"
    tree1 = parse_and_validate(fenced_1)
    assert tree1.summary_text == VALID_TREE_DATA["summary_text"]

    fenced_2 = f"```\n{raw_json}\n```"
    tree2 = parse_and_validate(fenced_2)
    assert tree2.summary_text == VALID_TREE_DATA["summary_text"]


def test_validator_scenario_7_invalid_json_rejected():
    """情境 7：非法 JSON 語法拋出 TreeValidationError。"""
    invalid_raw = "{'pre_op': '不是合法的 json string...'"
    with pytest.raises(TreeValidationError, match="不是合法 JSON"):
        parse_and_validate(invalid_raw)


def test_validator_short_field_warning():
    """驗證欄位長度過短（<10字）時會產生警告但不拋出錯誤。"""
    data = dict(VALID_TREE_DATA)
    data["pre_op"] = "請注意空腹"  # 5字
    raw = json.dumps(data, ensure_ascii=False)
    tree = parse_and_validate(raw)
    assert len(tree.warnings) == 1
    assert "pre_op 內容過短" in tree.warnings[0]


def test_build_prompt_structure():
    """驗證 build_prompt 包含必要的療程名稱、規則（含立場中立）與繁體中文指示。"""
    prompt = build_prompt("自體脂肪補臉", reference_context="健保不給付，純自費醫美項目")
    assert "自體脂肪補臉" in prompt
    assert "健保不給付" in prompt
    assert "繁體中文" in prompt
    assert "絕對禁止出現任何具體價格" in prompt
    assert "不要生成 physician_notes" in prompt
    assert "立場中立" in prompt


@pytest.mark.parametrize(
    "political_phrase",
    [
        "台灣是中國不可分割的一部分",
        "堅持一個中國原則",
        "中國台灣地區的美容醫學標準",
        "本療程適用於台灣地區患者",
    ],
)
def test_validator_political_stance_rejected(political_phrase: str):
    """驗證輸出含有政治立場相關表述時，parse_and_validate 拋出 TreeValidationError。"""
    data = dict(VALID_TREE_DATA)
    data["pre_op"] = f"術前衛教須知：{political_phrase}，需配合相關規定。"
    raw = json.dumps(data, ensure_ascii=False)
    with pytest.raises(TreeValidationError, match="政治立場"):
        parse_and_validate(raw)

