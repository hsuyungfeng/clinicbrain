"""
tests/test_disease_seeds.py - 疾病種子與題型標籤測試 (Phase 12 GC-01)
驗證 question_tags 欄位支援、資料校驗與批次不讀取 proposed 檔之硬閘門。
"""

import json
from pathlib import Path
import pytest

from src.batch.topic_sources import (
    SeedTopic,
    load_seed_file,
    validate_seed_data,
)


def _make_valid_seed_data() -> dict:
    return {
        "schema_version": 1,
        "tree_procedure_names": {
            "hifu-lifting": "海芙音波拉提",
        },
        "topics": [
            {
                "topic_key": "test-topic",
                "title": "測試主題",
                "category": "general",
                "clinic_id": None,
                "keywords": [],
                "always": True,
                "tree_doc_id": None,
                "questions": [
                    "什麼是測試主題？",
                    "測試主題常見症狀有哪些？",
                ],
                "question_tags": ["what", "symptoms"],
            }
        ],
    }


def test_question_tags_constant():
    """QUESTION_TAGS 必須包含且僅包含 4 種合法題型。"""
    from src.batch.topic_sources import QUESTION_TAGS
    assert QUESTION_TAGS == frozenset({"what", "symptoms", "when_to_see_doctor", "home_care"})


def test_validate_seed_data_question_tags_valid():
    """合法的 question_tags 通過驗證。"""
    data = _make_valid_seed_data()
    errors = validate_seed_data(data)
    assert errors == []


def test_validate_seed_data_question_tags_omitted():
    """缺省 question_tags 不報錯。"""
    data = _make_valid_seed_data()
    del data["topics"][0]["question_tags"]
    errors = validate_seed_data(data)
    assert errors == []


def test_validate_seed_data_question_tags_length_mismatch():
    """question_tags 長度與 questions 不同時回傳錯誤訊息。"""
    data = _make_valid_seed_data()
    data["topics"][0]["question_tags"] = ["what"]  # 1 tag vs 2 questions
    errors = validate_seed_data(data)
    assert len(errors) == 1
    assert "question_tags" in errors[0]
    assert "test-topic" in errors[0]


def test_validate_seed_data_question_tags_invalid_value():
    """question_tags 包含非法題型時回傳錯誤訊息。"""
    data = _make_valid_seed_data()
    data["topics"][0]["question_tags"] = ["what", "invalid_tag"]
    errors = validate_seed_data(data)
    assert len(errors) == 1
    assert "question_tags" in errors[0]
    assert "invalid_tag" in errors[0]


def test_validate_seed_data_question_tags_not_list():
    """question_tags 不是 list 時回傳錯誤訊息。"""
    data = _make_valid_seed_data()
    data["topics"][0]["question_tags"] = "what,symptoms"
    errors = validate_seed_data(data)
    assert len(errors) == 1
    assert "question_tags" in errors[0]


def test_load_seed_file_with_question_tags(tmp_path: Path):
    """load_seed_file 能正確將 question_tags 轉為 tuple 存入 SeedTopic。"""
    data = _make_valid_seed_data()
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    loaded = load_seed_file(seed_file)
    assert len(loaded.topics) == 1
    assert loaded.topics[0].question_tags == ("what", "symptoms")


def test_load_seed_file_without_question_tags(tmp_path: Path):
    """缺省 question_tags 時 SeedTopic.question_tags 預設為空 tuple ()。"""
    data = _make_valid_seed_data()
    del data["topics"][0]["question_tags"]
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    loaded = load_seed_file(seed_file)
    assert len(loaded.topics) == 1
    assert loaded.topics[0].question_tags == ()


def test_hard_gate_no_code_references_proposed():
    """
    硬閘門防禦：
    掃描 src/ 與 scripts/ 下所有 .py 檔案，不得有任何檔案引用 'faq_seeds.proposed'。
    """
    base_dir = Path(__file__).resolve().parent.parent
    py_files = list((base_dir / "src").rglob("*.py")) + list((base_dir / "scripts").rglob("*.py"))

    violations = []
    for f in py_files:
        content = f.read_text(encoding="utf-8")
        if "faq_seeds.proposed" in content:
            violations.append(str(f.relative_to(base_dir)))

    assert violations == [], f"發現未經簽核即引用 faq_seeds.proposed 的程式碼檔案: {violations}"


def test_nightly_batch_default_seed_path():
    """scripts/run_nightly_batch.py 的 DEFAULT_SEED_PATH 檔名必須為 faq_seeds.json。"""
    from scripts.run_nightly_batch import DEFAULT_SEED_PATH

    assert Path(DEFAULT_SEED_PATH).name == "faq_seeds.json"


def _get_target_seed_file() -> Path:
    base_dir = Path(__file__).resolve().parent.parent
    proposed = base_dir / "data" / "batch" / "faq_seeds.proposed.json"
    if proposed.exists():
        return proposed
    return base_dir / "data" / "batch" / "faq_seeds.json"


def test_seed_file_structure_and_disease_coverage():
    """
    種子結構與疾病涵蓋測試 (W7, GC-01):
    1. 載入 proposed 檔（或改名後的 faq_seeds.json）
    2. general 主題恰含 4 種疾病: common-cold-home-care, influenza-basics, acute-gastroenteritis, allergic-rhinitis
    3. 每個 general 主題涵蓋 what, symptoms, when_to_see_doctor, home_care 四類 question_tags
    4. 感冒主題保留既有兩題原文
    5. 所有題目不含「藥」「抗生素」「吃什麼」
    6. category/clinic_id/always/tree_doc_id 正確
    7. 3 個 special 主題與 6 個 tree_procedure_names 仍在
    8. 每題通過四層檢查
    9. 總共恰好 17 題 general 問題
    """
    from src.ingestion.generate_faq import validate_single_faq

    seed_path = _get_target_seed_file()
    assert seed_path.exists(), f"種子檔案不存在: {seed_path}"

    loaded = load_seed_file(seed_path)

    # 檢查 6 個 tree_procedure_names 仍在
    expected_tree_names = {
        "laser-skin-resurfacing",
        "botox-injection",
        "electrowave-facelift",
        "hyaluronic-acid-filler",
        "fractional-laser",
        "hifu-lifting",
    }
    assert set(loaded.tree_procedure_names.keys()) == expected_tree_names

    # 檢查 3 個 special 主題仍在
    special_topics = [t for t in loaded.topics if t.category == "special"]
    assert {t.topic_key for t in special_topics} == {
        "ingrown-nail-care",
        "hifu-lifting-faq",
        "hyaluronic-acid-filler-faq",
    }

    # 檢查 4 個 general 主題
    general_topics = [t for t in loaded.topics if t.category == "general"]
    expected_general_keys = {
        "common-cold-home-care",
        "influenza-basics",
        "acute-gastroenteritis",
        "allergic-rhinitis",
    }
    assert {t.topic_key for t in general_topics} == expected_general_keys

    required_tags = {"what", "symptoms", "when_to_see_doctor", "home_care"}
    forbidden_terms = ["藥", "抗生素", "吃什麼"]

    total_general_questions = 0
    for topic in general_topics:
        assert topic.clinic_id is None
        assert topic.always is True
        assert topic.tree_doc_id is None
        assert set(topic.question_tags) >= required_tags
        assert len(topic.question_tags) == len(topic.questions)
        total_general_questions += len(topic.questions)

        for q in topic.questions:
            # 藥物/飲食處方邊界檢查
            for forbidden in forbidden_terms:
                assert forbidden not in q, f"問題 '{q}' 包含禁止詞彙 '{forbidden}'"

            # 四層合規檢核
            valid, reason = validate_single_faq({"question": q, "answer": "請致電診所確認"})
            assert valid, f"問題 '{q}' 未通過合規檢查: {reason}"

    # 驗證總共有 17 題 general 問題
    assert total_general_questions == 17

    # 感冒主題保留既有兩題原文
    cold_topic = next(t for t in general_topics if t.topic_key == "common-cold-home-care")
    assert "感冒時在家要如何照護與休息？" in cold_topic.questions
    assert "感冒時需要多喝水嗎？" in cold_topic.questions
    assert len(cold_topic.questions) == 5
