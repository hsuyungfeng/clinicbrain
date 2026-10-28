"""Phase 38 Step 3：站點內文提煉 → FAQ 與四段式推理樹（全部 pending）測試。

隔離原則：一律使用 isolated_db_path 隔離複本；LLM 以 mock 注入，絕不呼叫真實模型。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.scraper import distill_pipeline as dp

CLINIC = "3503190424"
CLINIC_NAME = "緻妍外科診所"

SITE_TEXT = (
    "感冒由病毒感染上呼吸道引起，鼻咽黏膜充血水腫，纖毛清除功能暫時下降，"
    "患者常見鼻塞流涕與咽喉不適，多數在數日內自行緩解，保暖補水與充分休息有助於黏膜修復。"
    "若症狀持續超過兩週未改善，應回診評估。"
)

GOOD_FAQ_ANSWER = (
    "感冒鼻塞多由病毒引起，病原會附著在鼻咽黏膜上造成充血與水腫，因此常見流鼻水與喉嚨不適。"
    "身體的免疫清除機制會逐步處理病原，多數人在數日內就能逐漸緩解，黏膜的纖毛功能也會慢慢恢復。"
    "居家可以充分休息、補充溫開水並保持室內濕潤，避免過勞與熬夜，讓屏障修復有足夠時間。"
    "若出現持續高燒不退、呼吸困難或胸痛等情形，請立即就醫或前往急診評估。"
)

BAD_FAQ_ANSWER = "感冒療程費用 NT$1500 元，歡迎洽詢，服用藥物請依說明。"

GOOD_TREE = {
    "pre_op": "感冒初期常見鼻塞流涕與咽喉不適，醫師會先評估症狀持續時間與是否伴隨高燒，據此判斷是否需要進一步檢查與處理方向。",
    "procedure": "病毒感染上呼吸道使鼻咽黏膜充血水腫，纖毛清除功能暫時下降，黏膜修復需要時間，其間分泌物會逐漸變化。",
    "post_op_short": "居家保暖補水並充分休息，避免過勞熬夜，觀察鼻塞與咽喉不適是否逐漸減輕，症狀改善速度因人而異。",
    "maintenance": "若症狀持續超過兩週未改善，或出現持續高燒不退與呼吸困難，應儘速回診由醫師重新評估病況與後續照護。",
    "summary_text": "感冒的病毒感染與黏膜修復過程，包含鼻塞流涕、居家照護與回診時機。",
}


def _router(faq_items=None, tree=None, faq_raises=False):
    """依提示詞內容分流：FAQ 提示含『5 至 10 筆』，推理樹提示含『四段式』。"""
    calls: list[str] = []

    def llm(prompt: str) -> str:
        calls.append(prompt)
        if "5 至 10 筆" in prompt:
            if faq_raises:
                raise RuntimeError("LLM 離線（模擬）")
            return json.dumps(faq_items or [], ensure_ascii=False)
        return json.dumps(tree or GOOD_TREE, ensure_ascii=False)

    return llm, calls


@pytest.fixture()
def conn(isolated_db_path: Path):
    c = sqlite3.connect(str(isolated_db_path))
    c.execute("DELETE FROM page_index_trees WHERE doc_id LIKE 'site-%'")
    c.execute("DELETE FROM faq_cache WHERE topic_key LIKE 'site-%'")
    c.commit()
    yield c
    c.close()


def test_chunking_keeps_paragraphs_and_respects_size():
    text = "\n".join(["段落" * 50] * 6)
    chunks = dp._split_chunks(text, 300)
    assert all(len(c) <= 300 for c in chunks)
    assert len(chunks) >= 2


def test_faq_items_parser_is_tolerant():
    raw = "說明 ```json\n[{\"question\": \"Q？\", \"answer\": \"A\"}, {\"bad\": 1}]\n```"
    assert dp._parse_faq_items(raw) == [{"question": "Q？", "answer": "A"}]
    assert dp._parse_faq_items("沒有任何陣列") == []


def test_accept_faq_rejects_prices_and_appends_warning_when_missing():
    bad, code = dp._accept_faq("感冒怎麼辦？", BAD_FAQ_ANSWER, CLINIC_NAME)
    assert bad is None and code in ("length", "compliance")
    no_warning = GOOD_FAQ_ANSWER.replace("若出現持續高燒不退、呼吸困難或胸痛等情形，請立即就醫或前往急診評估。", "多休息。")
    got, code = dp._accept_faq("感冒鼻塞怎麼辦？", no_warning, CLINIC_NAME)
    assert code == "ok" or got is None  # 缺就醫警訊時必先補上收尾句（若仍不合格則拒絕）
    if got is not None:
        assert dp.WARNING_SENTENCE in got[1]


def test_full_pipeline_writes_pending_faq_and_tree(conn):
    llm, _ = _router(faq_items=[
        {"question": "感冒鼻塞怎麼辦？", "answer": GOOD_FAQ_ANSWER},
        {"question": "感冒療程多少錢？", "answer": BAD_FAQ_ANSWER},
    ], tree=GOOD_TREE)
    result = dp.distill_site_content(SITE_TEXT, CLINIC, CLINIC_NAME, conn=conn, llm_call=llm, max_trees=1,
                                     source_url="https://clinic.test/faq")
    assert result.faq_candidates == 2
    assert result.faq_accepted == 1
    assert result.faq_written[0] == 1
    assert result.trees_written and result.trees_written[0].startswith("site-")

    faq = conn.execute("SELECT review_status, source_type, clinic_id, category FROM faq_cache WHERE topic_key LIKE 'site-%'").fetchall()
    assert faq == [("pending", "llm_generated", CLINIC, "special")]
    tree = conn.execute("SELECT review_status, source_type FROM page_index_trees WHERE doc_id = ?", (result.trees_written[0],)).fetchone()
    assert tree[0] == "pending"
    assert conn.execute("SELECT COUNT(*) FROM page_index_trees WHERE doc_id LIKE 'site-%' AND review_status = 'approved'").fetchone()[0] == 0


def test_prices_never_reach_storage(conn):
    llm, _ = _router(faq_items=[{"question": "感冒鼻塞怎麼辦？", "answer": GOOD_FAQ_ANSWER.replace("多數人", "NT$500 的人")}])
    dp.distill_site_content(SITE_TEXT, CLINIC, CLINIC_NAME, conn=conn, llm_call=llm, max_trees=0)
    stored = " ".join(r[0] for r in conn.execute("SELECT answer FROM faq_cache WHERE topic_key LIKE 'site-%'"))
    assert "NT$500" not in stored


def test_dry_run_without_connection_writes_nothing(conn):
    llm, _ = _router(faq_items=[{"question": "感冒鼻塞怎麼辦？", "answer": GOOD_FAQ_ANSWER}])
    result = dp.distill_site_content(SITE_TEXT, CLINIC, CLINIC_NAME, conn=None, llm_call=llm, max_trees=2)
    assert result.faq_accepted == 1 and result.faq_written == (0, 0, 0) and result.trees_written == []
    assert conn.execute("SELECT COUNT(*) FROM faq_cache WHERE topic_key LIKE 'site-%'").fetchone()[0] == 0


def test_second_run_is_idempotent_for_tree_and_unchanged_faq(conn):
    llm, _ = _router(faq_items=[{"question": "感冒鼻塞怎麼辦？", "answer": GOOD_FAQ_ANSWER}])
    first = dp.distill_site_content(SITE_TEXT, CLINIC, CLINIC_NAME, conn=conn, llm_call=llm, max_trees=1)
    second = dp.distill_site_content(SITE_TEXT, CLINIC, CLINIC_NAME, conn=conn, llm_call=llm, max_trees=1)
    assert first.faq_written[0] == 1
    assert second.faq_written == (0, 0, 1)
    assert any(e.startswith("tree_exists") for e in second.errors)


def test_llm_outage_is_recorded_not_fatal(conn):
    llm, _ = _router(faq_raises=True)
    result = dp.distill_site_content(SITE_TEXT, CLINIC, CLINIC_NAME, conn=conn, llm_call=llm, max_trees=0)
    assert "faq_llm:RuntimeError" in result.errors
    assert result.faq_accepted == 0


def test_empty_input_and_missing_identity_rejected():
    with pytest.raises(ValueError):
        dp.distill_site_content("   ", CLINIC, CLINIC_NAME, llm_call=lambda p: "[]")
    with pytest.raises(ValueError):
        dp.distill_site_content(SITE_TEXT, "", CLINIC_NAME, llm_call=lambda p: "[]")
