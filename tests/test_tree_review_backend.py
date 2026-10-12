"""
Taiwan Clinic Medical PageIndex RAG System - 臨床決策推理樹審核架構與後端 API 測試
Phase 21 Plan 21-01: 測試遷移、visible_tree_sql 隔離、提煉引擎與管理 API 端點
"""

import sqlite3
import pytest
from fastapi.testclient import TestClient

from pathlib import Path
from scripts.migrate_page_index_review import derive_alter_statements, migrate_database, SCHEMA_PATH
from src.api.app import app
from src.api.config import config
from src.pageindex.tree_distiller import distill_tree_from_text
from src.pageindex.tree_review import (
    approve_tree,
    count_trees_by_status,
    delete_tree,
    get_tree,
    has_tree_review_status,
    list_trees,
    reject_tree,
    update_tree,
    visible_tree_sql,
)
from src.query.search import search_page_index_trees

CLINIC_ID = "3503190424"


@pytest.fixture
def test_client(isolated_db_path, monkeypatch):
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "admin_api_key", "")
    with TestClient(app) as tc:
        yield tc


def test_migration_and_review_status_detection(isolated_db_path):
    """驗證資料庫遷移腳本對 page_index_trees 的冪等擴充與欄位檢測。"""
    schema_path = SCHEMA_PATH
    alter_sqls = derive_alter_statements(schema_path)

    # 首次遷移
    changed1, msgs1 = migrate_database(isolated_db_path, alter_sqls, dry_run=False)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        assert has_tree_review_status(conn) is True
        # 既有 6 筆手寫資料應補齊為 approved
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM page_index_trees WHERE review_status = 'approved'")
        assert cur.fetchone()[0] >= 6
    finally:
        conn.close()

    # 二次執行冪等性
    changed2, msgs2 = migrate_database(isolated_db_path, alter_sqls, dry_run=False)
    assert changed2 == 0


def test_tree_review_crud_and_counts(isolated_db_path):
    """驗證 tree_review 的 CRUD、審核流程與狀態計數。"""
    migrate_database(isolated_db_path, derive_alter_statements(SCHEMA_PATH))

    conn = sqlite3.connect(str(isolated_db_path))
    try:
        # 插入一筆 pending 草稿
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO page_index_trees (
                doc_id, title, clinic_id, category, pre_op, procedure, post_op_short, maintenance,
                summary_text, source_type, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "test-rf-surgery", "微創電波手術", CLINIC_ID, "special",
                "術前空腹與評估事項", "微創電波消融步驟", "術後冰敷二十分鐘", "維持健康作息",
                "微創電波手術摘要", "web_upload", "pending",
            ),
        )
        tree_id = cur.lastrowid
        conn.commit()

        # 1. 列表查詢
        trees, total = list_trees(conn, status="pending", clinic_id=CLINIC_ID)
        assert any(t["id"] == tree_id for t in trees)

        # 2. 詳情查詢
        t_data = get_tree(conn, tree_id)
        assert t_data["doc_id"] == "test-rf-surgery"
        assert t_data["pre_op_physician_notes"] is None

        # 3. 填寫醫師醫囑
        updated = update_tree(conn, tree_id, {"pre_op_physician_notes": "請於術前兩週停用抗凝血劑。"})
        assert updated["pre_op_physician_notes"] == "請於術前兩週停用抗凝血劑。"
        assert updated["content_version"] == 2

        # 4. 審核駁回再核准
        assert reject_tree(conn, tree_id) is True
        assert get_tree(conn, tree_id)["review_status"] == "rejected"

        assert approve_tree(conn, tree_id) is True
        assert get_tree(conn, tree_id)["review_status"] == "approved"

        # 5. 計數
        counts = count_trees_by_status(conn, clinic_id=CLINIC_ID)
        assert counts.get("approved", 0) >= 1
    finally:
        conn.close()


def test_fail_closed_search_isolation(isolated_db_path):
    """驗證 Fail-Closed 隔離：未核准之推理樹草稿對 search_page_index_trees 絕對不可見。"""
    migrate_database(isolated_db_path, derive_alter_statements(SCHEMA_PATH))

    conn = sqlite3.connect(str(isolated_db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO page_index_trees (
                doc_id, title, clinic_id, category, pre_op, procedure, post_op_short, maintenance,
                summary_text, source_type, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "secret-nano-surgery", "秘密奈米微創手術", CLINIC_ID, "special",
                "術前須知秘密", "秘密奈米療程步驟", "術後秘密照護", "長期秘密維持",
                "秘密奈米微創手術摘要說明，僅供院內測試使用", "web_upload", "pending",
            ),
        )
        secret_id = cur.lastrowid
        conn.commit()

        # 搜尋關鍵字「秘密奈米」
        hits_before = search_page_index_trees(conn, "秘密奈米", clinic_id=CLINIC_ID)
        assert len(hits_before) == 0  # 絕對隔離

        # 核准後應可搜尋到
        approve_tree(conn, secret_id)
        hits_after = search_page_index_trees(conn, "秘密奈米", clinic_id=CLINIC_ID)
        assert len(hits_after) == 1
        assert hits_after[0].fields["doc_id"] == "secret-nano-surgery"
    finally:
        conn.close()


def test_tree_distiller_compliance_and_physician_notes_empty(isolated_db_path):
    """驗證提煉引擎合規檢核：*_physician_notes 強制為 None，價格深度清洗，pending 寫入。"""
    migrate_database(isolated_db_path, derive_alter_statements(SCHEMA_PATH))

    mock_llm_output = """{
        "pre_op": "術前請充分溝通評估，費用約需 15000元，需禁食四小時。",
        "procedure": "採用高頻微波精準加熱深層組織，促進膠原收縮。",
        "post_op_short": "術後立即冰敷，局部微紅屬正常現象，多補充水分。",
        "maintenance": "維持規律作息與防曬，建議三至六個月定期追蹤保養。",
        "summary_text": "微波深層組織緊膚療程，術前禁食，術後加強冰敷保濕與防曬。"
    }"""

    conn = sqlite3.connect(str(isolated_db_path))
    try:
        res = distill_tree_from_text(
            conn,
            title="微波深層緊膚",
            text="微波深層緊膚完整臨床指引與衛教內文...",
            clinic_id=CLINIC_ID,
            doc_id="microwave-tightening",
            llm_call=lambda p: mock_llm_output,
            source_type="web_upload",
        )
        assert res["review_status"] == "pending"
        # 醫師指令強制為 None
        assert res["pre_op_physician_notes"] is None
        assert res["procedure_physician_notes"] is None
        assert res["post_op_short_physician_notes"] is None
        assert res["maintenance_physician_notes"] is None
        # 價格已清洗
        assert "15000元" not in res["pre_op"]
        assert "請致電診所確認" in res["pre_op"]

        # 驗證資料庫實際欄位
        t_db = get_tree(conn, 1)  # 隨便取或者查 doc_id
        cur = conn.cursor()
        cur.execute("SELECT review_status, pre_op FROM page_index_trees WHERE doc_id = 'microwave-tightening'")
        status_in_db, pre_op_in_db = cur.fetchone()
        assert status_in_db == "pending"
        assert "請致電診所確認" in pre_op_in_db
    finally:
        conn.close()


def test_admin_trees_api_endpoints(test_client, isolated_db_path, monkeypatch):
    """驗證 Admin API /api/v1/admin/trees 相關端點操作。"""
    migrate_database(isolated_db_path, derive_alter_statements(SCHEMA_PATH))

    # 1. 提煉端點 (POST /trees/distill)
    mock_llm_output = """{
        "pre_op": "術前需專業醫師諮詢評估體質與禁忌症。",
        "procedure": "利用微細光纖導入皮下脂肪層進行均勻加熱液化。",
        "post_op_short": "術後穿戴塑身加壓帶二十四小時，維持傷口清潔乾燥。",
        "maintenance": "維持均衡飲食與規律運動，避免暴飲暴食導致復胖。",
        "summary_text": "光纖溶脂手術衛教，術前評估，術後加壓護理與長期作息維持。"
    }"""
    from src.api.routes import admin
    monkeypatch.setattr(admin, "_local_llm_call", lambda p: mock_llm_output)

    res_distill = test_client.post(
        "/api/v1/admin/trees/distill",
        json={
            "title": "光纖溶脂手術",
            "text": "光纖溶脂手術完整文件說明內容長度需大於二十個字元...",
            "clinic_id": CLINIC_ID,
            "category": "special",
        },
    )
    assert res_distill.status_code == 200
    distill_data = res_distill.json()
    assert distill_data["status"] == "ok"
    doc_id = distill_data["tree"]["doc_id"]

    # 2. 列表查詢 (GET /trees)
    res_list = test_client.get("/api/v1/admin/trees?status=pending")
    assert res_list.status_code == 200
    trees = res_list.json()["trees"]
    target = next((t for t in trees if t["doc_id"] == doc_id), None)
    assert target is not None
    tree_id = target["id"]

    # 3. 詳情查詢 (GET /trees/{id})
    res_get = test_client.get(f"/api/v1/admin/trees/{tree_id}")
    assert res_get.status_code == 200
    assert res_get.json()["title"] == "光纖溶脂手術"

    # 4. 更新/填寫醫囑 (PUT /trees/{id})
    res_update = test_client.put(
        f"/api/v1/admin/trees/{tree_id}",
        json={"procedure_physician_notes": "能量設定需依組織厚度嚴格控制在 6W 以下。"},
    )
    assert res_update.status_code == 200
    assert res_update.json()["tree"]["procedure_physician_notes"] == "能量設定需依組織厚度嚴格控制在 6W 以下。"

    # 5. 核准 (POST /trees/{id}/approve)
    res_approve = test_client.post(f"/api/v1/admin/trees/{tree_id}/approve")
    assert res_approve.status_code == 200

    # 驗證狀態已變更為 approved
    res_get_app = test_client.get(f"/api/v1/admin/trees/{tree_id}")
    assert res_get_app.json()["review_status"] == "approved"
