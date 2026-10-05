"""
tests/test_sync_general_validation.py - 雙向同步匯入對 general FAQ 之醫療合規驗證測試 (Phase 12 GC-02, GC-03)

驗證：
1. general FAQ 具備就醫警訊且無用藥劑量處方 -> 200 成功匯入
2. general FAQ 踩用藥劑量處方 -> 400 阻擋，detail 含「用藥劑量」且不洩漏答案原文，整批未寫入
3. general FAQ 缺就醫警訊 -> 400 阻擋，detail 含「何時該就醫」
4. special FAQ 踩用藥劑量處方 -> 200 成功（維持診所自有內容信任）
5. category 繞過防禦：非合法 special 者一律依 fail-closed 走 general 驗證
6. 缺省 category 預設為 special，維持向後相容
"""

import sqlite3
from fastapi.testclient import TestClient
import pytest

from src.api.app import create_app
from src.api.config import config


@pytest.fixture
def api_client(isolated_db_path, monkeypatch):
    """建立連線至獨立資料庫複本的 TestClient。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "admin_api_key", None)
    app = create_app()

    with TestClient(app) as client:
        yield client


def test_sync_import_general_faq_valid(api_client, isolated_db_path):
    """合規的 general FAQ（含就醫警訊、無用藥劑量）成功匯入。"""
    payload = {
        "clinic_id": "3503190424",
        "data": {
            "faqs": [
                {
                    "topic_key": "general-valid-cold",
                    "question": "感冒時在家要如何照護？",
                    "answer": "感冒期間應多休息並補充水分；若出現呼吸困難或胸痛，請立即前往急診就醫。",
                    "category": "general",
                }
            ]
        },
    }
    response = api_client.post("/api/v1/sync/import", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["faqs_inserted"] == 1

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    cur.execute("SELECT question, answer, category FROM faq_cache WHERE question = ?", ("感冒時在家要如何照護？",))
    row = cur.fetchone()
    conn.close()
    assert row is not None
    assert row[2] == "general"


def test_sync_import_general_faq_dosage_blocked_and_atomic(api_client, isolated_db_path):
    """
    general FAQ 含用藥處方劑量：
    - 回傳 HTTP 400
    - detail 含「用藥劑量」且絕不回顯答案原文
    - 整批原子性未寫入：同 payload 的另一筆合法 general FAQ 與 notes 亦未寫入
    """
    bad_answer = "若疼痛難耐建議吃止痛藥 500mg 每日三次以緩解症狀；若持續發燒請就醫。"
    payload = {
        "clinic_id": "3503190424",
        "sync_type": "full",
        "data": {
            "faqs": [
                {
                    "topic_key": "general-good",
                    "question": "合法的問題？",
                    "answer": "多喝水充分休息；若出現呼吸困難，請立即就醫。",
                    "category": "general",
                },
                {
                    "topic_key": "general-bad-dosage",
                    "question": "頭痛該吃什麼藥？",
                    "answer": bad_answer,
                    "category": "general",
                },
            ],
            "notes": [
                {
                    "section": "parking",
                    "note": "全新停車備註文字。",
                }
            ],
        },
    }
    response = api_client.post("/api/v1/sync/import", json=payload)
    assert response.status_code == 400
    detail = response.json().get("detail", "")
    assert "用藥劑量" in detail or "處方" in detail
    assert bad_answer not in detail, "detail 絕不可回顯違規答案原文"

    # 驗證整批未寫入
    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM faq_cache WHERE question IN ('合法的問題？', '頭痛該吃什麼藥？')")
    assert cur.fetchone()[0] == 0

    cur.execute("SELECT COUNT(*) FROM clinic_custom_notes WHERE note = '全新停車備註文字。'")
    assert cur.fetchone()[0] == 0
    conn.close()


def test_sync_import_general_faq_missing_doctor_warning_blocked(api_client, isolated_db_path):
    """general FAQ 缺少就醫警訊收尾句回傳 HTTP 400，detail 含「何時該就醫」。"""
    payload = {
        "clinic_id": "3503190424",
        "data": {
            "faqs": [
                {
                    "topic_key": "general-no-warning",
                    "question": "腸胃炎如何飲食？",
                    "answer": "急性期可少量補充清淡米湯或電解質液，待症狀好轉再循序漸進恢復正常飲食。",
                    "category": "general",
                }
            ]
        },
    }
    response = api_client.post("/api/v1/sync/import", json=payload)
    assert response.status_code == 400
    detail = response.json().get("detail", "")
    assert "何時該就醫" in detail or "警訊" in detail


def test_sync_import_special_faq_dosage_trusted(api_client, isolated_db_path):
    """special 類別維持診所自有內容信任：即使包含特定處方字句亦不被新層攔截。"""
    payload = {
        "clinic_id": "3503190424",
        "data": {
            "faqs": [
                {
                    "topic_key": "special-ingrown-care",
                    "question": "甲溝炎術後止痛說明？",
                    "answer": "醫師若開立止痛藥，請依藥袋指示服用；若有紅腫化膿請立即回診追蹤。",
                    "category": "special",
                }
            ]
        },
    }
    response = api_client.post("/api/v1/sync/import", json=payload)
    assert response.status_code == 200
    assert response.json()["summary"]["faqs_inserted"] == 1


def test_sync_import_category_bypass_defense(api_client, isolated_db_path):
    """
    category 繞過防禦（Fail-Closed）：
    非精準 'special' 者（如 'general ', ' general', 'GENERAL', None, 123 等），
    若包含違規用藥劑量，一律被攔截為 400，整批不寫入。
    """
    bypass_categories = ["general ", " general", "GENERAL", None, 123]

    for bad_cat in bypass_categories:
        payload = {
            "clinic_id": "3503190424",
            "sync_type": "full",
            "data": {
                "faqs": [
                    {
                        "topic_key": "bypass-test",
                        "question": f"繞過測試題_{bad_cat}？",
                        "answer": "建議吃止痛藥 500mg 每日三次。",
                        "category": bad_cat,
                    }
                ]
            },
        }
        res = api_client.post("/api/v1/sync/import", json=payload)
        assert res.status_code == 400, f"category={bad_cat!r} 應被阻擋但回傳 {res.status_code}"

    # 缺省 category 預設為 special，維持向後相容
    payload_default_special = {
        "clinic_id": "3503190424",
        "sync_type": "full",
        "data": {
            "faqs": [
                {
                    "topic_key": "special-default-cat",
                    "question": "預設為特殊主題之問題？",
                    "answer": "醫師若開立止痛藥，請依指示服用即可。",
                    # 缺少 category 欄位
                }
            ]
        },
    }
    res_def = api_client.post("/api/v1/sync/import", json=payload_default_special)
    assert res_def.status_code == 200
