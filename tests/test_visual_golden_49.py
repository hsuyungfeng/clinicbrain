"""Phase 34 Plan 01：49 筆推理樹 Scene 1 模板黃金測試。

黃金檔由 scripts/export_golden_tree_blueprints.py 以唯讀方式產生。
本測試只讀黃金檔與推理樹的識別欄位，不連線資料庫。
任何推斷規則改動若改變某筆模板，測試會失敗並指出 doc_id。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.visual.autodraft import infer_scene1_blueprint
from src.visual.blueprints import BLUEPRINTS

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "data" / "visual" / "golden" / "tree_blueprints_49.json"


@pytest.fixture(scope="module")
def golden() -> list[dict]:
    assert GOLDEN_PATH.exists(), f"缺少黃金檔：{GOLDEN_PATH}"
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_golden_has_49_unique_entries(golden):
    assert len(golden) == 49
    doc_ids = [e["doc_id"] for e in golden]
    assert len(set(doc_ids)) == 49


def test_golden_blueprints_are_registered(golden):
    for e in golden:
        assert e["blueprint"] in BLUEPRINTS, (e["doc_id"], e["blueprint"])


def test_scene1_blueprints_match_golden_for_all_49(golden):
    mismatches = []
    for e in golden:
        tree = {"doc_id": e["doc_id"], "title": e["title"], "summary_text": "", "procedure": ""}
        got, _reason = infer_scene1_blueprint(tree)
        if got != e["blueprint"]:
            mismatches.append((e["doc_id"], e["blueprint"], got))
    assert mismatches == [], f"模板與黃金值不符（doc_id, 黃金, 目前）：{mismatches}"


@pytest.mark.parametrize(
    "title",
    [
        "Ultherapy 美國音波深層極線音波拉提療程",
        "Ultraformer MPT 媚必提微脈衝音波拉提療程",
        "Thermage FLX 鳳凰電波單極緊膚療程",
        "HIFU 高強度聚焦超音波拉提",
    ],
)
def test_energy_devices_never_classified_as_surgical(title):
    """音波與電波儀器內文常含「下顎線」等部位詞，不得誤判為外科骨骼處置。"""
    tree = {"doc_id": "synthetic-energy", "title": title, "summary_text": "提拉下顎線輪廓", "procedure": ""}
    got, _ = infer_scene1_blueprint(tree)
    assert got != "surgical_action", title
