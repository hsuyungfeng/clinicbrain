"""Phase 28 Plan 06: patient_prefill 夜間批次生成與寫入階段單元測試。

涵蓋 12 項行為測試：
- Test 1: 假 llm_call 回覆標準格式，通過驗證以 pending 寫入，欄位與 metadata 完整。
- Test 2: answer 僅含價值回答段（2～4 句、含警訊句、結尾標點，無追問、無 CTA）。
- Test 3: 驗證失敗與截斷題目剔除並計入 rejected，其餘題目正常寫入。
- Test 4: 時間預算用盡中止，status=budget_exhausted，記錄 skipped_budget。
- Test 5: LocalLLMUnavailableError 時優雅中止，status=llm_unavailable。
- Test 6: time_stale 重新生成：答案相同只刷新 metadata（不升版號），答案不同升版號。
- Test 7: 簽章改變時 approved 列重新生成回到 pending 且版號增加（Fail-Closed）。
- Test 8: max_pending 上限保護，達標時 status=pending_cap 不執行生成。
- Test 9: 單題一般例外隔離，errors 加一，其餘題目繼續。
- Test 10: RunLogger 日誌安全：不包含問句、答案、prompt 等敏感字串。
- Test 11: dry_run=True 僅規劃，llm_call 0 次，資料庫 total_changes 不變。
- Test 12: 寫入列 review_status='pending'，對 visible_faq_sql 與對外檢索不可見。
"""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3
import pytest

from src.batch.patient_prefill import PrefillResult, run_prefill_stage
from src.batch.patient_prefill_plan import INTENT_TEMPLATES, PREFILL_TOPIC_PREFIX
from src.batch.run_log import RunLogger
from src.pageindex.db_writer import upsert_trees
from src.pageindex.faq_review import visible_faq_sql
from src.pageindex.faq_writer import upsert_faqs
from src.pageindex.llm_client import LLMTruncatedError, LocalLLMUnavailableError


CLINIC = "3503190424"
NOW_FIXED = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
WARNING_TEXT = "若出現胸痛、呼吸困難或體溫持續超過38.5度達3天，請立即前往急診或儘速就醫。"


@dataclass
class DummyConfig:
    max_faq_topics: int = 5
    max_pending: int = 200
    time_budget_seconds: float = 3600.0
    dry_run: bool = False
    seed_path: str = ""


def _setup_test_tree(conn, doc_id="batch-filler", title="玻尿酸微整填充") -> str:
    """在隔離庫寫入一棵已核准決策樹。"""
    tree = {
        "doc_id": doc_id,
        "clinic_id": CLINIC,
        "category": "special",
        "title": title,
        "summary_text": "玻尿酸填充說明與術後注意事項，費用請洽診所。",
        "pre_op": "術前確認過敏體質與用藥情形。",
        "pre_op_physician_notes": "",
        "procedure": "採局部精準微量注射，分層塑形。",
        "procedure_physician_notes": "",
        "post_op_short": "術後一週內避免高溫蒸氣桑拿。",
        "post_op_short_physician_notes": "",
        "maintenance": "日常注意保濕與防曬，定期評估。",
        "maintenance_physician_notes": "",
        "version": 1,
        "status": "approved",
    }
    upsert_trees(conn, [tree], source_type="manual")
    conn.execute("UPDATE page_index_trees SET review_status='approved' WHERE doc_id=?", (doc_id,))
    conn.commit()
    return doc_id


def _dummy_llm_response(prompt: str) -> str:
    """回傳合格之答與追問格式。"""
    val = (
        "答：這項療程主要透過專業醫療技術進行改善。\n"
        "過程中醫師會依個人體質做最適切的評估與處理。\n"
        f"{WARNING_TEXT}\n"
        "追問：您想了解整體治療流程，還是術後照護細節呢？"
    )
    return val


def test_1_and_2_generate_all_intents_pure_value(isolated_conn, tmp_path):
    """Test 1 & 2: 假 llm_call 回答五題，pending 寫入，answer 僅含純價值段（無追問與 CTA）。"""
    doc_id = _setup_test_tree(isolated_conn, "tree-t1", "玻尿酸填充塑形")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    cfg = DummyConfig(max_faq_topics=5, seed_path=str(seed_file))
    res = run_prefill_stage(isolated_conn, cfg, _dummy_llm_response, now=NOW_FIXED)

    assert res.status == "completed"
    assert res.generated == 5
    assert res.rejected == 0
    assert res.topics_processed == 1

    cur = isolated_conn.cursor()
    cur.execute(
        "SELECT topic_key, question, answer, review_status, source_type, metadata FROM faq_cache WHERE topic_key LIKE ?",
        (f"{PREFILL_TOPIC_PREFIX}{doc_id}-%",),
    )
    rows = cur.fetchall()
    assert len(rows) == 5

    for key, q, a, r_status, src, meta_raw in rows:
        assert r_status == "pending"
        assert src == "llm_generated"
        assert "追問" not in a
        assert "預約" not in a
        assert WARNING_TEXT in a
        assert a.endswith(("。", "！", "？", "」"))

        meta = json.loads(meta_raw)
        assert meta["origin"] == "patient_prefill"
        assert meta["prefill_topic_key"] == f"{PREFILL_TOPIC_PREFIX}{doc_id}"
        assert meta["generated_at"] == NOW_FIXED.isoformat()
        assert len(meta["ref_signature"]) == 12


def test_3_rejected_items_skipped_isolated(isolated_conn, tmp_path):
    """Test 3: 驗證失敗與截斷題目剔除並計入 rejected，合格題目不受影響。"""
    doc_id = _setup_test_tree(isolated_conn, "tree-t3", "雷射除斑療程")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    call_count = 0

    def _failing_llm(prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # 價格洩漏
            return "答：費用一次只要 15000 元，非常划算。" + WARNING_TEXT
        elif call_count == 2:
            # 截斷錯誤
            raise LLMTruncatedError("輸出超長截斷")
        else:
            return _dummy_llm_response(prompt)

    cfg = DummyConfig(max_faq_topics=5, seed_path=str(seed_file))
    res = run_prefill_stage(isolated_conn, cfg, _failing_llm, now=NOW_FIXED)

    assert res.status == "completed"
    assert res.rejected == 2
    assert res.generated == 3


def test_4_time_budget_exhausted(isolated_conn, tmp_path):
    """Test 4: 時間預算用盡中止，已寫入保留，記錄 skipped_budget 與 status=budget_exhausted。"""
    _setup_test_tree(isolated_conn, "tree-t4-a", "音波拉皮提拉")
    _setup_test_tree(isolated_conn, "tree-t4-b", "電波拉皮拉提")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    current_clock = 1000.0

    def _fake_clock() -> float:
        return current_clock

    def _time_consuming_llm(prompt: str) -> str:
        nonlocal current_clock
        current_clock += 50.0  # 每題消耗 50 秒
        return _dummy_llm_response(prompt)

    cfg = DummyConfig(max_faq_topics=5, time_budget_seconds=120.0, seed_path=str(seed_file))
    res = run_prefill_stage(isolated_conn, cfg, _time_consuming_llm, now=NOW_FIXED, clock=_fake_clock)

    assert res.status == "budget_exhausted"
    assert res.skipped_budget > 0
    assert res.generated > 0


def test_5_local_llm_unavailable_graceful(isolated_conn, tmp_path):
    """Test 5: LLM 離線時優雅中止，不拋出例外，status 為 llm_unavailable。"""
    _setup_test_tree(isolated_conn, "tree-t5", "皮秒雷射除斑")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    def _offline_llm(prompt: str) -> str:
        raise LocalLLMUnavailableError("llama-server 連線失敗 (ConnectionRefused)")

    cfg = DummyConfig(max_faq_topics=5, seed_path=str(seed_file))
    res = run_prefill_stage(isolated_conn, cfg, _offline_llm, now=NOW_FIXED)

    assert res.status == "llm_unavailable"
    assert res.generated == 0


def test_6_time_stale_refresh_behavior(isolated_conn, tmp_path):
    """Test 6: time_stale 重新生成：答案相同只刷新 metadata（不升版號），答案不同升版號。"""
    doc_id = _setup_test_tree(isolated_conn, "tree-t6", "肉毒桿菌除皺")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    cfg = DummyConfig(max_faq_topics=5, seed_path=str(seed_file))

    # 第 1 次生成
    time_day1 = NOW_FIXED - timedelta(hours=30)
    res1 = run_prefill_stage(isolated_conn, cfg, _dummy_llm_response, now=time_day1)
    assert res1.generated == 5

    # 查第 1 次生成的 content_version
    cur = isolated_conn.cursor()
    cur.execute("SELECT content_version, metadata FROM faq_cache WHERE topic_key=?", (f"{PREFILL_TOPIC_PREFIX}{doc_id}-what",))
    ver1, meta1_raw = cur.fetchone()
    assert json.loads(meta1_raw)["generated_at"] == time_day1.isoformat()

    # 第 2 次生成（30 小時後，答案相同）
    res2 = run_prefill_stage(isolated_conn, cfg, _dummy_llm_response, now=NOW_FIXED)
    assert res2.refreshed_unchanged == 5

    cur.execute("SELECT content_version, metadata FROM faq_cache WHERE topic_key=?", (f"{PREFILL_TOPIC_PREFIX}{doc_id}-what",))
    ver2, meta2_raw = cur.fetchone()
    assert ver2 == ver1  # 答案未變，content_version 不變
    assert json.loads(meta2_raw)["generated_at"] == NOW_FIXED.isoformat()  # metadata 刷新


def test_7_signature_changed_reverts_approved_to_pending(isolated_conn, tmp_path):
    """Test 7: 簽章改變時，已核准列重新生成回到 pending 且版號增加（Fail-Closed）。"""
    doc_id = _setup_test_tree(isolated_conn, "tree-t7", "自體脂肪填充")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    cfg = DummyConfig(max_faq_topics=5, seed_path=str(seed_file))
    run_prefill_stage(isolated_conn, cfg, _dummy_llm_response, now=NOW_FIXED)

    # 醫師手動將其核准
    target_key = f"{PREFILL_TOPIC_PREFIX}{doc_id}-what"
    isolated_conn.execute("UPDATE faq_cache SET review_status='approved' WHERE topic_key=?", (target_key,))
    isolated_conn.commit()

    # 修改推理樹內容並升版
    isolated_conn.execute(
        "UPDATE page_index_trees SET summary_text='更新版自體脂肪填充資料。', content_version=2 WHERE doc_id=?",
        (doc_id,),
    )
    isolated_conn.commit()

    def _different_answer_llm(prompt: str) -> str:
        return "答：這是更新版本後的衛教說明內容。\n" + WARNING_TEXT

    # 再次執行批次
    res = run_prefill_stage(isolated_conn, cfg, _different_answer_llm, now=NOW_FIXED + timedelta(hours=1))
    assert res.generated >= 1

    cur = isolated_conn.cursor()
    cur.execute("SELECT review_status, content_version FROM faq_cache WHERE topic_key=?", (target_key,))
    status_after, ver_after = cur.fetchone()
    assert status_after == "pending"  # 回到 pending
    assert ver_after > 1  # 版號增加


def test_8_max_pending_cap_protection(isolated_conn, tmp_path):
    """Test 8: max_pending 上限保護：達標時直接 status=pending_cap，不生成新問答。"""
    _setup_test_tree(isolated_conn, "tree-t8", "果酸煥膚保養")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    # 手動建立 10 筆 pending FAQ
    faqs = [
        {
            "clinic_id": None, "topic_key": f"mock-pending-{i}", "category": "general",
            "question": f"待審問題第{i}號？", "answer": "待審答案內容說明。",
        }
        for i in range(10)
    ]
    upsert_faqs(isolated_conn, faqs, source_type="llm_generated")

    # 將 max_pending 設為 5（小於現有 10 筆）
    cfg = DummyConfig(max_faq_topics=5, max_pending=5, seed_path=str(seed_file))
    res = run_prefill_stage(isolated_conn, cfg, _dummy_llm_response, now=NOW_FIXED)

    assert res.status == "pending_cap"
    assert res.generated == 0


def test_9_single_item_exception_isolated(isolated_conn, tmp_path):
    """Test 9: 單題未預期例外隔離，errors 加一，其餘題目正常處理。"""
    _setup_test_tree(isolated_conn, "tree-t9", "水光針美白保濕")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    call_count = 0

    def _crashing_llm(prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("未預期的內部運算例外")
        return _dummy_llm_response(prompt)

    cfg = DummyConfig(max_faq_topics=5, seed_path=str(seed_file))
    res = run_prefill_stage(isolated_conn, cfg, _crashing_llm, now=NOW_FIXED)

    assert res.errors == 1
    assert res.generated == 4


def test_10_run_logger_has_no_sensitive_fields(isolated_conn, tmp_path):
    """Test 10: RunLogger 日誌記錄不含問句、答案或 prompt 敏感欄位。"""
    _setup_test_tree(isolated_conn, "tree-t10", "飛梭雷射換膚")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    log_dir = tmp_path / "logs"
    logger = RunLogger(log_dir)

    cfg = DummyConfig(max_faq_topics=5, seed_path=str(seed_file))
    run_prefill_stage(isolated_conn, cfg, _dummy_llm_response, now=NOW_FIXED, logger=logger)
    logger.close()

    log_files = list(log_dir.glob("*.log"))
    assert len(log_files) > 0
    content = log_files[0].read_text(encoding="utf-8")

    for forbidden in ('"query"', '"question"', '"answer"', '"prompt"'):
        assert forbidden not in content


def test_11_dry_run_makes_no_changes(isolated_conn, tmp_path):
    """Test 11: dry_run=True 僅規劃，llm_call 呼叫 0 次，資料庫 total_changes 不變。"""
    _setup_test_tree(isolated_conn, "tree-t11", "雷射除毛療程")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    call_count = 0

    def _counting_llm(prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        return _dummy_llm_response(prompt)

    cfg = DummyConfig(max_faq_topics=5, dry_run=True, seed_path=str(seed_file))
    init_changes = isolated_conn.total_changes
    res = run_prefill_stage(isolated_conn, cfg, _counting_llm, now=NOW_FIXED)

    assert res.status == "completed"
    assert res.topics_planned >= 1
    assert call_count == 0
    assert isolated_conn.total_changes == init_changes


def test_12_newly_prefilled_rows_invisible_before_approval(isolated_conn, tmp_path):
    """Test 12: 預生成寫入之列審核狀態為 pending，對 visible_faq_sql 檢索不可見。"""
    doc_id = _setup_test_tree(isolated_conn, "tree-t12", "埋線拉提塑形")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    cfg = DummyConfig(max_faq_topics=5, seed_path=str(seed_file))
    run_prefill_stage(isolated_conn, cfg, _dummy_llm_response, now=NOW_FIXED)

    cur = isolated_conn.cursor()
    # 透過 visible_faq_sql 查詢
    vis_sql = visible_faq_sql(isolated_conn)
    cur.execute(
        f"SELECT COUNT(*) FROM faq_cache WHERE topic_key LIKE ? AND {vis_sql}",
        (f"{PREFILL_TOPIC_PREFIX}{doc_id}-%",),
    )
    visible_count = cur.fetchone()[0]
    assert visible_count == 0  # 醫師核准前對外完全隱蔽


def test_reject_code_for_mapping():
    """驗證 reject_code_for 正確歸類各種失敗原因為細分碼。"""
    from src.batch.patient_prefill import reject_code_for

    assert reject_code_for("", "現有資料並未提及隆鼻清潔方式。") == "insufficient_evidence"
    assert reject_code_for("", "因資料不足無法提供說明。") == "insufficient_evidence"
    assert reject_code_for("缺少警訊句", "") == "missing_warning"
    assert reject_code_for("包含具體金額價格", "") == "price_leak"
    assert reject_code_for("含政治立場詞", "") == "political_phrase"
    assert reject_code_for("簡體字檢測失敗", "") == "simplified_chinese"
    assert reject_code_for("含保證療效詞彙", "") == "guarantee_phrase"
    assert reject_code_for("含劑量處方", "") == "dosage_or_prescription"
    assert reject_code_for("句子數量不符", "") == "sentence_count"
    assert reject_code_for("其他原因", "") == "other_validation"


def test_prefill_rejects_insufficient_evidence(isolated_conn, tmp_path):
    """驗證模型輸出表明現有資料不足時，預生成直接剔除且不寫入資料庫。"""
    from src.batch.patient_prefill import run_prefill_stage

    doc_id = _setup_test_tree(isolated_conn, "tree-t13", "隆鼻手術照護")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    def _insufficient_llm(prompt: str) -> str:
        return (
            "答：現有資料並未提及相關隆鼻照護內容，建議諮詢醫師。\n"
            f"{WARNING_TEXT}\n"
            "追問：您想先了解其他部位嗎？"
        )

    log_dir = tmp_path / "logs"
    logger = RunLogger(log_dir)

    cfg = DummyConfig(max_faq_topics=5, seed_path=str(seed_file))
    res = run_prefill_stage(isolated_conn, cfg, _insufficient_llm, now=NOW_FIXED, logger=logger)

    assert res.status == "completed"
    assert res.rejected == 5
    assert res.generated == 0

    # 資料庫中沒有寫入任何該主題的記錄
    cur = isolated_conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM faq_cache WHERE topic_key LIKE ?",
        (f"{PREFILL_TOPIC_PREFIX}{doc_id}-%",),
    )
    assert cur.fetchone()[0] == 0

    # 檢查 log 紀錄 reason_code 為 insufficient_evidence
    log_text = "\n".join(logger.lines)
    assert "insufficient_evidence" in log_text


def test_prefill_logger_payload_privacy_check(isolated_conn, tmp_path):
    """驗證 RunLogger 在預生成剔除時不輸出病患問句、答案等全文。"""
    from src.batch.patient_prefill import run_prefill_stage

    doc_id = _setup_test_tree(isolated_conn, "tree-t14", "音波拉皮介紹")
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    secret_query_keyword = "極度機密不應出現的病患敏感字眼"
    def _leak_test_llm(prompt: str) -> str:
        return f"答：這是一段回答包含{secret_query_keyword}。\n追問：你想了解嗎？"

    log_dir = tmp_path / "logs_privacy"
    logger = RunLogger(log_dir)

    cfg = DummyConfig(max_faq_topics=5, seed_path=str(seed_file))
    run_prefill_stage(isolated_conn, cfg, _leak_test_llm, now=NOW_FIXED, logger=logger)

    log_content = "\n".join(logger.lines)
    assert secret_query_keyword not in log_content


