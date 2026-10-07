"""
tests/test_soap_hardening.py - Phase 14 SOAP 去識別化與 API 防護補強（複審）

涵蓋：
1. 身分證／電話緊鄰中文字時仍須遮蔽（\\b 在 Unicode 下不視中英文交界為邊界）
2. 「姓名」標籤後無分隔符的姓名遮蔽
3. patient_token 的 HMAC 金鑰必須來自環境變數，不得內建預設 salt（無金鑰 fail-closed）
4. 外部傳入的 patient_token／external_id／tags 不得夾帶個資
5. 例外不得經 HTTP 回應洩漏內部訊息；LIKE 萬用字元須跳脫
"""

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config
from src.soap.deid import DeidKeyError, deidentify_text, generate_patient_token

CLINIC = "3503190424"


@pytest.mark.parametrize(
    "text,leaked",
    [
        ("病患身分證字號A123456789，請回診", "A123456789"),
        ("身分證A123456789", "A123456789"),
        ("聯絡電話0912345678請回電", "0912345678"),
        ("聯絡電話0912-345-678請回電", "0912-345-678"),
        ("電話04-23950960請回電", "23950960"),
        ("居留證FA12345678備查", "FA12345678"),
        ("姓名王小明，主訴頭痛", "王小明"),
        ("病患姓名王小明主訴頭痛", "王小明"),
        ("患者：王小明 主訴頭痛", "王小明"),
    ],
)
def test_deid_masks_pii_adjacent_to_cjk(text, leaked):
    assert leaked not in deidentify_text(text)


def test_deid_does_not_overmask_clinical_text():
    t = "患者持續發燒三天，體溫38.5度，血壓120/80，處方0.5mg"
    assert deidentify_text(t) == t


def test_token_requires_key(monkeypatch):
    monkeypatch.delenv("CLINICBRAIN_DEID_KEY", raising=False)
    monkeypatch.delenv("CLINICBRAIN_ADMIN_API_KEY", raising=False)
    with pytest.raises(DeidKeyError):
        generate_patient_token("A123456789", CLINIC)


def test_token_depends_on_key_and_is_deterministic(monkeypatch):
    monkeypatch.delenv("CLINICBRAIN_ADMIN_API_KEY", raising=False)
    monkeypatch.setenv("CLINICBRAIN_DEID_KEY", "key-one")
    a1 = generate_patient_token("PID-1", CLINIC)
    a2 = generate_patient_token("PID-1", CLINIC)
    monkeypatch.setenv("CLINICBRAIN_DEID_KEY", "key-two")
    b = generate_patient_token("PID-1", CLINIC)
    assert a1 == a2 and a1 != b and a1.startswith("PTK-")


def test_token_dedicated_key_preferred_over_admin_key(monkeypatch):
    monkeypatch.setenv("CLINICBRAIN_ADMIN_API_KEY", "admin")
    monkeypatch.setenv("CLINICBRAIN_DEID_KEY", "deid")
    t = generate_patient_token("P", CLINIC)
    monkeypatch.delenv("CLINICBRAIN_DEID_KEY")
    assert generate_patient_token("P", CLINIC) != t  # 退回 admin key 時結果不同


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setenv("CLINICBRAIN_DEID_KEY", "test-key")
    with TestClient(app) as c:
        yield c


def _post(client, rec):
    return client.post("/api/v1/soap/records", json={"clinic_id": CLINIC, "records": [rec]})


def test_api_missing_key_returns_503_without_detail(client, monkeypatch):
    monkeypatch.delenv("CLINICBRAIN_DEID_KEY")
    monkeypatch.delenv("CLINICBRAIN_ADMIN_API_KEY", raising=False)
    r = _post(client, {"external_id": "H-1", "patient_id": "A123456789", "subjective": "咳嗽"})
    assert r.status_code == 503
    assert "A123456789" not in r.text


@pytest.mark.parametrize("token", ["A123456789", "0912345678", "王小明", "PTK X", "x" * 80])
def test_api_rejects_pii_like_patient_token(client, token):
    r = _post(client, {"external_id": "H-2", "patient_token": token, "subjective": "咳嗽"})
    assert r.status_code == 400
    assert token not in r.text


def test_api_accepts_normal_token(client):
    r = _post(client, {"external_id": "H-3", "patient_token": "PTK-ABC_123", "subjective": "咳嗽"})
    assert r.status_code == 200


def test_api_rejects_pii_in_external_id(client):
    r = _post(client, {"external_id": "A123456789", "patient_token": "PTK-1", "subjective": "咳嗽"})
    assert r.status_code == 400


def test_api_tags_are_deidentified(client):
    r = _post(client, {
        "external_id": "H-4", "patient_token": "PTK-4", "subjective": "咳嗽",
        "tags": ["耳鼻喉科", "電話0912345678"],
    })
    assert r.status_code == 200
    g = client.get("/api/v1/soap/records/H-4", params={"clinic_id": CLINIC}).json()
    assert all("0912345678" not in t for t in g["tags"])


def test_api_internal_error_does_not_leak(client, monkeypatch):
    import src.api.routes.soap as soap_routes

    def boom(*a, **k):
        raise RuntimeError("SECRET-INTERNAL-PATH /var/db")

    monkeypatch.setattr(soap_routes, "upsert_soap_records", boom)
    r = _post(client, {"external_id": "H-5", "patient_token": "PTK-5", "subjective": "咳嗽"})
    assert r.status_code == 500
    assert "SECRET-INTERNAL" not in r.text


def test_search_like_wildcards_escaped(client):
    for i, s in enumerate(["咳嗽", "頭痛"]):
        assert _post(client, {"external_id": f"W-{i}", "patient_token": "PTK-W", "subjective": s}).status_code == 200
    r = client.post("/api/v1/soap/search", json={"clinic_id": CLINIC, "query": "%"})
    assert r.status_code == 200
    assert r.json()["total"] == 0  # 「%」只比對字面百分號，不得變成萬用字元
