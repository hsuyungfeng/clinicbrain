"""Phase 19：批量簽核、內聯編輯與本機 LLM 答案生成 API 測試（全程使用複本資料庫與假 LLM）。"""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config
from src.api.routes import admin as admin_mod
from src.pageindex.faq_writer import upsert_faqs

CLINIC = "3503190424"
GOOD_ANSWER = (
    "術後初期請保持傷口清潔乾燥，避免劇烈運動與長時間曝曬，並依醫囑回診追蹤。"
    "日常可適度冰敷減輕腫脹感，睡眠時墊高頭部有助於消腫，飲食以清淡均衡為主，避免菸酒。"
    "若傷口出現紅腫熱痛加劇、化膿或有異味，請勿自行處理，應回診由醫師評估。"
    "若出現高燒超過3天、持續劇烈疼痛或呼吸困難，請儘速就醫。"
)


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


def _seed(db, topic, items, source="web_upload"):
    faqs = [
        {"clinic_id": CLINIC, "topic_key": topic, "question": q, "answer": a, "category": "special"}
        for q, a in items
    ]
    upsert_faqs(db, faqs, source_type=source)
    return [r[0] for r in db.execute("SELECT id FROM faq_cache WHERE topic_key=? ORDER BY id", (topic,))]


def _row(db, fid):
    return db.execute("SELECT question, answer, review_status, source_type FROM faq_cache WHERE id=?", (fid,)).fetchone()


# ---------------- 批量簽核 ----------------
def test_batch_approve_and_reject(client, db):
    ids = _seed(db, "p19-batch", [(f"批次測試問題{i}？", f"請保持清潔，若出現高燒超過3天或呼吸困難請儘速就醫{i}。") for i in range(4)])
    r = client.post("/api/v1/admin/review/batch", json={"action": "approve", "faq_ids": ids[:3]})
    assert r.status_code == 200 and r.json()["success_count"] == 3
    r = client.post("/api/v1/admin/review/batch", json={"action": "reject", "faq_ids": ids[3:]})
    assert r.json()["success_count"] == 1
    assert [_row(db, i)[2] for i in ids] == ["approved"] * 3 + ["rejected"]


def test_batch_limits_and_validation(client):
    assert client.post("/api/v1/admin/review/batch", json={"action": "approve", "faq_ids": list(range(1, 102))}).status_code == 422
    assert client.post("/api/v1/admin/review/batch", json={"action": "approve", "faq_ids": []}).status_code == 422
    assert client.post("/api/v1/admin/review/batch", json={"action": "delete", "faq_ids": [1]}).status_code == 422
    assert client.post("/api/v1/admin/review/batch", json={"action": "approve", "faq_ids": ["1; DROP TABLE faq_cache"]}).status_code == 422
    assert client.post("/api/v1/admin/review/batch", json={"action": "approve", "faq_ids": [True]}).status_code == 422
    assert client.post("/api/v1/admin/review/batch", json={"action": "approve", "faq_ids": [1], "x": 1}).status_code == 422


def test_batch_reports_failed_ids_and_keeps_others(client, db):
    ids = _seed(db, "p19-partial", [("部分失敗問題一？", "請保持清潔並依醫囑回診追蹤。"), ("部分失敗問題二？", "本療程保證有效，百分之百有效。")])
    r = client.post("/api/v1/admin/review/batch", json={"action": "approve", "faq_ids": ids + [999999]}).json()
    assert r["success_count"] == 1 and set(r["failed_ids"]) == {ids[1], 999999}
    assert _row(db, ids[0])[2] == "approved" and _row(db, ids[1])[2] == "pending"


def test_batch_rolls_back_on_unexpected_error(client, db, monkeypatch):
    ids = _seed(db, "p19-rollback", [("回滾問題？", "請保持清潔並依醫囑回診追蹤。")])
    import src.pageindex.faq_review as fr

    real = fr.set_review_status

    def boom(conn, ids_, status_, **kw):
        conn.execute("UPDATE faq_cache SET review_status='approved' WHERE id=?", (ids_[0],))
        raise RuntimeError("boom")

    monkeypatch.setattr(fr, "set_review_status", boom)
    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.post("/api/v1/admin/review/batch", json={"action": "approve", "faq_ids": ids}).status_code == 500
    monkeypatch.setattr(fr, "set_review_status", real)
    assert _row(db, ids[0])[2] == "pending"


# ---------------- 內聯編輯 ----------------
def test_patch_edit_sanitizes_and_keeps_pending(client, db):
    (fid,) = _seed(db, "p19-patch", [("編輯測試問題？", "原始答案請保持清潔並依醫囑回診。")])
    r = client.patch(f"/api/v1/admin/review/faqs/{fid}", json={"answer": "請保持清潔，療程費用 30000 元，電話0912345678。若高燒超過3天請儘速就醫。"})
    assert r.status_code == 200
    q, a, st, _ = _row(db, fid)
    assert "30000" not in a and "0912345678" not in a and st == "pending"


def test_patch_rejects_unsafe_and_approved_and_unknown(client, db):
    ids = _seed(db, "p19-patch2", [("編輯測試二？", "請保持清潔並依醫囑回診追蹤。"), ("編輯測試三？", "請保持清潔並依醫囑回診追蹤。")])
    assert client.patch(f"/api/v1/admin/review/faqs/{ids[0]}", json={"answer": "保證有效，百分之百有效"}).status_code == 422
    assert client.patch(f"/api/v1/admin/review/faqs/{ids[0]}", json={}).status_code == 422
    assert client.patch(f"/api/v1/admin/review/faqs/{ids[0]}", json={"answer": "   "}).status_code == 422
    client.post("/api/v1/admin/review/batch", json={"action": "approve", "faq_ids": [ids[1]]})
    assert client.patch(f"/api/v1/admin/review/faqs/{ids[1]}", json={"answer": "改寫已核准內容"}).status_code == 409
    assert client.patch("/api/v1/admin/review/faqs/999999", json={"answer": "x"}).status_code == 404


def test_patch_refuses_non_gated_sources(client, db):
    (fid,) = _seed(db, "p19-manual", [("手寫來源問題？", "手寫答案請保持清潔並依醫囑回診追蹤。")], source="manual")
    assert client.patch(f"/api/v1/admin/review/faqs/{fid}", json={"answer": "想偷改對外內容"}).status_code == 409


def test_patch_duplicate_question_conflict(client, db):
    ids = _seed(db, "p19-dup", [("重複題目甲？", "答案甲請保持清潔並依醫囑回診。"), ("重複題目乙？", "答案乙請保持清潔並依醫囑回診。")])
    assert client.patch(f"/api/v1/admin/review/faqs/{ids[0]}", json={"question": "重複題目乙？"}).status_code == 422


# ---------------- AI 生成 ----------------
def test_generate_answer_placeholder_question_list(client, db, monkeypatch):
    monkeypatch.setattr(admin_mod, "_local_llm_call", lambda p: GOOD_ANSWER)
    (fid,) = _seed(db, "doc-p19-endo", [("【診所文件】p19-endo - 指示 1", "4. Endolift與其他非手術治療眼袋有何不同？")])
    r = client.post(f"/api/v1/admin/review/faqs/{fid}/generate-answer", json={})
    assert r.status_code == 200, r.text
    q, a, st, _ = _row(db, fid)
    assert q == "Endolift與其他非手術治療眼袋有何不同？"  # 佔位題改為真正問句
    assert a == GOOD_ANSWER and st == "pending"
    meta = json.loads(db.execute("SELECT metadata FROM faq_cache WHERE id=?", (fid,)).fetchone()[0])
    assert meta["answer_source"] == "local_llm"


def test_generate_answer_masks_prices_or_rejects(client, db, monkeypatch):
    monkeypatch.setattr(admin_mod, "_local_llm_call", lambda p: GOOD_ANSWER.replace("均衡為主", "均衡為主，療程費用約 15000 元"))
    (fid,) = _seed(db, "p19-gen-price", [("價格洩漏測試問題？", "短答")])
    r = client.post(f"/api/v1/admin/review/faqs/{fid}/generate-answer", json={})
    assert r.status_code == 200
    assert "15000" not in _row(db, fid)[1]


@pytest.mark.parametrize(
    "bad",
    [
        "太短。",
        "請多休息。" * 30,  # 長度合格但缺就醫警訊
        GOOD_ANSWER + "本療程保證有效。",
        GOOD_ANSWER + "建議每次服用2顆。",
    ],
)
def test_generate_answer_rejects_noncompliant_output(client, db, monkeypatch, bad):
    monkeypatch.setattr(admin_mod, "_local_llm_call", lambda p: bad)
    (fid,) = _seed(db, "p19-gen-bad", [("不合規輸出測試？", "短答")])
    r = client.post(f"/api/v1/admin/review/faqs/{fid}/generate-answer", json={})
    assert r.status_code == 422
    assert _row(db, fid)[1] == "短答"  # 未寫入


def test_generate_answer_llm_down_and_guards(client, db, monkeypatch):
    from src.pageindex.llm_client import LocalLLMUnavailableError

    def down(p):
        raise LocalLLMUnavailableError("offline")

    monkeypatch.setattr(admin_mod, "_local_llm_call", down)
    (fid,) = _seed(db, "p19-gen-down", [("離線測試問題？", "短答")])
    assert client.post(f"/api/v1/admin/review/faqs/{fid}/generate-answer", json={}).status_code == 503
    # 已有完整答案：需明確 overwrite
    monkeypatch.setattr(admin_mod, "_local_llm_call", lambda p: GOOD_ANSWER)
    (full,) = _seed(db, "p19-gen-full", [("完整答案題目？", GOOD_ANSWER)])
    assert client.post(f"/api/v1/admin/review/faqs/{full}/generate-answer", json={}).status_code == 409
    assert client.post(f"/api/v1/admin/review/faqs/{full}/generate-answer", json={"overwrite": True}).status_code == 200
    # 已核准不可改寫、非待審來源不可生成、未知欄位被拒
    client.post("/api/v1/admin/review/batch", json={"action": "approve", "faq_ids": [full]})
    assert client.post(f"/api/v1/admin/review/faqs/{full}/generate-answer", json={"overwrite": True}).status_code == 409
    (man,) = _seed(db, "p19-gen-man", [("手寫題目？", "短答")], source="manual")
    assert client.post(f"/api/v1/admin/review/faqs/{man}/generate-answer", json={}).status_code == 409
    assert client.post(f"/api/v1/admin/review/faqs/{fid}/generate-answer", json={"x": 1}).status_code == 422
    assert client.post("/api/v1/admin/review/faqs/999999/generate-answer", json={}).status_code == 404


def test_generate_answer_busy_returns_429(client, db, monkeypatch):
    (fid,) = _seed(db, "p19-gen-busy", [("忙碌測試問題？", "短答")])
    assert admin_mod._GENERATION_LOCK.acquire(blocking=False)
    try:
        assert client.post(f"/api/v1/admin/review/faqs/{fid}/generate-answer", json={}).status_code == 429
    finally:
        admin_mod._GENERATION_LOCK.release()


def test_new_endpoints_require_admin_key(isolated_db_path, monkeypatch):
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", False)
    monkeypatch.setattr(config, "admin_api_key", "k-p19")
    with TestClient(app) as c:
        assert c.post("/api/v1/admin/review/batch", json={"action": "approve", "faq_ids": [1]}).status_code == 401
        assert c.patch("/api/v1/admin/review/faqs/1", json={"answer": "x"}).status_code == 401
        assert c.post("/api/v1/admin/review/faqs/1/generate-answer", json={}).status_code == 401


def test_list_exposes_needs_answer_flag(client, db):
    _seed(db, "doc-p19-flag", [("【診所文件】p19-flag - 指示 1", "5. 術後多久可以洗臉？")])
    body = client.get("/api/v1/admin/review/faqs?status=pending&limit=200").json()
    mine = [f for f in body["faqs"] if f["topic_key"] == "doc-p19-flag"]
    assert mine and mine[0]["needs_answer"] is True
