"""Phase 36：ClinicBrain Native Harness² 雙層遞迴馬具測試。

隔離原則：
- 所有寫檔（harness_lessons.json）皆導向 tmp_path（autouse fixture 以 monkeypatch 覆寫預設路徑）。
- 資料庫測試一律使用 isolated_db_path 複本；不呼叫真實 LLM（以 mock 注入）。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.visual import harness_optimizer as ho
from src.visual.autodraft import (
    autodraft_from_tree,
    build_tree_visual_prompt,
    parse_and_build_tree_ir,
)
from src.visual.harness_optimizer import (
    build_alignment_critique_prompt,
    format_lessons_for_prompt,
    load_harness_lessons,
    record_review_lesson,
    score_visual_ir_alignment,
    select_lessons_for_tree,
)
from src.visual.ir import validate_ir
from src.visual.review import adopt_v2_candidate, set_review_status
from tests.conftest import apply_visual_migration
from tests.test_visual_autodraft import TREE_APPROVED, VALID_MODEL_JSON, _seed_tree


@pytest.fixture(autouse=True)
def _isolate_lessons(tmp_path, monkeypatch):
    """所有測試預設使用 tmp_path 內的教訓檔，避免污染正式 data/visual/harness_lessons.json。"""
    target = tmp_path / "harness_lessons.json"
    target.write_text(
        (ho.DEFAULT_LESSONS_PATH).read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setattr(ho, "DEFAULT_LESSONS_PATH", target)
    return target


# ---------------------------------------------------------------------------
# 測試用推理樹與 IR 建構器
# ---------------------------------------------------------------------------

MOMMY_TREE = {
    "id": 9001,
    "doc_id": "mommy-abdominoplasty",
    "clinic_id": "3503190424",
    "title": "產後媽咪腹部改造",
    "summary_text": "產後腹部輪廓與腹直肌分離的修復",
    "pre_op": "評估腹直肌分離程度與腹壁鬆弛範圍",
    "procedure": "縫合分離的腹直肌並收緊腹壁筋膜，重塑肚臍位置",
    "post_op_short": "術後加壓束腹並進行腰腹核心訓練",
    "maintenance": "定期追蹤腹壁狀態與妊娠紋改善情形",
    "pre_op_physician_notes": "腹直肌分離寬度需以超音波評估",
    "procedure_physician_notes": "",
    "post_op_short_physician_notes": "",
    "maintenance_physician_notes": "",
}

FUE_TREE = {
    "id": 9002,
    "doc_id": "fue-hair-transplant",
    "title": "FUE 植髮毛囊移植",
    "summary_text": "毛囊單位逐一鑽取並於受植區開槽種植",
    "pre_op": "評估髮際線與供應區毛囊密度",
    "procedure": "以毛囊鑽取器逐一取出毛囊單位，於受植區開槽種植",
    "post_op_short": "術後避免日曬與劇烈運動",
    "maintenance": "定期追蹤新生毛髮生長狀況",
}

RESP_TREE = {
    "id": 9003,
    "doc_id": "pc-common-cold",
    "title": "感冒上呼吸道感染",
    "summary_text": "病毒附著鼻咽黏膜引起充血與纖毛功能下降",
    "pre_op": "評估鼻塞流涕與咽喉不適程度",
    "procedure": "以休息與補充水分支持黏膜修復",
    "post_op_short": "保暖並避免過勞熬夜",
    "maintenance": "症狀持續未改善時回診評估",
}

HYPERTENSION_TREE = {
    "id": 9004,
    "doc_id": "pc-hypertension",
    "title": "高血壓血管壁負荷",
    "summary_text": "血壓長期偏高使動脈管壁承受壓力",
    "pre_op": "量測血壓並評估心血管風險",
    "procedure": "減少鹽分攝取並規律運動調控血壓",
    "post_op_short": "維持作息與定期監測",
    "maintenance": "長期追蹤血壓變化與器官負擔",
}


def _scene(bp, title, caption, labels, params=None):
    sc = {"blueprint": bp, "title": title, "caption": caption, "labels": labels}
    if params is not None:
        sc["params"] = params
    return sc


def _ir(title, keywords, s1, s2, s3):
    return {"topic_key": "tree-test-topic", "title": title, "keywords": keywords, "scenes": [s1, s2, s3]}


def _good_mommy_ir():
    return _ir(
        "產後腹直肌修復原理",
        ["產後媽咪", "腹直肌分離", "腹壁筋膜"],
        _scene("surgical_action", "腹直肌縫合",
               "縫合分離的腹直肌並收緊腹壁筋膜，重塑肚臍位置，讓腹部輪廓回復平整。",
               [{"text": "腹直肌", "tone": "neutral"}, {"text": "腹壁筋膜", "tone": "optimal"}]),
        _scene("contrast", "分離前後對照",
               "分離未修復的腹壁鬆弛與縫合後的核心支撐，兩者在腰腹穩定度與妊娠紋表現上差異明顯。",
               [{"text": "分離鬆弛", "tone": "warning"}, {"text": "核心支撐", "tone": "optimal"}]),
        _scene("timeline", "核心恢復進程",
               "術後腹壁逐步癒合，腰腹核心力量恢復，超音波追蹤肚臍與腹直肌分離寬度的改善，實際恢復程度因人而異，需由醫師評估。",
               [{"text": "腹壁癒合", "tone": "neutral"}, {"text": "核心恢復", "tone": "optimal"}]),
    )


def _generic_ir():
    """罐頭模板 IR：合法但無臨床專一性，且誤觸闊頸肌與罐頭標籤。"""
    return _ir(
        "重要標籤一",
        ["重要標籤", "步驟一"],
        _scene("corset_platysmaplasty", "第一階段",
               "步驟一與第一階段的重要標籤內容，建議方案如下，闊頸肌與下臉說明在此。",
               [{"text": "重要標籤一", "tone": "neutral"}]),
        _scene("contrast", "第一階段",
               "步驟一與第一階段的重要標籤內容，建議方案如下，闊頸肌與下臉說明在此。",
               [{"text": "問題狀態", "tone": "warning"}]),
        _scene("timeline", "第一階段",
               "步驟一與第一階段的重要標籤內容，建議方案如下，闊頸肌與下臉說明在此，因人而異。",
               [{"text": "建議方案", "tone": "neutral"}]),
    )


# ---------------------------------------------------------------------------
# 1. 教訓載入與匹配
# ---------------------------------------------------------------------------

def test_load_harness_lessons_reads_twelve_seed_lessons():
    lessons = load_harness_lessons()
    assert len(lessons) == 12
    ids = {l["lesson_id"] for l in lessons}
    assert {
        "lesson-body-abdominoplasty", "lesson-hair-fue-transplant", "lesson-eye-blepharoplasty",
        "lesson-rhinoplasty-cartilage", "lesson-jaw-orthognathic", "lesson-scar-subcision",
        "lesson-pc-respiratory", "lesson-pc-vascular-metabolic", "lesson-pc-gi-tract",
        "lesson-pc-skin-barrier", "lesson-pc-joint-spine", "lesson-pc-uro-pelvic",
    } <= ids


def test_lesson_fields_are_traditional_chinese_without_digits():
    import re

    for lesson in load_harness_lessons():
        for key in ("match_terms", "negative_terms", "positive_terms"):
            for term in lesson[key]:
                assert not re.search(r"\d", term), (lesson["lesson_id"], term)
                assert re.search(r"[一-鿿]", term), (lesson["lesson_id"], term)
        assert not re.search(r"\d", lesson["rule"]), lesson["lesson_id"]


def test_load_harness_lessons_is_safe_on_missing_or_corrupt(tmp_path):
    assert load_harness_lessons(tmp_path / "nope.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text("{不是 json", encoding="utf-8")
    assert load_harness_lessons(bad) == []
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"lessons": "x"}), encoding="utf-8")
    assert load_harness_lessons(wrong) == []


def test_select_lessons_matches_mommy_fue_respiratory_and_hypertension():
    assert select_lessons_for_tree(MOMMY_TREE)[0]["lesson_id"] == "lesson-body-abdominoplasty"
    assert select_lessons_for_tree(FUE_TREE)[0]["lesson_id"] == "lesson-hair-fue-transplant"
    assert select_lessons_for_tree(RESP_TREE)[0]["lesson_id"] == "lesson-pc-respiratory"
    assert select_lessons_for_tree(HYPERTENSION_TREE)[0]["lesson_id"] == "lesson-pc-vascular-metabolic"


def test_select_lessons_respects_max_and_skips_unrelated():
    unrelated = {"title": "海芙音波拉提", "doc_id": "hifu", "summary_text": "聚焦超音波緊緻", "pre_op": "", "procedure": "", "post_op_short": "", "maintenance": ""}
    assert select_lessons_for_tree(unrelated) == []
    assert len(select_lessons_for_tree(MOMMY_TREE, max_lessons=1)) == 1


def test_format_lessons_for_prompt_contains_rules_and_forbidden_terms():
    block = format_lessons_for_prompt(select_lessons_for_tree(MOMMY_TREE))
    assert "Harness² 跨任務治理經驗防護欄" in block
    assert "腹直肌" in block
    assert "闊頸肌" in block  # 禁用詞須被明列
    assert format_lessons_for_prompt([]) == ""


def test_build_tree_visual_prompt_injects_matched_lessons():
    prompt = build_tree_visual_prompt(MOMMY_TREE)
    assert "Harness² 跨任務治理經驗防護欄" in prompt
    unrelated = dict(MOMMY_TREE, title="海芙音波拉提", doc_id="hifu-x", pre_op="", procedure="", post_op_short="", maintenance="", summary_text="", pre_op_physician_notes="", procedure_physician_notes="")
    assert "Harness² 跨任務治理經驗防護欄" not in build_tree_visual_prompt(unrelated)


# ---------------------------------------------------------------------------
# 2. 臨床對齊評分器
# ---------------------------------------------------------------------------

def test_high_specificity_ir_scores_high_and_passes():
    report = score_visual_ir_alignment(MOMMY_TREE, _good_mommy_ir())
    assert report["passed_threshold"] is True, report
    assert report["score"] >= 0.85, report
    assert set(report["breakdown"]) == {"lesson_compliance", "lexical_specificity", "scene_diversity", "physician_note_alignment"}


def test_wrong_lexicon_and_generic_labels_score_low_with_specific_feedback():
    report = score_visual_ir_alignment(MOMMY_TREE, _generic_ir())
    assert report["score"] < 0.6, report
    assert report["passed_threshold"] is False
    assert any("闊頸肌" in p for p in report["penalties"]), report["penalties"]
    assert any("重要標籤" in p or "步驟一" in p for p in report["penalties"]), report["penalties"]
    assert report["suggestions"], report


def test_invalid_ir_is_rejected_with_zero_score():
    bad = dict(_good_mommy_ir(), title="")
    report = score_visual_ir_alignment(MOMMY_TREE, bad)
    assert report["score"] == 0.0
    assert report["passed_threshold"] is False


def test_repetitive_scene_captions_are_penalized():
    ir = _good_mommy_ir()
    same = ir["scenes"][0]["caption"]
    ir["scenes"][1]["caption"] = same
    ir["scenes"][2]["caption"] = same
    report = score_visual_ir_alignment(MOMMY_TREE, ir)
    assert any("高度重複" in p for p in report["penalties"]), report["penalties"]


# ---------------------------------------------------------------------------
# 3. 任務級精煉提示詞
# ---------------------------------------------------------------------------

def test_build_alignment_critique_prompt_carries_penalties_and_suggestions():
    report = score_visual_ir_alignment(MOMMY_TREE, _generic_ir())
    prompt = build_alignment_critique_prompt("BASE PROMPT", _generic_ir(), report)
    assert prompt.startswith("BASE PROMPT")
    assert "任務級遞迴精煉" in prompt
    assert "具體扣分原因" in prompt
    assert "改進建議" in prompt
    assert "闊頸肌" in prompt


# ---------------------------------------------------------------------------
# 4. autodraft：pathology_mechanism 解析與 --k 遞迴選優
# ---------------------------------------------------------------------------

def _pathology_raw_json():
    return json.dumps({
        "title": "胃食道逆流機轉",
        "keywords": ["胃食道逆流", "胃酸逆流"],
        "scenes": [
            {
                "blueprint": "pathology_mechanism",
                "title": "胃酸逆流刺激",
                "caption": "胃酸逆流至食道下段，刺激黏膜引起灼熱感，調整生活習慣有助於改善，實際反應因人而異。",
                "labels": [{"text": "胃酸逆流", "tone": "warning"}],
                "params": {
                    "organ_system": "gi_tract",
                    "lesion_label": "食道黏膜發炎區域超過八字",
                    "trigger_label": "宵夜飽食",
                    "defense_label": "保護膜修復",
                    "severity_level": 3,
                    "highlight_fill": "accent",
                    "mechanism_label": "不應保留",
                    "layer_labels": ["不應", "保留", "欄位"],
                    "step_labels": ["胃酸逆流至食道", "黏膜受刺激", "少量多餐修復"],
                },
            },
            {
                "blueprint": "contrast",
                "title": "飽食平躺對照",
                "caption": "宵夜飽食並飯後平躺會使胃酸逆流，少量多餐並抬高床頭則有助於減少逆流，實際變化因人而異。",
                "labels": [{"text": "飽食平躺", "tone": "warning"}, {"text": "少量墊高", "tone": "optimal"}],
                "params": {
                    "left": {"title": "飽食平躺", "note": "胃酸易逆流", "mode": "metabolic_mechanical_overload", "core_effect": "none", "core_label": "逆流加重", "footnote": "飯後平躺加重逆流", "unit_fill": "warn"},
                    "right": {"title": "少量墊高", "note": "減少逆流", "mode": "lifestyle_homeostasis_load", "rows": 3, "per_row": 5, "footnote": "少量多餐並墊高床頭", "unit_fill": "ok"},
                },
            },
            {
                "blueprint": "timeline",
                "title": "逆流長期調控",
                "caption": "胃食道逆流的症狀起伏與生活習慣密切相關，改善速度因人而異，請依醫師評估調整照護方式。",
                "labels": [{"text": "波動收斂", "tone": "optimal"}],
                "params": {"milestones": ["燒心反酸", "生活調整", "症狀平穩"], "unit_effect": "steady", "connectors": "homeostasis_control", "units": 3, "unit_fill": "ok"},
            },
        ],
    }, ensure_ascii=False)


def test_parse_pathology_mechanism_shapes_to_registered_spec():
    ir, code = parse_and_build_tree_ir(_pathology_raw_json(), topic_key="tree-gerd", fallback_title="胃食道逆流機轉")
    assert code == "ok", code
    assert validate_ir(ir) == (True, "ok")
    p = ir["scenes"][0]["params"]
    assert p["organ_system"] == "gi_tract"
    assert len(p["lesion_label"]) <= 8
    assert p["accent_fill"] == "accent"  # highlight_fill 對應規格之 accent_fill
    assert p["severity_level"] == 3
    assert p["step_labels"] == ["胃酸逆流至食道", "黏膜受刺激", "少量多餐修復"]
    assert set(p) == {"organ_system", "organ_label", "lesion_label", "trigger_label", "defense_label", "severity_level", "accent_fill", "step_labels"}


def test_parse_pathology_mechanism_falls_back_on_bad_organ():
    raw = json.loads(_pathology_raw_json())
    raw["scenes"][0]["params"]["organ_system"] = "not_an_organ"
    ir, code = parse_and_build_tree_ir(json.dumps(raw, ensure_ascii=False), topic_key="tree-gerd", fallback_title="x")
    assert code == "ok"
    assert ir["scenes"][0]["params"]["organ_system"] == "respiratory_mucosa"


def test_unknown_blueprint_message_lists_pathology():
    from src.visual.autodraft import build_self_healing_feedback

    assert "pathology_mechanism" in build_self_healing_feedback("unknown_blueprint")


def _seed_hifu(conn):
    return _seed_tree(conn, doc_id="test-hifu-lifting", clinic_id="3503190424", review_status=TREE_APPROVED)


def _low_hifu_json():
    raw = json.loads(VALID_MODEL_JSON)
    raw["title"] = "重要標籤一"
    raw["keywords"] = ["重要標籤", "步驟一"]
    for sc in raw["scenes"]:
        sc["caption"] = sc["caption"][:0] + "步驟一與第一階段的重要標籤內容，建議方案如下，因人而異需由醫師評估說明在此。"
        sc["title"] = "第一階段"
    raw["scenes"][0]["labels"] = [{"text": "重要標籤一", "tone": "neutral"}]
    return json.dumps(raw, ensure_ascii=False)


def _capture_calls(sequence):
    calls: list[str] = []
    seq = list(sequence)

    def fake(prompt):
        calls.append(prompt)
        return seq.pop(0) if seq else seq_last[0]

    seq_last = [sequence[-1]]
    return fake, calls


def test_autodraft_k1_keeps_legacy_behaviour_and_records_harness_metadata(isolated_db_path: Path):
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        tid = _seed_hifu(conn)
        res = autodraft_from_tree(conn, tid, llm_call=lambda p: VALID_MODEL_JSON, db_path=isolated_db_path)
        assert res["status"] == "ok"
        assert res["harness_k"] == 1 and res["harness_mode"] == "sequential"
        meta = json.loads(conn.execute("SELECT metadata FROM visual_assets WHERE topic_key = 'tree-test-hifu-lifting'").fetchone()[0])
        assert meta["harness_k"] == 1
        assert isinstance(meta["harness_score"], float)
        assert isinstance(meta["harness_penalties"], list)
    finally:
        conn.close()


def test_autodraft_sequential_k3_critiques_then_selects_best(isolated_db_path: Path):
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        tid = _seed_hifu(conn)
        fake, calls = _capture_calls([_low_hifu_json(), VALID_MODEL_JSON, VALID_MODEL_JSON])
        res = autodraft_from_tree(conn, tid, llm_call=fake, db_path=isolated_db_path, k_candidates=3, recursion_mode="sequential")
        assert res["status"] == "ok", res
        assert len(calls) >= 2
        assert "任務級遞迴精煉" in calls[1], "sequential 第二輪應使用批評提示詞"
        assert "任務級遞迴精煉" not in calls[0]
        tree = _seed_tree_dict(conn, tid)
        high_ir = parse_and_build_tree_ir(VALID_MODEL_JSON, "tree-test-hifu-lifting", "x")[0]
        low_ir = parse_and_build_tree_ir(_low_hifu_json(), "tree-test-hifu-lifting", "x")[0]
        high = score_visual_ir_alignment(tree, high_ir)["score"]
        low = score_visual_ir_alignment(tree, low_ir)["score"]
        assert low < high, (low, high)
        assert res["harness_score"] == high, "應選中最高分候選"
        meta = json.loads(conn.execute("SELECT metadata FROM visual_assets WHERE topic_key = 'tree-test-hifu-lifting'").fetchone()[0])
        assert meta["harness_k"] == 3
        assert meta["harness_mode"] == "sequential"
        assert meta["harness_score"] == res["harness_score"]
    finally:
        conn.close()


def test_autodraft_parallel_k3_generates_independently_and_selects_best(isolated_db_path: Path):
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        tid = _seed_hifu(conn)
        fake, calls = _capture_calls([_low_hifu_json(), VALID_MODEL_JSON, _low_hifu_json()])
        res = autodraft_from_tree(conn, tid, llm_call=fake, db_path=isolated_db_path, k_candidates=3, recursion_mode="parallel")
        assert res["status"] == "ok", res
        assert res["harness_mode"] == "parallel"
        assert all("任務級遞迴精煉" not in c for c in calls), "parallel 每輪皆應由原始提示詞獨立生成"
        meta = json.loads(conn.execute("SELECT metadata FROM visual_assets WHERE topic_key = 'tree-test-hifu-lifting'").fetchone()[0])
        assert meta["harness_mode"] == "parallel" and meta["harness_k"] == 3
        assert meta["harness_candidates_explored"] == 3
    finally:
        conn.close()


def test_autodraft_rejects_invalid_recursion_arguments(isolated_db_path: Path):
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        tid = _seed_hifu(conn)
        bad_mode = autodraft_from_tree(conn, tid, llm_call=lambda p: VALID_MODEL_JSON, db_path=isolated_db_path, recursion_mode="chaos")
        assert bad_mode == {"status": "error", "code": "invalid_argument"}
        bad_k = autodraft_from_tree(conn, tid, llm_call=lambda p: VALID_MODEL_JSON, db_path=isolated_db_path, k_candidates=0)
        assert bad_k == {"status": "error", "code": "invalid_argument"}
    finally:
        conn.close()


def _seed_tree_dict(conn, tree_id):
    row = conn.execute("SELECT * FROM page_index_trees WHERE id = ?", (tree_id,)).fetchone()
    cols = [d[0] for d in conn.execute("SELECT * FROM page_index_trees LIMIT 0").description]
    return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# 5. 治理級經驗沉澱
# ---------------------------------------------------------------------------

def test_record_review_lesson_writes_isolated_and_is_idempotent(tmp_path):
    target = tmp_path / "lessons_out.json"
    v1 = _good_mommy_ir()
    v2 = json.loads(json.dumps(v1))
    v2["keywords"] = ["產後媽咪", "腹直肌修復", "核心肌群"]
    v2["scenes"][0]["params"] = {"step_labels": ["腹直肌分離評估", "縫合收緊腹壁", "核心訓練恢復"]}
    lesson = record_review_lesson(v1, v2, topic_key="tree-mommy", title="產後媽咪腹部改造", path=target)
    assert lesson is not None
    assert lesson["lesson_id"].startswith("lesson-review-")
    assert "核心肌群" in lesson["positive_terms"] or "腹直肌分離評估" in lesson["positive_terms"]
    assert "腹直肌分離" in lesson["negative_terms"] or "腹壁筋膜" in lesson["negative_terms"]
    assert not any(ch.isdigit() for ch in lesson["rule"])

    again = record_review_lesson(v1, v2, topic_key="tree-mommy", title="產後媽咪腹部改造", path=target)
    assert again["lesson_id"] == lesson["lesson_id"]
    stored = json.loads(target.read_text(encoding="utf-8"))["lessons"]
    assert len([x for x in stored if x["lesson_id"] == lesson["lesson_id"]]) == 1
    # 寫入的是隔離檔，預設正式檔不受影響
    assert all(x["lesson_id"] != lesson["lesson_id"] for x in load_harness_lessons())


def test_record_review_lesson_skips_when_no_substantive_difference(tmp_path):
    target = tmp_path / "lessons_none.json"
    v1 = _good_mommy_ir()
    v2 = json.loads(json.dumps(v1))
    v2["scenes"][0]["caption"] = "第二代文案只改變說明，關鍵詞與步驟用語完全相同，藍圖也不變，實際結果因人而異。"
    assert record_review_lesson(v1, v2, topic_key="tree-mommy", path=target) is None
    assert not target.exists()


def test_adopt_v2_candidate_promotes_and_distills_lesson(isolated_db_path: Path, tmp_path):
    apply_visual_migration(isolated_db_path)
    lessons_out = tmp_path / "adopt_lessons.json"
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        tid = _seed_hifu(conn)
        res_v1 = autodraft_from_tree(conn, tid, llm_call=lambda p: VALID_MODEL_JSON, db_path=isolated_db_path)
        assert res_v1["status"] == "ok"
        set_review_status(conn, "tree-test-hifu-lifting", "approved", clinic_id="3503190424")

        v2 = json.loads(VALID_MODEL_JSON)
        v2["keywords"] = ["深層筋膜", "熱凝結點", "拉提機轉"]
        v2["scenes"][0]["params"]["step_labels"] = ["深層能量導入", "筋膜熱凝結", "膠原緊縮拉提"]
        v2_str = json.dumps(v2, ensure_ascii=False)
        res_v2 = autodraft_from_tree(conn, tid, llm_call=lambda p: v2_str, db_path=isolated_db_path, topic_key_suffix="-v2")
        assert res_v2["status"] == "ok"

        prom = adopt_v2_candidate(conn, "tree-test-hifu-lifting-v2", clinic_id="3503190424", lessons_path=lessons_out)
        assert prom["status"] == "ok"
        stored = json.loads(lessons_out.read_text(encoding="utf-8"))["lessons"]
        assert any(x["lesson_id"].startswith("lesson-review-") and x["topic_key"] == "tree-test-hifu-lifting" for x in stored)
    finally:
        conn.close()


def test_adopt_v2_candidate_survives_lesson_write_failure(isolated_db_path: Path, tmp_path, monkeypatch):
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        tid = _seed_hifu(conn)
        autodraft_from_tree(conn, tid, llm_call=lambda p: VALID_MODEL_JSON, db_path=isolated_db_path)
        set_review_status(conn, "tree-test-hifu-lifting", "approved", clinic_id="3503190424")
        v2 = json.loads(VALID_MODEL_JSON)
        v2["keywords"] = ["深層筋膜", "拉提機轉", "熱凝結點"]
        autodraft_from_tree(conn, tid, llm_call=lambda p: json.dumps(v2, ensure_ascii=False), db_path=isolated_db_path, topic_key_suffix="-v2")

        def boom(*a, **k):
            raise OSError("磁碟寫入失敗（模擬）")

        monkeypatch.setattr(ho, "record_review_lesson", boom)
        prom = adopt_v2_candidate(conn, "tree-test-hifu-lifting-v2", clinic_id="3503190424", lessons_path=tmp_path / "x.json")
        assert prom["status"] == "ok", "沉澱失敗不得影響主交易"
    finally:
        conn.close()


def test_cli_passes_k_and_mode_to_autodraft(isolated_db_path: Path, monkeypatch, capsys):
    import scripts.autodraft_visual_from_trees as cli

    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        _seed_hifu(conn)
    finally:
        conn.close()

    captured = {}

    def fake(conn_, tree, **kwargs):
        captured.update(kwargs)
        return {"status": "ok", "topic_key": "tree-test-hifu-lifting", "review_status": "pending"}

    monkeypatch.setattr(cli, "autodraft_from_tree", fake)
    rc = cli.main(["--db", str(isolated_db_path), "--doc-id", "test-hifu-lifting", "--k", "2", "--mode", "parallel", "--force"])
    assert rc == 0
    assert captured["k_candidates"] == 2
    assert captured["recursion_mode"] == "parallel"
