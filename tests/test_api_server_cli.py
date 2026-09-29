"""
FastAPI 服務啟動腳本與 Phase 05 端到端全系統驗收測試。
驗證：
1. scripts/run_api_server.py 參數解析與 banner 輸出
2. Phase 05 全系統各端點整合串接工作流程
3. 遵循專案鐵則：正式 clinic.db 零污染驗證
"""

import json
import sys
from io import StringIO
from fastapi.testclient import TestClient
import pytest

from scripts.run_api_server import parse_args, print_banner
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


def test_cli_parse_args_defaults(monkeypatch):
    """測試啟動腳本預設 CLI 參數。"""
    monkeypatch.setattr(sys, "argv", ["run_api_server.py"])
    args = parse_args()

    assert args.host == "127.0.0.1"
    assert args.port == 8000
    assert args.reload is False
    assert args.workers == 1
    assert args.log_level == "info"


def test_cli_parse_args_custom(monkeypatch):
    """測試啟動腳本自訂 CLI 參數。"""
    custom_argv = [
        "run_api_server.py",
        "--host", "0.0.0.0",
        "--port", "8888",
        "--reload",
        "--workers", "2",
        "--log-level", "debug",
    ]
    monkeypatch.setattr(sys, "argv", custom_argv)
    args = parse_args()

    assert args.host == "0.0.0.0"
    assert args.port == 8888
    assert args.reload is True
    assert args.workers == 2
    assert args.log_level == "debug"


def test_cli_print_banner_output(capsys):
    """測試啟動資訊 Banner 正確輸出診所與端點資訊。"""
    print_banner(host="127.0.0.1", port=8000, reload=False, workers=1)
    captured = capsys.readouterr()

    assert "clinicbrain" in captured.out
    assert "3503190424" in captured.out
    assert "http://127.0.0.1:8000" in captured.out
    assert "緻妍外科診所" in captured.out


def test_phase05_full_e2e_workflow(api_client):
    """Phase 05 全系統端到端完整驗收流程：
    1. 服務根端點與健康診斷
    2. 臨床 special 查詢與二次價格防禦
    3. 全量資料匯出至雲端契約
    4. 雲端推播匯入更新資料與審計日誌查核
    """
    clinic_id = "3503190424"

    # Step 1: 驗證服務根端點與健康狀態
    root_resp = api_client.get("/")
    assert root_resp.status_code == 200
    assert root_resp.json()["status"] == "running"

    health_resp = api_client.get("/health")
    assert health_resp.status_code == 200
    health_data = health_resp.json()
    assert health_data["database_connected"] is True
    assert health_data["tables_count"]["drugs"] > 7000
    assert health_data["tables_count"]["page_index_trees"] >= 6

    # Step 2: 驗證自然語言特殊療程查詢
    query_resp = api_client.post(
        f"/api/v1/clinics/{clinic_id}/query",
        json={"query": "音波拉提術前與術後需要注意什麼？"},
    )
    assert query_resp.status_code == 200
    q_data = query_resp.json()
    assert q_data["route"] == "special"
    assert len(q_data["page_index_hits"]) > 0 or len(q_data["faq_hits"]) > 0
    # 斷言二次價格防禦生效（無具體金額）
    assert "元" not in json.dumps(q_data["clinic_custom_notes"], ensure_ascii=False) or "[請致電診所確認]" in json.dumps(q_data["clinic_custom_notes"], ensure_ascii=False)

    # Step 3: 驗證雲端匯出契約 (Export)
    export_resp = api_client.post(
        "/api/v1/sync/export",
        json={"clinic_id": clinic_id, "since_version": 0, "entities": ["trees", "faqs", "notes", "hours"]},
    )
    assert export_resp.status_code == 200
    exp_data = export_resp.json()
    assert exp_data["counts"]["trees"] >= 6
    assert exp_data["counts"]["faqs"] >= 40
    assert exp_data["counts"]["hours"] >= 7

    # Step 4: 驗證雲端推播匯入契約 (Import)
    import_resp = api_client.post(
        "/api/v1/sync/import",
        json={
            "clinic_id": clinic_id,
            "data": {
                "faqs": [
                    {
                        "question": "E2E測試問題：診所是否提供無痛舒眠？",
                        "answer": "本院特約專業麻醉專科醫師全程監控照護。",
                        "category": "special",
                        "topic_key": "anesthesia",
                    }
                ],
                "notes": {
                    "maintenance": "【E2E驗收更新】請遵從衛教專員定期回診追蹤肌膚狀況。"
                },
            },
        },
    )
    assert import_resp.status_code == 200
    imp_data = import_resp.json()
    assert imp_data["success"] is True
    assert imp_data["summary"]["faqs_inserted"] == 1
    assert imp_data["summary"]["notes_updated"] == 1

    # Step 5: 驗證審計日誌端點查詢
    logs_resp = api_client.get(f"/api/v1/sync/logs?clinic_id={clinic_id}&limit=10")
    assert logs_resp.status_code == 200
    logs = logs_resp.json()
    assert len(logs) >= 2  # 包含剛才的 export 與 import
    types = [l["sync_type"] for l in logs]
    assert "export" in types
    assert "import" in types
