"""Phase 20：管理端「向 LLM 提問」——只依對外可見資料作答、紅旗／無資料不呼叫模型。"""

import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config
from src.api.routes import admin as admin_mod
from src.pageindex.faq_writer import upsert_faqs

CLINIC = "3503190424"
TOKEN_OK = "鈦合金星海療程"      # 測試專用罕見詞，避免命中真實資料
TOKEN_PENDING = "水晶月光療程"


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "admin_api_key", "")
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(isolated_db_path):
    conn = sqlite3.connect(str(isolated_db_path))
    yield conn
    conn.close()


def _seed_visible_and_pending(db):
    upsert_faqs(db, [{"clinic_id": CLINIC, "topic_key": "p20-ok", "category": "special",
                      "question": f"{TOKEN_OK}術後可以洗臉嗎？",
                      "answer": f"{TOKEN_OK}術後隔天即可輕柔洗臉，避免用力搓揉，保持清潔乾燥。"}], source_type="clinic_upload")
    upsert_faqs(db, [{"clinic_id": CLINIC, "topic_key": "p20-pend", "category": "special",
                      "question": f"{TOKEN_PENDING}術後可以洗臉嗎？",
                      "answer": f"{TOKEN_PENDING}尚未審核的機密內容不可外洩。"}], source_type="web_upload")


def test_answers_from_visible_data_only(client, db, monkeypatch):
    _seed_visible_and_pending(db)
    seen = {}

    def fake(prompt):
        seen["prompt"] = prompt
        return "術後隔天即可輕柔洗臉並保持清潔乾燥 [F1]。若出現高燒超過3天或傷口化膿，請儘速就醫。"

    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", fake)
    r = client.post("/api/v1/admin/ask", json={"question": f"{TOKEN_OK}術後可以洗臉嗎？", "clinic_id": CLINIC})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "answered" and body["used_llm"] and body["compliance"]["ok"]
    assert any(s["type"] == "faq" for s in body["sources"])
    assert TOKEN_OK in seen["prompt"]

    # 未核准草稿即使問句直接命中，也不得進入模型 context
    seen.clear()
    r2 = client.post("/api/v1/admin/ask", json={"question": f"{TOKEN_PENDING}術後可以洗臉嗎？", "clinic_id": CLINIC}).json()
    assert "機密內容" not in seen.get("prompt", "")   # 問句本身會出現在 prompt，但待審「答案」不得進入
    assert "機密內容" not in r2["answer"]


def test_no_evidence_skips_llm(client, monkeypatch):
    calls = []
    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", lambda p: calls.append(p) or "x")
    r = client.post("/api/v1/admin/ask", json={"question": "龘龘鱻爨靐麤", "clinic_id": CLINIC}).json()
    assert r["mode"] == "no_evidence" and r["used_llm"] is False and r["sources"] == [] and calls == []


def test_red_flag_skips_llm(client, monkeypatch):
    calls = []
    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", lambda p: calls.append(p) or "x")
    r = client.post("/api/v1/admin/ask", json={"question": "我現在胸痛喘不過氣怎麼辦", "clinic_id": CLINIC}).json()
    assert r["mode"] == "red_flag" and r["red_flag_level"] and calls == []
    assert "119" in r["answer"] or "急診" in r["answer"]


def test_output_prices_masked_and_noncompliant_flagged(client, db, monkeypatch):
    _seed_visible_and_pending(db)
    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", lambda p: f"{TOKEN_OK}費用約 15000 元，保證有效，百分之百有效。")
    r = client.post("/api/v1/admin/ask", json={"question": f"{TOKEN_OK}術後可以洗臉嗎？", "clinic_id": CLINIC}).json()
    assert "15000" not in r["answer"]
    assert r["compliance"]["ok"] is False and r["compliance"]["reason"]


def test_validation_auth_and_errors(client, db, isolated_db_path, monkeypatch):
    from src.pageindex.llm_client import LocalLLMUnavailableError

    assert client.post("/api/v1/admin/ask", json={"question": "", "clinic_id": CLINIC}).status_code == 422
    assert client.post("/api/v1/admin/ask", json={"question": "字" * 301, "clinic_id": CLINIC}).status_code == 422
    assert client.post("/api/v1/admin/ask", json={"question": "測試", "clinic_id": CLINIC, "x": 1}).status_code == 422
    assert client.post("/api/v1/admin/ask", json={"question": "測試", "clinic_id": "9999999999"}).status_code == 404

    _seed_visible_and_pending(db)

    def down(p):
        raise LocalLLMUnavailableError("offline")

    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", down)
    q = {"question": f"{TOKEN_OK}術後可以洗臉嗎？", "clinic_id": CLINIC}
    assert client.post("/api/v1/admin/ask", json=q).status_code == 503

    assert admin_mod._GENERATION_LOCK.acquire(blocking=False)
    try:
        assert client.post("/api/v1/admin/ask", json=q).status_code == 429
    finally:
        admin_mod._GENERATION_LOCK.release()

    monkeypatch.setattr(config, "allow_no_auth", False)
    monkeypatch.setattr(config, "admin_api_key", "k-ask")
    assert client.post("/api/v1/admin/ask", json=q).status_code == 401


def test_ask_is_read_only(client, db, isolated_db_path, monkeypatch):
    """提問不得改動資料庫（以 total_changes 與列數比對）。"""
    _seed_visible_and_pending(db)
    before = db.execute("SELECT COUNT(*), SUM(content_version) FROM faq_cache").fetchone()
    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", lambda p: "術後隔天可輕柔洗臉。若高燒超過3天請儘速就醫。")
    client.post("/api/v1/admin/ask", json={"question": f"{TOKEN_OK}術後可以洗臉嗎？", "clinic_id": CLINIC})
    assert db.execute("SELECT COUNT(*), SUM(content_version) FROM faq_cache").fetchone() == before


def test_ui_has_ask_tab_and_no_html_injection(client):
    html = client.get("/admin/").text
    assert 'data-tab="tab-ask"' in html and 'id="tab-ask"' in html and 'id="btnAsk"' in html
    # 順序：向 LLM 提問頁籤在 SOAP 之後
    assert html.index('data-tab="tab-soap"') < html.index('data-tab="tab-ask"')
    js = client.get("/admin/app.js").text
    ask = js[js.index("// 7. 向 LLM 提問"):]
    assert "/api/v1/admin/ask" in ask
    assert not re.search(r"innerHTML|insertAdjacentHTML|document\.write|outerHTML|eval\(", ask)


def test_ask_uses_faithful_sampling_without_repetition_penalty(monkeypatch):
    """RAG 提問必須單次關閉重複懲罰（否則模型會為避免重複而改字／掉字），且不影響預設呼叫。"""
    import json
    from src.pageindex import llm_client

    sent = []

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"choices": [{"message": {"content": "答案"}}]}).encode()

    monkeypatch.setattr(llm_client, "check_llm_health", lambda timeout=5: "ok")
    monkeypatch.setattr(llm_client.urllib.request, "urlopen", lambda req, timeout=0: sent.append(json.loads(req.data)) or _Resp())
    admin_mod._local_llm_ask_call("q")
    llm_client.local_llm_call("q")
    assert sent[0]["dry_multiplier"] == 0.0 and sent[0]["repeat_penalty"] == 1.0 and sent[0]["temperature"] == 0.1
    assert "dry_multiplier" not in sent[1] and "repeat_penalty" not in sent[1]
