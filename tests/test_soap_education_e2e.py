"""
Taiwan Clinic Medical PageIndex RAG System - SOAP 衛教提煉與審核流端到端測試 (test_soap_education_e2e)
Phase 15 Plan 15-03: 端到端閉環測試（推播 -> 提煉 pending -> 公開端點不可見 -> 審核 approved -> 查詢短路命中）
"""

import json
import sqlite3
import pytest
from fastapi.testclient import TestClient

import scripts.distill_soap_faqs as distill_script
from src.api.app import app
from src.api.config import config
from src.pageindex.faq_review import get_faq, set_review_status
from src.soap.distiller import distill_soap_records
from src.soap.soap_writer import upsert_soap_records

CLINIC = "3503190424"


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    """建立指向 isolated_db_path 測試複本之 TestClient。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setenv("CLINICBRAIN_DEID_KEY", "test-deid-key")
    with TestClient(app) as test_client:
        yield test_client


def _seed_five_soap_records(conn: sqlite3.Connection):
    """插入 5 筆包含「急性咽喉炎」與照護重點之 SOAP 紀錄。"""
    records = []
    for i in range(1, 6):
        records.append({
            "external_id": f"E2E-SOAP-00{i}",
            "patient_token": f"PTK-E{i}",
            "subjective": f"病患主訴咽喉疼痛發燒第 {i} 天。",
            "objective": "咽喉黏膜急性充血。",
            "assessment": "急性咽喉炎",
            "plan": "開立症狀緩解藥物。衛教：請多喝溫水與充分休息。衛教：避免油膩辛辣飲食。",
            "raw_text": f"主訴：咽喉疼痛\n診斷：急性咽喉炎\n處置：衛教：請多喝溫水與充分休息。衛教：避免油膩辛辣飲食。",
        })
    upsert_soap_records(conn, records, CLINIC)


def test_soap_education_e2e_lifecycle(client, isolated_db_path):
    """測試端到端閉環生命週期：SOAP 推播 -> 提煉 pending -> 公開不可見 -> 醫師簽核 -> 查詢命中。"""
    db_path = isolated_db_path
    conn = sqlite3.connect(str(db_path))

    try:
        # 1. SOAP 紀錄推播入庫
        _seed_five_soap_records(conn)

        # 2. 執行衛教提煉
        res = distill_soap_records(conn, CLINIC, min_occurrences=2)
        assert res["distilled_count"] >= 1
        assert "急性咽喉炎" in res["conditions"]

        cur = conn.cursor()
        cur.execute("SELECT id, review_status FROM faq_cache WHERE topic_key = 'care-急性咽喉炎'")
        row = cur.fetchone()
        assert row is not None
        faq_id, review_status = row
        assert review_status == "pending"

        # 3. 呼叫公開自然語言查詢端點 (/api/v1/query)，驗證 pending 狀態絕對不可見（隔離性）
        q_resp_before = client.post(
            "/api/v1/query",
            json={"query": "急性咽喉炎 居家照護", "clinic_id": CLINIC},
        )
        assert q_resp_before.status_code == 200
        data_before = q_resp_before.json()
        assert data_before.get("source") != "cache"  # 絕對不可透過快取短路命中未核准項目
        assert "【照護指引】" not in data_before.get("answer", "")

        # 4. 醫師審核工具核准該筆 FAQ
        review_res = set_review_status(conn, [faq_id], "approved")
        assert review_res.changed == [faq_id]

        faq_approved = get_faq(conn, faq_id)
        assert faq_approved["review_status"] == "approved"

        # 5. 再次呼叫公開自然語言查詢端點，驗證核准後成功短路命中
        q_resp_after = client.post(
            "/api/v1/query",
            json={"query": "【照護指引】罹患急性咽喉炎應注意哪些居家照護事項？", "clinic_id": CLINIC},
        )
        assert q_resp_after.status_code == 200
        data_after = q_resp_after.json()
        assert data_after["source"] == "cache"
        assert data_after["data_level"] == "clinic"
        assert "多喝溫水與充分休息" in data_after["cache_answer"]
    finally:
        conn.close()


def test_distill_cli_script_dry_run(isolated_db_path, capsys):
    """測試 distill_soap_faqs.py CLI 腳本 --dry-run 功能。"""
    db_path = isolated_db_path
    conn = sqlite3.connect(str(db_path))
    try:
        _seed_five_soap_records(conn)
    finally:
        conn.close()

    # 執行 dry-run
    ret = distill_script.main(["--clinic-id", CLINIC, "--db", str(db_path), "--dry-run"])
    assert ret == 0

    captured = capsys.readouterr()
    assert "Dry-Run 模式" in captured.out
    assert "未對資料庫進行任何實質修改" in captured.out

    # 驗證資料庫無任何提煉產物寫入
    conn2 = sqlite3.connect(str(db_path))
    try:
        cur = conn2.cursor()
        cur.execute("SELECT COUNT(*) FROM faq_cache WHERE source_type = 'soap_distilled'")
        assert cur.fetchone()[0] == 0
    finally:
        conn2.close()
