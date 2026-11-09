"""Phase 40 Wave 1: 健保 201-400 權威種子目錄完整性與隔離防禦測試。"""

import json
import sqlite3
from pathlib import Path
import pytest

from src.visual.nhi_dedup import verify_seed_separation, DEFAULT_CATALOG_400_PATH, DEFAULT_INDEX_400_PATH

VALID_BLUEPRINTS = {
    "surgical_action",
    "deep_plane_facelift",
    "corset_platysmaplasty",
    "cyst_excision",
    "nail_matrix",
    "subdermal_curettage",
    "process_diagram",
    "skin_energy",
    "laser_action",
    "neuromuscular",
    "dermal_support",
    "contrast",
    "timeline",
    "dental_oral",
    "tcm_meridian",
}


def test_seed_400_count_and_fields():
    """驗證 201-400 種子資料共 200 筆，且欄位完整無缺失。"""
    assert DEFAULT_CATALOG_400_PATH.exists()
    with open(DEFAULT_CATALOG_400_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) == 200
    w_count = sum(1 for x in data if x.get("system") == "western")
    c_count = sum(1 for x in data if x.get("system") == "tcm")
    d_count = sum(1 for x in data if x.get("system") == "dental")

    assert w_count == 120
    assert c_count == 50
    assert d_count == 30

    required_keys = {"id", "system", "category", "name", "icd10", "alias", "keywords", "clinical_feature", "recommended_blueprint"}
    for item in data:
        assert required_keys.issubset(set(item.keys()))
        assert item["recommended_blueprint"] in VALID_BLUEPRINTS
        assert isinstance(item["alias"], list)
        assert isinstance(item["keywords"], list)
        assert len(item["keywords"]) >= 2


def test_seed_separation_from_200_and_db():
    """驗證 201-400 與前 200 筆及資料庫已核准資產無衝突。"""
    conn = sqlite3.connect("clinic.db")
    try:
        report = verify_seed_separation(db_conn=conn)
        assert report["seed_conflicts"] == []
        assert report["db_conflicts"] == []
        assert report["is_clean"] is True
    finally:
        conn.close()


def test_unified_1_400_index_file():
    """驗證 1-400 全景索引檔案為 400 筆，且編號連續。"""
    assert DEFAULT_INDEX_400_PATH.exists()
    with open(DEFAULT_INDEX_400_PATH, "r", encoding="utf-8") as f:
        idx_data = json.load(f)

    assert len(idx_data) == 400
    for idx, row in enumerate(idx_data, start=1):
        assert row["index_no"] == idx
        assert "name" in row
        assert "topic_key" in row
