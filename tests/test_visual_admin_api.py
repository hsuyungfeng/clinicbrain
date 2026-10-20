"""
Phase 31 Plan 31-03: 管理端動畫資產審核、列表、修訂與自動生成 API 測試 (test_visual_admin_api.py)。

測試涵蓋：
Task 1: src/visual/review.py 中的 list_visual_assets, get_visual_asset_by_id, update_visual_asset_by_id
Task 2: src/api/routes/admin.py 中的視覺資產管理端點與 summary 統計欄位
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config
from src.pageindex.tree_review import approve_tree
from src.pageindex.llm_client import LocalLLMUnavailableError
from src.visual.review import (
    get_visual_asset_by_id,
    list_visual_assets,
    set_review_status,
    update_visual_asset_by_id,
)
from src.visual.writer import upsert_assets
from tests.conftest import apply_visual_migration

CLINIC_ID = "3503190424"


def _sample_ir(
    topic_key: str = "autologous-fat-grafting",
    title: str = "自體脂肪移植原理與照護",
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "topic_key": topic_key,
        "title": title,
        "keywords": keywords or ["自體脂肪", "補脂", "移植"],
        "scenes": [
            {
                "blueprint": "process_diagram",
                "title": "抽取純化",
                "caption": "抽取適量脂肪並透過離心純化以保留健康脂肪細胞",
                "labels": [{"text": "抽取純化", "tone": "neutral"}],
            },
            {
                "blueprint": "contrast",
                "title": "分層注射",
                "caption": "以細微針管多層次均勻注入目標區域提升存活",
                "labels": [{"text": "分層注射", "tone": "optimal"}],
            },
            {
                "blueprint": "timeline",
                "title": "照護修復",
                "caption": "術後依醫囑照護觀察穩定維持實際成效因人而異",
                "labels": [{"text": "照護修復", "tone": "neutral"}],
            },
        ],
    }


@pytest.fixture
def test_client(isolated_db_path, monkeypatch):
    apply_visual_migration(isolated_db_path)
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "admin_api_key", "")
    with TestClient(app) as tc:
        yield tc


# ============================================================================
# Task 1: review.py 函式單元測試
# ============================================================================


def test_list_visual_assets_missing_table(isolated_db_path):
    """驗證未建立 visual_assets 資料表時安全回傳 ([], 0)。"""
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        # 測試複本尚未套用 visual schema
        items, total = list_visual_assets(conn)
        assert items == []
        assert total == 0
    finally:
        conn.close()


def test_list_visual_assets_filters_and_enrichment(isolated_db_path):
    """驗證 list_visual_assets 之狀態、診所範圍過濾與 merge_defaults 預設補齊。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        ir1 = _sample_ir(topic_key="general-fat", title="一般自體脂肪")
        ir2 = _sample_ir(topic_key="clinic-hifu", title="本院音波拉提")
        ir3 = _sample_ir(topic_key="other-clinic", title="他院療程")

        upsert_assets(conn, [{"topic_key": "general-fat", "title": ir1["title"], "keywords": ir1["keywords"], "ir": ir1, "clinic_id": None}], source_type="manual")
        upsert_assets(conn, [{"topic_key": "clinic-hifu", "title": ir2["title"], "keywords": ir2["keywords"], "ir": ir2, "clinic_id": CLINIC_ID}], source_type="manual")
        upsert_assets(conn, [{"topic_key": "other-clinic", "title": ir3["title"], "keywords": ir3["keywords"], "ir": ir3, "clinic_id": "9999999999"}], source_type="manual")

        # 預設 status="pending", scope="all", clinic_id=None -> 回傳全部 pending
        items, total = list_visual_assets(conn, status="pending")
        assert total == 3
        assert len(items) == 3

        # 驗證補齊：每個 scene 應包含 params 與 duration_sec，且 validation 為 ok
        first = items[0]
        assert "validation" in first
        assert first["validation"] == {"ok": True, "code": "ok"}
        assert len(first["scenes"]) == 3
        for sc in first["scenes"]:
            assert isinstance(sc["params"], dict)
            assert isinstance(sc["duration_sec"], int)
            assert 4 <= sc["duration_sec"] <= 12

        # 核准其中一筆
        set_review_status(conn, "general-fat", "approved", clinic_id=None)

        # 狀態過濾
        appr_items, appr_total = list_visual_assets(conn, status="approved")
        assert appr_total == 1
        assert appr_items[0]["topic_key"] == "general-fat"

        pend_items, pend_total = list_visual_assets(conn, status="pending")
        assert pend_total == 2

        all_items, all_total = list_visual_assets(conn, status="all")
        assert all_total == 3

        # scope="general"
        gen_items, gen_total = list_visual_assets(conn, status="all", scope="general")
        assert gen_total == 1
        assert gen_items[0]["topic_key"] == "general-fat"

        # scope="clinic", clinic_id=CLINIC_ID
        c_items, c_total = list_visual_assets(conn, status="all", clinic_id=CLINIC_ID, scope="clinic")
        assert c_total == 1
        assert c_items[0]["topic_key"] == "clinic-hifu"

        # scope="all", clinic_id=CLINIC_ID -> 本院專屬 + 一般共用
        combo_items, combo_total = list_visual_assets(conn, status="all", clinic_id=CLINIC_ID, scope="all")
        assert combo_total == 2
        combo_keys = {it["topic_key"] for it in combo_items}
        assert combo_keys == {"general-fat", "clinic-hifu"}
    finally:
        conn.close()


def test_get_and_update_visual_asset_by_id(isolated_db_path):
    """驗證 get_visual_asset_by_id 與 update_visual_asset_by_id 的合法修訂與阻斷。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        ir = _sample_ir(topic_key="fat-graft", title="原標題自體脂肪")
        upsert_assets(conn, [{"topic_key": "fat-graft", "title": ir["title"], "keywords": ir["keywords"], "ir": ir}], source_type="manual")

        # 取得剛寫入之資產
        cur = conn.cursor()
        cur.execute("SELECT id FROM visual_assets WHERE topic_key = 'fat-graft'")
        asset_id = cur.fetchone()[0]

        # 查單筆詳情
        asset = get_visual_asset_by_id(conn, asset_id)
        assert asset is not None
        assert asset["id"] == asset_id
        assert asset["title"] == "原標題自體脂肪"
        assert asset["review_status"] == "pending"

        # 先將其核准
        set_review_status(conn, "fat-graft", "approved", asset_id=asset_id)
        asset_appr = get_visual_asset_by_id(conn, asset_id)
        assert asset_appr["review_status"] == "approved"
        assert asset_appr["reviewed_at"] is not None

        # 修訂標題：成功後 review_status 應重置為 pending、reviewed_at 設為 NULL、version 遞增
        updated = update_visual_asset_by_id(conn, asset_id, title="新標題自體脂肪移植手術")
        assert updated is not None
        assert updated["title"] == "新標題自體脂肪移植手術"
        assert updated["review_status"] == "pending"
        assert updated["reviewed_at"] is None
        assert updated["content_version"] == 2

        # 嘗試修訂為包含阿拉伯數字 -> 拋出 ValueError("forbidden_phrase")
        with pytest.raises(ValueError) as excinfo:
            update_visual_asset_by_id(conn, asset_id, title="療程只需3天即可復原")
        assert "forbidden_phrase" in str(excinfo.value)

        # 嘗試在 caption 加入阿拉伯數字 -> 拋出 ValueError("forbidden_phrase")
        with pytest.raises(ValueError) as excinfo:
            update_visual_asset_by_id(conn, asset_id, scenes=[{"caption": "修復期僅需7天成效因人而異"}])
        assert "forbidden_phrase" in str(excinfo.value)

        # 不存在的 asset_id 回傳 None
        assert get_visual_asset_by_id(conn, 999999) is None
        assert update_visual_asset_by_id(conn, 999999, title="新標題") is None
    finally:
        conn.close()


# ============================================================================
# Task 2: 管理端 API 端點測試
# ============================================================================


def test_admin_visual_list_and_detail(test_client, isolated_db_path):
    """驗證 GET /api/v1/admin/visuals 與 GET /api/v1/admin/visuals/{asset_id}。"""
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        ir = _sample_ir(topic_key="rhinoplasty", title="結構式隆鼻手術原理")
        upsert_assets(conn, [{"topic_key": "rhinoplasty", "title": ir["title"], "keywords": ir["keywords"], "ir": ir}], source_type="manual")
        cur = conn.cursor()
        cur.execute("SELECT id FROM visual_assets WHERE topic_key = 'rhinoplasty'")
        asset_id = cur.fetchone()[0]
    finally:
        conn.close()

    # 列表端點
    res = test_client.get("/api/v1/admin/visuals?status=pending")
    assert res.status_code == 200
    data = res.json()
    assert "visuals" in data
    assert data["total"] >= 1
    item = next(it for it in data["visuals"] if it["id"] == asset_id)
    assert item["topic_key"] == "rhinoplasty"
    assert len(item["scenes"]) == 3

    # 單筆詳情端點
    res_single = test_client.get(f"/api/v1/admin/visuals/{asset_id}")
    assert res_single.status_code == 200
    single_data = res_single.json()
    assert single_data["id"] == asset_id
    assert single_data["topic_key"] == "rhinoplasty"

    # 單筆詳情 404
    res_404 = test_client.get("/api/v1/admin/visuals/999999")
    assert res_404.status_code == 404


def test_admin_visual_patch_validation_and_reset(test_client, isolated_db_path):
    """驗證 PATCH /api/v1/admin/visuals/{asset_id} 的內聯修訂與防護。"""
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        ir = _sample_ir(topic_key="eyelid-surgery", title="雙眼皮手術照護原理")
        upsert_assets(conn, [{"topic_key": "eyelid-surgery", "title": ir["title"], "keywords": ir["keywords"], "ir": ir}], source_type="manual")
        cur = conn.cursor()
        cur.execute("SELECT id FROM visual_assets WHERE topic_key = 'eyelid-surgery'")
        asset_id = cur.fetchone()[0]
    finally:
        conn.close()

    # 1. 成功修訂文字（標題與第一場景說明）
    patch_payload = {
        "title": "雙眼皮成形術手術照護原理",
        "scenes": [
            {"caption": "依眼部解剖結構進行精細縫合以形成對稱自然摺痕"}
        ],
    }
    res = test_client.patch(f"/api/v1/admin/visuals/{asset_id}", json=patch_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "雙眼皮成形術手術照護原理"
    assert data["review_status"] == "pending"

    # 2. 違規修訂：含阿拉伯數字 -> 422 且 detail 不洩漏原文
    bad_payload = {"title": "只需3天立即見效"}
    res_bad = test_client.patch(f"/api/v1/admin/visuals/{asset_id}", json=bad_payload)
    assert res_bad.status_code == 422
    err_detail = res_bad.json()["detail"]
    assert "動畫內容驗證未通過" in err_detail
    assert "只需3天" not in err_detail

    # 3. 違規修訂：帶入禁止的額外欄位 -> extra='forbid' 422
    forbid_payload = {"unknown_key": "invalid"}
    res_extra = test_client.patch(f"/api/v1/admin/visuals/{asset_id}", json=forbid_payload)
    assert res_extra.status_code == 422

    # 4. 不存在的 asset_id -> 404
    res_404 = test_client.patch("/api/v1/admin/visuals/999999", json={"title": "新標題"})
    assert res_404.status_code == 404


def test_admin_visual_approve_and_reject(test_client, isolated_db_path):
    """驗證 POST /api/v1/admin/visuals/{asset_id}/approve 與 reject。"""
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        ir = _sample_ir(topic_key="breast-aug", title="隆乳手術原理與照護")
        upsert_assets(conn, [{"topic_key": "breast-aug", "title": ir["title"], "keywords": ir["keywords"], "ir": ir}], source_type="manual")
        cur = conn.cursor()
        cur.execute("SELECT id FROM visual_assets WHERE topic_key = 'breast-aug'")
        asset_id = cur.fetchone()[0]
    finally:
        conn.close()

    # 核准
    res_appr = test_client.post(f"/api/v1/admin/visuals/{asset_id}/approve")
    assert res_appr.status_code == 200
    assert res_appr.json()["review_status"] == "approved"

    # 再次查詢確認狀態
    res_get = test_client.get(f"/api/v1/admin/visuals/{asset_id}")
    assert res_get.json()["review_status"] == "approved"

    # 駁回
    res_rej = test_client.post(f"/api/v1/admin/visuals/{asset_id}/reject")
    assert res_rej.status_code == 200
    assert res_rej.json()["review_status"] == "rejected"

    # 404 測試
    assert test_client.post("/api/v1/admin/visuals/999999/approve").status_code == 404
    assert test_client.post("/api/v1/admin/visuals/999999/reject").status_code == 404


def test_admin_visual_autodraft_flow(test_client, isolated_db_path, monkeypatch):
    """驗證 POST /api/v1/admin/visuals/autodraft 觸發自動生成之流程與異常邊界。"""
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        # 建立一筆測試用的推理樹
        cur = conn.cursor()
        cur.execute("DELETE FROM page_index_trees WHERE doc_id = 'test-autodraft-hifu'")
        cur.execute(
            """
            INSERT INTO page_index_trees (
                doc_id, title, clinic_id, category, pre_op, procedure, post_op_short, maintenance,
                review_status, content_version, created_at, updated_at
            ) VALUES (
                'test-autodraft-hifu', '高能量聚焦超音波測試', ?, 'special',
                '術前評估皮膚厚度與鬆弛程度並清潔治療部位',
                '利用高強度聚焦超音波作用於筋膜層產生微熱凝結點以刺激膠原蛋白新生',
                '術後局部微紅屬正常現象宜加強保濕與防曬',
                '定期維持適當生活作息以維持緊緻實際成效因人而異',
                'pending', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            (CLINIC_ID,),
        )
        tree_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    # 1. 推理樹未核准 -> 400
    res_not_approved = test_client.post("/api/v1/admin/visuals/autodraft", json={"tree_id": tree_id})
    assert res_not_approved.status_code == 400

    # 將該推理樹核准
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        approve_tree(conn, tree_id)
    finally:
        conn.close()

    # 2. 推理樹不存在 -> 404
    res_404 = test_client.post("/api/v1/admin/visuals/autodraft", json={"tree_id": 999999})
    assert res_404.status_code == 404

    # 3. 本地 LLM 不可用 -> 503
    def _mock_llm_fail(prompt):
        raise LocalLLMUnavailableError("llama-server unavailable")

    monkeypatch.setattr("src.api.routes.admin._visual_llm_call", _mock_llm_fail)
    res_503 = test_client.post("/api/v1/admin/visuals/autodraft", json={"tree_id": tree_id})
    assert res_503.status_code == 503

    # 4. 正常生成 -> 200 且狀態為 pending
    from tests.test_visual_autodraft import VALID_MODEL_JSON
    mock_llm_output = f"```json\n{VALID_MODEL_JSON}\n```"

    monkeypatch.setattr("src.api.routes.admin._visual_llm_call", lambda p: mock_llm_output)
    res_ok = test_client.post("/api/v1/admin/visuals/autodraft", json={"tree_id": tree_id})
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["review_status"] == "pending"
    assert data["topic_key"] == "tree-test-autodraft-hifu"


def test_admin_review_summary_includes_visual_totals(test_client, isolated_db_path):
    """驗證 GET /api/v1/admin/review/summary 包含 visuals_pending_total 與 visuals_approved_total。"""
    res = test_client.get("/api/v1/admin/review/summary")
    assert res.status_code == 200
    data = res.json()
    assert "visuals_pending_total" in data
    assert "visuals_approved_total" in data
    assert isinstance(data["visuals_pending_total"], int)
    assert isinstance(data["visuals_approved_total"], int)
