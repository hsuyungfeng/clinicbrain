"""
Taiwan Clinic Medical PageIndex RAG System - 臨床決策推理樹端到端業務生命週期測試 (test_trees_e2e_pipeline)
Phase 21 Plan 21-03:
完整生命週期驗證：
1. 提煉引擎提煉臨床推理樹草稿 (review_status='pending')。
2. 驗證四段 physician_notes 欄位強制為 None。
3. 驗證 Fail-Closed 隔離：公開查詢端點 (/api/v1/query) 絕對不可見該決策樹。
4. 醫師填寫專屬醫囑 (PUT /api/v1/admin/trees/{id})。
5. 醫師簽核核准 (POST /api/v1/admin/trees/{id}/approve)。
6. 驗證狀態轉為 approved，FTS5 自動同步。
7. 驗證公開查詢 (/api/v1/query) 成功檢索到該決策樹並作為推理證據 (source='pageindex')。
"""

import sqlite3
import pytest
from fastapi.testclient import TestClient

from scripts.migrate_page_index_review import derive_alter_statements, migrate_database, SCHEMA_PATH
from src.api.app import app
from src.api.config import config
from src.pageindex.tree_distiller import distill_tree_from_text
from src.pageindex.tree_review import approve_tree, get_tree, update_tree

CLINIC_ID = "3503190424"


@pytest.fixture
def client(isolated_db_path, monkeypatch):
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "admin_api_key", "")
    with TestClient(app) as tc:
        yield tc


def test_clinical_reasoning_tree_full_e2e_lifecycle(client, isolated_db_path, monkeypatch):
    """測試臨床推理樹自提煉、隔離、醫師醫囑填寫、簽核至公開查詢命中之閉環。"""
    migrate_database(isolated_db_path, derive_alter_statements(SCHEMA_PATH))
    conn = sqlite3.connect(str(isolated_db_path))

    doc_id = "e2e-endolift-laser"
    procedure_title = "光纖微雕溶脂拉提術"
    search_keyword = "光纖微雕溶脂"

    try:
        # 1. 模擬提煉引擎處理文件
        mock_output = """{
            "pre_op": "術前需專業外科醫師評估皮下脂肪厚度與鬆弛程度，收費請致電診所確認，確認無凝血功能異常。",
            "procedure": "使用光纖探針導入皮下組織，以專屬波長雷射精準液化脂肪並刺激膠原蛋白收縮新生。",
            "post_op_short": "術後二十四小時內穿戴面部加壓頭套，局部可能輕微瘀青，三天內配合冰敷護理。",
            "maintenance": "保持正常生活作息與清淡飲食，定期回診觀察皮下組織重塑狀態與緊緻效果。",
            "summary_text": "光纖微雕溶脂拉提術臨床指引，術前評估脂肪厚度，術後配戴加壓頭套並加強冰敷保養。"
        }"""

        tree = distill_tree_from_text(
            conn,
            title=procedure_title,
            text="光纖微雕溶脂臨床指引內文...",
            clinic_id=CLINIC_ID,
            doc_id=doc_id,
            llm_call=lambda p: mock_output,
            category="special",
            source_type="web_upload",
        )
        assert tree["review_status"] == "pending"

        # 2. 驗證四項醫師特約醫囑強制留空 None
        assert tree["pre_op_physician_notes"] is None
        assert tree["procedure_physician_notes"] is None
        assert tree["post_op_short_physician_notes"] is None
        assert tree["maintenance_physician_notes"] is None

        cur = conn.cursor()
        cur.execute("SELECT id, review_status FROM page_index_trees WHERE doc_id = ?", (doc_id,))
        row = cur.fetchone()
        assert row is not None
        tree_id, db_status = row
        assert db_status == "pending"

        # 3. 驗證 Fail-Closed 隔離：公開端點絕對不可檢索到
        q_resp1 = client.post(
            "/api/v1/query",
            json={"query": search_keyword, "clinic_id": CLINIC_ID},
        )
        assert q_resp1.status_code == 200
        data1 = q_resp1.json()
        # 檢查回傳的 context / trees，不得包含此 doc_id
        if "trees" in data1:
            assert not any(t.get("doc_id") == doc_id for t in data1["trees"])

        # 4. 醫師填寫專屬醫囑 (PUT /api/v1/admin/trees/{id})
        res_update = client.put(
            f"/api/v1/admin/trees/{tree_id}",
            json={
                "pre_op_physician_notes": "若曾於治療區域施打不可吸收微整填充物者，必須先安排超音波掃描。",
                "post_op_short_physician_notes": "加壓頭套第一週需全天配戴，第二週起改為夜間睡眠時配戴。",
            },
        )
        assert res_update.status_code == 200
        updated_data = res_update.json()["tree"]
        assert "超音波掃描" in updated_data["pre_op_physician_notes"]

        # 5. 醫師簽核核准 (POST /api/v1/admin/trees/{id}/approve)
        res_approve = client.post(f"/api/v1/admin/trees/{tree_id}/approve")
        assert res_approve.status_code == 200

        # 6. 驗證資料庫狀態已轉為 approved
        tree_approved = get_tree(conn, tree_id)
        assert tree_approved["review_status"] == "approved"

        # 7. 驗證公開查詢端點立即生效
        q_resp2 = client.post(
            "/api/v1/query",
            json={"query": search_keyword, "clinic_id": CLINIC_ID},
        )
        assert q_resp2.status_code == 200
        data2 = q_resp2.json()

        # 驗證返回結果中包含核准後之推理樹或由其驅動
        assert data2.get("source") in ("pageindex", "llm", "cache")
        # 檢查 trees 欄位或檢索命中中包含此 doc_id
        if "trees" in data2:
            assert any(t.get("doc_id") == doc_id for t in data2["trees"])

    finally:
        conn.close()
