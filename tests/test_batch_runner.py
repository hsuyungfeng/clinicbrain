"""
夜間批次執行器與日誌模組測試（Phase 09 BATCH-03 Task 1）。

驗證：
1. dry-run 模式：零 LLM 呼叫（連健康檢查都不呼叫）、零資料庫寫入、規劃輸出正確。
2. LLM 不可用（健康檢查或中途失敗）：優雅跳過並留下日誌，結束碼 0。
3. 成本/GPU 與積壓保護：上限截斷、不餓死其他主題、時間預算、pending 積壓上限。
4. 單筆失敗隔離：單一主題或單一樹失敗不影響同批其他項目。
5. 覆蓋手寫樹事件：被覆蓋的手寫樹觸發 tree_overwrote_handwritten 事件。
6. 日誌隱私：RunLogger 嚴格禁止記錄敏感鍵名 (query/question/answer 等)，日誌不含未過濾問答原文。
7. Logger 靜音與還原：content_loggers_silenced 正確靜音並可還原。
8. 零真實外部請求保證：autouse fixture 封鎖 urllib.request.urlopen。
"""

import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import urllib.request
import pytest

from src.batch.run_log import RunLogger, content_loggers_silenced
from src.batch.runner import (
    BatchConfig,
    BatchPreflightError,
    BatchSummary,
    run_batch,
)
from src.pageindex.db_writer import set_needs_regeneration, upsert_trees
from src.pageindex.faq_writer import upsert_faqs
from src.pageindex.llm_client import LocalLLMUnavailableError
from src.query.search import search_faq_cache


@pytest.fixture(autouse=True)
def _block_external_llm_calls(monkeypatch):
    """防禦性 fixture：保證測試期間絕對不發起任何真實外部網路請求。"""
    def _fail_urlopen(*args, **kwargs):
        raise AssertionError("測試期間禁止呼叫 urllib.request.urlopen 發起真實網路連線！")

    monkeypatch.setattr(urllib.request, "urlopen", _fail_urlopen)


def _get_db_digest(conn: sqlite3.Connection) -> str:
    """計算資料庫完整傾印之 SHA-256 雜湊，證明資料庫完全未變。"""
    hasher = hashlib.sha256()
    for line in conn.iterdump():
        hasher.update(line.encode("utf-8"))
    return hasher.hexdigest()


def _create_test_seed_file(path: Path) -> Path:
    """在指定路徑建立包含 4 個 always=True 的小型種子清單。"""
    data = {
        "schema_version": 1,
        "description": "批次執行器專用小型種子清單",
        "tree_procedure_names": {
            "hifu-lifting": "音波拉提",
            "botox-injection": "肉毒桿菌素注射",
        },
        "topics": [
            {
                "topic_key": "zz-runner-t1",
                "title": "主題1",
                "category": "special",
                "clinic_id": "3503190424",
                "keywords": ["音波"],
                "always": True,
                "tree_doc_id": "hifu-lifting",
                "questions": ["主題1問1？", "主題1問2？"],
            },
            {
                "topic_key": "zz-runner-t2",
                "title": "主題2",
                "category": "special",
                "clinic_id": "3503190424",
                "keywords": ["音波"],
                "always": True,
                "tree_doc_id": "hifu-lifting",
                "questions": ["主題2問1？", "主題2問2？"],
            },
            {
                "topic_key": "zz-runner-t3",
                "title": "主題3",
                "category": "special",
                "clinic_id": "3503190424",
                "keywords": [],
                "always": True,
                "tree_doc_id": None,
                "questions": ["主題3問1？", "主題3問2？"],
            },
            {
                "topic_key": "zz-runner-t4",
                "title": "主題4",
                "category": "special",
                "clinic_id": "3503190424",
                "keywords": [],
                "always": True,
                "tree_doc_id": None,
                "questions": ["主題4問1？", "主題4問2？"],
            },
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _mock_llm_response(prompt: str) -> str:
    """根據 prompt 中的問題動態產生合規 JSON。"""
    if "臨床推理樹" in prompt:
        return json.dumps(
            {
                "pre_op": "術前經過醫師親自評估個人健康狀況與治療目標。",
                "procedure": "療程施作過程精準控制各項參數以確保安全與品質。",
                "post_op_short": "術後一週內加強基礎防曬與保濕照護並避免劇烈運動。",
                "maintenance": "長期規律作息與專業門診追蹤能持續維持良好狀態。",
                "summary_text": "全新批次重建之臨床推理樹指引摘要文字。",
            },
            ensure_ascii=False,
        )

    # FAQ 輸出
    items = []
    lines = prompt.splitlines()
    for line in lines:
        if line.strip().startswith("- 主題"):
            q_text = line.strip()[2:]
            items.append({
                "question": q_text,
                "answer": f"這是針對【{q_text}】的繁體中文專業衛教解答文字說明。",
            })
    return json.dumps(items, ensure_ascii=False)


def test_dry_run_mode(isolated_conn, tmp_path: Path):
    """測試 dry-run 模式：零 LLM 呼叫、零資料庫寫入、資料庫前後 digest 相同。"""
    seed_file = _create_test_seed_file(tmp_path / "seed.json")
    # 標記一棵樹
    set_needs_regeneration(isolated_conn, ["hifu-lifting"], True)
    digest_before = _get_db_digest(isolated_conn)

    def fail_llm(*args, **kwargs):
        raise AssertionError("dry-run 不得呼叫 LLM！")

    def fail_health():
        raise AssertionError("dry-run 不得呼叫健康檢查！")

    logger = RunLogger(tmp_path / "logs", echo=False)
    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        dry_run=True,
        max_faq_topics=2,
        max_trees=3,
    )

    summary = run_batch(
        isolated_conn,
        cfg,
        llm_call=fail_llm,
        health_check=fail_health,
        logger=logger,
    )

    assert summary.status == "dry_run"
    assert summary.faq_topics_planned == 2
    assert summary.trees_planned == 1
    assert _get_db_digest(isolated_conn) == digest_before
    assert any("dry_run_done" in l for l in logger.lines)


def test_llm_unavailable_at_health_check(isolated_conn, tmp_path: Path):
    """測試 LLM 在健康檢查時不可用：優雅跳過、不寫庫、狀態 llm_unavailable。"""
    seed_file = _create_test_seed_file(tmp_path / "seed.json")
    digest_before = _get_db_digest(isolated_conn)

    def mock_health_fail():
        raise LocalLLMUnavailableError("健康檢查連線失敗")

    logger = RunLogger(tmp_path / "logs", echo=False)
    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        dry_run=False,
    )

    summary = run_batch(
        isolated_conn,
        cfg,
        llm_call=lambda p: "[]",
        health_check=mock_health_fail,
        logger=logger,
    )

    assert summary.status == "llm_unavailable"
    assert summary.faq_topics_processed == 0
    assert _get_db_digest(isolated_conn) == digest_before


def test_llm_unavailable_midway(isolated_conn, tmp_path: Path):
    """測試 LLM 在執行第 2 個主題時失敗：保留第 1 個主題寫入，終止後續階段。"""
    seed_file = _create_test_seed_file(tmp_path / "seed.json")
    set_needs_regeneration(isolated_conn, ["hifu-lifting"], True)

    call_count = 0

    def mock_llm_fail_on_second(p: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_llm_response(p)
        raise LocalLLMUnavailableError("中途 LLM 斷線")

    logger = RunLogger(tmp_path / "logs", echo=False)
    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        dry_run=False,
        max_faq_topics=3,
    )

    summary = run_batch(
        isolated_conn,
        cfg,
        llm_call=mock_llm_fail_on_second,
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.status == "llm_unavailable"
    assert summary.faq_topics_processed == 1
    assert summary.faq_inserted > 0
    # 樹階段不應被執行，hifu-lifting 仍維持待重建旗標 1
    cur = isolated_conn.cursor()
    cur.execute("SELECT needs_regeneration FROM page_index_trees WHERE doc_id = 'hifu-lifting'")
    assert cur.fetchone()[0] == 1


def test_resource_limits_and_no_starvation(isolated_conn, tmp_path: Path):
    """測試主題與樹數量上限截斷，且已完全存在的主題不佔名額（不餓死其他主題）。"""
    seed_file = _create_test_seed_file(tmp_path / "seed.json")

    # 先將主題 1 的問題全部預先手動寫入
    faq_t1 = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-runner-t1",
            "question": "主題1問1？",
            "answer": "既有答案",
            "category": "special",
        },
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-runner-t1",
            "question": "主題1問2？",
            "answer": "既有答案",
            "category": "special",
        },
    ]
    upsert_faqs(isolated_conn, faq_t1, source_type="manual")

    processed_topics = []

    def mock_llm(p: str) -> str:
        for t in ["zz-runner-t1", "zz-runner-t2", "zz-runner-t3", "zz-runner-t4"]:
            if t in p:
                processed_topics.append(t)
        return _mock_llm_response(p)

    logger = RunLogger(tmp_path / "logs", echo=False)
    # 設定 max_faq_topics=2：主題 1 應被跳過且不佔名額，被處理的應為主題 2 與主題 3
    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        max_faq_topics=2,
    )

    summary = run_batch(
        isolated_conn,
        cfg,
        llm_call=mock_llm,
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.status == "completed"
    assert summary.faq_topics_processed == 2
    # 主題 1 不應被呼叫 LLM
    assert "zz-runner-t1" not in processed_topics


def test_time_budget_exhaustion(isolated_conn, tmp_path: Path):
    """測試時間預算用盡即停，不發出新的 LLM 呼叫。"""
    seed_file = _create_test_seed_file(tmp_path / "seed.json")

    simulated_time = 0.0

    def mock_clock() -> float:
        nonlocal simulated_time
        simulated_time += 100.0  # 每次前進 100 秒
        return simulated_time

    logger = RunLogger(tmp_path / "logs", echo=False)
    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        time_budget_seconds=150.0,  # 預算 150 秒
        max_faq_topics=4,
    )

    summary = run_batch(
        isolated_conn,
        cfg,
        llm_call=_mock_llm_response,
        health_check=lambda: None,
        logger=logger,
        clock=mock_clock,
    )

    assert summary.status == "budget_exhausted"
    assert summary.faq_topics_processed < 4


def test_single_item_failure_isolation(isolated_conn, tmp_path: Path):
    """測試單一項目生成或寫入失敗不影響同批其他項目。"""
    seed_file = _create_test_seed_file(tmp_path / "seed.json")

    # 主題 1 回傳純文字（非合法 JSON，全部 rejected），主題 2 合規
    def mock_llm_partial_fail(p: str) -> str:
        if "主題1" in p:
            return "不是合法 JSON 純文字"
        return _mock_llm_response(p)

    logger = RunLogger(tmp_path / "logs", echo=False)
    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        max_faq_topics=2,
    )

    summary = run_batch(
        isolated_conn,
        cfg,
        llm_call=mock_llm_partial_fail,
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.status == "completed"
    assert summary.faq_topics_processed == 2
    assert summary.faq_rejected >= 1  # 主題 1 被剔除
    assert summary.faq_inserted > 0  # 主題 2 成功入庫


def test_backlog_protection_skips_faq(isolated_conn, tmp_path: Path):
    """測試 pending 積壓達上限時跳過 FAQ 生成，但仍繼續執行樹重建。"""
    seed_file = _create_test_seed_file(tmp_path / "seed.json")
    set_needs_regeneration(isolated_conn, ["hifu-lifting"], True)

    # 模擬資料庫已積壓 5 筆 pending
    pending_faqs = [
        {
            "clinic_id": "3503190424",
            "topic_key": f"backlog-{i}",
            "question": f"積壓問題{i}？",
            "answer": "答案內容",
            "category": "special",
        }
        for i in range(5)
    ]
    upsert_faqs(isolated_conn, pending_faqs, source_type="llm_generated")

    called_faq_llm = False

    def mock_llm(p: str) -> str:
        nonlocal called_faq_llm
        if "臨床推理樹" not in p:
            called_faq_llm = True
        return _mock_llm_response(p)

    logger = RunLogger(tmp_path / "logs", echo=False)
    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        max_pending=5,  # 設定上限為 5
    )

    summary = run_batch(
        isolated_conn,
        cfg,
        llm_call=mock_llm,
        health_check=lambda: None,
        logger=logger,
    )

    assert called_faq_llm is False
    assert summary.faq_topics_processed == 0
    assert summary.trees_rebuilt == 1


def test_tree_overwrote_handwritten_warning(isolated_conn, tmp_path: Path):
    """測試被重建的手寫樹觸發 tree_overwrote_handwritten 警告事件並記錄統計。"""
    seed_file = _create_test_seed_file(tmp_path / "seed.json")
    set_needs_regeneration(isolated_conn, ["hifu-lifting"], True)

    logger = RunLogger(tmp_path / "logs", echo=False)
    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        skip_faq=True,
    )

    summary = run_batch(
        isolated_conn,
        cfg,
        llm_call=_mock_llm_response,
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.trees_rebuilt == 1
    assert summary.trees_overwrote_handwritten == 1
    assert any("tree_overwrote_handwritten" in l for l in logger.lines)


def test_run_logger_privacy_and_silencing(tmp_path: Path):
    """測試 RunLogger 欄位白名單防禦與 content_loggers_silenced 靜音機制。"""
    logger = RunLogger(tmp_path / "logs", echo=False)

    # 1. 敏感鍵名拒絕
    for bad_key in ["query", "question", "answer", "prompt", "raw", "text", "content"]:
        with pytest.raises(ValueError):
            logger.info("test_event", **{bad_key: "敏感文字"})

    # 2. 測試 content_loggers_silenced
    faq_log = logging.getLogger("src.ingestion.generate_faq")
    prompt_log = logging.getLogger("src.pageindex.prompt_template")

    orig_faq_level = faq_log.level
    orig_prompt_level = prompt_log.level

    with content_loggers_silenced():
        assert faq_log.disabled is True
        assert prompt_log.disabled is True

    # 驗證狀態已還原
    assert faq_log.level == orig_faq_level
    assert prompt_log.level == orig_prompt_level
    assert faq_log.disabled is False
    assert prompt_log.disabled is False


def test_end_to_end_review_gate(isolated_conn, tmp_path: Path):
    """測試端到端閘門：新生成 FAQ 為 pending，search_faq_cache 不可見，審核通過後可見。"""
    from src.pageindex.faq_review import set_review_status
    seed_file = _create_test_seed_file(tmp_path / "seed.json")

    logger = RunLogger(tmp_path / "logs", echo=False)
    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        max_faq_topics=1,
    )

    summary = run_batch(
        isolated_conn,
        cfg,
        llm_call=_mock_llm_response,
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.status == "completed"
    assert summary.faq_inserted > 0

    # 查庫確認皆為 pending
    cur = isolated_conn.cursor()
    cur.execute("SELECT id, question, review_status FROM faq_cache WHERE topic_key = 'zz-runner-t1'")
    rows = cur.fetchall()
    assert len(rows) > 0
    faq_id = rows[0][0]
    q_text = rows[0][1]
    assert all(r[2] == "pending" for r in rows)

    # 檢索不可見
    hits = search_faq_cache(isolated_conn, q_text, clinic_id="3503190424")
    assert not any(h.fields.get("question") == q_text for h in hits)

    # 審核核准
    set_review_status(isolated_conn, [faq_id], "approved")

    # 檢索已可見
    hits_after = search_faq_cache(isolated_conn, q_text, clinic_id="3503190424")
    assert any(h.fields.get("question") == q_text for h in hits_after)


def test_missing_procedure_name_tree_skipped(isolated_conn, tmp_path: Path):
    """測試 doc_id 缺中文名對照的樹會被跳過並記錄 missing_procedure_name。"""
    # 建立一個 tree_procedure_names 為空的種子檔
    seed_file = tmp_path / "empty_names_seed.json"
    data = {
        "schema_version": 1,
        "description": "無中文名對照種子清單",
        "tree_procedure_names": {},
        "topics": [],
    }
    seed_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # 標記既有的 hifu-lifting
    set_needs_regeneration(isolated_conn, ["hifu-lifting"], True)

    logger = RunLogger(tmp_path / "logs", echo=False)
    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        skip_faq=True,
    )

    summary = run_batch(
        isolated_conn,
        cfg,
        llm_call=_mock_llm_response,
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.trees_skipped == 1
    assert any("missing_procedure_name" in l for l in logger.lines)


def test_unmigrated_db_preflight_handling(isolated_conn, tmp_path: Path, monkeypatch):
    """測試未遷移資料庫的前置檢查：非 dry-run 拋例外，dry-run 僅警告。"""
    seed_file = _create_test_seed_file(tmp_path / "seed.json")
    monkeypatch.setattr("src.batch.runner.has_review_status", lambda conn: False)

    # 非 dry-run
    logger1 = RunLogger(tmp_path / "logs1", echo=False)
    cfg1 = BatchConfig(seed_path=seed_file, snapshot_dir=tmp_path / "s1", dry_run=False)
    with pytest.raises(BatchPreflightError, match="scripts/migrate_faq_review_status.py"):
        run_batch(isolated_conn, cfg1, llm_call=lambda p: "", health_check=lambda: None, logger=logger1)

    # dry-run
    logger2 = RunLogger(tmp_path / "logs2", echo=False)
    cfg2 = BatchConfig(seed_path=seed_file, snapshot_dir=tmp_path / "s2", dry_run=True)
    summary2 = run_batch(isolated_conn, cfg2, llm_call=lambda p: "", health_check=lambda: None, logger=logger2)
    assert summary2.status == "dry_run"
    assert any("unmigrated_database_dry_run" in l for l in logger2.lines)


def test_run_logger_filename_sequence(tmp_path: Path):
    """測試同秒建立 RunLogger 時日誌檔名自動追加序號避免覆蓋。"""
    from datetime import datetime
    fixed_now = datetime(2026, 10, 1, 12, 0, 0)

    log1 = RunLogger(tmp_path / "logs", echo=False, now=lambda: fixed_now)
    log2 = RunLogger(tmp_path / "logs", echo=False, now=lambda: fixed_now)
    log3 = RunLogger(tmp_path / "logs", echo=False, now=lambda: fixed_now)

    assert log1.path.name == "nightly-20261001-120000.log"
    assert log2.path.name == "nightly-20261001-120000-2.log"
    assert log3.path.name == "nightly-20261001-120000-3.log"

    log1.close()
    log2.close()
    log3.close()

