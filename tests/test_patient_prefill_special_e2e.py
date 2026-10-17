"""Phase 28 Plan 09: Special 推理樹來源預生成問答核准後之匿名病人諮詢端到端測試。

涵蓋行為：
- Test 5（e2e：設定診所）:
  隔離複本上，診所 A 有已核准推理樹；經批次階段 8 產生 special 預生成問答（clinic_id=A、pending）；
  pending 時匿名 /consult（設定 A）不命中；醫師以 set_review_status 核准後，相同問句直答（0 次 LLM 呼叫），
  訊息含答案句與單一追問與預約邀請。
- Test 6（e2e：未設定診所）:
  同一核准後狀態，但 patient_clinic_id 未設定 -> 同一問句不命中該 special 內容（回一般路徑結果）。
- Test 7（e2e：設定了錯誤診所）:
  設定診所為 B -> 同一問句不命中 A 的內容。
- Test 8: 正式庫守門（SHA-256 前後完全相同）；測試不呼叫真實 LLM。
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config
from src.api.routes import general as general_route
from src.batch.runner import BatchConfig, run_batch
from src.batch.run_log import RunLogger
from src.general import consult_jobs
from src.general import patient_consult as pc
from src.pageindex.db_writer import upsert_trees
from src.pageindex.faq_review import set_review_status


CLINIC_A = "3503190424"
CLINIC_B = "3503264627"
NOW_FIXED = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
WARNING_TEXT = "若出現胸痛、呼吸困難或體溫持續超過38.5度達3天，請立即前往急診或儘速就醫。"
PROD_DB = Path("clinic.db").resolve()


def _get_db_hash() -> str:
    if not PROD_DB.exists():
        return ""
    return hashlib.sha256(PROD_DB.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def guard_prod_db():
    h_before = _get_db_hash()
    yield
    h_after = _get_db_hash()
    assert h_before == h_after, "正式資料庫 clinic.db 在測試中被修改！"


def _dummy_prefill_llm(prompt: str) -> str:
    return (
        "答：測試專利冷凝除疤術是利用低溫技術進行皮膚組織調理與修復以達淡化疤痕效果。\n"
        "日常維護時建議維持良好作息與適度防曬。\n"
        f"{WARNING_TEXT}\n"
        "追問：您目前是否有特定疤痕部位想先評估呢？"
    )


@pytest.fixture
def special_prefill_env(isolated_conn, isolated_db_path, tmp_path, monkeypatch):
    """建立診所 A 之 special 推理樹並執行階段 8 生成 5 題預生成問答。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)

    # 1. 植入診所 A 之已核准推理樹（使用專屬標題，summary_text 不含標題字樣以隔離樹直接命中）
    doc_id = "test-cryo-scar-removal"
    tree = {
        "doc_id": doc_id,
        "clinic_id": CLINIC_A,
        "category": "special",
        "title": "測試專利冷凝除疤術",
        "summary_text": "特定皮膚組織低溫修復技術之專業臨床處置說明，詳情請洽專案醫師諮詢。",
        "pre_op": "術前諮詢與皮膚狀況評估。",
        "pre_op_physician_notes": "",
        "procedure": "特定低溫探頭進行局部組織調理處置。",
        "procedure_physician_notes": "",
        "post_op_short": "術後短期照護注意事項。",
        "post_op_short_physician_notes": "",
        "maintenance": "長期日常維護保健要點。",
        "maintenance_physician_notes": "",
        "version": 1,
        "status": "approved",
    }
    upsert_trees(isolated_conn, [tree], source_type="manual")
    isolated_conn.execute("UPDATE page_index_trees SET review_status='approved' WHERE doc_id=?", (doc_id,))
    isolated_conn.commit()

    # 2. 執行批次階段 8 生成預生成問答
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"schema_version": 1, "topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snap",
        skip_faq=True,
        skip_trees=True,
        enable_soap_distill=False,
        now_fn=lambda: NOW_FIXED,
    )
    logger = RunLogger(tmp_path / "logs", echo=False)
    summary = run_batch(isolated_conn, cfg, llm_call=_dummy_prefill_llm, health_check=lambda: None, logger=logger)
    logger.close()

    assert summary.prefill_generated >= 5

    # 3. 查出 what 題之 id, question, answer
    cur = isolated_conn.cursor()
    cur.execute(
        "SELECT id, question, answer, review_status, clinic_id FROM faq_cache WHERE topic_key=?",
        (f"prefill-{doc_id}-what",),
    )
    row = cur.fetchone()
    assert row is not None, "必須成功生成 what 題"
    faq_id, q_text, ans_text, status, row_clinic = row[0], row[1], row[2], row[3], row[4]
    assert status == "pending"
    assert row_clinic == CLINIC_A

    # 4. Mock fallback LLM 防止意外呼叫真實 LLM
    mock_body = "一般醫學衛教未審說明內容。" + WARNING_TEXT

    def _mock_general_llm(p):
        return json.dumps([{"question": q_text, "answer": mock_body}], ensure_ascii=False)

    monkeypatch.setattr(general_route, "default_patient_llm", _mock_general_llm)
    monkeypatch.setattr(pc, "default_patient_llm", _mock_general_llm)

    consult_jobs.reset_for_tests()
    with TestClient(app) as client:
        yield {
            "conn": isolated_conn,
            "client": client,
            "faq_id": faq_id,
            "question": q_text,
            "answer": ans_text,
            "doc_id": doc_id,
        }
    consult_jobs.wait_idle(timeout=5.0)
    consult_jobs.reset_for_tests()


def test_5_special_tree_prefill_approved_direct_hit(special_prefill_env, monkeypatch):
    """Test 5: 設定診所 A，pending 時不命中；核准後直答，0 次 LLM 呼叫，含答案、追問與預約。"""
    env = special_prefill_env
    client = env["client"]
    conn = env["conn"]
    faq_id = env["faq_id"]
    q_text = env["question"]

    # 1. 設定伺服器診所為 A
    monkeypatch.setattr(config, "patient_clinic_id", CLINIC_A)

    # 2. pending 時：不命中直答
    r_pending = client.post("/api/v1/general/consult", json={"query": q_text})
    assert r_pending.status_code == 200
    assert r_pending.json()["status"] != "answered"

    # 3. 醫師核准
    set_review_status(conn, [faq_id], "approved")

    # 4. 核准後：0 次模型呼叫直答
    def _forbidden_llm(p):
        raise AssertionError("核准後直答不得呼叫任何 LLM！")

    monkeypatch.setattr(general_route, "default_patient_llm", _forbidden_llm)
    monkeypatch.setattr(pc, "default_patient_llm", _forbidden_llm)

    r_approved = client.post("/api/v1/general/consult", json={"query": q_text})
    assert r_approved.status_code == 200
    data = r_approved.json()
    assert data["status"] == "answered"
    assert "測試專利冷凝除疤術" in data["message"]
    assert "淡化疤痕" in data["message"]
    assert "？" in data["message"]
    assert "預約" in data["message"]


def test_6_special_tree_prefill_unset_clinic_does_not_hit(special_prefill_env, monkeypatch):
    """Test 6: 核准狀態下，若伺服器未設定 patient_clinic_id，相同問句絕不命中該 special 內容。"""
    env = special_prefill_env
    client = env["client"]
    conn = env["conn"]
    faq_id = env["faq_id"]
    q_text = env["question"]

    # 醫師核准該題
    set_review_status(conn, [faq_id], "approved")

    # 伺服器未設定診所
    monkeypatch.setattr(config, "patient_clinic_id", None)

    r = client.post("/api/v1/general/consult", json={"query": q_text})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] != "answered"
    # special 答案獨有的關鍵字絕不出現在回覆
    assert "淡化疤痕" not in data["message"]


def test_7_special_tree_prefill_wrong_clinic_does_not_hit(special_prefill_env, monkeypatch):
    """Test 7: 核准狀態下，若伺服器設定為診所 B，相同問句絕不命中診所 A 的內容。"""
    env = special_prefill_env
    client = env["client"]
    conn = env["conn"]
    faq_id = env["faq_id"]
    q_text = env["question"]

    # 醫師核准診所 A 的題目
    set_review_status(conn, [faq_id], "approved")

    # 伺服器設定為診所 B
    monkeypatch.setattr(config, "patient_clinic_id", CLINIC_B)

    r = client.post("/api/v1/general/consult", json={"query": q_text})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] != "answered"
    assert "淡化疤痕" not in data["message"]


def test_8_prod_db_guard_verified():
    """Test 8: 驗證正式資料庫 clinic.db SHA-256 守門 fixture 正常運作。"""
    assert PROD_DB.exists()
    assert len(_get_db_hash()) == 64
