"""
57-R 規格測試：夜間動畫草擬階段 (tests/test_visual_autodraft_nightly.py)。

測試範圍：
1. find_trees_missing_visual_assets：有無對應列、limit、doc_id 排序穩定。
2. autodraft_tree_to_pending：成功時狀態恆為 pending；既有列時回傳 skipped 且不覆寫；LLM 例外時回傳 failed。
3. runner：預設關閉時不呼叫任何 LLM；啟用且 LLM 不可用時回傳 llm_unavailable；單筆失敗不中斷。
4. 嚴格驗證：絕不產生任何 review_status='approved' 之草稿。
5. 隔離保證：所有測試使用臨時資料庫與 mock LLM，絕不存取正式 clinic.db，無網路呼叫。
"""

import json
from pathlib import Path
import sqlite3
import pytest
from unittest.mock import Mock

from scripts.migrate_visual_assets import apply_visual_schema
from src.batch.run_log import RunLogger
from src.batch.runner import BatchConfig, BatchSummary, run_batch
from src.pageindex.llm_client import LocalLLMUnavailableError
from src.visual.autodraft import (
    autodraft_tree_to_pending,
    find_trees_missing_visual_assets,
    normalize_tree_topic_key,
)


def _init_test_db(db_path: Path) -> sqlite3.Connection:
    """建立完全隔離之臨時測試資料庫，套用 visual_assets 與 page_index_trees 結構。"""
    apply_visual_schema(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS clinic_info (
            clinic_id TEXT PRIMARY KEY,
            name TEXT
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS page_index_trees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id TEXT,
            doc_id TEXT UNIQUE NOT NULL,
            title TEXT,
            summary_text TEXT,
            pre_op TEXT,
            procedure TEXT,
            post_op_short TEXT,
            maintenance TEXT,
            source_type TEXT DEFAULT 'manual',
            content_version INTEGER DEFAULT 1,
            review_status TEXT DEFAULT 'pending'
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS faq_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id TEXT,
            category TEXT,
            topic_key TEXT,
            question TEXT,
            answer TEXT,
            source_type TEXT DEFAULT 'manual',
            review_status TEXT DEFAULT 'pending',
            needs_regeneration INTEGER DEFAULT 0
        );
        """
    )
    conn.commit()
    return conn


from tests.test_visual_autodraft import VALID_MODEL_JSON


def _make_dummy_ir_json(topic_key: str = "tree-test", title: str = "海芙音波緊緻原理") -> str:
    """產生合法合規之 3 幕 Typed IR JSON 字串。"""
    data = json.loads(VALID_MODEL_JSON)
    data["topic_key"] = topic_key
    data["title"] = title
    return "```json\n" + json.dumps(data, ensure_ascii=False) + "\n```"


# ----------------------------------------------------------------------
# 1. find_trees_missing_visual_assets 測試
# ----------------------------------------------------------------------


def test_find_trees_missing_visual_assets(tmp_path: Path):
    """驗證缺失樹篩選：有無對應列、未核准樹排除、依 doc_id 穩定升冪排序、limit 截斷。"""
    conn = _init_test_db(tmp_path / "test1.db")

    # 插入 4 棵樹：
    # tree-c (approved)
    # tree-a (approved) -> 在 visual_assets 中已有資產
    # tree-b (approved)
    # tree-d (pending) -> 未核准，不應入選
    conn.execute(
        """
        INSERT INTO page_index_trees (doc_id, title, summary_text, review_status) VALUES
        ('c-doc', 'C療程', 'C療程原理說明', 'approved'),
        ('a-doc', 'A療程', 'A療程原理說明', 'approved'),
        ('b-doc', 'B療程', 'B療程原理說明', 'approved'),
        ('d-doc', 'D療程', 'D療程原理說明', 'pending');
        """
    )
    # 為 a-doc 建立視覺資產
    conn.execute(
        """
        INSERT INTO visual_assets (topic_key, title, keywords, ir_json, source_type, review_status, content_version)
        VALUES ('tree-a-doc', 'A療程', '["A"]', '{}', 'manual', 'pending', 1);
        """
    )
    conn.commit()

    # 查詢全部缺失樹
    missing = find_trees_missing_visual_assets(conn)
    # 應排除 a-doc (已有) 與 d-doc (未核准)，僅剩 b-doc 與 c-doc
    doc_ids = [t["doc_id"] for t in missing]
    assert doc_ids == ["b-doc", "c-doc"], f"必須依 doc_id 升冪排序，預期 ['b-doc', 'c-doc']，得到 {doc_ids}"

    # 測試 limit 限制
    missing_limit1 = find_trees_missing_visual_assets(conn, limit=1)
    assert len(missing_limit1) == 1
    assert missing_limit1[0]["doc_id"] == "b-doc"

    # 測試 limit=0
    assert find_trees_missing_visual_assets(conn, limit=0) == []

    conn.close()


# ----------------------------------------------------------------------
# 2. autodraft_tree_to_pending 測試
# ----------------------------------------------------------------------


def test_autodraft_tree_to_pending_success_and_never_approved(tmp_path: Path):
    """驗證生成草稿：review_status 恆為 pending，絕非 approved，且 source_type='llm_generated'。"""
    conn = _init_test_db(tmp_path / "test2.db")
    tree = {
        "id": 1,
        "doc_id": "pico-laser",
        "title": "皮秒雷射",
        "summary_text": "皮秒雷射擊碎黑色素",
        "review_status": "approved",
    }

    fake_llm = Mock(return_value=_make_dummy_ir_json(topic_key="tree-pico-laser", title="皮秒雷射原理"))

    res = autodraft_tree_to_pending(conn, tree, fake_llm)
    assert res["status"] == "ok"
    assert res["code"] == "ok"
    assert res["topic_key"] == "tree-pico-laser"

    # 檢查資料庫記錄
    row = conn.execute(
        "SELECT topic_key, review_status, source_type FROM visual_assets WHERE topic_key = 'tree-pico-laser'"
    ).fetchone()
    assert row is not None
    assert row[0] == "tree-pico-laser"
    assert row[1] == "pending", "草稿狀態必須為 pending！"
    assert row[2] == "llm_generated", "source_type 必須為 llm_generated！"

    # 嚴格斷言：全庫不存在任何 approved 列
    approved_count = conn.execute("SELECT COUNT(*) FROM visual_assets WHERE review_status = 'approved'").fetchone()[0]
    assert approved_count == 0, "絕不允許存在 approved 之視覺資產！"

    conn.close()


def test_autodraft_tree_to_pending_skipped_if_exists(tmp_path: Path):
    """驗證同一 topic_key 已存在列時直接 skipped 且不覆寫。"""
    conn = _init_test_db(tmp_path / "test3.db")
    # 預先插入既有資產
    conn.execute(
        """
        INSERT INTO visual_assets (topic_key, title, keywords, ir_json, source_type, review_status, content_version)
        VALUES ('tree-botox', '既有肉毒標題', '["肉毒"]', '{"scenes":[]}', 'manual', 'pending', 1);
        """
    )
    conn.commit()

    tree = {
        "id": 2,
        "doc_id": "botox",
        "title": "新肉毒標題（不應被寫入）",
        "summary_text": "肉毒桿菌素除皺",
        "review_status": "approved",
    }

    fake_llm = Mock(return_value=_make_dummy_ir_json(topic_key="tree-botox"))
    res = autodraft_tree_to_pending(conn, tree, fake_llm)

    assert res["status"] == "skipped"
    assert res["code"] == "already_exists"
    assert fake_llm.call_count == 0, "已存在列時不應呼叫 LLM！"

    # 驗證既有資料未被修改
    row = conn.execute("SELECT title FROM visual_assets WHERE topic_key = 'tree-botox'").fetchone()
    assert row[0] == "既有肉毒標題"

    conn.close()


def test_autodraft_tree_to_pending_llm_exceptions(tmp_path: Path):
    """驗證 LLM 例外與不可用時安全捕捉轉為 failed，不崩潰外部程式。"""
    conn = _init_test_db(tmp_path / "test4.db")
    tree = {
        "id": 3,
        "doc_id": "hifu-lift",
        "title": "音波拉提",
        "summary_text": "聚焦音波緊緻",
        "review_status": "approved",
    }

    # 1. 一般例外（如 RuntimeError）
    err_llm = Mock(side_effect=RuntimeError("GPU OOM"))
    res1 = autodraft_tree_to_pending(conn, tree, err_llm)
    assert res1["status"] == "failed"

    # 2. LocalLLMUnavailableError
    unavail_llm = Mock(side_effect=LocalLLMUnavailableError("LLM server offline"))
    res2 = autodraft_tree_to_pending(conn, tree, unavail_llm)
    assert res2["status"] == "failed"
    assert res2["code"] == "llm_unavailable"

    # 驗證沒有殘留髒資料
    count = conn.execute("SELECT COUNT(*) FROM visual_assets WHERE topic_key = 'tree-hifu-lift'").fetchone()[0]
    assert count == 0

    conn.close()


# ----------------------------------------------------------------------
# 3. runner 整合測試
# ----------------------------------------------------------------------


def test_runner_visual_autodraft_disabled_by_default(tmp_path: Path):
    """驗證預設 enable_visual_autodraft=False 時完全跳過該階段，不呼叫 LLM。"""
    conn = _init_test_db(tmp_path / "test_runner1.db")
    conn.execute(
        """
        INSERT INTO page_index_trees (doc_id, title, summary_text, review_status) VALUES
        ('tree1', '樹1', '說明1', 'approved');
        """
    )
    conn.commit()

    log_dir = tmp_path / "logs"
    logger = RunLogger(log_dir, echo=False)
    fake_seed = tmp_path / "faq_seeds.json"
    fake_seed.write_text('{"schema_version": 1, "topics": [], "tree_procedure_names": {}}', encoding="utf-8")

    cfg = BatchConfig(
        seed_path=fake_seed,
        snapshot_dir=tmp_path / "snapshots",
        dry_run=False,
        skip_faq=True,
        skip_trees=True,
        enable_soap_distill=False,
        enable_patient_prefill=False,
        enable_gap_check=False,
        # enable_visual_autodraft 預設為 False
    )
    assert cfg.enable_visual_autodraft is False

    fake_llm = Mock(return_value=_make_dummy_ir_json())
    summary = run_batch(
        conn,
        cfg,
        llm_call=fake_llm,
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.status == "completed"
    assert summary.visual_autodraft_planned == 0
    assert summary.visual_autodraft_generated == 0
    assert summary.visual_autodraft_failed == 0
    assert fake_llm.call_count == 0

    conn.close()


def test_runner_visual_autodraft_enabled_flow(tmp_path: Path):
    """驗證啟用 enable_visual_autodraft=True 時正常草擬缺漏樹，並受 max_visual_autodraft 限制。"""
    conn = _init_test_db(tmp_path / "test_runner2.db")
    conn.execute(
        """
        INSERT INTO page_index_trees (doc_id, title, summary_text, review_status) VALUES
        ('tree-one', '療程一', '說明一', 'approved'),
        ('tree-two', '療程二', '說明二', 'approved'),
        ('tree-three', '療程三', '說明三', 'approved');
        """
    )
    conn.commit()

    log_dir = tmp_path / "logs"
    logger = RunLogger(log_dir, echo=False)
    fake_seed = tmp_path / "faq_seeds.json"
    fake_seed.write_text('{"schema_version": 1, "topics": [], "tree_procedure_names": {}}', encoding="utf-8")

    cfg = BatchConfig(
        seed_path=fake_seed,
        snapshot_dir=tmp_path / "snapshots",
        dry_run=False,
        skip_faq=True,
        skip_trees=True,
        enable_soap_distill=False,
        enable_patient_prefill=False,
        enable_gap_check=False,
        enable_visual_autodraft=True,
        max_visual_autodraft=2,  # 限制最多草擬 2 筆
    )

    fake_llm = Mock(side_effect=[
        _make_dummy_ir_json(topic_key="tree-one", title="療程一原理"),
        _make_dummy_ir_json(topic_key="tree-two", title="療程二原理"),
    ])

    summary = run_batch(
        conn,
        cfg,
        llm_call=fake_llm,
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.status == "completed"
    assert summary.visual_autodraft_planned == 2
    assert summary.visual_autodraft_generated == 2
    assert summary.visual_autodraft_failed == 0

    # 檢查產生之資產全為 pending
    rows = conn.execute("SELECT topic_key, review_status FROM visual_assets").fetchall()
    assert len(rows) == 2
    for r in rows:
        assert r[1] == "pending"

    # 再次確認全庫無 approved
    approved = conn.execute("SELECT COUNT(*) FROM visual_assets WHERE review_status = 'approved'").fetchone()[0]
    assert approved == 0

    conn.close()


def test_runner_visual_autodraft_llm_unavailable(tmp_path: Path):
    """驗證啟用時若 LLM 不可用，設定 status='llm_unavailable' 並提前回傳 True 結束階段。"""
    conn = _init_test_db(tmp_path / "test_runner3.db")
    conn.execute(
        """
        INSERT INTO page_index_trees (doc_id, title, summary_text, review_status) VALUES
        ('tree-err', '錯誤樹', '說明', 'approved');
        """
    )
    conn.commit()

    log_dir = tmp_path / "logs"
    logger = RunLogger(log_dir, echo=False)
    fake_seed = tmp_path / "faq_seeds.json"
    fake_seed.write_text('{"schema_version": 1, "topics": [], "tree_procedure_names": {}}', encoding="utf-8")

    cfg = BatchConfig(
        seed_path=fake_seed,
        snapshot_dir=tmp_path / "snapshots",
        dry_run=False,
        skip_faq=True,
        skip_trees=True,
        enable_soap_distill=False,
        enable_patient_prefill=False,
        enable_gap_check=False,
        enable_visual_autodraft=True,
    )

    unavail_llm = Mock(side_effect=LocalLLMUnavailableError("service unreachable"))
    summary = run_batch(
        conn,
        cfg,
        llm_call=unavail_llm,
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.status == "llm_unavailable"
    assert summary.visual_autodraft_planned == 1
    assert summary.visual_autodraft_failed == 1
    assert summary.visual_autodraft_generated == 0

    conn.close()


def test_runner_visual_autodraft_single_failure_does_not_halt_batch(tmp_path: Path):
    """驗證單一樹草擬失敗（如 parse error）只計入 failed，批次不中斷並繼續下一筆。"""
    conn = _init_test_db(tmp_path / "test_runner4.db")
    conn.execute(
        """
        INSERT INTO page_index_trees (doc_id, title, summary_text, review_status) VALUES
        ('tree-fail', '失敗樹', '說明', 'approved'),
        ('tree-ok', '成功樹', '說明', 'approved');
        """
    )
    conn.commit()

    log_dir = tmp_path / "logs"
    logger = RunLogger(log_dir, echo=False)
    fake_seed = tmp_path / "faq_seeds.json"
    fake_seed.write_text('{"schema_version": 1, "topics": [], "tree_procedure_names": {}}', encoding="utf-8")

    cfg = BatchConfig(
        seed_path=fake_seed,
        snapshot_dir=tmp_path / "snapshots",
        dry_run=False,
        skip_faq=True,
        skip_trees=True,
        enable_soap_distill=False,
        enable_patient_prefill=False,
        enable_gap_check=False,
        enable_visual_autodraft=True,
    )

    # 第一棵失敗（回傳無效字串），第二棵成功
    mixed_llm = Mock(side_effect=[
        "invalid json output",
        "invalid json output",
        "invalid json output",  # 3 次 retry 皆失敗
        _make_dummy_ir_json(topic_key="tree-ok", title="成功樹原理"),
    ])

    summary = run_batch(
        conn,
        cfg,
        llm_call=mixed_llm,
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.status == "completed"
    assert summary.visual_autodraft_planned == 2
    assert summary.visual_autodraft_failed == 1
    assert summary.visual_autodraft_generated == 1

    # 檢查成功樹正確入庫為 pending
    row = conn.execute("SELECT review_status FROM visual_assets WHERE topic_key = 'tree-ok'").fetchone()
    assert row is not None
    assert row[0] == "pending"

    # 全庫不存在 approved
    assert conn.execute("SELECT COUNT(*) FROM visual_assets WHERE review_status = 'approved'").fetchone()[0] == 0

    conn.close()
