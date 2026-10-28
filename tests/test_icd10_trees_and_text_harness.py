"""Phase 37：選項 A（36 項 ICD-10 一般醫學推理樹）＋ 選項 B（Text Native Harness²）測試。

隔離原則：所有寫入皆使用 isolated_db_path 隔離複本；LLM 一律以 mock 注入；不呼叫真實模型。
"""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest

from src.pageindex import text_harness as th
from src.pageindex.answer_generator import GenerationError, generate_answer_for_faq
from src.pageindex.db_writer import upsert_trees
from src.pageindex.faq_writer import upsert_faqs
from src.pageindex.tree_distiller import TreeValidationError, distill_tree_from_text
from src.pageindex.tree_navigator import select_tree_branches
from src.visual import harness_optimizer as ho
from src.visual.icd10_catalog import entry_to_page_index_tree, load_icd10_catalog, seed_icd10_catalog
from src.general.consult import consult_general
from tests.conftest import apply_visual_migration


@pytest.fixture(autouse=True)
def _isolate_lessons(tmp_path, monkeypatch):
    target = tmp_path / "harness_lessons.json"
    target.write_text(ho.DEFAULT_LESSONS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(ho, "DEFAULT_LESSONS_PATH", target)


def _prepare_db(db_path: Path) -> sqlite3.Connection:
    """套用視覺遷移並清除副本內既有的 ICD 推理樹，使計數測試獨立於正式庫狀態。"""
    apply_visual_migration(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM page_index_trees WHERE doc_id LIKE 'icd-%'")
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# 選項 A：ICD-10 推理樹升格
# ---------------------------------------------------------------------------

def test_entry_to_page_index_tree_maps_four_segments():
    entry = load_icd10_catalog()[0]
    tree = entry_to_page_index_tree(entry)
    summary = entry["clinical_summary"]
    assert tree["doc_id"] == entry["topic_key"]
    assert tree["clinic_id"] is None
    assert tree["category"] == "general"
    assert tree["title"] == entry["ir"]["title"]
    assert tree["pre_op"] == summary["clinical_presentation"]
    assert tree["procedure"] == summary["pathophysiology"]
    assert tree["post_op_short"] == summary["management_care"]
    assert tree["maintenance"] == summary["red_flags_prevention"]
    for key in ("pre_op_physician_notes", "procedure_physician_notes",
                "post_op_short_physician_notes", "maintenance_physician_notes"):
        assert tree[key] is None
    assert tree["summary_text"].startswith(f"{entry['ir']['title']}（{entry['icd10_code']}）")


def test_upsert_trees_allows_general_without_clinic_but_rejects_special(isolated_db_path: Path):
    conn = _prepare_db(isolated_db_path)
    try:
        base = entry_to_page_index_tree(load_icd10_catalog()[0])
        upsert_trees(conn, [{**base, "review_status": "pending"}], source_type="llm_generated")
        row = conn.execute("SELECT clinic_id, category FROM page_index_trees WHERE doc_id = ?", (base["doc_id"],)).fetchone()
        assert row == (None, "general")

        special = {k: v for k, v in base.items() if k != "clinic_id"}
        special.update(doc_id="special-no-clinic", category="special")
        with pytest.raises(ValueError, match="clinic_id"):
            upsert_trees(conn, [special], source_type="llm_generated")
        empty = {**special, "clinic_id": ""}
        with pytest.raises(ValueError, match="clinic_id"):
            upsert_trees(conn, [empty], source_type="llm_generated")
    finally:
        conn.close()


def test_upsert_trees_commit_false_defers_to_caller(isolated_db_path: Path):
    conn = _prepare_db(isolated_db_path)
    try:
        base = entry_to_page_index_tree(load_icd10_catalog()[1])
        upsert_trees(conn, [{**base, "review_status": "pending"}], source_type="llm_generated", commit=False)
        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM page_index_trees WHERE doc_id = ?", (base["doc_id"],)).fetchone()[0] == 0
    finally:
        conn.close()


def test_seed_writes_36_general_trees_pending_by_default(isolated_db_path: Path):
    conn = _prepare_db(isolated_db_path)
    try:
        result = seed_icd10_catalog(conn, approve_visuals=False)
        assert result["trees"][0] == 36
        rows = conn.execute(
            "SELECT COUNT(*), SUM(clinic_id IS NULL), SUM(review_status = 'pending'), SUM(source_type = 'llm_generated') "
            "FROM page_index_trees WHERE doc_id LIKE 'icd-%'"
        ).fetchone()
        assert rows == (36, 36, 36, 36)
        again = seed_icd10_catalog(conn, approve_visuals=False)
        assert again["trees"] == (0, 0, 36)
    finally:
        conn.close()


def test_seed_approve_trees_makes_them_visible_and_navigable(isolated_db_path: Path):
    conn = _prepare_db(isolated_db_path)
    try:
        seed_icd10_catalog(conn, approve_trees=True)
        statuses = conn.execute(
            "SELECT DISTINCT review_status, source_type FROM page_index_trees WHERE doc_id LIKE 'icd-%'"
        ).fetchall()
        assert statuses == [("approved", "clinic_upload")]

        result = consult_general(conn, "感冒")
        assert result.status == "answered", result
        doc_ids = [h["doc_id"] for h in result.guide_hits]
        assert any(d.startswith("icd-") for d in doc_ids), doc_ids

        fields = conn.execute(
            "SELECT pre_op, procedure, post_op_short, maintenance, pre_op_physician_notes, "
            "procedure_physician_notes, post_op_short_physician_notes, maintenance_physician_notes "
            "FROM page_index_trees WHERE doc_id = 'icd-j069-uri'"
        ).fetchone()
        tree_fields = dict(zip(
            ["pre_op", "procedure", "post_op_short", "maintenance",
             "pre_op_physician_notes", "procedure_physician_notes",
             "post_op_short_physician_notes", "maintenance_physician_notes"], fields))
        branches = select_tree_branches(tree_fields, "感冒怎麼照顧")
        assert branches, "ICD 推理樹應可被分支導航命中"
    finally:
        conn.close()


def test_seed_script_flag_and_summary(isolated_db_path: Path, capsys):
    import scripts.seed_icd10_primary_care as cli

    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    conn.execute("DELETE FROM page_index_trees WHERE doc_id LIKE 'icd-%'")
    conn.commit()
    conn.close()
    rc = cli.main(["--db", str(isolated_db_path), "--approve-trees"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "推理樹" in out
    conn = sqlite3.connect(str(isolated_db_path))
    assert conn.execute("SELECT COUNT(*) FROM page_index_trees WHERE doc_id LIKE 'icd-%' AND review_status='approved'").fetchone()[0] == 36
    conn.close()


def test_search_include_general_is_opt_in(isolated_db_path: Path):
    from src.query.search import search_page_index_trees

    conn = _prepare_db(isolated_db_path)
    try:
        seed_icd10_catalog(conn, approve_trees=True)
        strict = search_page_index_trees(conn, "上呼吸道感染", clinic_id="3503190424")
        assert all(h.fields["clinic_id"] == "3503190424" for h in strict)
        merged = search_page_index_trees(conn, "上呼吸道感染", clinic_id="3503190424", include_general=True)
        assert any(h.fields["clinic_id"] is None for h in merged)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 選項 B：文字版 Harness²
# ---------------------------------------------------------------------------

_GOOD_ANSWER = (
    "感冒鼻塞多由病毒引起，常見流鼻水與喉嚨不適，多數人在數日內逐漸緩解。"
    "居家可以充分休息、補充溫開水並保持室內濕潤，避免過勞與熬夜，讓黏膜有時間修復。"
    "若出現持續高燒不退、呼吸困難或胸痛等情形，請立即就醫或前往急診評估。"
)

_LOW_ANSWER = (
    "這是一個很常見的問題，大家通常都會好奇。生活中有很多事情值得關注，天氣變化也會影響心情。"
    "大家可以多多留意自己的狀態，保持愉快的心情就好。平常多喝水、多休息，其他的事情看情況再說就可以了。"
    "若出現持續高燒不退、呼吸困難或胸痛等情形，請立即就醫或前往急診評估。"
)


def test_select_text_lessons_matches_domain_and_format_has_no_blueprint():
    lessons = th.select_text_lessons("產後媽咪腹直肌分離如何照顧？")
    assert lessons and lessons[0]["lesson_id"] == "lesson-body-abdominoplasty"
    assert th.select_text_lessons("海芙音波拉提保養") == []
    block = th.format_text_lessons_for_prompt(lessons)
    assert "防護欄" in block and "闊頸肌" in block
    assert "preferred_blueprint" not in block and "surgical_action" not in block
    assert th.format_text_lessons_for_prompt([]) == ""


def test_faq_alignment_prefers_on_topic_structured_answer():
    good = th.score_faq_answer_alignment("感冒鼻塞怎麼辦？", "感冒", _GOOD_ANSWER, lessons=[])
    low = th.score_faq_answer_alignment("感冒鼻塞怎麼辦？", "感冒", _LOW_ANSWER, lessons=[])
    assert good["score"] > low["score"], (good, low)
    assert good["passed_threshold"] is True, good
    assert low["penalties"], low
    assert low["suggestions"]


def test_faq_alignment_penalizes_cross_specialty_lexicon():
    lessons = th.select_text_lessons("產後媽咪腹直肌分離如何照顧？")
    bad = _GOOD_ANSWER + "闊頸肌與下臉的照護也需要注意。"
    rep = th.score_faq_answer_alignment("產後媽咪腹直肌分離如何照顧？", "媽咪改造", bad, lessons=lessons)
    assert any("闊頸肌" in p for p in rep["penalties"]), rep["penalties"]
    assert rep["breakdown"]["lesson_compliance"] < 1.0


def test_faq_critique_prompt_carries_penalties():
    rep = th.score_faq_answer_alignment("感冒鼻塞怎麼辦？", "感冒", _LOW_ANSWER, lessons=[])
    prompt = th.build_faq_critique_prompt("BASE", _LOW_ANSWER, rep)
    assert prompt.startswith("BASE") and "任務級遞迴精煉" in prompt and "具體扣分原因" in prompt


_SOURCE = (
    "感冒由病毒感染上呼吸道引起，鼻咽黏膜充血水腫，纖毛清除功能暫時下降，"
    "患者常見鼻塞流涕與咽喉不適，多數在數日內自行緩解，保暖補水與充分休息有助於黏膜修復。"
)

_GOOD_TREE = {
    "pre_op": "感冒初期常見鼻塞流涕與咽喉不適，醫師會先評估症狀持續時間與是否伴隨高燒，據此判斷是否需要進一步檢查與處理方向。",
    "procedure": "病毒感染上呼吸道使鼻咽黏膜充血水腫，纖毛清除功能暫時下降，黏膜修復需要時間，其間分泌物會逐漸變化。",
    "post_op_short": "居家保暖補水並充分休息，避免過勞熬夜，觀察鼻塞與咽喉不適是否逐漸減輕，症狀改善速度因人而異。",
    "maintenance": "若症狀持續超過兩週未改善，或出現持續高燒不退與呼吸困難，應儘速回診由醫師重新評估病況與後續照護。",
    "summary_text": "感冒的病毒感染與黏膜修復過程，包含鼻塞流涕、居家照護與回診時機。",
}

_LOW_TREE = {
    "pre_op": "感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒。",
    "procedure": "感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒。",
    "post_op_short": "感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒。",
    "maintenance": "感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒感冒。",
    "summary_text": "感冒",
}


def test_tree_alignment_rewards_specific_stages_and_penalizes_copy_paste():
    good = th.score_tree_distillation_alignment("感冒上呼吸道感染", _SOURCE, _GOOD_TREE, lessons=[])
    low = th.score_tree_distillation_alignment("感冒上呼吸道感染", _SOURCE, _LOW_TREE, lessons=[])
    assert good["score"] > low["score"], (good, low)
    assert good["passed_threshold"] is True, good
    assert any("相似度過高" in p for p in low["penalties"]), low["penalties"]


def test_tree_critique_prompt_carries_penalties():
    rep = th.score_tree_distillation_alignment("感冒", _SOURCE, _LOW_TREE, lessons=[])
    prompt = th.build_tree_critique_prompt("BASE", _LOW_TREE, rep)
    assert prompt.startswith("BASE") and "任務級遞迴精煉" in prompt


def _seed_draft(conn: sqlite3.Connection) -> int:
    upsert_faqs(conn, [{
        "question": "感冒鼻塞怎麼辦？",
        "answer": "待補",
        "category": "general",
        "clinic_id": None,
        "topic_key": "icd-j069-uri",
        "metadata": None,
    }], source_type="llm_generated", commit=True)
    return conn.execute("SELECT id FROM faq_cache WHERE question = '感冒鼻塞怎麼辦？'").fetchone()[0]


def _sequence_llm(outputs: list[str]):
    calls: list[str] = []
    seq = list(outputs)

    def fake(prompt: str) -> str:
        calls.append(prompt)
        return seq.pop(0) if seq else outputs[-1]

    return fake, calls


@pytest.mark.parametrize("mode", ["sequential", "parallel"])
def test_generate_answer_k3_selects_highest_scoring_candidate(isolated_db_path: Path, mode):
    conn = _prepare_db(isolated_db_path)
    try:
        fid = _seed_draft(conn)
        fake, calls = _sequence_llm([_LOW_ANSWER, _GOOD_ANSWER, _LOW_ANSWER])
        res = generate_answer_for_faq(conn, fid, fake, overwrite=True, k_candidates=3, recursion_mode=mode)
        assert res["review_status"] == "pending"
        assert res["answer"] == _GOOD_ANSWER, "應選中最高分候選"
        meta = json.loads(conn.execute("SELECT metadata FROM faq_cache WHERE id = ?", (fid,)).fetchone()[0])
        assert meta["harness_mode"] == mode and meta["harness_k"] == 3
        assert meta["harness_score"] == res["harness_score"]
        if mode == "sequential":
            assert "任務級遞迴精煉" in calls[1]
        else:
            assert all("任務級遞迴精煉" not in c for c in calls)
    finally:
        conn.close()


def test_generate_answer_k1_legacy_path_still_writes_harness_metadata(isolated_db_path: Path):
    conn = _prepare_db(isolated_db_path)
    try:
        fid = _seed_draft(conn)
        res = generate_answer_for_faq(conn, fid, lambda p: _GOOD_ANSWER, overwrite=True)
        assert res["answer"] == _GOOD_ANSWER
        assert "harness_score" in res
    finally:
        conn.close()


def test_generate_answer_rejects_invalid_recursion_args(isolated_db_path: Path):
    conn = _prepare_db(isolated_db_path)
    try:
        fid = _seed_draft(conn)
        with pytest.raises(GenerationError):
            generate_answer_for_faq(conn, fid, lambda p: _GOOD_ANSWER, overwrite=True, recursion_mode="chaos")
    finally:
        conn.close()


def test_prompts_carry_lessons_for_matching_topic():
    from src.pageindex.answer_generator import build_answer_prompt

    assert "防護欄" in build_answer_prompt("產後媽咪腹直肌分離如何照顧？", "媽咪改造")
    assert "防護欄" not in build_answer_prompt("海芙音波拉提後保養重點是什麼？", "海芙音波")


@pytest.mark.parametrize("mode", ["sequential", "parallel"])
def test_distill_k3_selects_highest_scoring_tree(isolated_db_path: Path, mode):
    conn = _prepare_db(isolated_db_path)
    try:
        fake, calls = _sequence_llm([
            json.dumps(_LOW_TREE, ensure_ascii=False),
            json.dumps(_GOOD_TREE, ensure_ascii=False),
            json.dumps(_LOW_TREE, ensure_ascii=False),
        ])
        res = distill_tree_from_text(
            conn, "感冒上呼吸道感染", _SOURCE, clinic_id="3503190424", doc_id="test-distill-cold",
            llm_call=fake, k_candidates=3, recursion_mode=mode,
        )
        assert res["pre_op"] == _GOOD_TREE["pre_op"]
        assert res["harness_mode"] == mode and res["harness_k"] == 3
        assert res["harness_score"] > 0.5
        stored = conn.execute("SELECT review_status FROM page_index_trees WHERE doc_id = 'test-distill-cold'").fetchone()
        assert stored[0] == "pending"
        if mode == "sequential":
            assert "任務級遞迴精煉" in calls[1]
        else:
            assert all("任務級遞迴精煉" not in c for c in calls)
    finally:
        conn.close()


def test_distill_k1_still_raises_on_invalid_json(isolated_db_path: Path):
    conn = _prepare_db(isolated_db_path)
    try:
        with pytest.raises(TreeValidationError):
            distill_tree_from_text(
                conn, "感冒", _SOURCE, clinic_id="3503190424", doc_id="test-distill-bad",
                llm_call=lambda p: "不是 json",
            )
    finally:
        conn.close()
