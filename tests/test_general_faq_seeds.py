"""
Taiwan Clinic Medical PageIndex RAG System - 一般醫學衛教種子結構與合規驗證測試 (test_general_faq_seeds)
Phase 17 Plan 17-01: 通用醫學疾病種子清單擴充與結構校驗
"""

from pathlib import Path
import re
import pytest

from src.batch.topic_sources import (
    QUESTION_TAGS,
    SLUG_REGEX,
    SeedFileError,
    load_seed_file,
)
from src.ingestion.convert_chinese import to_traditional
from src.ingestion.generate_faq import validate_single_faq

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_FILE_PATH = PROJECT_ROOT / "data" / "batch" / "faq_seeds.json"

NEW_GENERAL_SLUGS = {
    "hypertension-basics",
    "diabetes-type2-care",
    "urticaria-care",
    "asthma-home-care",
    "gerd-management",
    "gout-basics",
    "herpes-zoster-care",
    "migraine-basics",
}


def test_load_seed_file_success():
    """驗證 data/batch/faq_seeds.json 可順利載入且無 SeedFileError。"""
    seed_file = load_seed_file(SEED_FILE_PATH)
    assert seed_file is not None
    # 原有 7 主題 + 新增 8 主題 = 15 主題
    assert len(seed_file.topics) >= 15


def test_new_general_topics_exist_and_conform():
    """驗證新增 8 個 general 主題均存在且規格符合作業規範。"""
    seed_file = load_seed_file(SEED_FILE_PATH)
    topic_map = {t.topic_key: t for t in seed_file.topics}

    for slug in NEW_GENERAL_SLUGS:
        assert slug in topic_map, f"缺少預期之 general 主題 slug: {slug}"
        topic = topic_map[slug]

        # 1. slug 格式檢核
        assert SLUG_REGEX.match(topic.topic_key)

        # 2. category 與 clinic_id 檢核
        assert topic.category == "general"
        assert topic.clinic_id is None
        assert topic.always is True
        assert topic.tree_doc_id is None

        # 3. title 繁體中文檢核
        assert to_traditional(topic.title) == topic.title

        # 4. questions 數量與題籤檢核
        assert len(topic.questions) == 4
        assert len(topic.question_tags) == 4

        for tag in topic.question_tags:
            assert tag in QUESTION_TAGS

        # 5. 問句四層合規性與簡體字檢核
        for q in topic.questions:
            assert to_traditional(q) == q, f"問題包含簡體字: {q}"
            is_valid, reason = validate_single_faq({"question": q, "answer": "請致電診所確認"})
            assert is_valid, f"問題未通過合規性檢查 ({reason}): {q}"
