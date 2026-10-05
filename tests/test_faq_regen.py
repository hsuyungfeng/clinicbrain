"""
tests/test_faq_regen.py - 被駁回 FAQ 人工標記重新生成與審核增強測試 (Phase 12 DEBT-03)

驗證：
1. mark_for_regeneration 限制（僅 rejected llm_generated 列）與 clear_regeneration_flag / regen_marked_rows
2. existing_questions 排除標記列 (exclude_regen_marked=True)
3. 重生成三種結果：成功 (regenerated)、相同 (unchanged)、違規拒絕 (failed)
4. runner 優先規劃標記主題與 BatchSummary 統計
5. set_review_status 審核核准之劑量處方與就醫警訊檢查
"""

import json
from pathlib import Path
import sqlite3
import pytest

from src.batch.topic_sources import SeedTopic
from src.pageindex.faq_review import (
    REVIEW_APPROVED,
    REVIEW_PENDING,
    REVIEW_REJECTED,
    set_review_status,
)
from src.pageindex.faq_writer import upsert_faqs


def test_mark_for_regeneration_restrictions(isolated_conn: sqlite3.Connection):
    """
    驗證 mark_for_regeneration 之安全限制：
    - 僅 rejected + llm_generated 列可被標記為 needs_regeneration=1
    - clinic_upload (approved) 與 manual 列回報 not_llm_generated，旗標仍為 0
    - pending 之 llm 列回報 not_rejected
    - 不存在 id 回報 not_found
    - 已標記列再次標記回報 already_marked
    """
    from src.pageindex.faq_review import mark_for_regeneration

    # 1. 建立 rejected llm_generated 列
    faqs_llm = [
        {
            "clinic_id": "3503190424",
            "topic_key": "test-topic-regen",
            "question": "測試重生成問題1？",
            "answer": "這是舊答案，等待重新生成。",
            "category": "special",
        },
        {
            "clinic_id": "3503190424",
            "topic_key": "test-topic-regen",
            "question": "測試重生成問題2（待核准）？",
            "answer": "這是待核准答案。",
            "category": "special",
        },
    ]
    upsert_faqs(isolated_conn, faqs_llm, source_type="llm_generated")
    cur = isolated_conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE question = ?", ("測試重生成問題1？",))
    rej_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM faq_cache WHERE question = ?", ("測試重生成問題2（待核准）？",))
    pending_id = cur.fetchone()[0]

    # 將第 1 題駁回
    set_review_status(isolated_conn, [rej_id], REVIEW_REJECTED)

    # 2. 建立 clinic_upload (approved) 列
    faqs_upload = [
        {
            "clinic_id": "3503190424",
            "topic_key": "test-topic-regen",
            "question": "診所上傳問題？",
            "answer": "診所上傳之權威答案。",
            "category": "special",
        }
    ]
    upsert_faqs(isolated_conn, faqs_upload, source_type="clinic_upload")
    cur.execute("SELECT id FROM faq_cache WHERE question = ?", ("診所上傳問題？",))
    upload_id = cur.fetchone()[0]

    # 3. 建立 manual 列
    faqs_manual = [
        {
            "clinic_id": "3503190424",
            "topic_key": "test-topic-regen",
            "question": "人工手寫問題？",
            "answer": "人工手寫之權威答案。",
            "category": "special",
        }
    ]
    upsert_faqs(isolated_conn, faqs_manual, source_type="manual")
    cur.execute("SELECT id FROM faq_cache WHERE question = ?", ("人工手寫問題？",))
    manual_id = cur.fetchone()[0]

    # 4. 批次執行標記
    res = mark_for_regeneration(isolated_conn, [rej_id, upload_id, manual_id, pending_id, 999999])

    assert res.changed == [rej_id]
    skipped_map = dict(res.skipped)
    assert skipped_map[upload_id] == "not_llm_generated"
    assert skipped_map[manual_id] == "not_llm_generated"
    assert skipped_map[pending_id] == "not_rejected"
    assert skipped_map[999999] == "not_found"

    # 驗證資料庫狀態：rej_id needs_regeneration=1, content_version 未變, review_status 仍為 rejected
    cur.execute("SELECT needs_regeneration, content_version, review_status FROM faq_cache WHERE id = ?", (rej_id,))
    needs_reg, c_ver, rev_stat = cur.fetchone()
    assert needs_reg == 1
    assert c_ver == 1
    assert rev_stat == REVIEW_REJECTED

    # 診所手寫與上傳列旗標仍為 0
    cur.execute("SELECT needs_regeneration FROM faq_cache WHERE id IN (?, ?)", (upload_id, manual_id))
    for r in cur.fetchall():
        assert r[0] == 0

    # 5. 重複標記已標記列 -> already_marked
    res2 = mark_for_regeneration(isolated_conn, [rej_id])
    assert res2.changed == []
    assert res2.skipped == [(rej_id, "already_marked")]


def test_clear_regeneration_flag_and_regen_marked_rows(isolated_conn: sqlite3.Connection):
    """驗證 clear_regeneration_flag 與 regen_marked_rows 函式。"""
    from src.pageindex.faq_review import (
        clear_regeneration_flag,
        mark_for_regeneration,
        regen_marked_rows,
    )

    faqs = [
        {
            "clinic_id": "3503190424",
            "topic_key": "test-clear-flag",
            "question": "待清旗標問題？",
            "answer": "待清旗標答案。",
            "category": "special",
        }
    ]
    upsert_faqs(isolated_conn, faqs, source_type="llm_generated")
    cur = isolated_conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE question = ?", ("待清旗標問題？",))
    faq_id = cur.fetchone()[0]

    set_review_status(isolated_conn, [faq_id], REVIEW_REJECTED)
    mark_for_regeneration(isolated_conn, [faq_id])

    # 查詢標記列
    marked = regen_marked_rows(isolated_conn)
    marked_ids = [m["id"] for m in marked]
    assert faq_id in marked_ids
    target = next(m for m in marked if m["id"] == faq_id)
    assert target["clinic_id"] == "3503190424"
    assert target["topic_key"] == "test-clear-flag"
    assert target["question"] == "待清旗標問題？"

    # 清除旗標
    cleared = clear_regeneration_flag(isolated_conn, [faq_id, 888888])
    assert cleared == 1

    # 再次查詢標記列已無此列
    marked_after = regen_marked_rows(isolated_conn)
    assert faq_id not in [m["id"] for m in marked_after]

    cur.execute("SELECT needs_regeneration, review_status FROM faq_cache WHERE id = ?", (faq_id,))
    row = cur.fetchone()
    assert row[0] == 0
    assert row[1] == REVIEW_REJECTED


def test_existing_questions_exclude_regen_marked(isolated_conn: sqlite3.Connection):
    """
    驗證 existing_questions 的 exclude_regen_marked 參數：
    - 預設 False：含所有已存在問題（包含被標記重生成的 rejected 題）
    - 為 True：排除 needs_regeneration=1 AND llm_generated AND rejected 的題目
    - 但依然包含未標記的 rejected 與 raw UPDATE 設旗標的 clinic_upload 列
    """
    from src.batch.faq_generator import existing_questions
    from src.pageindex.faq_review import mark_for_regeneration

    topic_key = "test-existing-q"
    clinic_id = "3503190424"

    # 1. 被標記重生成的 rejected llm 列
    upsert_faqs(
        isolated_conn,
        [{"clinic_id": clinic_id, "topic_key": topic_key, "question": "Q1_marked_rej？", "answer": "A1", "category": "special"}],
        source_type="llm_generated",
    )
    # 2. 未標記的 rejected llm 列
    upsert_faqs(
        isolated_conn,
        [{"clinic_id": clinic_id, "topic_key": topic_key, "question": "Q2_unmarked_rej？", "answer": "A2", "category": "special"}],
        source_type="llm_generated",
    )
    # 3. clinic_upload 列（模擬舊庫旗標殘留 needs_regeneration=1）
    upsert_faqs(
        isolated_conn,
        [{"clinic_id": clinic_id, "topic_key": topic_key, "question": "Q3_upload_flag1？", "answer": "A3", "category": "special"}],
        source_type="clinic_upload",
    )

    cur = isolated_conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE question = ?", ("Q1_marked_rej？",))
    id1 = cur.fetchone()[0]
    cur.execute("SELECT id FROM faq_cache WHERE question = ?", ("Q2_unmarked_rej？",))
    id2 = cur.fetchone()[0]

    set_review_status(isolated_conn, [id1, id2], REVIEW_REJECTED)
    mark_for_regeneration(isolated_conn, [id1])

    # 模擬 clinic_upload 異常旗標
    cur.execute("UPDATE faq_cache SET needs_regeneration = 1 WHERE question = ?", ("Q3_upload_flag1？",))
    isolated_conn.commit()

    # 預設 exclude_regen_marked=False
    all_q = existing_questions(isolated_conn, clinic_id, topic_key)
    assert {"Q1_marked_rej？", "Q2_unmarked_rej？", "Q3_upload_flag1？"}.issubset(all_q)

    # exclude_regen_marked=True
    filtered_q = existing_questions(isolated_conn, clinic_id, topic_key, exclude_regen_marked=True)
    assert "Q1_marked_rej？" not in filtered_q
    assert "Q2_unmarked_rej？" in filtered_q
    assert "Q3_upload_flag1？" in filtered_q


def test_regeneration_outcome_success(isolated_conn: sqlite3.Connection):
    """
    重生成結果 A (成功)：
    - generate_topic_faqs 與 write_topic_faqs 執行
    - 同一 id，content_version 1 -> 2，review_status 回到 pending，needs_regeneration 回到 0
    - settle_regen_flags 回傳 {"regenerated": 1, "unchanged": 0, "failed": 0}
    """
    from src.batch.faq_generator import (
        generate_topic_faqs,
        settle_regen_flags,
        write_topic_faqs,
    )
    from src.pageindex.faq_review import mark_for_regeneration

    topic = SeedTopic(
        topic_key="test-regen-success",
        title="重生成成功測試",
        category="special",
        clinic_id="3503190424",
        keywords=(),
        always=True,
        tree_doc_id=None,
        questions=("測試成功重生成題目？",),
    )

    # 初始寫入並駁回
    upsert_faqs(
        isolated_conn,
        [{"clinic_id": topic.clinic_id, "topic_key": topic.topic_key, "question": topic.questions[0], "answer": "舊答案不合格", "category": topic.category}],
        source_type="llm_generated",
    )
    cur = isolated_conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE question = ?", (topic.questions[0],))
    faq_id = cur.fetchone()[0]

    set_review_status(isolated_conn, [faq_id], REVIEW_REJECTED)
    mark_for_regeneration(isolated_conn, [faq_id])

    # Mock LLM 回覆合規的新答案
    def mock_llm(_prompt: str) -> str:
        return json.dumps([
            {
                "question": "測試成功重生成題目？",
                "answer": "這是全面修改後的合格衛教新答案，請遵照醫囑按時回診追蹤。",
            }
        ], ensure_ascii=False)

    gen_res = generate_topic_faqs(isolated_conn, topic, llm_call=mock_llm)
    assert len(gen_res.valid) == 1
    assert "測試成功重生成題目？" in gen_res.regen_questions

    write_res = write_topic_faqs(isolated_conn, topic, gen_res)
    assert write_res.updated == 1

    settle = settle_regen_flags(isolated_conn, topic, gen_res)
    assert settle == {"regenerated": 1, "unchanged": 0, "failed": 0}

    # 斷言資料庫狀態
    cur.execute(
        "SELECT id, content_version, review_status, needs_regeneration, answer FROM faq_cache WHERE question = ?",
        (topic.questions[0],),
    )
    row = cur.fetchone()
    assert row[0] == faq_id
    assert row[1] == 2
    assert row[2] == REVIEW_PENDING
    assert row[3] == 0
    assert "這是全面修改後的合格衛教新答案" in row[4]


def test_regeneration_outcome_unchanged(isolated_conn: sqlite3.Connection):
    """
    重生成結果 B (答案相同)：
    - Mock LLM 回覆與舊答案完全相同
    - write 回傳 unchanged
    - settle_regen_flags 回傳 unchanged==1，旗標被清除為 0，列仍維持 rejected
    - 後續再跑 generate_topic_faqs 時不呼叫 LLM (called_llm False)
    """
    from src.batch.faq_generator import (
        generate_topic_faqs,
        settle_regen_flags,
        write_topic_faqs,
    )
    from src.pageindex.faq_review import mark_for_regeneration

    old_answer = "這是舊答案完全不變，請遵照醫囑按時回診追蹤。"
    topic = SeedTopic(
        topic_key="test-regen-unchanged",
        title="重生成相同測試",
        category="special",
        clinic_id="3503190424",
        keywords=(),
        always=True,
        tree_doc_id=None,
        questions=("測試答案相同題目？",),
    )

    upsert_faqs(
        isolated_conn,
        [{"clinic_id": topic.clinic_id, "topic_key": topic.topic_key, "question": topic.questions[0], "answer": old_answer, "category": topic.category}],
        source_type="llm_generated",
    )
    cur = isolated_conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE question = ?", (topic.questions[0],))
    faq_id = cur.fetchone()[0]

    set_review_status(isolated_conn, [faq_id], REVIEW_REJECTED)
    mark_for_regeneration(isolated_conn, [faq_id])

    def mock_llm_same(_prompt: str) -> str:
        return json.dumps([{"question": topic.questions[0], "answer": old_answer}], ensure_ascii=False)

    gen_res = generate_topic_faqs(isolated_conn, topic, llm_call=mock_llm_same)
    assert len(gen_res.valid) == 1
    write_res = write_topic_faqs(isolated_conn, topic, gen_res)
    assert write_res.unchanged == 1

    settle = settle_regen_flags(isolated_conn, topic, gen_res)
    assert settle == {"regenerated": 0, "unchanged": 1, "failed": 0}

    # 斷言旗標已被清為 0，狀態維持 rejected
    cur.execute("SELECT needs_regeneration, review_status FROM faq_cache WHERE id = ?", (faq_id,))
    row = cur.fetchone()
    assert row[0] == 0
    assert row[1] == REVIEW_REJECTED

    # 再次執行 generate_topic_faqs 時，因旗標已為 0 且列已存在，跳過呼叫 LLM
    gen_res2 = generate_topic_faqs(isolated_conn, topic, llm_call=mock_llm_same)
    assert gen_res2.called_llm is False


def test_regeneration_outcome_validation_failed(isolated_conn: sqlite3.Connection):
    """
    重生成結果 C (驗證器拒絕)：
    - Mock LLM 回覆踩劑量處方違規（例如「建議吃止痛藥 500mg」）
    - generate_topic_faqs 判定為 rejected
    - settle_regen_flags 回傳 failed==1，旗標清除為 0，原列內容與狀態未變
    """
    from src.batch.faq_generator import (
        generate_topic_faqs,
        settle_regen_flags,
        write_topic_faqs,
    )
    from src.pageindex.faq_review import mark_for_regeneration

    old_answer = "這是合法的原答案，請遵照專業醫師之指示。"
    topic = SeedTopic(
        topic_key="test-regen-failed",
        title="重生成失敗測試",
        category="special",
        clinic_id="3503190424",
        keywords=(),
        always=True,
        tree_doc_id=None,
        questions=("測試驗證拒絕題目？",),
    )

    upsert_faqs(
        isolated_conn,
        [{"clinic_id": topic.clinic_id, "topic_key": topic.topic_key, "question": topic.questions[0], "answer": old_answer, "category": topic.category}],
        source_type="llm_generated",
    )
    cur = isolated_conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE question = ?", (topic.questions[0],))
    faq_id = cur.fetchone()[0]

    set_review_status(isolated_conn, [faq_id], REVIEW_REJECTED)
    mark_for_regeneration(isolated_conn, [faq_id])

    def mock_llm_bad(_prompt: str) -> str:
        return json.dumps([
            {
                "question": topic.questions[0],
                "answer": "若疼痛難耐建議吃止痛藥 500mg 每日三次緩解症狀。",
            }
        ], ensure_ascii=False)

    gen_res = generate_topic_faqs(isolated_conn, topic, llm_call=mock_llm_bad)
    assert len(gen_res.rejected) == 1
    assert len(gen_res.valid) == 0

    write_res = write_topic_faqs(isolated_conn, topic, gen_res)
    assert write_res.inserted == 0 and write_res.updated == 0

    settle = settle_regen_flags(isolated_conn, topic, gen_res)
    assert settle == {"regenerated": 0, "unchanged": 0, "failed": 1}

    # 斷言旗標已被清為 0，原列答案與狀態未變
    cur.execute("SELECT needs_regeneration, review_status, answer FROM faq_cache WHERE id = ?", (faq_id,))
    row = cur.fetchone()
    assert row[0] == 0
    assert row[1] == REVIEW_REJECTED
    assert row[2] == old_answer


def test_runner_prioritizes_marked_topic(isolated_conn: sqlite3.Connection, tmp_path: Path):
    """
    驗證 runner 執行時：
    - 非 always 且無熱門統計之主題，若含被標記列，排在最前面優先規劃
    - prompt 只包含被標記題，未被標記的 rejected 題不生成
    - summary 包含 faq_regen_regenerated == 1
    - 無標記時 summary 三個 faq_regen_* 皆為 0
    """
    from src.batch.runner import BatchConfig, run_batch
    from src.pageindex.faq_review import mark_for_regeneration

    # 建立測試用種子清單，含一個 always=False 主題
    topic_key = "special-not-always"
    clinic_id = "3503190424"
    seed_data = {
        "schema_version": 1,
        "description": "runner 測試清單",
        "tree_procedure_names": {},
        "topics": [
            {
                "topic_key": topic_key,
                "title": "非常駐主題",
                "category": "special",
                "clinic_id": clinic_id,
                "keywords": [],
                "always": False,
                "tree_doc_id": None,
                "questions": ["問題A標記？", "問題B未標記？"],
            }
        ],
    }
    seed_file = tmp_path / "seeds_runner.json"
    seed_file.write_text(json.dumps(seed_data, ensure_ascii=False), encoding="utf-8")

    # 在資料庫中建立這兩題，皆設為 rejected
    upsert_faqs(
        isolated_conn,
        [
            {"clinic_id": clinic_id, "topic_key": topic_key, "question": "問題A標記？", "answer": "答案A舊", "category": "special"},
            {"clinic_id": clinic_id, "topic_key": topic_key, "question": "問題B未標記？", "answer": "答案B舊", "category": "special"},
        ],
        source_type="llm_generated",
    )
    cur = isolated_conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE question = ?", ("問題A標記？",))
    id_a = cur.fetchone()[0]
    cur.execute("SELECT id FROM faq_cache WHERE question = ?", ("問題B未標記？",))
    id_b = cur.fetchone()[0]

    set_review_status(isolated_conn, [id_a, id_b], REVIEW_REJECTED)
    # 僅標記問題 A
    mark_for_regeneration(isolated_conn, [id_a])

    prompt_received = []

    def mock_llm_call(prompt: str) -> str:
        prompt_received.append(prompt)
        return json.dumps([
            {"question": "問題A標記？", "answer": "問題A全新衛教合規解答，遵照醫囑回診。"}
        ], ensure_ascii=False)

    cfg = BatchConfig(
        seed_path=str(seed_file),
        snapshot_dir=tmp_path / "snapshots",
        max_faq_topics=5,
    )
    from src.batch.run_log import RunLogger

    logger = RunLogger(tmp_path / "logs", echo=False)
    summary = run_batch(
        conn=isolated_conn,
        cfg=cfg,
        llm_call=mock_llm_call,
        health_check=lambda: None,
        logger=logger,
    )

    # 斷言該主題被成功規劃與重生成
    assert summary.faq_topics_planned == 1
    assert summary.faq_regen_regenerated == 1
    assert summary.faq_regen_unchanged == 0
    assert summary.faq_regen_failed == 0

    # 斷言 prompt 中只含標記題，絕不含未標記的 rejected 題 B
    assert len(prompt_received) == 1
    assert "問題A標記？" in prompt_received[0]
    assert "問題B未標記？" not in prompt_received[0]

    # 無標記時再次執行，該 non-always 主題不會被規劃（0 planned），三個 faq_regen_* 皆為 0
    logger2 = RunLogger(tmp_path / "logs2", echo=False)
    summary2 = run_batch(
        conn=isolated_conn,
        cfg=cfg,
        llm_call=mock_llm_call,
        health_check=lambda: None,
        logger=logger2,
    )
    assert summary2.faq_topics_planned == 0
    assert summary2.faq_regen_regenerated == 0
    assert summary2.faq_regen_unchanged == 0
    assert summary2.faq_regen_failed == 0


def test_set_review_status_new_validations(isolated_conn: sqlite3.Connection):
    """
    驗證 set_review_status 核准前驗證：
    1. llm 列 answer 含「建議吃止痛藥」-> validation_failed 包含「用藥劑量」
    2. 合規答案核准成功
    3. general 列答案無就醫警訊：
       - enforce_general_warning=False（預設）：核准成功（向後相容）
       - enforce_general_warning=True：skipped 且原因包含「何時該就醫」
    4. special 列即使 enforce_general_warning=True 也不要求警訊
    """
    # 1. 建立包含用藥處方違規的 llm 列（手動 INSERT 模擬待審核）
    cur = isolated_conn.cursor()
    cur.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status, content_version)
        VALUES ('3503190424', 'test-val', '頭痛該怎麼辦？', '若疼痛難耐建議吃止痛藥 500mg 每日三次。', 'special', 'llm_generated', 'pending', 1)
        """
    )
    dosage_id = cur.lastrowid

    # 嘗試核准 -> 應被第 5 層劑量攔截器阻擋
    res_dosage = set_review_status(isolated_conn, [dosage_id], REVIEW_APPROVED)
    assert res_dosage.changed == []
    assert len(res_dosage.skipped) == 1
    skip_reason = res_dosage.skipped[0][1]
    assert "validation_failed" in skip_reason
    assert "用藥劑量" in skip_reason

    # 2. 建立 general 列（無就醫警訊）
    cur.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status, content_version)
        VALUES (NULL, 'common-cold-home-care', '感冒如何照護？', '感冒期間請多喝溫開水，並保持充分睡眠與休息。', 'general', 'llm_generated', 'pending', 1)
        """
    )
    general_id = cur.lastrowid

    # 預設 enforce_general_warning=False -> 核准成功
    res_gen_default = set_review_status(isolated_conn, [general_id], REVIEW_APPROVED)
    assert res_gen_default.changed == [general_id]

    # 將狀態改回 pending
    set_review_status(isolated_conn, [general_id], REVIEW_PENDING)

    # enforce_general_warning=True -> 阻擋，因缺少警訊
    res_gen_enforce = set_review_status(isolated_conn, [general_id], REVIEW_APPROVED, enforce_general_warning=True)
    assert res_gen_enforce.changed == []
    assert len(res_gen_enforce.skipped) == 1
    assert "何時該就醫" in res_gen_enforce.skipped[0][1]

    # 3. 建立 special 列（無就醫警訊）
    cur.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status, content_version)
        VALUES ('3503190424', 'special-val', '術後保養？', '術後請加強保濕與防曬，避免使用刺激性保養品。', 'special', 'llm_generated', 'pending', 1)
        """
    )
    special_id = cur.lastrowid

    # special 列即使 enforce_general_warning=True 也不要求警訊
    res_spec_enforce = set_review_status(isolated_conn, [special_id], REVIEW_APPROVED, enforce_general_warning=True)
    assert res_spec_enforce.changed == [special_id]
