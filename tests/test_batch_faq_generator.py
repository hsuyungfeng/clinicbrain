"""
FAQ 夜間批次預生成模組測試（Phase 09 BATCH-01 Task 1）。

驗證：
1. 正常生成：種子問題逐字符合、通過四層醫療驗證、寫入 faq_cache 預設為 pending。
2. Prompt 檢驗：包含種子問題、合規宣告，且絕不洩漏 physician_notes 或非相關資料。
3. 拒絕情境與隱私過濾：各類違規精準對應固定代碼 (price_leak, simplified, forbidden,
   political, question_not_in_seed, answer_too_short, duplicate_question, json_invalid, malformed_item)，
   絕不回顯未驗證原文或含有命中敏感詞的原始錯誤訊息。
4. 已存在項目跳過：已存在之問題（不論審核狀態）自動過濾，不重複呼叫 LLM。
5. 異常傳播：LocalLLMUnavailableError 向上透明傳播。
6. 單一寫入途徑保證：一律經由 faq_writer.upsert_faqs 寫入。
7. 零外部請求保證：autouse fixture 封鎖 urllib.request.urlopen。
"""

import json
from pathlib import Path
import sqlite3
import urllib.request
import pytest

from src.batch.faq_generator import (
    MIN_ANSWER_CHARS,
    REJECT_CODES,
    TopicGenResult,
    build_seed_faq_prompt,
    classify_reject_reason,
    existing_questions,
    generate_topic_faqs,
    reference_from_tree,
    write_topic_faqs,
)
from src.batch.topic_sources import SeedTopic
from src.pageindex.faq_review import (
    REVIEW_APPROVED,
    REVIEW_PENDING,
    REVIEW_REJECTED,
    set_review_status,
)
from src.pageindex.faq_writer import upsert_faqs
from src.pageindex.llm_client import LocalLLMUnavailableError


@pytest.fixture(autouse=True)
def _block_external_llm_calls(monkeypatch):
    """防禦性 fixture：保證測試期間絕對不發起任何對外 HTTP/LLM 連線。"""
    def _fail_urlopen(*args, **kwargs):
        raise AssertionError("測試期間禁止呼叫 urllib.request.urlopen 發起真實網路連線！")

    monkeypatch.setattr(urllib.request, "urlopen", _fail_urlopen)


def test_classify_reject_reason_mapping():
    """表驅動測試：驗證各類驗證器錯誤訊息皆精確映射至 REJECT_CODES 成員，且不含原訊息。"""
    mapping_cases = [
        ("檢出具體金額：1500元", "price_leak"),
        ("檢測到價格數字洩漏", "price_leak"),
        ("輸出包含簡體字：这个", "simplified"),
        ("違反醫療廣告合規限制，包含禁用之誇大或保證療效詞彙: 保證有效", "forbidden"),
        ("包含政治立場爭議詞彙: 中國台灣", "political"),
        ("第 0 筆問題為空或非字串", "malformed_item"),
        ("缺少必要欄位", "malformed_item"),
        ("JSONDecodeError: Expecting value", "json_invalid"),
        ("頂層結構非陣列", "json_invalid"),
        ("未知的奇特例外訊息", "other"),
    ]
    for msg, expected_code in mapping_cases:
        code = classify_reject_reason(msg)
        assert code == expected_code
        assert code in REJECT_CODES


def test_generate_and_write_topic_faqs_happy_path(isolated_conn):
    """測試正常流程：產生 3 筆符合種子之問答，寫入後為 pending。"""
    topic = SeedTopic(
        topic_key="zz-batch-hifu",
        title="音波拉提常見問題",
        category="special",
        clinic_id="3503190424",
        keywords=("音波",),
        always=False,
        tree_doc_id="hifu-lifting",
        questions=(
            "音波拉提術後多久可以恢復正常保養？",
            "音波拉提大約多久需要再做一次？",
            "哪些人不適合接受音波拉提？",
        ),
    )

    mock_response = json.dumps(
        [
            {
                "question": "音波拉提術後多久可以恢復正常保養？",
                "answer": "音波拉提為非侵入式療程，術後當日即可進行溫和之基礎保濕與防曬保養。",
            },
            {
                "question": "音波拉提大約多久需要再做一次？",
                "answer": "多數患者通常建議每年進行一次評估與維持保養，實際週期應由醫師評估。",
            },
            {
                "question": "哪些人不適合接受音波拉提？",
                "answer": "懷孕婦女、治療區域有開放性傷口或嚴重囊腫型痤瘡者不宜施作此療程。",
            },
        ],
        ensure_ascii=False,
    )

    result = generate_topic_faqs(isolated_conn, topic, lambda prompt: mock_response)
    assert result.called_llm is True
    assert result.requested == 3
    assert result.skipped_existing == 0
    assert len(result.valid) == 3
    assert len(result.rejected) == 0

    # 寫入資料庫
    ins, upd, unc = write_topic_faqs(isolated_conn, result.valid)
    assert (ins, upd, unc) == (3, 0, 0)

    cur = isolated_conn.cursor()
    cur.execute(
        """
        SELECT question, source_type, review_status, clinic_id, topic_key
        FROM faq_cache
        WHERE topic_key = 'zz-batch-hifu'
        ORDER BY id ASC
        """
    )
    rows = cur.fetchall()
    assert len(rows) == 3
    for r in rows:
        assert r[1] == "llm_generated"
        assert r[2] == "pending"
        assert r[3] == "3503190424"
        assert r[4] == "zz-batch-hifu"


def test_build_seed_faq_prompt_and_privacy(isolated_conn):
    """測試 Prompt 構建：包含種子問題與參考資料，但絕不洩漏 physician_notes。"""
    # 在測試庫上為 hifu-lifting 寫入機密 physician_notes
    cur = isolated_conn.cursor()
    secret_note = "醫師機密指令：音波能量不得高於三級"
    cur.execute(
        "UPDATE page_index_trees SET procedure_physician_notes = ? WHERE doc_id = 'hifu-lifting'",
        (secret_note,),
    )
    isolated_conn.commit()

    captured_prompts = []

    def mock_llm(prompt: str) -> str:
        captured_prompts.append(prompt)
        return "[]"

    topic = SeedTopic(
        topic_key="zz-batch-privacy",
        title="隱私測試主題",
        category="special",
        clinic_id="3503190424",
        keywords=("音波",),
        always=False,
        tree_doc_id="hifu-lifting",
        questions=("音波拉提安全嗎？",),
    )

    generate_topic_faqs(isolated_conn, topic, mock_llm)
    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]

    # 檢查必要合規字眼
    assert "請致電診所確認" in prompt
    assert "繁體中文" in prompt
    assert "JSON" in prompt
    assert "音波拉提安全嗎？" in prompt

    # 保證不含 physician_notes 機密字樣
    assert secret_note not in prompt


def test_generate_topic_faqs_rejection_reasons(isolated_conn):
    """測試各類違規情況之精準拒絕代碼，且結果不包含未過濾敏感字樣。"""
    topic = SeedTopic(
        topic_key="zz-batch-reject",
        title="違規測試主題",
        category="special",
        clinic_id="3503190424",
        keywords=(),
        always=False,
        tree_doc_id=None,
        questions=(
            "問題1-價格？",
            "問題2-簡體？",
            "問題3-禁詞？",
            "問題4-政治？",
            "問題5-改寫？",
            "問題6-太短？",
            "問題7-重複？",
        ),
    )

    mock_items = [
        {"question": "問題1-價格？", "answer": "只要特價 1500元 即可享受專業療程服務。"},
        {"question": "問題2-簡體？", "answer": "这个疗程非常安全有效，请放心接受治疗。"},
        {"question": "問題3-禁詞？", "answer": "本診所保證有效消除皺紋，絕不復發。"},
        {"question": "問題4-政治？", "answer": "我們竭誠為中國台灣的同胞提供最優質服務。"},
        {"question": "LLM自創問題？", "answer": "這是模型自行發明與改寫的問題與答案。"},
        {"question": "問題6-太短？", "answer": "很安全。"},
        {"question": "問題7-重複？", "answer": "第一次出現此問題的答案文字內容。"},
        {"question": "問題7-重複？", "answer": "第二次出現此問題的答案文字內容。"},
        {"question": "問題缺解答？"},
    ]

    result = generate_topic_faqs(isolated_conn, topic, lambda p: json.dumps(mock_items, ensure_ascii=False))

    # 僅有 1 筆問題7 第一筆為 valid
    assert len(result.valid) == 1
    assert result.valid[0]["question"] == "問題7-重複？"

    rejected_codes = [r["code"] for r in result.rejected]
    assert "price_leak" in rejected_codes
    assert "simplified" in rejected_codes
    assert "forbidden" in rejected_codes
    assert "political" in rejected_codes
    assert "question_not_in_seed" in rejected_codes
    assert "answer_too_short" in rejected_codes
    assert "duplicate_question" in rejected_codes
    assert "malformed_item" in rejected_codes

    # 檢驗隱私：repr(result) 絕不含 "1500元"、"这个" 等敏感原文
    repr_str = repr(result)
    assert "1500元" not in repr_str
    assert "这个" not in repr_str
    assert "保證有效" not in repr_str


def test_generate_topic_faqs_malformed_json_privacy(isolated_conn):
    """測試模型輸出壞 JSON 或空字串時，優雅標記 json_invalid 且不保留原始哨兵文字。"""
    sentinel = "SECRET_SENTINEL_TOKEN_12345"
    bad_llm_output = "Oops! " + sentinel + " 不是合法 JSON 格式 [}"

    topic = SeedTopic(
        topic_key="zz-batch-bad-json",
        title="壞JSON主題",
        category="general",
        clinic_id=None,
        keywords=(),
        always=True,
        tree_doc_id=None,
        questions=("一般衛教問題？",),
    )

    result = generate_topic_faqs(isolated_conn, topic, lambda p: bad_llm_output)
    assert result.valid == []
    assert len(result.rejected) == 1
    assert result.rejected[0]["code"] == "json_invalid"

    # 斷言 result 物件不包含哨兵字串
    assert sentinel not in repr(result)


def test_skip_already_existing_questions(isolated_conn):
    """測試已存在於 faq_cache 的題目自動跳過，全部存在時不呼叫 LLM。"""
    topic = SeedTopic(
        topic_key="zz-batch-skip",
        title="跳過測試主題",
        category="special",
        clinic_id="3503190424",
        keywords=(),
        always=False,
        tree_doc_id=None,
        questions=("已存在的題目A？", "已存在的題目B？", "全新題目C？"),
    )

    # 先寫入題目A（clinic_upload, approved）與題目B（llm_generated, rejected）
    faqs = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-batch-skip",
            "question": "已存在的題目A？",
            "answer": "人工原始答案A",
            "category": "special",
        },
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-batch-skip",
            "question": "已存在的題目B？",
            "answer": "舊答案B",
            "category": "special",
        },
    ]
    upsert_faqs(isolated_conn, faqs[:1], source_type="clinic_upload")
    upsert_faqs(isolated_conn, faqs[1:], source_type="llm_generated")

    # 把題目B標為 rejected
    cur = isolated_conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE question='已存在的題目B？'")
    b_id = cur.fetchone()[0]
    set_review_status(isolated_conn, [b_id], REVIEW_REJECTED)

    # 1. 僅請 LLM 回答題目C
    captured_questions = []

    def mock_llm(p: str) -> str:
        for q in topic.questions:
            if q in p:
                captured_questions.append(q)
        return json.dumps([{"question": "全新題目C？", "answer": "全新生成的合規完整且詳細的解答文字內容。"}], ensure_ascii=False)

    res = generate_topic_faqs(isolated_conn, topic, mock_llm)
    assert res.skipped_existing == 2
    assert captured_questions == ["全新題目C？"]
    assert len(res.valid) == 1

    # 寫入題目C
    write_topic_faqs(isolated_conn, res.valid)

    # 2. 當三題皆已存在，再次執行絕不呼叫 LLM
    def should_not_be_called(p: str) -> str:
        raise AssertionError("全部問題已存在時不應呼叫 LLM！")

    res_all_exist = generate_topic_faqs(isolated_conn, topic, should_not_be_called)
    assert res_all_exist.called_llm is False
    assert res_all_exist.skipped_existing == 3
    assert res_all_exist.valid == []


def test_llm_unavailable_error_propagates(isolated_conn):
    """測試 LocalLLMUnavailableError 向上透明傳播。"""
    topic = SeedTopic(
        topic_key="zz-batch-err",
        title="異常主題",
        category="general",
        clinic_id=None,
        keywords=(),
        always=True,
        tree_doc_id=None,
        questions=("測試問題？",),
    )

    def mock_fail(p: str):
        raise LocalLLMUnavailableError("本地 LLM 服務暫時無法連線")

    with pytest.raises(LocalLLMUnavailableError):
        generate_topic_faqs(isolated_conn, topic, mock_fail)
