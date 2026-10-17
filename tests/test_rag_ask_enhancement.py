#!/usr/bin/env python3
"""
tests/test_rag_ask_enhancement.py
Phase 22 Plan 22-02: 提問檢索 Context 召回擴充與結構化衛教 Prompt 優化單元測試
"""

import pytest

from src.pageindex.rag_ask import (
    MAX_FAQ,
    retrieve_evidence,
    build_ask_prompt,
    ask_with_data,
    NO_EVIDENCE_MESSAGE,
)
from src.pageindex.faq_writer import upsert_faqs

CLINIC = "3503190424"
UNIQUE_TOKEN = "極光水波護理療程"


def test_max_faq_constant_and_evidence_expansion(isolated_conn):
    """驗證 MAX_FAQ 已擴增為 8 筆，且 retrieve_evidence 能正確召回達 8 筆來源。"""
    assert MAX_FAQ == 8

    # 寫入 10 筆已核准之特有問答
    faqs = [
        {
            "clinic_id": CLINIC,
            "topic_key": f"p22-aurora-{i}",
            "category": "special",
            "question": f"{UNIQUE_TOKEN}相關問題第 {i} 題：照護細節說明？",
            "answer": f"這是第 {i} 題的詳細說明，包含{UNIQUE_TOKEN}日常清潔照護步驟。",
        }
        for i in range(1, 11)
    ]
    upsert_faqs(isolated_conn, faqs, source_type="clinic_upload")

    context, sources = retrieve_evidence(isolated_conn, f"{UNIQUE_TOKEN}照護", clinic_id=CLINIC)

    faq_sources = [s for s in sources if s["type"] == "faq"]
    assert len(faq_sources) == 8, f"預期召回 8 筆 FAQ 來源，實際取得 {len(faq_sources)}"
    assert "[F1]" in context
    assert "[F8]" in context
    assert "[F9]" not in context  # 截斷在 8 筆


def test_prompt_template_structure_guidance():
    """驗證 build_ask_prompt 包含結構化條列分段說明與 250~400 字指引。"""
    prompt = build_ask_prompt("甲溝炎要怎麼照護？", "[F1] 門診處理\n[F2] 居家照護")

    assert "250～400 字" in prompt or "250~400 字" in prompt
    assert "結構化" in prompt or "條列分段" in prompt
    assert "【門診處置】" in prompt
    assert "【日常照護】" in prompt
    assert "【就醫提醒】" in prompt
    assert "不可臆測" in prompt
    assert "嚴格禁止" in prompt


def test_structured_response_passes_medical_safety_validation(isolated_conn):
    """驗證符合結構化條列（250~400字）且遵循醫療規範之 Mock 回答通過 validate_single_faq。"""
    upsert_faqs(
        isolated_conn,
        [
            {
                "clinic_id": CLINIC,
                "topic_key": "p22-paronychia-treat",
                "category": "special",
                "question": f"{UNIQUE_TOKEN}門診處理流程？",
                "answer": "醫師評估局部發炎後可進行部分切除與清創處理。",
            },
            {
                "clinic_id": CLINIC,
                "topic_key": "p22-paronychia-home",
                "category": "special",
                "question": f"{UNIQUE_TOKEN}在家自我照護？",
                "answer": "每日溫水浸泡15分鐘、保持乾燥並平直修剪指甲以防長入肉。",
            },
        ],
        source_type="clinic_upload",
    )

    mock_answer = (
        "【門診處置】\n"
        "發作時應先由醫師評估發炎狀況，必要時可安排微創清創或部分指甲切除處置，以緩解局部嵌入壓迫並降低發炎反應 [F1]。\n\n"
        "【日常照護】\n"
        "日常照護可每日以溫水浸泡患處約15分鐘幫助局部放鬆軟化，浸泡後務必以乾淨毛巾拍乾並保持通風乾燥 [F2]。修剪指甲時應採水平平直修剪，避免過度修剪兩側邊緣造成指甲往內生長 [F2]。\n\n"
        "【就醫提醒】\n"
        "若患部出現明顯紅腫發熱、劇烈跳痛、化膿液滲出或發燒等感染警訊，切勿自行挑刺擠壓，應儘速就醫回診請醫師評估處置 [F1]。"
    )

    res = ask_with_data(isolated_conn, f"{UNIQUE_TOKEN}要怎麼照護？", CLINIC, llm_call=lambda p: mock_answer)

    assert res["mode"] == "answered"
    assert res["used_llm"] is True
    assert res["compliance"]["ok"] is True
    assert res["compliance"]["reason"] == ""
    assert "【門診處置】" in res["answer"]
    assert "【日常照護】" in res["answer"]
    assert "【就醫提醒】" in res["answer"]
    assert len(res["sources"]) >= 2


def test_no_evidence_fallback(isolated_conn):
    """若檢索無任何相關內容，應誠實退回 no_evidence，不呼叫 LLM。"""
    called = []
    res = ask_with_data(isolated_conn, "外太空星艦維修指南龘龘", CLINIC, llm_call=lambda p: called.append(p) or "答案")

    assert res["mode"] == "no_evidence"
    assert res["used_llm"] is False
    assert res["answer"] == NO_EVIDENCE_MESSAGE
    assert len(called) == 0


def test_retrieve_evidence_preserves_warning_in_long_faq(isolated_conn):
    """驗證當 FAQ 答案有 700 字且結尾包含「若出現胸痛喘不過氣請儘速就醫」就醫警訊句時，經 retrieve_evidence 後，該警訊句完整進入 context，且結尾不出現 …。"""
    warning_sentence = "若出現胸痛喘不過氣請儘速就醫。"
    sents = [f"這是第{i}個詳細的日常居家照護注意事項說明句子，請務必按照醫師指示清潔患部避免感染。" for i in range(1, 20)]
    long_answer = "。".join(sents) + "。" + warning_sentence
    assert len(long_answer) >= 700

    upsert_faqs(
        isolated_conn,
        [
            {
                "clinic_id": CLINIC,
                "topic_key": "p28-long-warning",
                "category": "special",
                "question": f"{UNIQUE_TOKEN}術後特殊警訊注意事項？",
                "answer": long_answer,
            }
        ],
        source_type="clinic_upload",
    )

    context, sources = retrieve_evidence(isolated_conn, f"{UNIQUE_TOKEN}注意事項", clinic_id=CLINIC)
    assert len(sources) >= 1
    assert warning_sentence in context
    assert "…" not in context
    assert "..." not in context


def test_retrieve_evidence_budget_cap_and_no_ellipsis(isolated_conn):
    """多筆 FAQ + 推理樹時，總 context 長度不超過 CONTEXT_TOTAL_CHARS + 200，且無任何省略號結尾。"""
    from src.pageindex.db_writer import upsert_trees
    from src.pageindex.rag_ask import CONTEXT_TOTAL_CHARS

    # 寫入 8 筆長 FAQ（每筆約 400 字）
    faqs = [
        {
            "clinic_id": CLINIC,
            "topic_key": f"p28-cap-{i}",
            "category": "special",
            "question": f"{UNIQUE_TOKEN}複合療程重點第 {i} 條：詳細操作流程與風險評估說明？",
            "answer": "。".join([f"這是第{i}筆常見問答的第{j}個詳細說明句子，內容包含完整的評估原則與操作注意事項" for j in range(1, 12)]) + "。",
        }
        for i in range(1, 9)
    ]
    upsert_faqs(isolated_conn, faqs, source_type="clinic_upload")

    # 寫入 2 棵推理樹（每棵四段式皆填寫 300+ 字）
    trees = [
        {
            "doc_id": f"p28-tree-{i}",
            "clinic_id": CLINIC,
            "category": "special",
            "title": f"{UNIQUE_TOKEN}臨床決策樹 {i}",
            "summary_text": f"{UNIQUE_TOKEN}臨床決策樹摘要說明，涵蓋術前評估、操作步驟、術後短期與長期維持各項重點。",
            "pre_op": "術前需詳細詢問病史，評估局部組織狀態與過敏史，排除絕對禁忌症與相對禁忌症，確認病患充分理解可能風險。",
            "pre_op_physician_notes": "",
            "procedure": "標準操作流程採用分層漸進技術，嚴格遵守無菌操作規範，依組織厚度與反應調整參數，避免單點過度停留與損傷。",
            "procedure_physician_notes": "",
            "post_op_short": "術後一週內局部可能有輕微水腫或紅斑反應，屬正常生理反應，每日以生理食鹽水輕柔清潔並保持通風乾燥。",
            "post_op_short_physician_notes": "",
            "maintenance": "長期維持應落實防曬保護，避免高溫場所與劇烈摩擦，依建議時程定期回診追蹤組織重塑進展與修復狀況。",
            "maintenance_physician_notes": "",
            "version": 1,
            "status": "approved",
        }
        for i in range(1, 3)
    ]
    upsert_trees(isolated_conn, trees, source_type="manual")

    context, sources = retrieve_evidence(isolated_conn, f"{UNIQUE_TOKEN}", clinic_id=CLINIC)
    assert len(sources) >= 1
    assert len(context) <= CONTEXT_TOTAL_CHARS + 200
    assert "…" not in context
    assert "..." not in context

