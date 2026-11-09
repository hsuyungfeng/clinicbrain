"""
Unit tests for NHI 200 catalog, deduplicator, and DeepSeek client with night-time discount guard.
Phase 39 Wave 1 (39-01-PLAN).
"""

import json
from datetime import datetime, timezone
from pathlib import Path
import pytest

from src.visual.nhi_dedup import (
    load_nhi_catalog,
    match_item_against_assets,
    partition_nhi_catalog,
    normalize_term,
)
from src.pageindex.deepseek_client import (
    is_off_peak_hours,
    call_deepseek,
    DeepSeekDaytimeBlockedError,
    DeepSeekAPIError,
)

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "nhi_primary_care_200.json"


def test_nhi_catalog_structure():
    """驗證健保 200 目錄完整度與欄位規範。"""
    catalog = load_nhi_catalog(CATALOG_PATH)
    assert len(catalog) >= 150, "健保核心目錄應涵蓋至少 150 筆常見疾病"

    systems = set()
    for item in catalog:
        assert "id" in item
        assert "system" in item
        assert "name" in item
        assert "category" in item
        assert "icd10" in item
        assert isinstance(item.get("alias", []), list)
        assert isinstance(item.get("keywords", []), list)
        systems.add(item["system"])

    assert {"western", "tcm", "dental"}.issubset(systems), "必須完整涵蓋西醫、中醫、牙醫三大體系"


def test_nhi_deduplicator_matching():
    """驗證去重比對邏輯對既有 88 個主題之精確識別。"""
    mock_assets = [
        {"id": 1, "topic_key": "icd-j069-uri", "title": "感冒（急性上呼吸道感染）"},
        {"id": 2, "topic_key": "icd-e119-diabetes", "title": "第二型糖尿病"},
        {"id": 3, "topic_key": "tree-paronychia-matrixectomy", "title": "甲溝炎嵌甲甲床重整手術原理圖解"},
    ]

    item_cold = {"id": "W001", "name": "急性上呼吸道感染（感冒）", "icd10": "J06.9", "alias": ["感冒"]}
    matched = match_item_against_assets(item_cold, mock_assets)
    assert matched is not None
    assert matched["topic_key"] == "icd-j069-uri"

    item_diabetes = {"id": "W025", "name": "第二型糖尿病", "icd10": "E11.9", "alias": ["第2型糖尿病"]}
    matched_dm = match_item_against_assets(item_diabetes, mock_assets)
    assert matched_dm is not None
    assert matched_dm["topic_key"] == "icd-e119-diabetes"

    # 未包含於資產庫之新項目（牙髓炎）
    item_dental = {"id": "D002", "name": "急性牙髓炎", "icd10": "K04.01", "alias": ["牙神經痛"]}
    matched_new = match_item_against_assets(item_dental, mock_assets)
    assert matched_new is None


def test_nhi_partition_catalog():
    """驗證全量目錄與模擬資產庫之劃分結果。"""
    catalog = load_nhi_catalog(CATALOG_PATH)
    mock_assets = [
        {"id": 1, "topic_key": "icd-j069-uri", "title": "感冒（急性上呼吸道感染）"},
        {"id": 2, "topic_key": "icd-e119-diabetes", "title": "第二型糖尿病"},
    ]
    covered, to_generate = partition_nhi_catalog(catalog, mock_assets)
    assert len(covered) >= 2
    assert len(to_generate) == len(catalog) - len(covered)


def test_deepseek_off_peak_hours_logic():
    """驗證 DeepSeek 夜間半價優惠時段（UTC 16:30 ~ 00:30）判定。"""
    # 台灣時間 01:00 (UTC 17:00) -> 優惠時段
    dt_off_peak = datetime(2026, 11, 6, 17, 0, tzinfo=timezone.utc)
    assert is_off_peak_hours(dt_off_peak) is True

    # 台灣時間 07:00 (UTC 23:00) -> 優惠時段
    dt_early_morning = datetime(2026, 11, 6, 23, 0, tzinfo=timezone.utc)
    assert is_off_peak_hours(dt_early_morning) is True

    # 台灣時間 12:00 (UTC 04:00) -> 非優惠時段
    dt_daytime = datetime(2026, 11, 6, 4, 0, tzinfo=timezone.utc)
    assert is_off_peak_hours(dt_daytime) is False

    # 台灣時間 20:00 (UTC 12:00) -> 非優惠時段
    dt_evening = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
    assert is_off_peak_hours(dt_evening) is False


def test_deepseek_daytime_enforcement(monkeypatch):
    """驗證非夜間優惠時段下，批次生成會被安全阻斷，除非傳入 allow_daytime=True。"""
    # 模擬當前時間為日間（UTC 05:00）
    daytime_dt = datetime(2026, 11, 6, 5, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("src.pageindex.deepseek_client.is_off_peak_hours", lambda dt=None: False)

    # 未放行日間且非測試 -> 拋出 DeepSeekDaytimeBlockedError
    with pytest.raises(DeepSeekDaytimeBlockedError):
        call_deepseek("測試提示詞", allow_daytime=False, is_test=False)


def test_deepseek_fallback_to_local(monkeypatch):
    """驗證 DeepSeek API 異常時，自動平滑降級至本地 llama-server。"""
    monkeypatch.setattr("src.pageindex.deepseek_client.is_off_peak_hours", lambda dt=None: True)

    def mock_bad_urlopen(*args, **kwargs):
        raise OSError("模擬網路斷線")

    monkeypatch.setattr("urllib.request.urlopen", mock_bad_urlopen)

    # 本地降級 mock
    called_local = []
    def mock_local_call(prompt, timeout=60):
        called_local.append(prompt)
        return "本地降級成功回覆"

    monkeypatch.setattr("src.pageindex.deepseek_client.local_llm_call", mock_local_call)

    res = call_deepseek("測試降級", is_test=True, fallback_to_local=True)
    assert res == "本地降級成功回覆"
    assert len(called_local) == 1
