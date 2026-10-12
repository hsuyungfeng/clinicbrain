"""Phase 21 對抗性審查加固測試：Fail-Closed 隔離、醫囑保護、合規防禦、遷移冪等、併發鎖。
全程使用 isolated_db_path 複本與假 LLM；測試禁止觸及正式庫。"""

import dataclasses
import json
import pathlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config
from src.api.routes import admin as admin_mod
from src.batch import db_lock
from src.pageindex.db_writer import upsert_trees
from src.pageindex.llm_client import LocalLLMUnavailableError
from src.pageindex.prompt_template import TreeValidationError

PROD_PATH = (pathlib.Path(__file__).resolve().parent.parent / "clinic.db").resolve()
CLINIC = "3503190424"
TERM = "星海拉提療程"          # 測試專用罕見詞，避免命中真實資料
VALID_JSON = json.dumps({
    "pre_op": "術前應評估適應症與禁忌，確認無凝血異常。",
    "procedure": "以超音波能量作用於真皮深層，逐步收緊組織。",
    "post_op_short": "術後初期避免按壓，依醫囑回診追蹤。",
    "maintenance": "長期做好防曬與規律保養以維持效果。",
    "summary_text": "說明術前評估、療程原理與術後照護重點。",
}, ensure_ascii=False)


@pytest.fixture(autouse=True)
def _guards(monkeypatch):
    def forbid(prompt):
        raise AssertionError("測試禁止呼叫真實 LLM")
    monkeypatch.setattr(admin_mod, "_local_llm_call", forbid)
    monkeypatch.setattr(admin_mod, "_local_llm_ask_call", forbid)
    yield
    if admin_mod._GENERATION_LOCK.locked():
        admin_mod._GENERATION_LOCK.release()


def _migrate_copy(path):
    """隔離複本套用 Phase 21 遷移（正式庫目前尚未遷移，測試不得依賴正式庫結構）。"""
    from scripts.migrate_page_index_review import SCHEMA_PATH, derive_alter_statements, migrate_database
    assert pathlib.Path(path).resolve() != PROD_PATH, "測試禁止遷移正式庫"
    migrate_database(pathlib.Path(path), derive_alter_statements(SCHEMA_PATH))


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    assert pathlib.Path(isolated_db_path).resolve() != PROD_PATH, "測試禁止使用正式庫"
    _migrate_copy(isolated_db_path)
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "admin_api_key", "")
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(isolated_db_path):
    assert pathlib.Path(isolated_db_path).resolve() != PROD_PATH
    _migrate_copy(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    yield conn
    conn.close()


def _row(doc, *, clinic=CLINIC, category="special", text=TERM):
    return {
        "doc_id": doc, "clinic_id": clinic, "category": category,
        "pre_op": f"{text}術前評估與禁忌說明。", "pre_op_physician_notes": None,
        "procedure": "超音波能量作用於真皮深層的療程原理。", "procedure_physician_notes": None,
        "post_op_short": "術後初期避免按壓並依醫囑回診。", "post_op_short_physician_notes": None,
        "maintenance": "長期防曬與規律保養。", "maintenance_physician_notes": None,
        "summary_text": f"{text}的摘要與照護重點。",
    }


def _tree_status(db, doc):
    return db.execute("SELECT review_status FROM page_index_trees WHERE doc_id=?", (doc,)).fetchone()[0]


def _dump(obj):
    data = dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) else obj.__dict__
    return json.dumps(data, default=str, ensure_ascii=False)


# ---------------- 1. Fail-Closed：公開通道不得檢索未核准樹 ----------------
def test_anonymous_general_endpoint_hides_pending_general_tree(client, db):
    db.execute(
        """INSERT INTO page_index_trees (doc_id, clinic_id, category, pre_op, procedure, post_op_short,
           maintenance, summary_text, source_type, review_status)
           VALUES ('p21-gen-pending', NULL, 'general', ?, '療程原理', '術後照護', '長期保養', ?, 'llm_generated', 'pending')""",
        (f"{TERM}術前說明。", f"{TERM}的一般衛教摘要。"),
    )
    db.commit()
    r = client.post("/api/v1/general/query", json={"query": TERM})
    assert r.status_code == 200
    assert "p21-gen-pending" not in r.text and TERM not in r.text
    # 正向對照：核准後應可被檢索（確保測試不是空轉）
    db.execute("UPDATE page_index_trees SET review_status='approved' WHERE doc_id='p21-gen-pending'")
    db.commit()
    assert "p21-gen-pending" in client.post("/api/v1/general/query", json={"query": TERM}).text


def test_consult_general_and_handle_query_hide_unapproved(db):
    from src.general.consult import consult_general
    from src.query.router import classify, handle_query
    gen_term = "星海高血壓"       # 不含 special 路由關鍵字（已驗證為 general），確保走 general 路由
    assert classify(gen_term).route == "general"
    db.execute(
        """INSERT INTO page_index_trees (doc_id, clinic_id, category, pre_op, procedure, post_op_short,
           maintenance, summary_text, source_type, review_status)
           VALUES ('p21-consult', NULL, 'general', ?, '療程原理', '術後照護', '長期保養', ?, 'web_upload', 'rejected')""",
        (f"{gen_term}術前說明。", f"{gen_term}的一般衛教摘要。"),
    )
    db.commit()
    assert "p21-consult" not in _dump(consult_general(db, gen_term))
    # NULL clinic_id + general 路由的 handle_query（統一入口）
    assert "p21-consult" not in _dump(handle_query(db, gen_term, None, limit=5, cache_shortcut=False))
    # 正向對照：核准後兩條路徑皆可檢索到（確保測試不是空轉）
    db.execute("UPDATE page_index_trees SET review_status='approved' WHERE doc_id='p21-consult'")
    db.commit()
    assert "p21-consult" in _dump(handle_query(db, gen_term, None, limit=5, cache_shortcut=False))


# ---------------- 2. 同步匯出不得外送未核准樹 ----------------
def test_sync_export_excludes_unreviewed_trees(client, db):
    upsert_trees(db, [_row("p21-sync-pending")], source_type="llm_generated", review_status="pending")
    upsert_trees(db, [_row("p21-sync-approved")], source_type="llm_generated", review_status="approved")
    body = client.post("/api/v1/sync/export", json={"clinic_id": CLINIC, "since_version": 0, "entities": ["trees"]}).json()
    docs = {t["doc_id"] for t in body["data"].get("trees", [])}
    assert "p21-sync-approved" in docs          # 正向對照
    assert "p21-sync-pending" not in docs


# ---------------- 3. 夜間重建不得把未審 LLM 內容變成可見 ----------------
def test_rebuild_of_approved_manual_tree_becomes_pending(db):
    upsert_trees(db, [_row("p21-rebuild")], source_type="manual")
    assert _tree_status(db, "p21-rebuild") == "approved"
    changed = _row("p21-rebuild", text="全新的 LLM 重建內容")
    upsert_trees(db, [changed], source_type="llm_generated")       # 不指定 review_status
    assert _tree_status(db, "p21-rebuild") == "pending"


# ---------------- 4. 醫囑保護：提煉不得覆寫既有醫師樹 ----------------
def test_distill_refuses_existing_doc_and_keeps_physician_notes(client, db, monkeypatch):
    upsert_trees(db, [_row("p21-doctor")], source_type="manual")
    db.execute("UPDATE page_index_trees SET pre_op_physician_notes='醫師親自註記：術後禁止平躺4小時' WHERE doc_id='p21-doctor'")
    db.commit()
    monkeypatch.setattr(admin_mod, "_local_llm_call", lambda p: VALID_JSON)
    r = client.post("/api/v1/admin/trees/distill", json={
        "title": "覆寫測試療程", "text": "這是一段足夠長的療程文字內容，用來測試覆寫防護。",
        "clinic_id": CLINIC, "doc_id": "p21-doctor"})
    assert r.status_code == 409, r.text
    row = db.execute("SELECT pre_op_physician_notes, source_type, review_status FROM page_index_trees WHERE doc_id='p21-doctor'").fetchone()
    assert row == ("醫師親自註記：術後禁止平躺4小時", "manual", "approved")


def test_llm_cannot_write_physician_notes(client, db, monkeypatch):
    poisoned = json.loads(VALID_JSON)
    poisoned["pre_op_physician_notes"] = "LLM 自編醫囑：可立即運動"
    monkeypatch.setattr(admin_mod, "_local_llm_call", lambda p: json.dumps(poisoned, ensure_ascii=False))
    r = client.post("/api/v1/admin/trees/distill", json={
        "title": "醫囑偽造測試", "text": "這是一段足夠長的療程文字內容，用來測試醫囑保護機制。",
        "clinic_id": CLINIC, "doc_id": "p21-no-notes"})
    assert r.status_code == 200, r.text
    notes = db.execute("SELECT pre_op_physician_notes FROM page_index_trees WHERE doc_id='p21-no-notes'").fetchone()[0]
    assert notes is None


# ---------------- 5. 醫療合規：編輯與簽核都要重跑檢驗 ----------------
def test_update_reverts_approved_gated_tree_to_pending(client, db):
    upsert_trees(db, [_row("p21-edit")], source_type="llm_generated", review_status="approved")
    tid = db.execute("SELECT id FROM page_index_trees WHERE doc_id='p21-edit'").fetchone()[0]
    r = client.put(f"/api/v1/admin/trees/{tid}", json={"pre_op": "改過的術前說明內容。"})
    assert r.status_code == 200
    assert _tree_status(db, "p21-edit") == "pending"


def test_update_rejects_forbidden_phrase_and_masks_price(client, db):
    upsert_trees(db, [_row("p21-edit2")], source_type="manual")
    tid = db.execute("SELECT id FROM page_index_trees WHERE doc_id='p21-edit2'").fetchone()[0]
    r = client.put(f"/api/v1/admin/trees/{tid}", json={"pre_op_physician_notes": "本療程保證有效"})
    assert r.status_code == 422
    r2 = client.put(f"/api/v1/admin/trees/{tid}", json={"procedure": "療程費用 15000 元整"})
    assert r2.status_code == 200
    assert "15000" not in db.execute("SELECT procedure FROM page_index_trees WHERE id=?", (tid,)).fetchone()[0]


def test_approve_rechecks_compliance(client, db):
    upsert_trees(db, [_row("p21-approve-bad")], source_type="llm_generated", review_status="pending")
    db.execute("UPDATE page_index_trees SET maintenance='長期保養後百分之百有效' WHERE doc_id='p21-approve-bad'")
    db.commit()
    tid = db.execute("SELECT id FROM page_index_trees WHERE doc_id='p21-approve-bad'").fetchone()[0]
    r = client.post(f"/api/v1/admin/trees/{tid}/approve")
    assert r.status_code == 422
    assert _tree_status(db, "p21-approve-bad") == "pending"


def test_approve_requires_all_four_segments(client, db):
    upsert_trees(db, [_row("p21-approve-empty")], source_type="llm_generated", review_status="pending")
    db.execute("UPDATE page_index_trees SET procedure='' WHERE doc_id='p21-approve-empty'")
    db.commit()
    tid = db.execute("SELECT id FROM page_index_trees WHERE doc_id='p21-approve-empty'").fetchone()[0]
    assert client.post(f"/api/v1/admin/trees/{tid}/approve").status_code == 422
    assert _tree_status(db, "p21-approve-empty") == "pending"


# ---------------- 6. 提煉輸入與錯誤處理 ----------------
@pytest.mark.parametrize("raw", ['["x"]', "5", "null", '"text"'])
def test_distill_rejects_non_object_json(db, raw):
    """非物件的合法 JSON（數字、null）會讓 `key in data` 拋 TypeError，必須轉為 TreeValidationError。"""
    from src.pageindex.tree_distiller import distill_tree_from_text
    with pytest.raises(TreeValidationError):
        distill_tree_from_text(db, "測試", "這是一段足夠長的療程文字內容用來測試。", CLINIC, "p21-list", llm_call=lambda p: raw)


def test_distill_llm_offline_is_503(client, monkeypatch):
    def down(p):
        raise LocalLLMUnavailableError("offline")
    monkeypatch.setattr(admin_mod, "_local_llm_call", down)
    r = client.post("/api/v1/admin/trees/distill", json={
        "title": "離線測試", "text": "這是一段足夠長的療程文字內容，用來測試離線處理。", "clinic_id": CLINIC})
    assert r.status_code == 503


def test_distill_reports_truncation(client, monkeypatch):
    monkeypatch.setattr(admin_mod, "_local_llm_call", lambda p: VALID_JSON)
    long_text = "這是一段很長的療程文字內容。" * 400    # > 3500 字，提煉端會截斷
    r = client.post("/api/v1/admin/trees/distill", json={"title": "長文測試", "text": long_text, "clinic_id": CLINIC})
    assert r.status_code == 200
    assert r.json().get("truncated") is True


def test_distill_rejects_bad_doc_id(client):
    r = client.post("/api/v1/admin/trees/distill", json={
        "title": "格式測試", "text": "這是一段足夠長的療程文字內容，用來測試識別碼格式。",
        "clinic_id": CLINIC, "doc_id": "../../etc/x"})
    assert r.status_code == 422


def test_distill_cross_process_lock_is_respected(client, isolated_db_path, monkeypatch):
    monkeypatch.setattr(admin_mod, "_local_llm_call", lambda p: VALID_JSON)
    fd = db_lock.try_acquire(isolated_db_path)           # 夜間批次持鎖
    try:
        r = client.post("/api/v1/admin/trees/distill", json={
            "title": "鎖測試", "text": "這是一段足夠長的療程文字內容，用來測試跨行程鎖。", "clinic_id": CLINIC})
        assert r.status_code == 409
    finally:
        db_lock.release(fd)


# ---------------- 7. 提煉草稿不得進入 FAQ 生成的參考上下文（未核准） ----------------
def test_faq_generator_tree_context_excludes_unapproved(db):
    from src.batch.faq_generator import reference_from_tree
    upsert_trees(db, [_row("p21-faqctx")], source_type="llm_generated", review_status="pending")
    assert reference_from_tree(db, "p21-faqctx") is None


# ---------------- 8. 遷移：既有 gated 列不得因預設值被自動核准 ----------------
def test_migration_does_not_auto_approve_gated_existing_rows(tmp_path):
    from scripts.migrate_page_index_review import SCHEMA_PATH, derive_alter_statements, migrate_database
    db_file = tmp_path / "legacy.db"
    c = sqlite3.connect(str(db_file))
    c.execute("CREATE TABLE page_index_trees (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT UNIQUE, "
              "clinic_id TEXT, category TEXT, source_type TEXT DEFAULT 'manual')")
    c.executemany("INSERT INTO page_index_trees (doc_id, clinic_id, category, source_type) VALUES (?,?,?,?)",
                  [("hand", CLINIC, "special", "manual"), ("cu", CLINIC, "special", "clinic_upload"),
                   ("llm", CLINIC, "special", "llm_generated"), ("web", CLINIC, "special", "web_upload")])
    c.commit()
    c.close()
    migrate_database(db_file, derive_alter_statements(SCHEMA_PATH))
    c = sqlite3.connect(str(db_file))
    got = dict(c.execute("SELECT doc_id, review_status FROM page_index_trees").fetchall())
    c.close()
    assert got == {"hand": "approved", "cu": "approved", "llm": "pending", "web": "pending"}


def test_migration_is_idempotent_and_keeps_manual(tmp_path):
    from scripts.migrate_page_index_review import SCHEMA_PATH, derive_alter_statements, migrate_database
    db_file = tmp_path / "legacy2.db"
    c = sqlite3.connect(str(db_file))
    c.execute("CREATE TABLE page_index_trees (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT UNIQUE, "
              "clinic_id TEXT, category TEXT, source_type TEXT DEFAULT 'manual')")
    c.execute("INSERT INTO page_index_trees (doc_id, clinic_id, category, source_type) VALUES ('hand', ?, 'special', 'manual')", (CLINIC,))
    c.commit()
    c.close()
    alters = derive_alter_statements(SCHEMA_PATH)
    migrate_database(db_file, alters)
    changed, _ = migrate_database(db_file, alters)
    assert changed == 0
    c = sqlite3.connect(str(db_file))
    assert c.execute("SELECT review_status FROM page_index_trees WHERE doc_id='hand'").fetchone()[0] == "approved"
    c.close()


def test_distill_title_is_price_masked_and_checked(db, monkeypatch):
    """標題亦屬可見文字：價格遮蔽，禁詞於標題中同樣拒絕。"""
    from src.pageindex.tree_distiller import distill_tree_from_text
    row = distill_tree_from_text(db, "拉提療程 15000 元", "這是一段足夠長的療程文字內容，用來測試標題價格遮蔽。",
                                 CLINIC, "p21-title-price", llm_call=lambda p: VALID_JSON)
    assert "15000" not in row["title"]
    with pytest.raises(TreeValidationError):
        distill_tree_from_text(db, "保證有效療程", "這是一段足夠長的療程文字內容，用來測試標題禁詞檢驗。",
                               CLINIC, "p21-title-bad", llm_call=lambda p: VALID_JSON)
