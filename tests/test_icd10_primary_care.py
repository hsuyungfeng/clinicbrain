"""Phase 35：臺灣基層診所 36 項 ICD-10 高頻疾病目錄測試。

守則：
- 寫入測試一律使用 isolated_db_path 隔離複本，絕不觸碰正式 clinic.db。
- CLI 正式庫拒絕測試以 --db 指向正式庫路徑，驗證拒絕發生於任何連線之前（結束碼 2）。
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from src.visual.icd10_catalog import (
    SPECIALTY_TARGETS,
    load_icd10_catalog,
    seed_icd10_catalog,
    validate_catalog_entry,
)
from tests.conftest import apply_visual_migration

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROD_DB_PATH = PROJECT_ROOT / "clinic.db"
CLI = PROJECT_ROOT / "scripts" / "seed_icd10_primary_care.py"
DIGIT_RE = re.compile(r"\d")


@pytest.fixture(scope="module")
def catalog():
    return load_icd10_catalog()


def test_catalog_has_36_entries_with_expected_specialty_distribution(catalog):
    assert len(catalog) == 36
    counts: dict[str, int] = {}
    for entry in catalog:
        counts[entry["specialty"]] = counts.get(entry["specialty"], 0) + 1
    assert counts == SPECIALTY_TARGETS
    assert sorted(SPECIALTY_TARGETS.values()) == [4, 5, 6, 6, 7, 8]


def test_topic_keys_unique_and_well_formed(catalog):
    keys = [e["topic_key"] for e in catalog]
    assert len(set(keys)) == len(keys)
    for key in keys:
        assert re.fullmatch(r"[a-z0-9-]{3,64}", key), key


def test_acute_otitis_media_uses_h6690_and_diabetes_uses_chinese_type_two(catalog):
    otitis = next(e for e in catalog if e["icd10_code"] == "H66.90")
    assert otitis["topic_key"] == "icd-h6690-otitis-media"
    assert otitis["ir"]["title"] == "急性中耳炎"
    dm = next(e for e in catalog if e["icd10_code"] == "E11.9")
    assert "第二型糖尿病" in dm["ir"]["title"]
    assert not DIGIT_RE.search(dm["ir"]["title"])


def test_every_entry_passes_validate_catalog_entry(catalog):
    failures = [(e["topic_key"], validate_catalog_entry(e)[1]) for e in catalog if not validate_catalog_entry(e)[0]]
    assert failures == []


def test_all_ir_pass_validate_ir_and_have_no_arabic_digits(catalog):
    from src.visual.ir import validate_ir

    for entry in catalog:
        ok, code = validate_ir(entry["ir"])
        assert ok, (entry["topic_key"], code)
        for text in _visible_strings(entry["ir"]):
            assert not DIGIT_RE.search(text), (entry["topic_key"], text)


def test_no_entry_uses_surgical_action(catalog):
    for entry in catalog:
        blueprints = [s["blueprint"] for s in entry["ir"]["scenes"]]
        assert "surgical_action" not in blueprints, entry["topic_key"]
        assert blueprints[1] == "contrast", entry["topic_key"]
        assert blueprints[2] == "timeline", entry["topic_key"]
        assert blueprints[0] == "pathology_mechanism", entry["topic_key"]


def test_every_entry_has_two_faqs_passing_validate_single_faq(catalog):
    from src.ingestion.generate_faq import validate_single_faq

    for entry in catalog:
        assert len(entry["faqs"]) == 2, entry["topic_key"]
        for item in entry["faqs"]:
            ok, reason = validate_single_faq(item, check_dosage=True, require_doctor_warning=True)
            assert ok, (entry["topic_key"], reason)


def _clear_icd_faqs_in_copy(db_path):
    """隔離副本可能已含正式庫的 ICD 衛教列；只清除副本內的 icd- 列，確保計數測試獨立於正式庫狀態。"""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DELETE FROM faq_cache WHERE topic_key LIKE 'icd-%'")
        conn.commit()
    finally:
        conn.close()


def test_seed_is_idempotent_and_writes_general_rows(isolated_db_path, catalog):
    apply_visual_migration(isolated_db_path)
    _clear_icd_faqs_in_copy(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        first = seed_icd10_catalog(conn, catalog, approve_visuals=False)
        assert first["visuals"]["inserted"] == 36
        assert first["faqs"][0] == 72

        second = seed_icd10_catalog(conn, catalog, approve_visuals=False)
        assert second["visuals"]["inserted"] == 0
        assert second["visuals"]["unchanged"] == 36
        assert second["faqs"][2] == 72

        rows = conn.execute(
            "SELECT COUNT(*) FROM visual_assets WHERE clinic_id IS NULL AND review_status = 'pending'"
        ).fetchone()[0]
        assert rows >= 36
        faq_general = conn.execute(
            "SELECT COUNT(*) FROM faq_cache WHERE clinic_id IS NULL AND category = 'general' "
            "AND review_status = 'pending' AND source_type = 'llm_generated'"
        ).fetchone()[0]
        assert faq_general >= 72
    finally:
        conn.close()


def test_seed_approve_visuals_sets_approved(isolated_db_path, catalog):
    apply_visual_migration(isolated_db_path)
    _clear_icd_faqs_in_copy(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        result = seed_icd10_catalog(conn, catalog, approve_visuals=True)
        assert result["approved"] == 36
        approved = conn.execute(
            "SELECT COUNT(*) FROM visual_assets WHERE clinic_id IS NULL AND review_status = 'approved' "
            "AND topic_key LIKE 'icd-%'"
        ).fetchone()[0]
        assert approved == 36
    finally:
        conn.close()


def test_seed_rejects_invalid_entry_without_writing(isolated_db_path, catalog):
    apply_visual_migration(isolated_db_path)
    # 故意把標題寫成阿拉伯數字版本（「第2型」），應於寫入前整批拒絕
    bad_entry = {**catalog[0], "ir": {**catalog[0]["ir"], "title": "第2型糖尿病"}}
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        with pytest.raises(ValueError):
            seed_icd10_catalog(conn, [bad_entry, *catalog[1:3]])
        n = conn.execute(
            "SELECT COUNT(*) FROM visual_assets WHERE topic_key IN (?, ?, ?)",
            (catalog[0]["topic_key"], catalog[1]["topic_key"], catalog[2]["topic_key"]),
        ).fetchone()[0]
        assert n == 0  # 驗證在任何寫入之前完成，批次內其他合格條目亦不得寫入
    finally:
        conn.close()


def test_cli_dry_run_is_offline_and_succeeds(tmp_path):
    missing_db = tmp_path / "does_not_exist.db"
    proc = subprocess.run(
        [sys.executable, str(CLI), "--db", str(missing_db), "--dry-run"],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert not missing_db.exists()
    assert "36" in proc.stdout


def test_cli_refuses_prod_db_before_connecting():
    proc = subprocess.run(
        [sys.executable, str(CLI), "--db", str(PROD_DB_PATH)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 2
    assert "操作拒絕" in proc.stderr


def test_cli_writes_isolated_db_idempotently(isolated_db_path):
    apply_visual_migration(isolated_db_path)
    _clear_icd_faqs_in_copy(isolated_db_path)
    args = [sys.executable, str(CLI), "--db", str(isolated_db_path)]
    first = subprocess.run(args, capture_output=True, text=True, timeout=300)
    assert first.returncode == 0, first.stderr
    second = subprocess.run(args, capture_output=True, text=True, timeout=300)
    assert second.returncode == 0, second.stderr
    assert "未變 36" in second.stdout


def _visible_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k != "topic_key":
                yield from _visible_strings(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _visible_strings(item)


# ---------------------------------------------------------------------------
# Phase 35-02：pathology_mechanism 升級、臨床四段式摘要與 LLM 退回機制
# ---------------------------------------------------------------------------

from src.visual.icd10_enrichment import (  # noqa: E402
    OFFLINE_KNOWLEDGE,
    SUMMARY_KEYS,
    SYSTEM_BY_SPECIALTY,
    enrich_entry,
    enrich_with_llm,
    validate_summary,
)


def test_all_scene1_are_pathology_with_matching_organ_system(catalog):
    for entry in catalog:
        scene1 = entry["ir"]["scenes"][0]
        assert scene1["blueprint"] == "pathology_mechanism", entry["topic_key"]
        assert scene1["params"]["organ_system"] == SYSTEM_BY_SPECIALTY[entry["specialty"]], entry["topic_key"]
    organs = {e["ir"]["scenes"][0]["params"]["organ_system"] for e in catalog}
    assert organs == set(SYSTEM_BY_SPECIALTY.values())


def test_every_entry_has_four_part_clinical_summary(catalog):
    for entry in catalog:
        summary = entry["clinical_summary"]
        assert set(summary.keys()) == set(SUMMARY_KEYS), entry["topic_key"]
        ok, code = validate_summary(summary)
        assert ok, (entry["topic_key"], code)


def test_organ_labels_are_within_limits_and_digit_free(catalog):
    for entry in catalog:
        params = entry["ir"]["scenes"][0]["params"]
        for key in ("organ_label", "lesion_label", "trigger_label", "defense_label"):
            assert 1 <= len(params[key]) <= 8, (entry["topic_key"], key)
            assert not DIGIT_RE.search(params[key]), (entry["topic_key"], key)


def test_enrich_entry_is_pure_and_idempotent(catalog):
    import copy

    original = copy.deepcopy(catalog[0])
    once = enrich_entry(catalog[0])
    assert catalog[0] == original  # 不改動輸入
    twice = enrich_entry(once)
    assert twice == once


def test_validate_summary_rejects_digits_dosage_and_schema():
    base = dict(zip(SUMMARY_KEYS, OFFLINE_KNOWLEDGE["icd-j069-uri"][6]))
    assert validate_summary(base)[0] is True
    assert validate_summary({**base, "management_care": "充分休息並補充水分，每日服用 2 次，持續觀察症狀變化與精神狀況。"})[1] == "arabic_digit"
    assert validate_summary({**base, "red_flags_prevention": "症狀未改善時可每次吃兩顆，每日三次即可，並持續觀察身體反應與精神狀況。"})[1] == "dosage_or_price"
    assert validate_summary({**base, "pathophysiology": "本療程保證治癒各類病況，並可使症狀完全消失，無需再行追蹤評估。"})[1] == "forbidden_phrase"
    assert validate_summary({k: v for k, v in base.items() if k != "management_care"})[1] == "summary_schema"


def test_llm_success_path_uses_validated_llm_summary(catalog):
    import json

    entry = catalog[0]
    fake = {
        "pathophysiology": "病毒附著於鼻咽黏膜，引起局部發炎與黏膜水腫與纖毛功能下降。",
        "clinical_presentation": "常見鼻塞、流鼻水與喉嚨不適，多數在數日內逐漸減輕。",
        "management_care": "充分休息、補充水分並保持室內濕潤，依醫囑觀察症狀變化。",
        "red_flags_prevention": "若出現持續高燒不退或呼吸困難，請立即就醫評估。",
    }
    out, origin = enrich_with_llm(entry, lambda prompt: "前言\n" + json.dumps(fake, ensure_ascii=False))
    assert origin == "llm"
    assert out["clinical_summary"] == fake
    assert out["ir"]["scenes"][0]["blueprint"] == "pathology_mechanism"


def test_llm_failures_fall_back_to_offline_source(catalog):
    entry = catalog[0]

    def boom(prompt):
        raise RuntimeError("離線")

    _, origin = enrich_with_llm(entry, boom)
    assert origin == "offline_fallback"

    _, origin = enrich_with_llm(entry, lambda p: "不是 JSON")
    assert origin == "offline_fallback"

    bad = '{"pathophysiology": "每日服用 3 次，每次 2 顆", "clinical_presentation": "x", "management_care": "y", "red_flags_prevention": "z"}'
    _, origin = enrich_with_llm(entry, lambda p: bad)
    assert origin == "offline_fallback"


def test_enrichment_cli_check_mode_is_offline_and_passes():
    script = PROJECT_ROOT / "scripts" / "enrich_icd10_primary_care.py"
    proc = subprocess.run([sys.executable, str(script), "--check"], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert "36" in proc.stdout


def test_enrichment_cli_writes_only_to_given_out_path(tmp_path):
    script = PROJECT_ROOT / "scripts" / "enrich_icd10_primary_care.py"
    out = tmp_path / "catalog_out.json"
    proc = subprocess.run(
        [sys.executable, str(script), "--out", str(out)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) == 36
    assert all(validate_catalog_entry(e)[0] for e in data)


# ---------------------------------------------------------------------------
# Phase 35-03：場景 2／3 個別化語意與基層模式契約
# ---------------------------------------------------------------------------

from src.visual.icd10_enrichment import CONNECTORS_BASE, LEFT_MODES_BASE, RIGHT_MODES_BASE  # noqa: E402

# 脂肪肝的「脂肪」為正當醫學用語，禁用詞僅限醫美脂肪移植與外科隱痕敘述
FORBIDDEN_CONTRAST_TIMELINE_TEXT = ("穩定隱痕", "移植物", "脂肪移植", "自體脂肪", "術後", "注射", "套管", "抽脂", "隱痕")


def test_scene2_and_scene3_use_base_modes_with_expected_distribution(catalog):
    connectors = {}
    for entry in catalog:
        s2 = entry["ir"]["scenes"][1]
        s3 = entry["ir"]["scenes"][2]
        assert s2["params"]["left"]["mode"] in LEFT_MODES_BASE, entry["topic_key"]
        assert s2["params"]["right"]["mode"] in RIGHT_MODES_BASE, entry["topic_key"]
        assert s3["params"]["connectors"] in CONNECTORS_BASE, entry["topic_key"]
        connectors[s3["params"]["connectors"]] = connectors.get(s3["params"]["connectors"], 0) + 1
    assert connectors == {"mucosal_clearance": 12, "homeostasis_control": 19, "structural_rehab": 5}


def test_scene2_and_scene3_content_is_individualized(catalog):
    s2_captions = {e["ir"]["scenes"][1]["caption"] for e in catalog}
    s3_captions = {e["ir"]["scenes"][2]["caption"] for e in catalog}
    s2_titles = {(e["ir"]["scenes"][1]["params"]["left"]["title"], e["ir"]["scenes"][1]["params"]["right"]["title"]) for e in catalog}
    assert len(s2_captions) == 36
    assert len(s3_captions) == 36
    assert len(s2_titles) >= 30
    for entry in catalog:
        left = entry["ir"]["scenes"][1]["params"]["left"]
        right = entry["ir"]["scenes"][1]["params"]["right"]
        assert left["title"] != "延誤處理", entry["topic_key"]
        assert right["title"] != "及時處理", entry["topic_key"]
        milestones = entry["ir"]["scenes"][2]["params"]["milestones"]
        assert "初期不適" not in milestones, entry["topic_key"]
        caption3 = entry["ir"]["scenes"][2]["caption"]
        assert ("因人而異" in caption3) or ("醫師評估" in caption3), entry["topic_key"]


def test_no_surgical_or_fat_graft_wording_in_scene2_or_scene3(catalog):
    for entry in catalog:
        for idx in (1, 2):
            scene = entry["ir"]["scenes"][idx]
            for text in _visible_strings(scene):
                for word in FORBIDDEN_CONTRAST_TIMELINE_TEXT:
                    assert word not in text, (entry["topic_key"], idx, word)


def test_validate_catalog_entry_rejects_wrong_base_mode(catalog):
    import copy

    bad = copy.deepcopy(catalog[0])
    bad["ir"]["scenes"][1]["params"]["left"]["mode"] = "tissue_trauma_torn_vessel"
    ok, code = validate_catalog_entry(bad)
    assert not ok
    assert code == "scene2_left_mode"

    bad3 = copy.deepcopy(catalog[0])
    bad3["ir"]["scenes"][2]["params"]["connectors"] = "skin_retraction"
    ok3, code3 = validate_catalog_entry(bad3)
    assert not ok3
    assert code3 == "scene3_connectors"
