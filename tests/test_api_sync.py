"""
FastAPI 雙向同步契約端點測試（Phase 05 TASK-03）。
涵蓋：
1. POST /api/v1/sync/export 增量匯出、實體篩選、價格全面遮蔽、審計日誌
2. POST /api/v1/sync/import 權威寫入路徑、content_version 遞增、冪等未變檢查
3. 合規安全防禦：保證療效禁詞攔截、政治立場攔截、簡體字轉換/攔截、價格清洗
4. 管理員 API 金鑰認證（X-API-Key 401 攔截與授權通過）
5. GET /api/v1/sync/logs 審計紀錄查詢

遵循專案鐵則：所有測試透過 isolated_db_path 進行，正式 clinic.db SHA-256 零變動。
"""

import json
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


def test_sync_export_all_entities(api_client, isolated_db_path):
    """測試匯出所有實體（trees, faqs, notes, hours），驗證資料結構與筆數。"""
    payload = {
        "clinic_id": "3503190424",
        "since_version": 0,
        "entities": ["trees", "faqs", "notes", "hours"],
    }
    response = api_client.post("/api/v1/sync/export", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["clinic_id"] == "3503190424"
    assert "exported_at" in data
    assert "counts" in data
    assert "data" in data

    counts = data["counts"]
    exported = data["data"]

    # 驗證四大實體皆有匯出且筆數符合
    assert counts["trees"] >= 6
    assert len(exported["trees"]) == counts["trees"]
    assert counts["faqs"] >= 40
    assert len(exported["faqs"]) == counts["faqs"]
    assert counts["notes"] >= 3
    assert counts["hours"] >= 7

    # 驗證樹狀結構中必要欄位
    first_tree = exported["trees"][0]
    assert "doc_id" in first_tree
    assert "pre_op" in first_tree
    assert "summary_text" in first_tree
    assert "content_version" in first_tree

    # 驗證 sync_logs 審計資料表有記錄
    conn = sqlite3.connect(str(isolated_db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT sync_type, direction, status, record_count FROM sync_logs ORDER BY id DESC LIMIT 1")
    log_row = cursor.fetchone()
    conn.close()

    assert log_row is not None
    assert log_row[0] == "export"
    assert log_row[1] == "pull"
    assert log_row[2] == "success"
    assert log_row[3] == sum(counts.values())


def test_sync_export_incremental_filtering(api_client):
    """測試 since_version 增量過濾邏輯。"""
    # 正常情況 content_version 通常為 1 或 2，若 since_version 設為 999 應無樹或 FAQ
    payload = {
        "clinic_id": "3503190424",
        "since_version": 999,
        "entities": ["trees", "faqs"],
    }
    response = api_client.post("/api/v1/sync/export", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["counts"]["trees"] == 0
    assert len(data["data"]["trees"]) == 0
    assert data["counts"]["faqs"] == 0
    assert len(data["data"]["faqs"]) == 0


def test_sync_export_deep_price_masking(api_client, isolated_db_path):
    """測試匯出資料具備嚴格二次價格遮蔽，絕不洩漏未遮蔽之金額。"""
    # 在測試庫的自訂備註中暫時插入含有具體金額的測試資料
    conn = sqlite3.connect(str(isolated_db_path))
    conn.execute(
        "UPDATE clinic_custom_notes SET note = '預付定金 5000 元，特價 NT$3888' WHERE clinic_id = '3503190424' AND section = 'pre_op'"
    )
    conn.commit()
    conn.close()

    payload = {
        "clinic_id": "3503190424",
        "since_version": 0,
        "entities": ["notes"],
    }
    response = api_client.post("/api/v1/sync/export", json=payload)
    assert response.status_code == 200
    data = response.json()

    pre_op_note = data["data"]["notes"]["pre_op"]
    # 斷言原始金額被遮蔽為 [請致電診所確認]
    assert "5000 元" not in pre_op_note
    assert "NT$3888" not in pre_op_note
    assert "[請致電診所確認]" in pre_op_note


def test_sync_import_trees_and_idempotency(api_client, isolated_db_path):
    """測試匯入臨床推理樹，驗證 content_version 遞增與二次匯入冪等性。"""
    # 1. 取得既有 hifu-lifting 的 content_version
    conn = sqlite3.connect(str(isolated_db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT content_version, pre_op_physician_notes FROM page_index_trees WHERE doc_id = 'hifu-lifting'")
    initial_tree = cursor.fetchone()
    init_version = initial_tree[0]
    conn.close()

    # 2. 第一次匯入：變更 pre_op_physician_notes
    update_payload = {
        "clinic_id": "3503190424",
        "data": {
            "trees": [
                {
                    "doc_id": "hifu-lifting",
                    "pre_op_physician_notes": "【醫師指示更新】術前請確實卸除金屬飾品並塗抹表面麻醉膏。",
                }
            ]
        },
    }
    resp1 = api_client.post("/api/v1/sync/import", json=update_payload)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["success"] is True
    assert data1["summary"]["trees_updated"] == 1

    # 驗證資料庫中的版本號遞增
    conn = sqlite3.connect(str(isolated_db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT content_version, pre_op_physician_notes FROM page_index_trees WHERE doc_id = 'hifu-lifting'")
    updated_tree = cursor.fetchone()
    conn.close()

    assert updated_tree[0] == init_version + 1
    assert "術前請確實卸除金屬飾品" in updated_tree[1]

    # 3. 第二次匯入相同內容：驗證冪等跳過（unchanged == 1，版本號不變）
    resp2 = api_client.post("/api/v1/sync/import", json=update_payload)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["summary"]["trees_updated"] == 0
    assert data2["summary"]["trees_unchanged"] == 1

    conn = sqlite3.connect(str(isolated_db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT content_version FROM page_index_trees WHERE doc_id = 'hifu-lifting'")
    same_version = cursor.fetchone()[0]
    conn.close()

    assert same_version == init_version + 1


def test_sync_import_faqs_and_notes(api_client, isolated_db_path):
    """測試匯入 FAQ 與診所自訂通用備註。"""
    import_payload = {
        "clinic_id": "3503190424",
        "data": {
            "faqs": [
                {
                    "question": "雲端同步測試問題：術後可以洗臉嗎？",
                    "answer": "術後當日建議以溫水輕柔潑洗，避免用力搓揉。",
                    "category": "special",
                    "topic_key": "general-care",
                }
            ],
            "notes": {
                "post_op_short": "【雲端同步更新】術後一週內嚴格禁止前往高溫場所與劇烈運動。"
            },
        },
    }
    response = api_client.post("/api/v1/sync/import", json=import_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["summary"]["faqs_inserted"] == 1
    assert data["summary"]["notes_updated"] == 1

    # 驗證資料庫寫入成功
    conn = sqlite3.connect(str(isolated_db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT answer FROM faq_cache WHERE question = '雲端同步測試問題：術後可以洗臉嗎？'")
    faq_row = cursor.fetchone()
    assert faq_row is not None
    assert "術後當日建議以溫水" in faq_row[0]

    cursor.execute("SELECT note FROM clinic_custom_notes WHERE clinic_id = '3503190424' AND section = 'post_op_short'")
    note_row = cursor.fetchone()
    assert note_row is not None
    assert "【雲端同步更新】" in note_row[0]
    conn.close()


def test_sync_import_rejects_forbidden_phrases(api_client):
    """測試匯入內容包含違法保證療效詞彙（如「保證根除」、「百分之百有效」）時被安全攔截。"""
    payload = {
        "clinic_id": "3503190424",
        "data": {
            "notes": {
                "pre_op": "本療程保證根除黑斑，百分之百有效。"
            }
        },
    }
    response = api_client.post("/api/v1/sync/import", json=payload)
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "保證療效" in detail or "保證根除" in detail


def test_sync_import_rejects_political_stance(api_client):
    """測試匯入內容包含政治爭議立場詞彙時被安全攔截。"""
    payload = {
        "clinic_id": "3503190424",
        "data": {
            "faqs": [
                {
                    "question": "診所服務範圍？",
                    "answer": "服務中國台灣地區全體民眾。",
                    "category": "special",
                }
            ]
        },
    }
    response = api_client.post("/api/v1/sync/import", json=payload)
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "政治立場" in detail


def test_sync_import_simplified_chinese_handling(api_client, isolated_db_path):
    """測試簡體中文處理：
    1. auto_convert_simplified=True 時自動轉為正體中文
    2. auto_convert_simplified=False 時攔截報錯
    """
    # 測試自動轉換
    auto_convert_payload = {
        "clinic_id": "3503190424",
        "auto_convert_simplified": True,
        "data": {
            "faqs": [
                {
                    "question": "术后注意事项是什么？",
                    "answer": "请遵医嘱按时服药与复诊。",
                    "category": "special",
                    "topic_key": "simplified-test",
                }
            ]
        },
    }
    resp1 = api_client.post("/api/v1/sync/import", json=auto_convert_payload)
    assert resp1.status_code == 200

    conn = sqlite3.connect(str(isolated_db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT question, answer FROM faq_cache WHERE topic_key = 'simplified-test'")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "術後注意事項是什麼？"
    assert "請遵醫囑" in row[1]

    # 測試停用自動轉換時檢出簡體即報錯
    strict_payload = {
        "clinic_id": "3503190424",
        "auto_convert_simplified": False,
        "data": {
            "notes": {
                "pre_op": "术前请勿进食"
            }
        },
    }
    resp2 = api_client.post("/api/v1/sync/import", json=strict_payload)
    assert resp2.status_code == 400
    assert "簡體中文" in resp2.json()["detail"]


def test_sync_import_washes_prices(api_client, isolated_db_path):
    """測試匯入資料若含有具體金額，自動清洗遮蔽為 [請致電診所確認]，避免價格洩漏進庫。"""
    payload = {
        "clinic_id": "3503190424",
        "data": {
            "notes": {
                "procedure": "本項微創療程單堂 1200 元，加購精華液特價 NT$500。"
            }
        },
    }
    response = api_client.post("/api/v1/sync/import", json=payload)
    assert response.status_code == 200

    conn = sqlite3.connect(str(isolated_db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT note FROM clinic_custom_notes WHERE clinic_id = '3503190424' AND section = 'procedure'")
    stored_note = cursor.fetchone()[0]
    conn.close()

    assert "1200 元" not in stored_note
    assert "NT$500" not in stored_note
    assert "[請致電診所確認]" in stored_note


def test_sync_admin_api_key_authentication(monkeypatch, isolated_db_path):
    """測試管理員金鑰認證：未授權 401 拒絕與帶 Header X-API-Key 授權通過。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "admin_api_key", "valid-clinic-secret-token")
    app = create_app()

    with TestClient(app) as client:
        payload = {
            "clinic_id": "3503190424",
            "data": {"notes": {"pre_op": "安全測試"}},
        }

        # 1. 未提供 X-API-Key -> 401
        res_no_key = client.post("/api/v1/sync/import", json=payload)
        assert res_no_key.status_code == 401

        # 2. 提供錯誤金鑰 -> 401
        res_wrong_key = client.post(
            "/api/v1/sync/import",
            json=payload,
            headers={"X-API-Key": "wrong-token"},
        )
        assert res_wrong_key.status_code == 401

        # 3. 提供正確金鑰 -> 200
        res_ok = client.post(
            "/api/v1/sync/import",
            json=payload,
            headers={"X-API-Key": "valid-clinic-secret-token"},
        )
        assert res_ok.status_code == 200


def test_get_sync_logs(api_client):
    """測試 GET /api/v1/sync/logs 查詢審計日誌端點。"""
    # 先觸發一次 export 產生日誌
    api_client.post(
        "/api/v1/sync/export",
        json={"clinic_id": "3503190424", "entities": ["notes"]},
    )

    response = api_client.get("/api/v1/sync/logs?clinic_id=3503190424&limit=5")
    assert response.status_code == 200
    logs = response.json()

    assert isinstance(logs, list)
    assert len(logs) >= 1
    first_log = logs[0]
    assert first_log["clinic_id"] == "3503190424"
    assert first_log["status"] == "success"
    assert "sync_type" in first_log
    assert "direction" in first_log
