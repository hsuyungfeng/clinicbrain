"""
Taiwan Clinic Medical PageIndex RAG System - SOAP 衛教提煉與草稿生成模組測試 (test_soap_distiller)
Phase 15 Plan 15-01: 臨床 SOAP 衛教提煉與草稿寫入測試
"""

import json
import sqlite3
import pytest

from src.soap.distiller import distill_soap_records
from src.soap.soap_writer import upsert_soap_records
from src.pageindex.faq_writer import upsert_faqs
from src.pageindex.faq_review import get_faq, list_faqs

CLINIC = "3503190424"


def _seed_sample_soap_records(conn: sqlite3.Connection):
    """前置準備：在測試連線插入 3 筆帶有相同條件與照護重點之去識別化 SOAP 紀錄。"""
    records = [
        {
            "external_id": "DIST-001",
            "patient_token": "PTK-D1",
            "subjective": "患者發燒與喉嚨痛發作。",
            "objective": "咽喉紅腫。",
            "assessment": "急性咽喉炎",
            "plan": "開立消炎藥。衛教：請多喝溫水與充分休息。衛教：避免油膩辛辣飲食。",
            "raw_text": "主訴：患者發燒與喉嚨痛發作。\n診斷：急性咽喉炎\n處置：衛教：請多喝溫水與充分休息。衛教：避免油膩辛辣飲食。",
        },
        {
            "external_id": "DIST-002",
            "patient_token": "PTK-D2",
            "subjective": "咽喉疼痛加劇。",
            "objective": "扁桃腺充血。",
            "assessment": "急性咽喉炎",
            "plan": "給予症狀治療。衛教事項：請多喝溫水與充分休息。",
            "raw_text": "主訴：咽喉疼痛加劇。\n診斷：急性咽喉炎\n處置：衛教事項：請多喝溫水與充分休息。",
        },
        {
            "external_id": "DIST-003",
            "patient_token": "PTK-D3",
            "subjective": "頭痛與流鼻水。",
            "objective": "鼻黏膜腫脹。",
            "assessment": "感冒",
            "plan": "衛教：多喝水休息。",
            "raw_text": "主訴：頭痛與流鼻水。\n診斷：感冒\n處置：衛教：多喝水休息。",
        },
    ]
    upsert_soap_records(conn, records, CLINIC)


def test_distill_soap_records_creates_pending_faq(isolated_conn):
    """測試從 soap_records 提煉衛教草稿，寫入 faq_cache 且預設為 pending 狀態。"""
    conn = isolated_conn
    _seed_sample_soap_records(conn)

    res = distill_soap_records(conn, CLINIC, min_occurrences=2)
    assert res["distilled_count"] >= 1
    assert "急性咽喉炎" in res["conditions"]

    # 驗證寫入 faq_cache 記錄
    faqs = list_faqs(conn, status="pending", source_type="soap_distilled")
    assert len(faqs) == 1

    faq = faqs[0]
    assert faq["clinic_id"] == CLINIC
    assert faq["category"] == "special"
    assert faq["source_type"] == "soap_distilled"
    assert faq["review_status"] == "pending"
    assert "【照護指引】罹患急性咽喉炎應注意哪些居家照護事項？" in faq["question"]
    assert "多喝溫水與充分休息" in faq["answer"]
    assert "【就醫警訊】" in faq["answer"]
    assert "【免責聲明】" in faq["answer"]

    # 驗證 metadata 溯源資訊
    assert "metadata" in faq
    meta = json.loads(faq["metadata"])
    assert meta["source"] == "soap_distilled"
    assert meta["record_count"] == 2
    assert meta["condition"] == "急性咽喉炎"


def test_distill_soap_records_masks_prices(isolated_conn):
    """測試提煉過程自動執行價格數字清洗。"""
    conn = isolated_conn
    records = [
        {
            "external_id": "DIST-PRICE-01",
            "patient_token": "PTK-P1",
            "assessment": "過敏性鼻炎",
            "plan": "衛教：諮詢自費噴劑費用 2000元 整，多喝水休息。",
            "raw_text": "診斷：過敏性鼻炎\n處置：衛教：諮詢自費噴劑費用 2000元 整，多喝水休息。",
        },
        {
            "external_id": "DIST-PRICE-02",
            "patient_token": "PTK-P2",
            "assessment": "過敏性鼻炎",
            "plan": "衛教：諮詢自費噴劑費用 2000元 整，多喝水休息。",
            "raw_text": "診斷：過敏性鼻炎\n處置：衛教：諮詢自費噴劑費用 2000元 整，多喝水休息。",
        },
    ]
    upsert_soap_records(conn, records, CLINIC)

    res = distill_soap_records(conn, CLINIC, min_occurrences=2)
    assert res["distilled_count"] >= 1

    faqs = list_faqs(conn, status="pending", source_type="soap_distilled")
    target = [f for f in faqs if "過敏性鼻炎" in f["question"]][0]

    assert "2000元" not in target["answer"]
    assert "[請致電診所確認]" in target["answer"]


def test_distill_soap_records_empty_records_returns_zero(isolated_conn):
    """測試查無 SOAP 紀錄時回傳 0 筆。"""
    res = distill_soap_records(isolated_conn, CLINIC, min_occurrences=2)
    assert res["distilled_count"] == 0
    assert res["conditions"] == []
    assert res["faqs"] == []
