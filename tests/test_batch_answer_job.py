"""Phase 21：標題片段生成（以文件內文為依據）與背景批次補齊作業。"""

import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config
from src.api.routes import admin as admin_mod
from src.pageindex import batch_answer_job
from src.pageindex.answer_generator import classify_draft, is_answer_thin
from src.pageindex.faq_writer import upsert_faqs

CLINIC = "3503190424"
PH = "【診所文件】{t} - 指示 {n}"
ANSWER = (
    "常見的疑難傷口包括糖尿病足潰瘍、血管性潰瘍與壓力性傷口，共同特點是在正常照護下超過六週仍難以癒合。"
    "這類傷口常與血糖控制不佳、血液循環不良或長期受壓有關，需要由醫師評估原因後再規劃處置。"
    "日常請保持傷口清潔乾燥並依醫囑換藥，避免自行處理。"
    "若傷口出現紅腫熱痛加劇、化膿、異味或發燒超過38.5度，請儘速就醫。"
)
TOPIC_OUT = "問題：常見的疑難傷口有哪些類型？\n答案：" + ANSWER


@pytest.fixture(autouse=True)
def _reset_job():
    batch_answer_job._state = None
    batch_answer_job._cancel.clear()
    yield
    batch_answer_job._cancel.set()
    batch_answer_job.wait(10)
    batch_answer_job._state = None


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


def _doc(db, key, rows):
    upsert_faqs(db, [{"clinic_id": CLINIC, "topic_key": f"doc-{key}", "category": "special",
                      "question": PH.format(t=key, n=i), "answer": a} for i, a in enumerate(rows, 1)],
                source_type="web_upload")
    return [r[0] for r in db.execute("SELECT id FROM faq_cache WHERE topic_key=? ORDER BY id", (f"doc-{key}",))]


def _wait_done(client, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        s = client.get("/api/v1/admin/review/batch-generate/status").json()
        if s["state"] != "running":
            return s
        time.sleep(0.05)
    raise AssertionError("job did not finish")


BODY = "困難傷口是指在正常照護下超過六週難以癒合的傷口，這些傷口可能無法經由正常的癒合過程恢復，常見於糖尿病足潰瘍與壓力性傷口患者身上。"


# ---------------- 類型判定 ----------------
def test_classify_draft_cases():
    q = PH.format(t="x", n=1)
    assert classify_draft(q, "- 常見疑難傷口型別") == ("topic", "常見疑難傷口型別")      # 使用者實例 ID 671
    assert classify_draft(q, "困難傷口與PRP使用") == ("topic", "困難傷口與PRP使用")
    assert classify_draft(q, "4. Endolift與其他治療有何不同？")[0] == "question"
    assert classify_draft(q, BODY)[0] == "content"
    assert classify_draft(q, "第一行\n第二行")[0] == "content"
    assert classify_draft("術後多久可以洗臉？", "短")[0] == "question"
    assert is_answer_thin(q, "- 定義疑難傷口") is True and is_answer_thin(q, BODY) is False


# ---------------- 標題片段：以文件內文為依據 ----------------
def test_topic_fragment_generated_from_document_context(client, db, monkeypatch):
    ids = _doc(db, "p21doc", ["困難傷口與PRP使用", BODY, "- 定義疑難傷口", "- 常見疑難傷口型別", BODY + "第二段。"])
    seen = {}
    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", lambda p: seen.setdefault("p", p) and TOPIC_OUT)
    r = client.post(f"/api/v1/admin/review/faqs/{ids[3]}/generate-answer", json={})
    assert r.status_code == 200, r.text
    assert r.json()["question"] == "常見的疑難傷口有哪些類型？"
    assert "糖尿病足潰瘍" in db.execute("SELECT answer FROM faq_cache WHERE id=?", (ids[3],)).fetchone()[0]
    assert BODY[:20] in seen["p"] and "常見疑難傷口型別" in seen["p"] and "定義疑難傷口" in seen["p"]   # 內文＋大綱皆入 prompt
    assert db.execute("SELECT review_status FROM faq_cache WHERE id=?", (ids[3],)).fetchone()[0] == "pending"


def test_topic_without_context_or_insufficient_data_is_rejected(client, db, monkeypatch):
    (only,) = _doc(db, "p21solo", ["- 孤立的小標題"])
    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", lambda p: TOPIC_OUT)
    assert client.post(f"/api/v1/admin/review/faqs/{only}/generate-answer", json={}).status_code == 422
    ids = _doc(db, "p21insuf", [BODY, "- 無關標題"])
    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", lambda p: "資料不足")
    assert client.post(f"/api/v1/admin/review/faqs/{ids[1]}/generate-answer", json={}).status_code == 422
    assert db.execute("SELECT answer FROM faq_cache WHERE id=?", (ids[1],)).fetchone()[0] == "- 無關標題"


def test_topic_bad_question_falls_back(client, db, monkeypatch):
    ids = _doc(db, "p21fb", [BODY, "- 常見疑難傷口型別"])
    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", lambda p: "問題：隨便\n答案：" + ANSWER)
    assert client.post(f"/api/v1/admin/review/faqs/{ids[1]}/generate-answer", json={}).status_code == 200
    assert db.execute("SELECT question FROM faq_cache WHERE id=?", (ids[1],)).fetchone()[0] == "關於「常見疑難傷口型別」有哪些重點？"


# ---------------- 背景批次作業 ----------------
def test_batch_job_fills_all_and_keeps_pending(client, db, monkeypatch):
    ids = _doc(db, "p21job", [BODY, "- 標題甲", "- 標題乙", "- 標題丙"])
    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", lambda p: TOPIC_OUT)
    r = client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": ids[1:]})
    assert r.status_code == 200 and r.json()["total"] == 3
    s = _wait_done(client)
    assert s["state"] == "done" and s["ok"] == 3 and s["failed"] == []
    for fid in ids[1:]:
        assert db.execute("SELECT review_status FROM faq_cache WHERE id=?", (fid,)).fetchone()[0] == "pending"


def test_duplicate_model_questions_in_one_document_are_all_filled(client, db, monkeypatch):
    """模型對不同標題擬出相同問句時，不得讓後面的題目失敗或被誤判為略過。"""
    ids = _doc(db, "p21dup", [BODY, "- 標題甲", "- 標題乙"])
    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", lambda p: TOPIC_OUT)   # 兩題都回同一問句
    client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": ids[1:]})
    s = _wait_done(client)
    assert s["ok"] == 2 and s["failed"] == [] and s["skipped"] == 0
    qs = [r[0] for r in db.execute("SELECT question FROM faq_cache WHERE id IN (?,?)", ids[1:])]
    assert len(set(qs)) == 2 and any("有哪些重點" in q for q in qs)


def test_batch_job_isolates_failures_and_skips_ineligible(client, db, monkeypatch):
    ids = _doc(db, "p21mix", [BODY, "- 標題一", "- 標題二", "- 標題三"])
    client.post("/api/v1/admin/review/batch", json={"action": "approve", "faq_ids": [ids[3]]})   # 已核准 → 略過
    calls = {"n": 0}

    def flaky(p):
        calls["n"] += 1
        return "資料不足" if calls["n"] == 1 else TOPIC_OUT

    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", flaky)
    client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": ids[1:]})
    s = _wait_done(client)
    assert s["state"] == "done" and s["ok"] == 1 and len(s["failed"]) == 1 and s["skipped"] == 1


def test_batch_job_overwrite_regenerates_already_complete_pending_faqs(client, db, monkeypatch):
    """已有完整答案的待審草稿（如 71 筆基層疾病 FAQ），預設 skipped=1；帶 overwrite=True 時可強制重新生成。"""
    upsert_faqs(
        db,
        [{
            "clinic_id": None,
            "topic_key": "icd-j069-uri",
            "category": "general",
            "question": "感冒一般多久會好？",
            "answer": "一般感冒多由病毒引起，多數人在一到兩週內可逐漸緩解，期間可多休息、補充水分並注意保暖。若出現高燒不退或呼吸急促，請儘速就醫。",
        }],
        source_type="llm_generated",
    )
    fid = db.execute("SELECT id FROM faq_cache WHERE topic_key='icd-j069-uri'").fetchone()[0]
    monkeypatch.setattr(admin_mod, "_local_llm_call", lambda p: ANSWER)

    # 1. 未帶 overwrite：因答案已完整（>=30字），視為略過（skipped=1, ok=0）
    r1 = client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": [fid]})
    assert r1.status_code == 200
    s1 = _wait_done(client)
    assert s1["ok"] == 0 and s1["skipped"] == 1

    # 2. 帶 overwrite=True：強制由本機 LLM 重新生成並覆寫（ok=1, skipped=0）
    batch_answer_job._state = None
    r2 = client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": [fid], "overwrite": True})
    assert r2.status_code == 200
    s2 = _wait_done(client)
    assert s2["ok"] == 1 and s2["skipped"] == 0
    new_ans = db.execute("SELECT answer FROM faq_cache WHERE id=?", (fid,)).fetchone()[0]
    assert "糖尿病足潰瘍" in new_ans


def test_batch_job_aborts_when_llm_down(client, db, monkeypatch):
    from src.pageindex.llm_client import LocalLLMUnavailableError

    ids = _doc(db, "p21down", [BODY, "- 標題甲", "- 標題乙", "- 標題丙"])
    n = {"c": 0}

    def down(p):
        n["c"] += 1
        raise LocalLLMUnavailableError("offline")

    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", down)
    client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": ids[1:]})
    s = _wait_done(client)
    assert s["state"] == "aborted" and n["c"] == 1 and s["processed"] == 1     # 不空轉剩餘題目


def test_batch_job_single_instance_and_cancel(client, db, monkeypatch):
    ids = _doc(db, "p21cancel", [BODY, "- 標題甲", "- 標題乙", "- 標題丙"])
    gate = threading.Event()
    started = threading.Event()

    def slow(p):
        started.set()
        gate.wait(10)
        return TOPIC_OUT

    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", slow)
    assert client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": ids[1:]}).status_code == 200
    assert started.wait(5)
    assert client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": ids[1:]}).status_code == 409   # 同時只有一個
    assert client.post("/api/v1/admin/review/batch-generate/cancel").json()["cancelling"] is True
    gate.set()
    s = _wait_done(client)
    assert s["state"] == "cancelled" and s["processed"] == 1 and s["ok"] == 1     # 目前題完成後停止
    untouched = db.execute("SELECT answer FROM faq_cache WHERE id=?", (ids[3],)).fetchone()[0]
    assert untouched == "- 標題丙"


def test_batch_generate_validation_auth_and_status(client, isolated_db_path, monkeypatch):
    assert client.get("/api/v1/admin/review/batch-generate/status").json()["state"] == "idle"
    assert client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": []}).status_code == 422
    assert client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": list(range(1, 102))}).status_code == 422
    assert client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": ["1"]}).status_code == 422
    assert client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": [True]}).status_code == 422
    monkeypatch.setattr(config, "allow_no_auth", False)
    monkeypatch.setattr(config, "admin_api_key", "k21")
    for method, url, body in (("post", "/api/v1/admin/review/batch-generate", {"faq_ids": [1]}),
                              ("get", "/api/v1/admin/review/batch-generate/status", None),
                              ("post", "/api/v1/admin/review/batch-generate/cancel", None)):
        r = getattr(client, method)(url, **({"json": body} if body is not None else {}))
        assert r.status_code == 401, url
