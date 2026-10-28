"""測試 src/pageindex/tree_navigator.py（VectifyAI 節點導航、標準 Schema 匯出與長文件 TOC 濃縮）。"""

from __future__ import annotations

from src.pageindex.tree_navigator import (
    condense_long_document_by_toc,
    select_tree_branches,
    to_vectify_tree_schema,
)


def _sample_tree() -> dict:
    return {
        "doc_id": "rhinoplasty-strut",
        "title": "結構式隆鼻手術",
        "summary_text": "透過自體軟骨建立鼻尖力學三角支架，提升結構穩定度。",
        "pre_op": "術前需進行凝血功能檢查與鼻腔評估。若有慢性鼻竇炎或特殊體質請先告知醫師。",
        "pre_op_physician_notes": "有鼻部外傷史者須加做鼻中膈評估。",
        "procedure": "手術採複合式麻醉，分離鼻背筋膜空間，並以自體肋軟骨或耳軟骨搭建鼻小柱支撐。",
        "procedure_physician_notes": "",
        "post_op_short": "術後前三天可局部冰敷減緩腫脹，約一週回診拆線與移除鼻背板。若出現劇烈疼痛或發燒請立即回診。",
        "post_op_short_physician_notes": "嚴禁自行擠壓鼻頭或配戴沉重鏡框。",
        "maintenance": "術後一個月內避免碰撞與劇烈運動，日常清潔以無菌棉棒輕拭即可。",
        "maintenance_physician_notes": "",
    }


def test_select_tree_branches_prioritizes_intent_and_keeps_physician_notes():
    """驗證依問句意圖導航時，對應節點被標記為 is_primary 且完整保留醫師權威醫囑。"""
    tree = _sample_tree()
    branches = select_tree_branches(tree, "請問隆鼻術後恢復期要怎麼照顧？多久拆線？", intent="recovery", total_budget=800)
    assert len(branches) == 4

    by_key = {b.field_key: b for b in branches}
    assert by_key["post_op_short"].is_primary is True
    assert by_key["post_op_short"].node_id == "0003"
    assert "拆線" in by_key["post_op_short"].content
    assert "嚴禁自行擠壓鼻頭" in by_key["post_op_short"].physician_note


def test_to_vectify_tree_schema_structure():
    """驗證匯出為上游 VectifyAI/PageIndex 標準巢狀結構（含 node_id, summary, nodes）。"""
    tree = _sample_tree()
    schema = to_vectify_tree_schema(tree)
    assert schema["doc_name"] == "rhinoplasty-strut"
    assert schema["doc_title"] == "結構式隆鼻手術"
    assert isinstance(schema["structure"], list)
    assert len(schema["structure"]) == 4

    node_map = {n["node_id"]: n for n in schema["structure"]}
    assert "0001" in node_map
    assert "0003" in node_map
    # 0003 具有 post_op_short_physician_notes，應包含子節點 0003.1
    assert len(node_map["0003"]["nodes"]) == 1
    assert node_map["0003"]["nodes"][0]["node_id"] == "0003.1"
    assert "嚴禁自行擠壓鼻頭" in node_map["0003"]["nodes"][0]["summary"]


def test_condense_long_document_by_toc_preserves_tail_post_op():
    """驗證超過 3,500 字的長篇衛教文件經 TOC 分段濃縮後，不會丟失位於文末的術後照護與長期維持段落。"""
    filler_para = "一般背景說明文字與醫療概念介紹，協助讀者理解基礎解剖構造與常見問題。" * 42  # 約 1428 字
    long_doc = (
        "一、術前評估與準備\n術前請配合抽血檢查並主動告知過敏史與慢性病史。\n\n"
        + filler_para + "\n\n"
        + "二、手術原理與過程\n透過微創內視鏡輔助進行深層筋膜剝離與復位固定。\n\n"
        + filler_para + "\n\n"
        + filler_para + "\n\n"
        + "三、術後短期照護與回診警訊\n術後傷口需保持清潔乾燥，若出現持續紅腫熱痛或異常滲液請立即回診就醫。\n\n"
        + "四、長期維持與日常保養\n長期維持建議做好日常防曬與規律作息，避免抽菸影響組織微循環。"
    )
    assert len(long_doc) > 3800

    condensed = condense_long_document_by_toc(long_doc, max_chars=3500)
    assert len(condensed) <= 3500
    # 若只是硬切 text[:3500]，文末的第三、四節會被截斷；透過 TOC 節點濃縮必須保留
    assert "術後傷口需保持清潔乾燥" in condensed
    assert "長期維持建議做好日常防曬" in condensed


def test_rag_ask_render_evidence_uses_tree_navigator():
    """驗證 rag_ask._render_evidence 整合 select_tree_branches 後，能注入節點編號與醫師權威醫囑。"""
    from types import SimpleNamespace
    from src.pageindex.rag_ask import _render_evidence

    tree_hit = SimpleNamespace(row_id=99, fields=_sample_tree())
    ctx, sources = _render_evidence(
        faq_hits=[],
        tree_hits=[tree_hit],
        notes=[],
        clinic_info=None,
        budget_ratio=1.0,
        question="請問隆鼻術後恢復期怎麼照顧？",
    )
    assert "[T1]（臨床推理樹：rhinoplasty-strut）" in ctx
    assert "[0003 術後短期照護與警訊]" in ctx
    assert "醫囑：嚴禁自行擠壓鼻頭或配戴沉重鏡框" in ctx
    assert sources[0]["doc_id"] == "rhinoplasty-strut"

