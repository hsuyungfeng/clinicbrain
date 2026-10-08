"""Phase 19 端到端：僅含問題的文件上傳 → AI 生成解答 → 全選／反選批量核准 → 公開查詢短路命中。"""

import io
import sqlite3

import docx
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config
from src.api.routes import admin as admin_mod

CLINIC = "3503190424"
QUESTIONS = [
    "測試療程Z術後多久可以洗臉？",
    "測試療程Z術後飲食需要注意哪些事項？",
    "測試療程Z術後腫脹通常持續多久時間？",
]
ANSWER = (
    "測試療程Z術後初期請保持施作部位清潔乾燥，洗臉時以溫和方式輕拍，避免用力搓揉。"
    "飲食建議清淡均衡，暫時避免菸酒與刺激性食物，並維持充足睡眠幫助恢復。"
    "輕微腫脹屬常見現象，可依醫囑適度冰敷並墊高頭部休息。"
    "若出現高燒超過3天、傷口紅腫化膿或持續劇烈疼痛，請儘速就醫。"
)


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", False)
    monkeypatch.setattr(config, "admin_api_key", "ux-e2e-key")
    with TestClient(app) as c:
        yield c


def _docx(lines):
    buf = io.BytesIO()
    d = docx.Document()
    for ln in lines:
        d.add_paragraph(ln)
    d.save(buf)
    return buf.getvalue()


def test_clinical_ux_full_closed_loop(client, isolated_db_path, monkeypatch):
    H = {"X-API-Key": "ux-e2e-key"}
    monkeypatch.setattr(admin_mod, "_local_llm_call", lambda prompt: ANSWER)

    # 1. 上傳「只有問題清單」的文件
    up = client.post(
        "/api/v1/admin/upload",
        data={"clinic_id": CLINIC},
        files={"file": ("ux_e2e.docx", _docx([f"{i}. {q}" for i, q in enumerate(QUESTIONS, 1)]), "application/octet-stream")},
        headers=H,
    )
    assert up.status_code == 200, up.text

    listing = client.get("/api/v1/admin/review/faqs?status=pending&limit=200", headers=H).json()["faqs"]
    mine = sorted((f for f in listing if f["topic_key"] == "doc-ux_e2e"), key=lambda f: f["id"])
    assert len(mine) == 3 and all(f["needs_answer"] for f in mine)
    ids = [f["id"] for f in mine]

    # 2. 對前兩題呼叫本機 LLM 生成解答（第三題刻意不生成）
    for fid in ids[:2]:
        r = client.post(f"/api/v1/admin/review/faqs/{fid}/generate-answer", json={}, headers=H)
        assert r.status_code == 200, r.text
        assert r.json()["review_status"] == "pending"

    # 生成後、核准前：公開端點完全看不到
    before = client.post("/api/v1/query", json={"query": QUESTIONS[0], "clinic_id": CLINIC}).json()
    assert before.get("source") != "cache"

    # 3. 「全選 → 反選」：先選第三題再反選，得到前兩題，批量核准
    all_ids = set(ids)
    selected = {ids[2]}
    inverted = sorted(all_ids - selected)
    assert inverted == ids[:2]
    r = client.post("/api/v1/admin/review/batch", json={"action": "approve", "faq_ids": inverted}, headers=H)
    assert r.status_code == 200 and r.json()["success_count"] == 2

    # 4. 核准後公開查詢立即短路命中（含 AI 生成之答案）；未核准的第三題仍隱蔽
    after = client.post("/api/v1/query", json={"query": QUESTIONS[0], "clinic_id": CLINIC}).json()
    assert after["source"] == "cache" and "保持施作部位清潔乾燥" in after["cache_answer"]
    third = client.post("/api/v1/query", json={"query": QUESTIONS[2], "clinic_id": CLINIC}).json()
    assert third.get("source") != "cache"

    conn = sqlite3.connect(str(isolated_db_path))
    try:
        st = dict(conn.execute("SELECT id, review_status FROM faq_cache WHERE topic_key='doc-ux_e2e'").fetchall())
    finally:
        conn.close()
    assert st[ids[0]] == st[ids[1]] == "approved" and st[ids[2]] == "pending"
