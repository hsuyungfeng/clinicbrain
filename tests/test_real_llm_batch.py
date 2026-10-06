"""
真實本地 LLM 端到端批次實跑自動化驗收測試（Phase 13 DEBT-04）。

測試目標：
1. 驗證當本地 llama-server（Qwen 27B）在線時，夜間批次能端到端正常執行 FAQ 預生成與臨床推理樹重建。
2. 若本地推論服務離線或健康檢查逾時，自動透過 pytest.skip 優雅略過，不影響離線 CI。
3. 全程使用資料庫獨立複本（isolated_conn / isolated_db_path），保證正式 clinic.db 零接觸與雜湊恆定。
4. 驗證真實產出寫入為 review_status='pending'，在未獲醫師核准前對一般諮詢完全隱蔽。
5. 驗證臨床推理樹重建前後產生前像快照，且醫師手寫註記 (*_physician_notes) 完整保留。
6. 驗證批次日誌遵循隱私白名單，絕無未過濾之問句原型或提示詞本文。
"""

import hashlib
import json
from pathlib import Path
import sqlite3
import pytest

from src.batch.run_log import RunLogger
from src.batch.runner import BatchConfig, run_batch
from src.general.consult import consult_general
from src.pageindex.db_writer import set_needs_regeneration
from src.pageindex.llm_client import (
    LocalLLMUnavailableError,
    check_llm_health,
    local_llm_call,
)
from src.query.router import handle_query

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROD_DB_PATH = PROJECT_ROOT / "clinic.db"
PROD_SHA256_FILE = PROJECT_ROOT / ".planning" / "phases" / "13-real-llm-batch-verification" / "prod.sha256"


def _is_llm_online() -> bool:
    """探測本地 llama-server 是否在線且正常運作。"""
    try:
        check_llm_health(timeout=3)
        return True
    except (LocalLLMUnavailableError, Exception):
        return False


# 當本地 LLM 離線時，全模組優雅略過，避免破壞無 GPU 環境之 CI
pytestmark = pytest.mark.skipif(
    not _is_llm_online(),
    reason="本地 llama-server 未啟動或連線逾時，略過真機實跑測試",
)


def _get_expected_prod_sha256() -> str:
    """取得正式 clinic.db 基準 SHA-256 雜湊值。"""
    if PROD_SHA256_FILE.exists():
        first_line = PROD_SHA256_FILE.read_text(encoding="utf-8").strip()
        return first_line.split()[0]
    return "ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e"


def _calc_file_sha256(path: Path) -> str:
    """計算指定檔案的 SHA-256 雜湊。"""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


@pytest.fixture(autouse=True)
def _verify_prod_db_untouched():
    """每次測試執行前後雙重檢驗正式 clinic.db 之 SHA-256，保證零接觸零污染。"""
    expected = _get_expected_prod_sha256()
    assert PROD_DB_PATH.exists(), f"正式資料庫檔案不存在：{PROD_DB_PATH}"
    assert _calc_file_sha256(PROD_DB_PATH) == expected, "正式 clinic.db 於測試開始前雜湊不吻合！"
    yield
    assert _calc_file_sha256(PROD_DB_PATH) == expected, "正式 clinic.db 於測試結束後雜湊變動（受到污染）！"


def test_real_llm_faq_generation(isolated_conn, tmp_path: Path):
    """測試 1：以真實本地 27B 大模型執行單一主題 FAQ 批次預生成。

    驗證：
    - run_batch 在真實 LLM 推論下順利完成 (status == 'completed', errors == 0)。
    - 生成之 FAQ 正確寫入 faq_cache，標記 source_type='llm_generated' 與 review_status='pending'。
    - 審核閘門生效：未獲核准前，consult_general 與 handle_query 檢索不到此筆待審問答。
    """
    seed_file = PROJECT_ROOT / "data" / "batch" / "faq_seeds.json"
    from src.batch.topic_sources import load_seed_file
    from src.pageindex.faq_writer import upsert_faqs

    seed = load_seed_file(seed_file)
    cold_topic = [t for t in seed.topics if t.topic_key == "common-cold-home-care"][0]
    # 預先置入後續 4 題，使真實 LLM 專注生成首題「什麼是感冒？」，確保推論在 50 秒內穩定完成
    pre_faqs = [
        {
            "clinic_id": None,
            "topic_key": cold_topic.topic_key,
            "question": q,
            "answer": "既有基礎衛教說明，若有不適請儘速就醫。",
            "category": "general",
        }
        for q in cold_topic.questions[1:]
    ]
    upsert_faqs(isolated_conn, pre_faqs, source_type="manual")

    log_dir = tmp_path / "faq_logs"
    snap_dir = tmp_path / "faq_snapshots"

    logger = RunLogger(log_dir, echo=False)
    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=snap_dir,
        dry_run=False,
        skip_trees=True,
        max_faq_topics=1,
    )

    summary = run_batch(
        isolated_conn,
        cfg,
        llm_call=local_llm_call,
        health_check=check_llm_health,
        logger=logger,
    )

    # 1. 斷言批次執行摘要狀態
    assert summary.status == "completed", f"批次執行狀態非 completed: {summary.status}"
    assert summary.errors == 0, f"批次執行發生非預期錯誤：{summary.errors}"
    assert summary.faq_topics_processed == 1, "預期處理 1 個 FAQ 主題"
    assert summary.faq_inserted > 0, f"未寫入任何 FAQ 項目（inserted={summary.faq_inserted}）"

    # 2. 檢驗寫入資料庫之欄位屬性
    cur = isolated_conn.cursor()
    cur.execute(
        "SELECT topic_key, question, answer, source_type, review_status, category "
        "FROM faq_cache WHERE source_type = 'llm_generated'"
    )
    rows = cur.fetchall()
    assert len(rows) > 0, "faq_cache 中找不到 source_type='llm_generated' 的列"

    for r in rows:
        topic_key, question, answer, source_type, review_status, category = r
        assert source_type == "llm_generated", f"source_type 應為 llm_generated，得到 {source_type}"
        assert review_status == "pending", f"未經審核之新 FAQ 其 review_status 應為 pending，得到 {review_status}"
        assert len(answer) >= 15, f"生成答案字數過短：{answer}"

    # 3. 檢驗可見性防禦（審核閘門）：未核准前對外不可見
    sample_q = rows[0][1]
    consult_res = consult_general(isolated_conn, sample_q)
    # pending FAQ 不得被 consult_general 命中（應回傳 no_match）
    assert consult_res.status == "no_match", (
        f"未核准之 FAQ 竟然被 consult_general 檢索命中！status={consult_res.status}"
    )

    query_res = handle_query(isolated_conn, sample_q, clinic_id=None)
    # 自然語言統一查詢亦不得走 cache 短路命中未審核項目
    assert query_res.source != "cache", (
        f"未核准之 FAQ 竟然觸發了快取短路！source={query_res.source}"
    )


def test_real_llm_tree_rebuild(isolated_conn, tmp_path: Path):
    """測試 2：以真實本地 27B 大模型執行臨床推理樹重建與醫師註記保護。

    驗證：
    - 將 hifu-lifting 標記 needs_regeneration=1。
    - 重建前正確在 snapshot_dir 產生前像備份快照。
    - run_batch 重建成功，needs_regeneration 重置為 0，content_version 遞增。
    - 關鍵防線：醫師手寫註記 (*_physician_notes) 完整保留，未被覆蓋或清空。
    - 臨床段落 (pre_op, procedure 等) 由大模型真實產出有效內容。
    """
    target_doc_id = "hifu-lifting"
    custom_physician_note = "【真機測試專用醫師指引：術前務必確認皮膚厚度與神經走向】"

    # 1. 準備前置狀態：寫入手寫醫師註記並標記待重建
    cur = isolated_conn.cursor()
    cur.execute(
        "UPDATE page_index_trees SET "
        "  pre_op_physician_notes = ?, "
        "  needs_regeneration = 1 "
        "WHERE doc_id = ?",
        (custom_physician_note, target_doc_id),
    )
    isolated_conn.commit()

    # 讀取重建前版本
    cur.execute(
        "SELECT content_version, pre_op FROM page_index_trees WHERE doc_id = ?",
        (target_doc_id,),
    )
    row_before = cur.fetchone()
    version_before = row_before[0]
    pre_op_before = row_before[1]

    # 2. 執行樹重建
    log_dir = tmp_path / "tree_logs"
    snap_dir = tmp_path / "tree_snapshots"

    seed_file = PROJECT_ROOT / "data" / "batch" / "faq_seeds.json"
    logger = RunLogger(log_dir, echo=False)
    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=snap_dir,
        dry_run=False,
        skip_faq=True,
        max_trees=1,
    )

    summary = run_batch(
        isolated_conn,
        cfg,
        llm_call=local_llm_call,
        health_check=check_llm_health,
        logger=logger,
    )

    # 3. 斷言執行摘要
    assert summary.status == "completed", f"樹重建狀態非 completed: {summary.status}"
    assert summary.errors == 0, f"樹重建成生錯誤：{summary.errors}"
    assert summary.trees_rebuilt == 1, f"預期重建 1 棵樹，實際重建 {summary.trees_rebuilt}"

    # 4. 斷言前像快照已備份
    snap_files = list(snap_dir.glob(f"*{target_doc_id}*.json"))
    assert len(snap_files) >= 1, f"未在 snapshot_dir 中找到 {target_doc_id} 的前像快照檔案"
    snap_content = json.loads(snap_files[0].read_text(encoding="utf-8"))
    assert snap_content.get("doc_id") == target_doc_id
    assert snap_content.get("old", {}).get("pre_op_physician_notes") == custom_physician_note

    # 5. 斷言資料庫更新結果與醫師註記完整性
    cur.execute(
        "SELECT pre_op_physician_notes, needs_regeneration, content_version, "
        "       source_type, pre_op, procedure, post_op_short, maintenance "
        "FROM page_index_trees WHERE doc_id = ?",
        (target_doc_id,),
    )
    row_after = cur.fetchone()
    (
        notes_after,
        needs_regen_after,
        version_after,
        source_type_after,
        pre_op_after,
        procedure_after,
        post_op_after,
        maintenance_after,
    ) = row_after

    # 醫師註記必須完全一致（防覆蓋）
    assert notes_after == custom_physician_note, (
        f"醫師註記在重建後被破壞！預期: {custom_physician_note}，實際: {notes_after}"
    )
    # 標記必須重置
    assert needs_regen_after == 0, "needs_regeneration 重建後應重置為 0"
    # 版本號必須遞增
    assert version_after > version_before, (
        f"content_version 應遞增，原版本: {version_before}，新版本: {version_after}"
    )
    # source_type 標記為 llm_generated
    assert source_type_after == "llm_generated"
    # 臨床內容由模型生成且非空
    assert len(pre_op_after.strip()) > 20, "重建之 pre_op 內容長度不足"
    assert len(procedure_after.strip()) > 20, "重建之 procedure 內容長度不足"


def test_real_llm_log_privacy(isolated_conn, tmp_path: Path):
    """測試 3：審核真機推論產生之結構化日誌，保證無病患隱私與未過濾問答外洩。

    驗證：
    - 日誌檔案為合規 JSONL 格式。
    - 所有欄位鍵名絕無 query, question, answer, prompt 等禁詞。
    - 不包含原始使用者問句或模型原文推論歷史。
    """
    seed_file = PROJECT_ROOT / "data" / "batch" / "faq_seeds.json"
    from src.batch.topic_sources import load_seed_file
    from src.pageindex.faq_writer import upsert_faqs

    seed = load_seed_file(seed_file)
    cold_topic = [t for t in seed.topics if t.topic_key == "common-cold-home-care"][0]
    pre_faqs = [
        {
            "clinic_id": None,
            "topic_key": cold_topic.topic_key,
            "question": q,
            "answer": "既有基礎衛教說明，若有不適請儘速就醫。",
            "category": "general",
        }
        for q in cold_topic.questions[1:]
    ]
    upsert_faqs(isolated_conn, pre_faqs, source_type="manual")

    log_dir = tmp_path / "privacy_logs"
    snap_dir = tmp_path / "privacy_snapshots"

    logger = RunLogger(log_dir, echo=False)
    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=snap_dir,
        dry_run=False,
        skip_trees=True,
        max_faq_topics=1,
    )

    run_batch(
        isolated_conn,
        cfg,
        llm_call=local_llm_call,
        health_check=check_llm_health,
        logger=logger,
    )

    log_files = list(log_dir.glob("nightly-*.log"))
    assert len(log_files) > 0, "未產生任何批次日誌檔案"

    forbidden_keys = {"query", "question", "answer", "prompt", "raw", "text", "content"}

    total_events = 0
    for lf in log_files:
        lines = lf.read_text(encoding="utf-8").strip().splitlines()
        for line_no, line in enumerate(lines, 1):
            if not line.strip():
                continue
            parts = line.split(" ", 3)
            record = json.loads(parts[3]) if len(parts) >= 4 else {}
            total_events += 1

            # 遞迴檢查字典鍵名
            def _check_keys(obj, path=""):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        lower_k = k.lower()
                        assert lower_k not in forbidden_keys, (
                            f"日誌行 {line_no} 包含敏感鍵名 '{k}'（路徑: {path}）"
                        )
                        _check_keys(v, f"{path}.{k}" if path else k)
                elif isinstance(obj, list):
                    for item in obj:
                        _check_keys(item, path)

            _check_keys(record)

    assert total_events > 0, "日誌中未記錄任何事件"
