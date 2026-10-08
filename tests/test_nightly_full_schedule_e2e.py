"""
Taiwan Clinic Medical PageIndex RAG System - 全系統定時排程端到端驗收測試 (test_nightly_full_schedule_e2e)
Phase 16 Plan 16-03: Systemd 排程單元、晨間審核通報與端到端排程閉環驗收
"""

from pathlib import Path
import sqlite3
import pytest

from src.batch.run_log import RunLogger
from src.batch.runner import BatchConfig, run_batch
from src.pageindex.faq_review import get_faq, set_review_status
from src.query.router import handle_query
from src.soap.soap_writer import upsert_soap_records
from src.sync.soap_sync_runner import sync_soap_records_before_batch
import scripts.review_faq as review_cli

CLINIC = "3503190424"


def test_nightly_full_schedule_e2e_lifecycle(isolated_db_path: Path, tmp_path: Path, capsys):
    """
    端到端排程閉環測試：
    1. 前置增量同步入庫 SOAP 紀錄。
    2. 夜間批次自動執行提煉，產出 pending 衛教草稿。
    3. 驗證審核閘門：未核准前，公開自然語言查詢端點絕對不可見（不觸發快取短路）。
    4. 晨間醫師通報：執行 review_faq.py pending-summary 輸出全區塊摘要。
    5. 醫師簽核核准草稿。
    6. 再次檢索：公開查詢端點成功短路命中該衛教快取！
    """
    db_path = isolated_db_path
    conn = sqlite3.connect(str(db_path))

    try:
        # ---------------------------------------------------------------------
        # 1. 步驟一：前置 SOAP 紀錄同步
        # ---------------------------------------------------------------------
        raw_soap = [
            {
                "clinic_id": CLINIC,
                "external_id": "e2e-soap-01",
                "patient_token": "PTK-E2E01",
                "raw_text": "S: 吞嚥困難，喉嚨痛發燒。 O: 咽喉粘膜充血。 A: 急性咽喉炎 P: 衛教：請多喝溫水與充分休息。開立消炎止痛藥。",
                "subjective": "吞嚥困難，喉嚨痛發燒。",
                "objective": "咽喉粘膜充血。",
                "assessment": "急性咽喉炎",
                "plan": "衛教：請多喝溫水與充分休息。開立消炎止痛藥。",
            },
            {
                "clinic_id": CLINIC,
                "external_id": "e2e-soap-02",
                "patient_token": "PTK-E2E02",
                "raw_text": "S: 喉嚨痛2天。 O: 咽喉紅腫。 A: 急性咽喉炎 P: 衛教：請多喝溫水與充分休息。",
                "subjective": "喉嚨痛2天。",
                "objective": "咽喉紅腫。",
                "assessment": "急性咽喉炎",
                "plan": "衛教：請多喝溫水與充分休息。",
            },
        ]

        sync_res = sync_soap_records_before_batch(conn, CLINIC, local_records=raw_soap)
        assert sync_res.status == "completed"
        assert sync_res.inserted == 2

        # ---------------------------------------------------------------------
        # 2. 步驟二：夜間批次執行提煉 (soap_only=True)
        # ---------------------------------------------------------------------
        seed_file = tmp_path / "seeds.json"
        seed_file.write_text('{"schema_version": 1, "topics": [], "tree_procedure_names": {}}', encoding="utf-8")
        log_dir = tmp_path / "logs"
        logger = RunLogger(log_dir, echo=False)

        cfg = BatchConfig(
            seed_path=seed_file,
            snapshot_dir=tmp_path / "snapshots",
            dry_run=False,
            soap_only=True,
            soap_clinic_id=CLINIC,
            soap_min_occurrences=2,
        )

        summary = run_batch(conn, cfg, llm_call=lambda p: "", health_check=lambda: None, logger=logger)
        assert summary.status == "completed"
        assert summary.soap_distilled_count == 1
        assert summary.soap_conditions == ["急性咽喉炎"]

        # 取得剛產出之 FAQ ID
        cur = conn.cursor()
        cur.execute("SELECT id FROM faq_cache WHERE topic_key = 'care-急性咽喉炎'")
        faq_row = cur.fetchone()
        assert faq_row is not None
        pending_id = faq_row[0]

        # ---------------------------------------------------------------------
        # 3. 步驟三：審核閘門防禦（未核准前對外不可見）
        # ---------------------------------------------------------------------
        q_text = "【照護指引】罹患急性咽喉炎應注意哪些居家照護事項？"
        q_res_before = handle_query(conn, q_text, clinic_id=CLINIC)
        assert q_res_before.source != "cache", "未簽核之 pending FAQ 不得觸發快取短路！"

        # ---------------------------------------------------------------------
        # 4. 步驟四：晨間醫師通報 CLI (pending-summary)
        # ---------------------------------------------------------------------
        ret = review_cli.main(["--db", str(db_path), "pending-summary"])
        assert ret == 0

        captured = capsys.readouterr()
        assert "晨間醫師簽核通報摘要" in captured.out
        assert "待簽核草稿總筆數：1 筆" in captured.out
        assert "SOAP 臨床病歷提煉衛教草稿" in captured.out
        assert "急性咽喉炎" in captured.out
        assert "參考病歷: 2 筆" in captured.out

        # ---------------------------------------------------------------------
        # 5. 步驟五：醫師審核核准
        # ---------------------------------------------------------------------
        app_res = set_review_status(conn, [pending_id], "approved")
        assert app_res.changed == [pending_id]

        approved_faq = get_faq(conn, pending_id)
        assert approved_faq["review_status"] == "approved"

        # ---------------------------------------------------------------------
        # 6. 步驟六：核准後公開端點短路命中
        # ---------------------------------------------------------------------
        q_res_after = handle_query(conn, q_text, clinic_id=CLINIC)
        assert q_res_after.source == "cache", "核准後之 FAQ 必須成功觸發快取短路！"
        assert "請多喝溫水與充分休息" in q_res_after.cache_answer
        assert "【就醫警訊】" in q_res_after.cache_answer
        assert "【免責聲明】" in q_res_after.cache_answer

    finally:
        conn.close()
