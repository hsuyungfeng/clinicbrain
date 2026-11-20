"""Phase 51 回歸測試：NHI400 衛教圖解解剖器官精準映射與零錯配防線。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.audit_manifest_anatomy import audit_manifest
from src.visual.blueprints import BLUEPRINTS


MANIFEST_PATH = PROJECT_ROOT / "data" / "visual" / "nhi400_manifest.json"
VISUAL_ENGINE_PATH = PROJECT_ROOT / "src" / "web" / "static" / "visual_engine.js"


def test_nhi400_manifest_zero_anatomy_mismatches():
    report = audit_manifest(MANIFEST_PATH)
    assert report["total"] == 200
    assert report["mismatch_count"] == 0, f"發現解剖錯配: {report['findings']}"


def test_d384_d385_and_representative_diseases_aligned():
    items = {it["id"]: it for it in json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))}

    assert items["D384"]["archetype"]["s1_organ"] == "dental_oral"
    assert items["D385"]["archetype"]["s1_organ"] == "dental_oral"
    assert items["D382"]["archetype"]["s1_organ"] == "dental_oral"
    assert items["D383"]["archetype"]["s1_organ"] == "dental_oral"
    assert items["D395"]["archetype"]["s1_organ"] == "dental_oral"

    assert items["W211"]["archetype"]["s1_organ"] in ("vascular_metabolic", "endocrine_receptor")
    assert items["W212"]["archetype"]["s1_organ"] == "endocrine_receptor"
    assert items["W222"]["archetype"]["s1_organ"] == "gi_tract"
    assert items["W228"]["archetype"]["s1_organ"] == "gi_tract"
    assert items["W315"]["archetype"]["s1_organ"] == "endocrine_receptor"


def test_all_manifest_organs_registered_in_blueprints_and_visual_engine():
    items = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    blueprint_organs = set(BLUEPRINTS["pathology_mechanism"]["params"]["organ_system"]["values"])
    js_text = VISUAL_ENGINE_PATH.read_text(encoding="utf-8")
    m = re.search(r"const PATHO_DRAWERS = \{(.*?)\};", js_text, flags=re.DOTALL)
    assert m is not None
    drawer_keys = set(re.findall(r"([a-z0-9_]+)\s*:", m.group(1)))

    for it in items:
        organ = it["archetype"]["s1_organ"]
        assert organ in blueprint_organs, f"{it['id']} 的 {organ} 未註冊於 BLUEPRINTS"
        assert organ in drawer_keys, f"{it['id']} 的 {organ} 未註冊於 visual_engine.js PATHO_DRAWERS"
