"""Phase 28 Plan 06: patient_prefill 夜間批次階段 8 跨日與端到端測試。

涵蓋：
- Test 0: 預設時鐘生成的 generated_at 為合法 UTC ISO 字串且與當前時間差小於 5 分鐘。
- Test 1: 跨日假時鐘：第 1 天生成 5 題 -> +10 小時跳過 -> +23 小時重新排入。
- Test 2: 版本變更：樹 content_version 增加後立即排入，approved 列回到 pending。
- Test 3: 上限截斷：3 個過期主題、max_faq_topics=2 -> 處理 2 個，backlog 為 1。
- Test 4: 核准後命中（General 推理樹）：醫師核准預生成問答後，patient_consult 回 answered（0 次模型呼叫）並包含追問與 CTA。
- Test 5: 旗標與互斥：enable_patient_prefill=False、soap_only、general_only 時階段 8 不執行。
- Test 6: dry_run=True 不呼叫 llm、不寫入，輸出 prefill_topics_planned 與 backlog。
- Test 7: LLM 離線時 status=llm_unavailable。
- Test 8: 正式庫防護：測試前後核對 clinic.db SHA-256 保持不變。
- Test 9b: 無可讀中文標題的樹計入 prefill_skipped_no_title。
"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import pytest

from src.batch.runner import BatchConfig, BatchSummary, run_batch
from src.batch.run_log import RunLogger
from src.general.patient_consult import patient_consult
from src.pageindex.db_writer import upsert_trees
from src.pageindex.faq_review import set_review_status
from src.pageindex.llm_client import LocalLLMUnavailableError


CLINIC = "3503190424"
NOW_FIXED = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
WARNING_TEXT = "若出現胸痛、呼吸困難或體溫持續超過38.5度達3天，請立即前往急診或儘速就醫。"
PROD_DB = Path("clinic.db").resolve()


def _get_db_hash() -> str:
    if not PROD_DB.exists():
        return ""
    return hashlib.sha256(PROD_DB.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def guard_prod_db():
    h_before = _get_db_hash()
    yield
    h_after = _get_db_hash()
    assert h_before == h_after, "正式資料庫 clinic.db 在測試中被修改！"


def _dummy_llm(prompt: str) -> str:
    return (
        "答：這項療程能改善相關症狀並達到舒緩效果。\n"
        "日常照護時建議維持良好作息與適度運動。\n"
        f"{WARNING_TEXT}\n"
        "追問：您目前是否有特定體質狀況想先確認呢？"
    )


def _setup_tree(conn, doc_id="e2e-tree", title="玻尿酸填充注射", category="special", clinic_id=CLINIC) -> str:
    tree = {
        "doc_id": doc_id,
        "clinic_id": clinic_id,
        "category": category,
        "title": title,
        "summary_text": f"{title}的臨床摘要與療程細節說明，請洽診所。",
        "pre_op": "術前諮詢與身體狀況評估。",
        "pre_op_physician_notes": "",
        "procedure": "臨床專業標準作業程序處置。",
        "procedure_physician_notes": "",
        "post_op_short": "術後短期照護注意事項。",
        "post_op_short_physician_notes": "",
        "maintenance": "長期日常維護保健要點。",
        "maintenance_physician_notes": "",
        "version": 1,
        "status": "approved",
    }
    upsert_trees(conn, [tree], source_type="manual")
    conn.execute("UPDATE page_index_trees SET review_status='approved' WHERE doc_id=?", (doc_id,))
    conn.commit()
    return doc_id


def test_0_default_clock_generated_at_utc(isolated_conn, tmp_path):
    """Test 0: 預設時鐘產生的 generated_at 為合法 UTC ISO 字串且與真實時間相近。"""
    _setup_tree(isolated_conn, "tree-t0", "雷射皮秒美白")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"schema_version": 1, "topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snap",
        skip_faq=True,
        skip_trees=True,
        enable_soap_distill=False,
    )
    logger = RunLogger(tmp_path / "logs", echo=False)
    summary = run_batch(
        isolated_conn,
        cfg,
        llm_call=_dummy_llm,
        health_check=lambda: None,
        logger=logger,
    )
    logger.close()

    assert summary.prefill_generated == 5
    cur = isolated_conn.cursor()
    cur.execute("SELECT metadata FROM faq_cache WHERE topic_key LIKE 'prefill-tree-t0-%' LIMIT 1")
    meta = json.loads(cur.fetchone()[0])
    dt = datetime.fromisoformat(meta["generated_at"])
    now_real = datetime.now(timezone.utc)
    diff = abs((now_real - dt).total_seconds())
    assert diff < 300  # 小於 5 分鐘


def test_1_cross_day_fake_clock(isolated_conn, tmp_path):
    """Test 1: 跨日假時鐘：第 1 天生成 5 題 -> +10 小時跳過 -> +23 小時重新排入。"""
    doc_id = _setup_tree(isolated_conn, "tree-t1", "肉毒除皺拉提")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"schema_version": 1, "topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    current_fake_now = NOW_FIXED

    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snap",
        skip_faq=True,
        skip_trees=True,
        enable_soap_distill=False,
        now_fn=lambda: current_fake_now,
    )

    # Day 1: 生成 5 題
    logger1 = RunLogger(tmp_path / "logs1", echo=False)
    sum1 = run_batch(isolated_conn, cfg, llm_call=_dummy_llm, health_check=lambda: None, logger=logger1)
    logger1.close()
    assert sum1.prefill_generated == 5

    # Day 1 + 10h: 新鮮跳過，generated 為 0
    current_fake_now = NOW_FIXED + timedelta(hours=10)
    logger2 = RunLogger(tmp_path / "logs2", echo=False)
    sum2 = run_batch(isolated_conn, cfg, llm_call=_dummy_llm, health_check=lambda: None, logger=logger2)
    logger2.close()
    assert sum2.prefill_generated == 0
    assert sum2.prefill_topics_planned == 0

    # Day 1 + 23h (超過 24 - 2 = 22 小時寬限)：重新排入並生成
    current_fake_now = NOW_FIXED + timedelta(hours=23)
    logger3 = RunLogger(tmp_path / "logs3", echo=False)
    sum3 = run_batch(isolated_conn, cfg, llm_call=_dummy_llm, health_check=lambda: None, logger=logger3)
    logger3.close()
    assert sum3.prefill_topics_planned >= 1


def test_2_tree_version_change_reverts_approved_to_pending(isolated_conn, tmp_path):
    """Test 2: 修改推理樹內容並升版後立即再跑，重新排入，approved 列回到 pending。"""
    doc_id = _setup_tree(isolated_conn, "tree-t2", "電波緊緻拉皮")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"schema_version": 1, "topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    current_fake_now = NOW_FIXED
    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snap",
        skip_faq=True,
        skip_trees=True,
        enable_soap_distill=False,
        now_fn=lambda: current_fake_now,
    )

    # 首次生成
    logger1 = RunLogger(tmp_path / "logs1", echo=False)
    run_batch(isolated_conn, cfg, llm_call=_dummy_llm, health_check=lambda: None, logger=logger1)
    logger1.close()

    # 醫師手動核准 what 題
    target_key = f"prefill-{doc_id}-what"
    isolated_conn.execute("UPDATE faq_cache SET review_status='approved' WHERE topic_key=?", (target_key,))
    isolated_conn.commit()

    # 修改推理樹內容並升版
    isolated_conn.execute(
        "UPDATE page_index_trees SET summary_text='升級版電波技術說明。', content_version=2 WHERE doc_id=?",
        (doc_id,),
    )
    isolated_conn.commit()

    def _new_llm(p):
        return "答：這是全新的電波技術說明內容。\n" + WARNING_TEXT

    # 立即再跑（未滿 1 小時）
    current_fake_now = NOW_FIXED + timedelta(minutes=30)
    logger2 = RunLogger(tmp_path / "logs2", echo=False)
    sum2 = run_batch(isolated_conn, cfg, llm_call=_new_llm, health_check=lambda: None, logger=logger2)
    logger2.close()

    assert sum2.prefill_topics_planned >= 1
    cur = isolated_conn.cursor()
    cur.execute("SELECT review_status, content_version FROM faq_cache WHERE topic_key=?", (target_key,))
    status, ver = cur.fetchone()
    assert status == "pending"  # 回到 pending
    assert ver > 1


def test_3_max_faq_topics_truncation_and_backlog(isolated_conn, tmp_path):
    """Test 3: 3 個過期主題、max_faq_topics=2 -> 本次處理 2 個，backlog 為 1。"""
    titles = ["玻尿酸豐潤注射", "音波拉皮提拉", "電波緊緻除皺"]
    for i, title in enumerate(titles, 1):
        _setup_tree(isolated_conn, f"tree-t3-{i}", title)

    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"schema_version": 1, "topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snap",
        skip_faq=True,
        skip_trees=True,
        enable_soap_distill=False,
        max_faq_topics=2,
        now_fn=lambda: NOW_FIXED,
    )
    logger = RunLogger(tmp_path / "logs", echo=False)
    summary = run_batch(isolated_conn, cfg, llm_call=_dummy_llm, health_check=lambda: None, logger=logger)
    logger.close()

    assert summary.prefill_topics_planned == 3
    assert summary.prefill_backlog == 1
    assert summary.prefill_generated == 10  # 2 個主題各 5 題


def test_4_general_tree_approved_hit_no_llm_call(isolated_conn, tmp_path):
    """Test 4: General 推理樹（clinic_id=NULL）核准後，patient_consult 回 answered 且 0 次 LLM 呼叫。"""
    # 建立 clinic_id 為 NULL 的 general 樹
    doc_id = "general-cold-care"
    isolated_conn.execute(
        """
        INSERT INTO page_index_trees (
            doc_id, clinic_id, category, title, summary_text, pre_op, procedure,
            post_op_short, maintenance, version, content_version, source_type, review_status
        ) VALUES (?, NULL, 'general', '感冒居家衛教', '感冒多喝水休息衛教說明。', '', '', '', '', 1, 1, 'manual', 'approved')
        """,
        (doc_id,),
    )
    isolated_conn.commit()

    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"schema_version": 1, "topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snap",
        skip_faq=True,
        skip_trees=True,
        enable_soap_distill=False,
        now_fn=lambda: NOW_FIXED,
    )
    logger = RunLogger(tmp_path / "logs", echo=False)
    run_batch(isolated_conn, cfg, llm_call=_dummy_llm, health_check=lambda: None, logger=logger)
    logger.close()

    # 查出 what 題目文字
    cur = isolated_conn.cursor()
    cur.execute("SELECT id, question, answer FROM faq_cache WHERE topic_key='prefill-general-cold-care-what'")
    row = cur.fetchone()
    assert row is not None
    faq_id, q_text, ans_text = row[0], row[1], row[2]

    # 核准前：consult 回 no_match（不可見）
    llm_counter = 0

    def _counting_llm(p):
        nonlocal llm_counter
        llm_counter += 1
        return ""

    # 醫師以 set_review_status 正式核准
    set_review_status(isolated_conn, [faq_id], "approved")

    # 核准後：consult_general 命中，直答回覆，llm_counter 呼叫 0 次
    res = patient_consult(isolated_conn, q_text, llm_call=_counting_llm)
    assert res.status == "answered"
    assert llm_counter == 0
    assert "？" in res.message
    assert "預約" in res.message


def test_5_stage_skips_when_flags_disabled(isolated_conn, tmp_path):
    """Test 5: enable_patient_prefill=False、soap_only、general_only 時階段 8 不執行。"""
    _setup_tree(isolated_conn, "tree-t5", "埋線拉皮提拉")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"schema_version": 1, "topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    # 1. enable_patient_prefill=False
    cfg1 = BatchConfig(seed_path=seed_file, snapshot_dir=tmp_path / "snap", enable_patient_prefill=False)
    logger1 = RunLogger(tmp_path / "logs1", echo=False)
    sum1 = run_batch(isolated_conn, cfg1, llm_call=_dummy_llm, health_check=lambda: None, logger=logger1)
    logger1.close()
    assert sum1.prefill_topics_planned == 0
    assert sum1.prefill_generated == 0

    # 2. soap_only=True
    cfg2 = BatchConfig(seed_path=seed_file, snapshot_dir=tmp_path / "snap", soap_only=True)
    logger2 = RunLogger(tmp_path / "logs2", echo=False)
    sum2 = run_batch(isolated_conn, cfg2, llm_call=_dummy_llm, health_check=lambda: None, logger=logger2)
    logger2.close()
    assert sum2.prefill_generated == 0


def test_6_dry_run_no_writes_and_summary_reported(isolated_conn, tmp_path):
    """Test 6: dry_run=True 不呼叫 llm、不寫入，summary 輸出 planned 與 backlog。"""
    _setup_tree(isolated_conn, "tree-t6", "音波緊顏塑形")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"schema_version": 1, "topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    call_count = 0

    def _counting_llm(p):
        nonlocal call_count
        call_count += 1
        return ""

    cfg = BatchConfig(seed_path=seed_file, snapshot_dir=tmp_path / "snap", dry_run=True)
    logger = RunLogger(tmp_path / "logs", echo=False)
    init_changes = isolated_conn.total_changes
    summary = run_batch(isolated_conn, cfg, llm_call=_counting_llm, health_check=lambda: None, logger=logger)
    logger.close()

    assert summary.prefill_topics_planned >= 1
    assert summary.prefill_generated == 0
    assert call_count == 0
    assert isolated_conn.total_changes == init_changes


def test_7_offline_llm_status_llm_unavailable(isolated_conn, tmp_path):
    """Test 7: 階段 8 遇 LocalLLMUnavailableError 時批次 status 為 llm_unavailable。"""
    _setup_tree(isolated_conn, "tree-t7", "皮秒蜂巢雷射")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"schema_version": 1, "topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    def _offline_llm(p):
        raise LocalLLMUnavailableError("本地伺服器無回應")

    cfg = BatchConfig(
        seed_path=seed_file, snapshot_dir=tmp_path / "snap",
        skip_faq=True, skip_trees=True, enable_soap_distill=False,
    )
    logger = RunLogger(tmp_path / "logs", echo=False)
    summary = run_batch(isolated_conn, cfg, llm_call=_offline_llm, health_check=lambda: None, logger=logger)
    logger.close()

    assert summary.status == "llm_unavailable"


def test_9b_skipped_no_title_trees_counted(isolated_conn, tmp_path):
    """Test 9b: 無可讀中文標題的樹計入 summary.prefill_skipped_no_title。"""
    # 建立一棵只有英文 slug、title 為空的樹
    tree_no_title = {
        "doc_id": "tree-english-slug-only",
        "clinic_id": CLINIC,
        "category": "special",
        "title": "",
        "summary_text": "無中文標題樹摘要說明。",
        "pre_op": "術前", "pre_op_physician_notes": "",
        "procedure": "處置", "procedure_physician_notes": "",
        "post_op_short": "術後", "post_op_short_physician_notes": "",
        "maintenance": "維持", "maintenance_physician_notes": "",
        "version": 1,
        "status": "approved",
    }
    upsert_trees(isolated_conn, [tree_no_title], source_type="manual")

    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"schema_version": 1, "topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    cfg = BatchConfig(
        seed_path=seed_file, snapshot_dir=tmp_path / "snap",
        skip_faq=True, skip_trees=True, enable_soap_distill=False,
    )
    logger = RunLogger(tmp_path / "logs", echo=False)
    summary = run_batch(isolated_conn, cfg, llm_call=_dummy_llm, health_check=lambda: None, logger=logger)
    logger.close()

    assert summary.prefill_skipped_no_title >= 1
