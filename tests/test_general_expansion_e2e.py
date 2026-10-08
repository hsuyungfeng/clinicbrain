"""
Taiwan Clinic Medical PageIndex RAG System - 一般醫學知識批次與審核流端到端測試 (test_general_expansion_e2e)
Phase 17 Plan 17-03: 通用衛教審核流擴充與端到端閉環測試
"""

import json
from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient

import scripts.review_faq as review_cli
from src.api.app import app
from src.api.config import config
from src.batch.runner import BatchConfig, run_batch
from src.pageindex.faq_review import get_faq


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    """建立指向 isolated_db_path 測試複本之 TestClient。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    with TestClient(app) as test_client:
        yield test_client


from src.batch.run_log import RunLogger


def _dummy_llm(prompt: str) -> str:
    """Mock LLM 回應產生器：針對 general 類別主題產生合格問答 JSON。"""
    lines = prompt.splitlines()
    q_list = []
    for l in lines:
        if (l.startswith("- ") or l.startswith("Q")) and "？" in l:
            q_list.append(l.lstrip("- Q").strip())

    items = []
    for q in q_list:
        if "高血壓" in q:
            items.append({
                "question": "什麼是高血壓？",
                "answer": "高血壓是指血管壓力持續高於正常值。平時應規律測量血壓、減少鹽分攝取與維持適度運動。若出現頭痛加重或心胸不適，請儘速就醫。",
            })
        else:
            items.append({
                "question": q,
                "answer": f"關於{q[:8]}之專業衛教說明。若出現高燒持續加重、呼吸困難或急性腹痛發作，請儘速就醫。",
            })
    if not items:
        items.append({
            "question": "什麼是高血壓？",
            "answer": "高血壓是指血管壓力持續高於正常值。平時應規律測量血壓、減少鹽分攝取與維持適度運動。若出現頭痛加重或心胸不適，請儘速就醫。",
        })

    return json.dumps(items, ensure_ascii=False)


def test_general_expansion_e2e_lifecycle(client, isolated_db_path, capsys, tmp_path):
    """測試端到端閉環生命週期：general-only 夜間批次 -> pending 草稿 -> 匿名端點不可見 -> pending-summary CLI 篩選 -> 醫師簽核 -> 端點命中。"""
    db_path = isolated_db_path
    conn = sqlite3.connect(str(db_path))
    logger = RunLogger(tmp_path / "logs", echo=False)

    try:
        # 1. 執行 --general-only 夜間批次
        b_config = BatchConfig(
            seed_path=Path("data/batch/faq_seeds.json"),
            snapshot_dir=tmp_path / "snapshots",
            general_only=True,
            max_faq_topics=1,
        )
        summary = run_batch(
            conn,
            b_config,
            llm_call=_dummy_llm,
            health_check=lambda: None,
            logger=logger,
        )
        assert summary.general_generated_count >= 1
        assert summary.soap_distilled_count == 0

        # 確認 faq_cache 中有 pending 狀態之 general 紀錄
        cur = conn.cursor()
        cur.execute(
            "SELECT id, topic_key, question, category, review_status FROM faq_cache WHERE category = 'general' AND review_status = 'pending'"
        )
        rows = cur.fetchall()
        assert len(rows) >= 1
        pending_id, topic_key, pending_q, category, review_status = rows[0]
        assert category == "general"
        assert review_status == "pending"

        # 2. 驗證 /api/v1/general/query 匿名端點 Fail-Closed 防禦（pending 草稿不可見）
        gen_resp_before = client.post(
            "/api/v1/general/query",
            json={"query": pending_q},
        )
        assert gen_resp_before.status_code == 200
        data_before = gen_resp_before.json()
        assert data_before["status"] != "answered" or len(data_before["faq_hits"]) == 0

        # 3. 測試 review_faq.py pending-summary --category general 通報輸出
        ret = review_cli.main(["--db", str(db_path), "pending-summary", "--category", "general"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "【LLM 預生成通用衛教草稿】" in captured.out
        assert f"ID {pending_id}" in captured.out

        # 4. 模擬醫師執行審核核准 approve
        ret_app = review_cli.main(["--db", str(db_path), "approve", str(pending_id)])
        assert ret_app == 0

        faq_approved = get_faq(conn, pending_id)
        assert faq_approved["review_status"] == "approved"

        # 5. 再次呼叫 /api/v1/general/query 驗證核准後可查詢命中
        gen_resp_after = client.post(
            "/api/v1/general/query",
            json={"query": pending_q},
        )
        assert gen_resp_after.status_code == 200
        data_after = gen_resp_after.json()
        assert data_after["status"] == "answered"
        assert len(data_after["faq_hits"]) >= 1
        assert faq_approved["answer"] in data_after["faq_hits"][0]["answer"]

    finally:
        conn.close()
