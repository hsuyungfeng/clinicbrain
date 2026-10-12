"""Phase 20 對抗性審查加固測試：併發鎖競爭、跨行程互斥、例外復原、取消、dry-run 守門、輪詢輕量化。
全程使用 isolated_db_path 複本與假 LLM，不觸及正式庫。"""

import json
import pathlib
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config
from src.api.routes import admin as admin_mod
from src.batch import db_lock
from src.batch.run_log import RunLogger
from src.batch.runner import BatchConfig, run_batch
from src.pageindex import batch_answer_job
from src.pageindex.answer_generator import is_answer_thin
from src.pageindex.llm_client import LocalLLMUnavailableError

CLINIC = "3503190424"
GOOD = (
    "術後請保持傷口清潔乾燥，避免劇烈運動與長時間曝曬，並依醫囑回診追蹤。"
    "日常可適度冰敷減輕腫脹感，睡眠時墊高頭部有助於消腫，飲食以清淡均衡為主，避免菸酒。"
    "若傷口紅腫熱痛加劇、化膿或有異味，請勿自行處理，應回診由醫師評估。"
    "若出現高燒超過3天、持續劇烈疼痛或呼吸困難，請儘速就醫。"
)


PROD_PATH = (pathlib.Path(__file__).resolve().parent.parent / "clinic.db").resolve()


def _clear_pending_in_copy(path):
    """僅清除『隔離複本』中的待審草稿，讓斷言不受正式庫的即時資料影響。
    安全守門：拒絕對正式庫路徑操作。"""
    assert pathlib.Path(path).resolve() != PROD_PATH, "測試禁止清理正式庫"
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("DELETE FROM faq_cache WHERE review_status = 'pending'")
        conn.commit()
    finally:
        conn.close()


def _reset_batch_state():
    from src.batch import db_lock
    batch_answer_job._cancel.set()
    batch_answer_job.wait(10)
    if admin_mod._GENERATION_LOCK.locked():
        admin_mod._GENERATION_LOCK.release()
    db_lock.release(batch_answer_job._db_lock_fd)
    batch_answer_job._db_lock_fd = None
    batch_answer_job._thread = None
    batch_answer_job._state = None
    batch_answer_job._cancel.clear()


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """測試一律不得呼叫真實本機 LLM（會佔用 GPU 並造成長時間逾時）；需要時各測試自行 monkeypatch。"""
    def forbid(prompt):
        raise AssertionError("測試禁止呼叫真實 LLM，請替換為假函式")
    monkeypatch.setattr(admin_mod, "_local_llm_call", forbid)
    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", forbid)


@pytest.fixture(autouse=True)
def _reset_job_state():
    batch_answer_job._cancel.set()
    batch_answer_job.wait(10)
    batch_answer_job._state = None
    batch_answer_job._cancel.clear()
    yield
    batch_answer_job._cancel.set()
    batch_answer_job.wait(10)
    if admin_mod._GENERATION_LOCK.locked():       # 防止前一測試遺留的模型鎖拖垮後續測試
        admin_mod._GENERATION_LOCK.release()
    db_lock.release(batch_answer_job._db_lock_fd)
    batch_answer_job._db_lock_fd = None
    batch_answer_job._state = None
    batch_answer_job._cancel.clear()


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "admin_api_key", "")
    with TestClient(app) as c:
        yield c


def _insert(conn, question, answer, *, source="web_upload", status="pending", topic="p20h"):
    cur = conn.execute(
        """INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status)
           VALUES (?, ?, ?, ?, 'special', ?, ?)""",
        (CLINIC, topic, question, answer, source, status),
    )
    conn.commit()
    return cur.lastrowid


def _seed_file(tmp_path: Path) -> Path:
    p = tmp_path / "seeds.json"
    p.write_text('{"schema_version": 1, "topics": [], "tree_procedure_names": {}}', encoding="utf-8")
    return p


def _wait_done(timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        s = batch_answer_job.snapshot()
        if s["state"] != "running":
            return s
        time.sleep(0.05)
    raise AssertionError("job did not finish")


# ---------------- 1. 選取規則與 Web 介面一致（回歸：問題清單型草稿曾被漏選）----------------
def test_selection_uses_same_rule_as_ui(isolated_db_path):
    _clear_pending_in_copy(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        qlist = _insert(conn, "【診所文件】p20h-a - 指示 1", "4. Endolift與其他非手術治療眼袋有何不同？", topic="p20h-a")
        stub = _insert(conn, "術後多久可以洗臉？", "短答", topic="p20h-b")
        standalone_thin = _insert(conn, "術後多久可以冰敷？", "二十五個字左右的短說明內容需要補強。", topic="p20h-c")
        _insert(conn, "【診所文件】p20h-d - 指示 1", "第一段內容。\n第二段內容。", topic="p20h-d")       # 實質多段 → 不選
        _insert(conn, "已核准題目？", "", status="approved", topic="p20h-e")                            # 非 pending
        _insert(conn, "已駁回題目？", "", status="rejected", topic="p20h-f")
        _insert(conn, "手寫題目？", "", source="manual", topic="p20h-g")                               # 權威來源
        llm_thin = _insert(conn, "通用空答？", "", source="llm_generated", topic="p20h-h")
        complete = _insert(conn, "完整答案題目？", GOOD, topic="p20h-i")                                # 完整 → 不選
        got = batch_answer_job.get_pending_unanswered_ids(conn, clinic_id=CLINIC, limit=100)
    finally:
        conn.close()
    assert set(got) == {qlist, stub, standalone_thin, llm_thin}
    assert complete not in got
    # 規則唯一來源：與 is_answer_thin 結果逐筆一致
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        rows = conn.execute("SELECT id, question, answer FROM faq_cache WHERE review_status='pending' AND source_type IN ('web_upload','llm_generated','soap_distilled')").fetchall()
    finally:
        conn.close()
    assert set(got) == {i for i, q, a in rows if is_answer_thin(q or "", a or "")}


def test_selection_limit_and_order(isolated_db_path):
    _clear_pending_in_copy(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        ids = [_insert(conn, f"限制測試題目{i}？", "", topic=f"p20lim-{i}") for i in range(5)]
        assert batch_answer_job.get_pending_unanswered_ids(conn, clinic_id=CLINIC, limit=3) == ids[:3]
    finally:
        conn.close()


# ---------------- 2. 跨行程互斥：與夜間批次共用同一把鎖 ----------------
def test_nightly_lock_name_matches_script(isolated_db_path):
    from scripts.run_nightly_batch import lock_path_for
    assert db_lock.nightly_lock_path(isolated_db_path) == lock_path_for(isolated_db_path)


def test_web_job_refused_while_nightly_holds_lock(client, isolated_db_path, monkeypatch):
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        fid = _insert(conn, "鎖測試題目？", "", topic="p20lock")
    finally:
        conn.close()
    nightly_fd = db_lock.try_acquire(isolated_db_path)     # 模擬夜間批次行程持鎖
    assert nightly_fd is not None
    try:
        r = client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": [fid]})
        assert r.status_code == 409
        assert batch_answer_job.snapshot()["state"] == "idle"
    finally:
        db_lock.release(nightly_fd)
    # 釋放後可正常啟動並完成
    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", lambda p: GOOD)
    assert client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": [fid]}).status_code == 200
    assert _wait_done()["state"] == "done"


def test_nightly_skips_when_web_job_holds_lock(client, isolated_db_path, monkeypatch):
    """反向：作業進行中時，另一行程取得同一把鎖會失敗（夜間批次依既有規則持鎖略過）。"""
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        fid = _insert(conn, "反向鎖測試題目？", "", topic="p20lock2")
    finally:
        conn.close()
    gate = threading.Event()
    monkeypatch.setattr(admin_mod, "_local_llm_call", lambda p: (gate.wait(10), GOOD)[1])
    assert client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": [fid]}).status_code == 200
    time.sleep(0.3)
    try:
        assert db_lock.try_acquire(isolated_db_path) is None
    finally:
        gate.set()
    _wait_done()
    fd = db_lock.try_acquire(isolated_db_path)   # 作業結束後釋放
    assert fd is not None
    db_lock.release(fd)


def test_autofill_all_refused_while_nightly_holds_lock(client, isolated_db_path):
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        _insert(conn, "一鍵鎖測試題目？", "", topic="p20lock3")
    finally:
        conn.close()
    fd = db_lock.try_acquire(isolated_db_path)
    try:
        assert client.post("/api/v1/admin/review/autofill/all").status_code == 409
    finally:
        db_lock.release(fd)


# ---------------- 3. 併發：與單題生成／提問共用模型鎖 ----------------
def test_single_generation_blocked_while_worker_holds_model_lock(client, isolated_db_path, monkeypatch):
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        a = _insert(conn, "併發測試題目甲？", "", topic="p20conc")
        b = _insert(conn, "併發測試題目乙？", "", topic="p20conc2")
    finally:
        conn.close()
    started, gate = threading.Event(), threading.Event()

    def slow(prompt):
        started.set()
        gate.wait(10)
        return GOOD

    monkeypatch.setattr(admin_mod, "_local_llm_call", slow)
    assert client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": [a, b]}).status_code == 200
    assert started.wait(5)
    try:
        # 背景作業持有模型鎖時，單題生成與提問都必須被擋（429），不得並發打 llama-server
        assert client.post(f"/api/v1/admin/review/faqs/{b}/generate-answer", json={}).status_code == 429
        assert client.post("/api/v1/admin/ask", json={"question": "測試", "clinic_id": CLINIC}).status_code == 429
    finally:
        gate.set()
    s = _wait_done()
    assert s["state"] == "done" and s["ok"] == 2


def test_cancel_while_waiting_for_model_lock(client, isolated_db_path):
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        ids = [_insert(conn, f"等鎖取消題目{i}？", "", topic=f"p20wait-{i}") for i in range(2)]
    finally:
        conn.close()
    assert admin_mod._GENERATION_LOCK.acquire(blocking=False)   # 模擬他人持有模型鎖
    try:
        assert client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": ids}).status_code == 200
        time.sleep(0.5)
        client.post("/api/v1/admin/review/batch-generate/cancel")
        s = _wait_done(timeout=10)
        assert s["state"] == "cancelled" and s["processed"] == 0
        fd = db_lock.try_acquire(isolated_db_path)              # 取消後跨行程鎖已釋放
        assert fd is not None
        db_lock.release(fd)
    finally:
        admin_mod._GENERATION_LOCK.release()


# ---------------- 4. 例外復原與優雅降級 ----------------
def test_llm_down_aborts_and_releases_all_locks(client, isolated_db_path, monkeypatch):
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        ids = [_insert(conn, f"斷線題目{i}？", "", topic=f"p20down-{i}") for i in range(3)]
    finally:
        conn.close()
    calls = {"n": 0}

    def down(prompt):
        calls["n"] += 1
        raise LocalLLMUnavailableError("offline")

    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", down)
    monkeypatch.setattr(admin_mod, "_local_llm_call", down)
    assert client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": ids}).status_code == 200
    s = _wait_done()
    assert s["state"] == "aborted" and calls["n"] == 1 and s["processed"] == 1
    assert admin_mod._GENERATION_LOCK.acquire(blocking=False)   # 模型鎖已釋放
    admin_mod._GENERATION_LOCK.release()
    assert batch_answer_job._db_lock_fd is None
    fd = db_lock.try_acquire(isolated_db_path)
    assert fd is not None
    db_lock.release(fd)
    # 斷線不得讓草稿被核准或內容被改壞
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        assert all(conn.execute("SELECT review_status, answer FROM faq_cache WHERE id=?", (i,)).fetchone() == ("pending", "") for i in ids)
    finally:
        conn.close()


def test_unexpected_error_isolated_per_item(client, isolated_db_path, monkeypatch):
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        a = _insert(conn, "非預期錯誤題目甲？", "", topic="p20err-a")
        b = _insert(conn, "非預期錯誤題目乙？", "", topic="p20err-b")
    finally:
        conn.close()
    n = {"c": 0}

    def flaky(prompt):
        n["c"] += 1
        if n["c"] == 1:
            raise RuntimeError("boom")
        return GOOD

    monkeypatch.setattr(admin_mod, "_local_llm_call", flaky)
    client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": [a, b]})
    s = _wait_done()
    assert s["state"] == "done" and s["ok"] == 1 and len(s["failed"]) == 1
    assert "RuntimeError" in s["failed"][0]["reason"] or "非預期" in s["failed"][0]["reason"]
    assert batch_answer_job._db_lock_fd is None


def test_restart_during_collapse_blocks_new_start(isolated_db_path):
    """上一作業已寫入最終狀態但尚未釋放鎖：新作業必須得到明確的「收尾中」訊息，而非誤報資料庫被占用。"""
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        fid = _insert(conn, "收尾測試題目？", "", topic="p20tail")
    finally:
        conn.close()
    batch_answer_job._state = {"state": "done", "total": 0, "processed": 0, "ok": 0, "skipped": 0,
                               "failed": [], "ok_ids": [], "current_id": None,
                               "started_at": 0, "finished_at": 0, "message": ""}
    batch_answer_job._db_lock_fd = db_lock.try_acquire(isolated_db_path)
    try:
        with pytest.raises(RuntimeError, match="收尾"):
            batch_answer_job.start(isolated_db_path, [fid], lambda p: GOOD, None, admin_mod._GENERATION_LOCK)
    finally:
        db_lock.release(batch_answer_job._db_lock_fd)
        batch_answer_job._db_lock_fd = None


def test_thread_start_failure_releases_lock(isolated_db_path, monkeypatch):
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        fid = _insert(conn, "執行緒失敗題目？", "", topic="p20thr")
    finally:
        conn.close()

    class Boom(threading.Thread):
        def start(self):
            raise RuntimeError("cannot start thread")

    monkeypatch.setattr(batch_answer_job.threading, "Thread", Boom)
    with pytest.raises(RuntimeError):
        batch_answer_job.start(isolated_db_path, [fid], lambda p: GOOD, None, admin_mod._GENERATION_LOCK)
    assert batch_answer_job._db_lock_fd is None and batch_answer_job._state is None
    fd = db_lock.try_acquire(isolated_db_path)
    assert fd is not None
    db_lock.release(fd)


# ---------------- 5. 輪詢端點輕量化（只讀記憶體快照，不碰資料庫） ----------------
def test_status_endpoint_has_no_db_dependency(client, monkeypatch):
    # 直接檢視 admin router 上的路由與其依賴（app.routes 會把子路由包進 Mount，不便比對）
    matches = [r for r in admin_mod.router.routes if getattr(r, "path", "").endswith("/review/batch-generate/status")]
    assert matches, "找不到狀態端點"
    dep_names = {d.call.__name__ for d in matches[0].dependant.dependencies if getattr(d, "call", None)}
    assert "get_read_db" not in dep_names and "get_write_db" not in dep_names
    # 認證由 router 層級套用（APIRouter(dependencies=[Depends(verify_admin_key)])），狀態端點不得例外放行
    router_deps = {d.dependency.__name__ for d in admin_mod.router.dependencies if getattr(d, "dependency", None)}
    assert "verify_admin_key" in router_deps

    def no_db(*a, **k):
        raise AssertionError("status 不得開啟資料庫連線")

    monkeypatch.setattr(sqlite3, "connect", no_db)
    r = client.get("/api/v1/admin/review/batch-generate/status")
    assert r.status_code == 200 and r.json()["state"] == "idle"


def test_status_snapshot_is_copy(isolated_db_path):
    batch_answer_job._state = {"state": "running", "total": 1, "processed": 0, "ok": 0, "skipped": 0,
                               "failed": [{"id": 1, "reason": "x"}], "ok_ids": [], "current_id": None,
                               "started_at": 0, "finished_at": None, "message": ""}
    snap = batch_answer_job.snapshot()
    snap["failed"].append({"id": 2, "reason": "y"})
    assert len(batch_answer_job._state["failed"]) == 1   # 快照為複本，外部修改不影響作業狀態


# ---------------- 6. 夜間批次階段：dry-run 守門與實際補齊 ----------------
def test_dry_run_never_calls_llm_for_autofill(isolated_conn, tmp_path):
    _insert(isolated_conn, "【診所文件】p20dry - 指示 1", "4. 乾跑測試問題？", topic="p20dry")
    called = []

    def must_not_call(prompt):
        called.append(prompt)
        raise AssertionError("dry-run 不得呼叫 LLM")

    cfg = BatchConfig(seed_path=_seed_file(tmp_path), snapshot_dir=tmp_path / "snap", dry_run=True,
                      skip_faq=True, skip_trees=True, enable_soap_distill=False, enable_autofill_answers=True)
    s = run_batch(isolated_conn, cfg, llm_call=must_not_call, health_check=lambda: None,
                  logger=RunLogger(tmp_path / "logs", echo=False))
    assert called == [] and s.errors == 0 and s.autofill_answers_count == 0


def test_nightly_stage_fills_question_list_rows(isolated_conn, tmp_path):
    isolated_conn.execute("DELETE FROM faq_cache WHERE review_status = 'pending'")
    isolated_conn.commit()
    rid = _insert(isolated_conn, "【診所文件】p20night - 指示 1", "4. 術後多久可以洗臉？", topic="p20night")
    cfg = BatchConfig(seed_path=_seed_file(tmp_path), snapshot_dir=tmp_path / "snap", dry_run=False,
                      skip_faq=True, skip_trees=True, enable_soap_distill=False, enable_autofill_answers=True)
    s = run_batch(isolated_conn, cfg, llm_call=lambda p: GOOD, health_check=lambda: None,
                  logger=RunLogger(tmp_path / "logs", echo=False))
    assert s.autofill_answers_count == 1
    q, a, st = isolated_conn.execute("SELECT question, answer, review_status FROM faq_cache WHERE id=?", (rid,)).fetchone()
    assert st == "pending" and a == GOOD and q == "術後多久可以洗臉？"


def test_nightly_autofill_disabled_flag(isolated_conn, tmp_path):
    _insert(isolated_conn, "【診所文件】p20off - 指示 1", "4. 關閉旗標測試？", topic="p20off")
    cfg = BatchConfig(seed_path=_seed_file(tmp_path), snapshot_dir=tmp_path / "snap", dry_run=False,
                      skip_faq=True, skip_trees=True, enable_soap_distill=False, enable_autofill_answers=False)
    s = run_batch(isolated_conn, cfg, llm_call=lambda p: (_ for _ in ()).throw(AssertionError("不應呼叫")),
                  health_check=lambda: None, logger=RunLogger(tmp_path / "logs", echo=False))
    assert s.autofill_answers_count == 0


# ---------------- 7. 端點不回傳未核准內容的隱蔽性（背景作業產出仍為 pending） ----------------
def test_background_output_stays_hidden_until_approved(client, isolated_db_path, monkeypatch):
    from src.pageindex.faq_review import visible_faq_sql
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        fid = _insert(conn, "隱蔽測試題目？", "", topic="p20hide")
    finally:
        conn.close()
    monkeypatch.setattr(admin_mod, "_local_llm_call", lambda p: GOOD)
    client.post("/api/v1/admin/review/batch-generate", json={"faq_ids": [fid]})
    assert _wait_done()["state"] == "done"
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        st = conn.execute("SELECT review_status FROM faq_cache WHERE id=?", (fid,)).fetchone()[0]
        visible = conn.execute(f"SELECT COUNT(*) FROM faq_cache WHERE id=? AND {visible_faq_sql(conn)}", (fid,)).fetchone()[0]
    finally:
        conn.close()
    assert st == "pending" and visible == 0
