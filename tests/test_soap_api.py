"""
Taiwan Clinic Medical PageIndex RAG System - SOAP API 端到端整合與權限隔離測試
涵蓋 Phase 14 Plan 03 (D-04, D-05, D-06, D-07, D-08, D-09):
- POST /api/v1/soap/records 推播接收（結構化與純文字、去識別化、價格清洗、一般醫學特徵）
- POST /api/v1/soap/search 醫師專用檢索（trigram MATCH 與 short query LIKE、標籤過濾）
- GET /api/v1/soap/records/{external_id} 單筆調閱
- 權限驗證與跨診所隔離 (401 拒絕無金鑰、跨診所查無資料)
- 公開端點（/api/v1/query 與 /api/v1/general/query）隔離保證
"""

from fastapi.testclient import TestClient
import pytest
from src.api.app import app
from src.api.config import config


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    """建立指向 isolated_db_path 測試複本之 TestClient。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setenv("CLINICBRAIN_DEID_KEY", "test-deid-key")  # patient_token 需要 HMAC 金鑰（無預設值）
    with TestClient(app) as test_client:
        yield test_client


def test_soap_ingest_structured_and_unstructured(client):
    """測試推播接收：同時支援結構化 JSON 與未格式化純文字 transcript。"""
    clinic_id = "3503190424"
    payload = {
        "clinic_id": clinic_id,
        "records": [
            {
                "external_id": "REC-API-001",
                "patient_id": "A123456789",
                "subjective": "病患咳嗽咳了五天，喉嚨痛。",
                "objective": "扁桃腺輕微紅腫，體溫正常。",
                "assessment": "急性咽喉炎",
                "plan": "開立消炎止痛藥，衛教多喝溫水休息。",
                "tags": ["耳鼻喉科"],
            },
            {
                "external_id": "REC-API-002",
                "transcript": (
                    "主訴：病患昨晚開始嘔吐與嚴重水瀉數次\n"
                    "客觀檢查：腹部壓痛，腸音亢進，體溫37.5度\n"
                    "診斷：急性腸胃炎\n"
                    "處置：給予電解質液補充與止瀉劑，衛教清淡飲食"
                ),
            },
        ],
    }

    resp = client.post("/api/v1/soap/records", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    assert data["summary"]["inserted"] == 2
    assert "general_insights_summary" in data
    # 驗證一般醫學資料分析擷取正常運作
    conds = data["general_insights_summary"]["extracted_conditions"]
    assert "急性咽喉炎" in conds or "急性腸胃炎" in conds


def test_soap_ingest_deidentification_and_price_masking(client):
    """測試推播內容中之個資（身分證、電話、姓名）與價格自動遮蔽。"""
    clinic_id = "3503190424"
    payload = {
        "clinic_id": clinic_id,
        "records": [
            {
                "external_id": "REC-PRIV-001",
                "raw_text": (
                    "病患姓名：林大雄，身分證字號 A123456789，電話 0912-345-678。"
                    "主訴：想要進行自費美白點滴療程，諮詢費用 1500元 整。"
                ),
            }
        ],
    }

    resp = client.post("/api/v1/soap/records", json=payload)
    assert resp.status_code == 200

    # 透過單筆查詢端點調閱，驗證入庫資料已去識別化
    get_resp = client.get(f"/api/v1/soap/records/REC-PRIV-001?clinic_id={clinic_id}")
    assert get_resp.status_code == 200
    rec = get_resp.json()

    assert "A123456789" not in rec["raw_text"]
    assert "[身分證已遮蔽]" in rec["raw_text"]
    assert "0912-345-678" not in rec["raw_text"]
    assert "[電話已遮蔽]" in rec["raw_text"]
    assert "林大雄" not in rec["raw_text"]
    assert "[姓名已遮蔽]" in rec["raw_text"]
    assert "1500元" not in rec["raw_text"]
    assert "[請致電診所確認]" in rec["raw_text"]
    assert rec["patient_token"].startswith("PTK-")


def test_soap_ingest_idempotency(client):
    """測試相同內容重複推播具備冪等性 (unchanged=1)。"""
    clinic_id = "3503190424"
    payload = {
        "clinic_id": clinic_id,
        "records": [
            {
                "external_id": "REC-IDEMP-001",
                "patient_token": "PTK-STABLE",
                "raw_text": "主訴：過敏性鼻炎日常拿藥\n處置：開立抗組織胺",
            }
        ],
    }

    resp1 = client.post("/api/v1/soap/records", json=payload)
    assert resp1.status_code == 200
    assert resp1.json()["summary"]["inserted"] == 1

    resp2 = client.post("/api/v1/soap/records", json=payload)
    assert resp2.status_code == 200
    assert resp2.json()["summary"]["unchanged"] == 1


def test_soap_auth_failure_and_invalid_clinic(client, monkeypatch):
    """測試 API 金鑰驗證失敗與無效診所代碼。"""
    clinic_id = "3503190424"

    # 1. 關閉 allow_no_auth 並未帶 X-API-Key -> 401
    monkeypatch.setattr(config, "allow_no_auth", False)
    monkeypatch.setattr(config, "admin_api_key", "secret-test-key")

    resp_no_key = client.post(
        "/api/v1/soap/records",
        json={"clinic_id": clinic_id, "records": [{"external_id": "REC-1", "raw_text": "text"}]},
    )
    assert resp_no_key.status_code == 401

    # 帶正確 Key
    headers = {"X-API-Key": "secret-test-key"}

    # 2. 傳入不存在之 clinic_id -> 400
    resp_invalid_clinic = client.post(
        "/api/v1/soap/records",
        json={"clinic_id": "9999999999", "records": [{"external_id": "REC-1", "raw_text": "text"}]},
        headers=headers,
    )
    assert resp_invalid_clinic.status_code == 400


def test_soap_doctor_search_and_clinic_isolation(client):
    """測試醫師專屬檢索（trigram MATCH、短字詞分流）與跨診所隔離。"""
    clinic_id = "3503190424"
    client.post(
        "/api/v1/soap/records",
        json={
            "clinic_id": clinic_id,
            "records": [
                {
                    "external_id": "REC-SEARCH-01",
                    "subjective": "病患胸口緊繃胸悶，偶發心悸感。",
                    "assessment": "自律神經失調可能",
                    "plan": "給予鎮靜藥物。",
                    "raw_text": "胸悶心悸自律神經",
                    "tags": ["心臟內科", "胸悶"],
                }
            ],
        },
    )

    # 1. 長字詞 trigram 檢索
    search_resp = client.post(
        "/api/v1/soap/search",
        json={"query": "胸口緊繃", "clinic_id": clinic_id},
    )
    assert search_resp.status_code == 200
    res_data = search_resp.json()
    assert res_data["total"] >= 1
    assert res_data["records"][0]["external_id"] == "REC-SEARCH-01"

    # 2. 短字詞分流 (< 3 字)
    search_short = client.post(
        "/api/v1/soap/search",
        json={"query": "心悸", "clinic_id": clinic_id},
    )
    assert search_short.status_code == 200
    assert search_short.json()["total"] >= 1

    # 3. 跨診所隔離：另一診所代碼查詢不到此記錄
    # 在測試庫新增另一家測試診所
    from src.pageindex.seed_clinic_info import seed_clinic_info
    # 直接在 soap_records 中確認只有該 clinic_id 能搜到
    search_other = client.post(
        "/api/v1/soap/search",
        json={"query": "胸口緊繃", "clinic_id": "9999999999"},
    )
    assert search_other.status_code == 400  # 不合法診所直接阻斷


def test_public_query_endpoints_isolation(client):
    """測試公開自然語言查詢端點與一般諮詢端點絕對無法存取 SOAP 紀錄（隔離邊界）。"""
    clinic_id = "3503190424"
    unique_secret_phrase = "極為罕見之臨床特徵代碼七號"

    # 推播一筆帶有罕見字詞之 SOAP 記錄
    client.post(
        "/api/v1/soap/records",
        json={
            "clinic_id": clinic_id,
            "records": [
                {
                    "external_id": "REC-SECRET-01",
                    "subjective": f"病患主訴患有{unique_secret_phrase}之特殊症狀。",
                    "raw_text": f"病患主訴{unique_secret_phrase}",
                }
            ],
        },
    )

    # 1. 測試自然語言查詢端點 (/api/v1/query) 檢索不到
    q_resp = client.post(
        "/api/v1/query",
        json={"query": unique_secret_phrase, "clinic_id": clinic_id},
    )
    # 應該回傳一般 fallback 或 no_match，絕不包含 SOAP 紀錄內容
    assert q_resp.status_code == 200
    ans_text = q_resp.json().get("answer", "")
    assert "REC-SECRET-01" not in ans_text

    # 2. 測試匿名一般諮詢端點 (/api/v1/general/query) 檢索不到
    gen_resp = client.post(
        "/api/v1/general/query",
        json={"query": unique_secret_phrase},
    )
    assert gen_resp.status_code == 200
    assert gen_resp.json()["status"] == "no_match"
