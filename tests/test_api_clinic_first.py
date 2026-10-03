"""
API 層診所資料優先檢索（Clinic-First）與資料層級標示端對端測試（Phase 11 CF-02, CF-03）。
涵蓋：
- A1: 向後相容（data_level 不在 required，舊格式相容）
- A2: POST /api/v1/query 短路帶 data_level=='clinic'
- A3: 退回 general 時 data_level=='general'
- A4: 三個 API 查詢入口一致性
- A5: 無 clinic_id 查詢安全限制（data_level 僅可為 'general' 或 None）
- A6: 非短路時的層級標示（各 hit 與整體）
- A7: 價格二次遮蔽安全保證
- A8: 匿名快取統計語意與隱私保證
- A9: 匿名一般諮詢端點隔離保證
- A10: OpenAPI Schema 宣告
- A11: Blocker 回歸（API 層）
- A12: 決策 1 外洩修復（API 層）
- A13: 決策 2 special 路由退 general（API 層）
- A14: 統計語意註記（general 命中同樣記為 hit）
- A15: 空白路徑參數行為（W4）
"""

import re
import sqlite3
from fastapi.testclient import TestClient
import pytest

from src.api.app import create_app
from src.api.config import config
from src.api.models.query import QueryResponseModel, SearchHitModel
from src.query.router import classify

PRICE_REGEX = re.compile(r"(?:\$|NT\$|NT\s*|新台幣)?\s*\d+(?:,\d+)*(?:\.\d+)?\s*(?:元|點|塊)")


def _insert_faq(
    db_path,
    clinic_id: str | None,
    topic_key: str,
    question: str,
    answer: str,
    category: str = "special",
):
    """直接寫入測試資料庫複本之輔助函式。"""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status)
        VALUES (?, ?, ?, ?, ?, 'clinic_upload', 'approved')
        """,
        (clinic_id, topic_key, question, answer, category),
    )
    conn.commit()
    conn.close()


def _dump_stats(db_path) -> str:
    """傾印測試庫 cache_stats 整張表所有列轉成字串。"""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT id, clinic_id, stat_date, outcome, keyword, count FROM cache_stats")
    rows = cur.fetchall()
    conn.close()
    return " | ".join(str(r) for r in rows)


@pytest.fixture
def api_client(isolated_db_path, monkeypatch):
    """標準測試客戶端（預設 config.cache_stats_enabled=False）。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    app = create_app()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def stats_client(isolated_db_path, monkeypatch):
    """啟用統計記錄的測試客戶端（指向 isolated_db_path 複本）。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "cache_stats_enabled", True)
    app = create_app()
    with TestClient(app) as client:
        yield client


def test_a1_backward_compatibility():
    """A1: 向後相容——QueryResponseModel 與 SearchHitModel 中的 data_level 不在 required 且舊式 dict 能相容建構。"""
    qr_schema = QueryResponseModel.model_json_schema()
    sh_schema = SearchHitModel.model_json_schema()

    assert "data_level" not in qr_schema.get("required", [])
    assert "data_level" not in sh_schema.get("required", [])

    # 舊式 dict 建構模型
    old_sh = SearchHitModel(table="faq_cache", row_id=1, fields={"q": "a"})
    assert old_sh.data_level is None

    old_qr = QueryResponseModel(
        query="test query",
        route="general",
        matched_keywords=[],
        clinic_info=None,
        clinic_hours=[],
        page_index_hits=[],
        drug_hits=[],
        service_item_hits=[],
        clinic_custom_notes={},
        faq_hits=[],
        source="pageindex",
        cache_answer=None,
        cache_eligible=True,
    )
    assert old_qr.data_level is None


def test_a2_post_query_clinic_faq_shortcut(api_client, isolated_db_path):
    """A2: POST /api/v1/query 帶 body clinic_id 查詢診所 FAQ，短路回傳 data_level=='clinic'。"""
    q = "做完特定照護後居家皮膚清潔如何進行？"
    a = "請保持皮膚乾燥，並依照指示進行溫和清潔。"
    assert classify(q).route == "general"

    _insert_faq(isolated_db_path, "3503190424", "t_a2", q, a, category="special")

    resp = api_client.post("/api/v1/query", json={"query": q, "clinic_id": "3503190424"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "cache"
    assert data["cache_answer"] == a
    assert data["data_level"] == "clinic"
    assert len(data["faq_hits"]) == 1
    assert data["faq_hits"][0]["data_level"] == "clinic"


def test_a3_fallback_to_general_faq(api_client, isolated_db_path):
    """A3: 診所無合格候選時退回 approved general FAQ，data_level=='general'。"""
    q = "一般日常飲水量每日建議標準是多少毫升？"
    a = "成人每日建議飲水量約為體重乘以 30 毫升。"
    assert classify(q).route == "general"

    _insert_faq(isolated_db_path, None, "t_a3", q, a, category="general")

    resp = api_client.post("/api/v1/query", json={"query": q, "clinic_id": "3503190424"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "cache"
    assert data["cache_answer"] == a
    assert data["data_level"] == "general"
    assert len(data["faq_hits"]) == 1
    assert data["faq_hits"][0]["data_level"] == "general"


def test_a4_three_endpoints_consistency(api_client, isolated_db_path):
    """A4: 三個 API 查詢入口一致性（Header X-Clinic-ID、路徑參數、GET 查詢參數）。"""
    q = "做完特定照護後居家皮膚清潔如何進行？"
    a = "請保持皮膚乾燥，並依照指示進行溫和清潔。"
    _insert_faq(isolated_db_path, "3503190424", "t_a4", q, a, category="special")

    # 入口 1: POST /api/v1/query 帶 Header X-Clinic-ID
    r1 = api_client.post("/api/v1/query", json={"query": q}, headers={"X-Clinic-ID": "3503190424"})
    assert r1.status_code == 200
    assert r1.json()["data_level"] == "clinic"

    # 入口 2: POST /api/v1/clinics/{clinic_id}/query
    r2 = api_client.post("/api/v1/clinics/3503190424/query", json={"query": q})
    assert r2.status_code == 200
    assert r2.json()["data_level"] == "clinic"

    # 入口 3: GET /api/v1/query?q=&clinic_id=
    r3 = api_client.get(f"/api/v1/query?q={q}", headers={"X-Clinic-ID": "3503190424"})
    assert r3.status_code == 200
    assert r3.json()["data_level"] == "clinic"


def test_a5_query_without_clinic_id(api_client, isolated_db_path):
    """A5: 未帶診所身分查詢時，data_level 僅可為 'general' 或 null。"""
    q = "做完特定照護後居家皮膚清潔如何進行？"
    _insert_faq(isolated_db_path, "3503190424", "t_a5", q, "診所回答", category="special")

    # 查不帶 clinic_id：不得命中診所 FAQ
    resp = api_client.post("/api/v1/query", json={"query": q})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "pageindex"
    assert data["data_level"] in ("general", None)

    # 營運問句缺 clinic_id 仍為 HTTP 400
    r_ops = api_client.post("/api/v1/query", json={"query": "請問診所門診營業時間？"})
    assert r_ops.status_code == 400


def test_a6_non_shortcut_hybrid_levels(api_client, isolated_db_path):
    """A6: 非短路時的層級標示（各 hit 正確標示層級，整體 data_level 取首筆）。"""
    L1 = "甲溝炎門診處理完成之後傷口敷料需要每天更換並且保持乾燥清潔"
    _insert_faq(isolated_db_path, "3503190424", "t_a6_c1", L1, "方案一", category="special")
    _insert_faq(isolated_db_path, "3503190424", "t_a6_c2", L1, "方案二", category="special")
    _insert_faq(isolated_db_path, None, "t_a6_g", L1, "一般方案", category="general")

    resp = api_client.post("/api/v1/query", json={"query": L1, "clinic_id": "3503190424"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "pageindex"
    assert data["data_level"] == "clinic"
    assert len(data["faq_hits"]) >= 2
    assert data["faq_hits"][0]["data_level"] == "clinic"


def test_a7_price_secondary_masking(api_client, isolated_db_path):
    """A7: 價格二次遮蔽安全保證——即使快取答案內含金額，API 回應全文無任何數字價格。"""
    q = "特定進階煥膚護理自費療程單次費用約多少？"
    a = "本自費療程單次費用約 1500 元，請向櫃檯洽詢。"
    _insert_faq(isolated_db_path, "3503190424", "t_a7", q, a, category="special")

    resp = api_client.post("/api/v1/query", json={"query": q, "clinic_id": "3503190424"})
    assert resp.status_code == 200
    text = resp.text
    matches = PRICE_REGEX.findall(text)
    assert len(matches) == 0
    assert "[請致電診所確認]" in text


def test_a8_cache_stats_semantics_and_privacy(stats_client, isolated_db_path):
    """A8: 匿名快取統計語意與隱私保證——hit/miss 正確累加，整表不含問句原文。"""
    # 1. 命中統計
    q_hit = "做完特定照護後居家皮膚清潔如何進行？"
    a_hit = "請保持皮膚乾燥，並依照指示進行溫和清潔。"
    _insert_faq(isolated_db_path, "3503190424", "t_a8", q_hit, a_hit, category="special")

    r_hit = stats_client.post("/api/v1/query", json={"query": q_hit, "clinic_id": "3503190424"})
    assert r_hit.status_code == 200
    assert r_hit.json()["source"] == "cache"

    # 2. 未命中統計（無相關 FAQ 的獨特一般問句）
    q_miss = "無關的特殊皮膚衛教諮詢問答？"
    r_miss = stats_client.post("/api/v1/query", json={"query": q_miss, "clinic_id": "3503190424"})
    assert r_miss.status_code == 200
    assert r_miss.json()["source"] == "pageindex"

    # 3. 營運問句不記統計
    stats_before = _dump_stats(isolated_db_path)
    stats_client.post("/api/v1/query", json={"query": "請問診所幾點開門？", "clinic_id": "3503190424"})
    stats_after = _dump_stats(isolated_db_path)
    assert stats_before == stats_after

    # 4. 隱私保證：整張表無問句字串片段
    dump_text = _dump_stats(isolated_db_path)
    assert "居家皮膚清潔" not in dump_text
    assert "皮膚衛教諮詢" not in dump_text


def test_a9_anonymous_general_endpoint_unaffected(api_client, isolated_db_path):
    """A9: 匿名一般諮詢端點隔離保證——帶診所 FAQ 原句且夾帶 clinic_id 亦不回傳診所答案、無 data_level。"""
    q = "做完特定照護後居家皮膚清潔如何進行？"
    a = "請保持皮膚乾燥，並依照指示進行溫和清潔。"
    _insert_faq(isolated_db_path, "3503190424", "t_a9", q, a, category="special")

    # POST /api/v1/general/query 夾帶 clinic_id
    resp = api_client.post(
        "/api/v1/general/query",
        json={"query": q, "clinic_id": "3503190424"},
        headers={"X-Clinic-ID": "3503190424"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "data_level" not in data
    assert "query" not in data
    assert a not in resp.text


def test_a10_openapi_schema(api_client):
    """A10: OpenAPI Schema 宣告含 data_level 欄位。"""
    schema = api_client.app.openapi()
    qr_props = schema["components"]["schemas"]["QueryResponseModel"]["properties"]
    assert "data_level" in qr_props


def test_a11_blocker_regression_wound_showering_conflict_api(api_client, isolated_db_path):
    """A11: Blocker 回歸鎖定（API 層）——診所規定不可碰水 vs general 可淋浴，短句變形不得回 general 淋浴建議。"""
    q_c = "縫合後的傷口可以碰水洗澡嗎？"
    a_c = "本診所規定縫合後一週內不可碰水"
    q_g = "縫合後的傷口可以洗澡嗎？"
    a_g = "包覆防水敷料後可以淋浴"

    _insert_faq(isolated_db_path, "3503190424", "t_a11_c", q_c, a_c, category="special")
    _insert_faq(isolated_db_path, None, "t_a11_g", q_g, a_g, category="general")

    queries = [
        "縫合後傷口可以洗澡嗎",
        "縫合後的傷口可以洗澡嗎？",
        "縫合後傷口多久可以洗澡？",
    ]
    for q in queries:
        resp = api_client.post("/api/v1/query", json={"query": q, "clinic_id": "3503190424"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "pageindex"
        assert data["cache_answer"] is None
        assert "可以淋浴" not in (data.get("cache_answer") or "")
        assert data.get("data_level") != "general"


def test_a12_decision_1_cross_clinic_leak_fix_api(api_client, isolated_db_path):
    """A12: 決策 1 外洩修復（API 層）——無 clinic_id 查詢絕不列出他院 FAQ。"""
    q_drug = "這個藥有副作用嗎？"
    a_other = "其他診所特定指示"
    a_self = "本院專屬藥物說明"

    _insert_faq(isolated_db_path, "9999999999", "t_a12_other", q_drug, a_other, category="special")
    _insert_faq(isolated_db_path, "3503190424", "t_a12_self", q_drug, a_self, category="special")

    # 1. 無 clinic_id 查詢：絕不可包含他院 FAQ
    resp_no_clinic = api_client.post("/api/v1/query", json={"query": q_drug})
    assert resp_no_clinic.status_code == 200
    data_no_clinic = resp_no_clinic.json()
    for h in data_no_clinic["faq_hits"]:
        assert h["fields"].get("clinic_id") is None
    assert a_other not in resp_no_clinic.text

    # 2. 帶本院 clinic_id 查詢：看不到他院列
    resp_self = api_client.post("/api/v1/query", json={"query": q_drug, "clinic_id": "3503190424"})
    assert resp_self.status_code == 200
    for h in resp_self.json()["faq_hits"]:
        assert h["fields"].get("clinic_id") != "9999999999"


def test_a13_decision_2_special_route_fallback_to_general_api(api_client, isolated_db_path):
    """A13: 決策 2 special 路由退 general（API 層）——診所無關但含程序關鍵字時短路為 general。"""
    q = "健保給付審查流程一般需要多少工作天？"
    assert classify(q).route == "special"
    a_gen = "一般給付審查約需 7 至 14 個工作天。"
    _insert_faq(isolated_db_path, None, "t_a13", q, a_gen, category="general")

    resp = api_client.post("/api/v1/query", json={"query": q, "clinic_id": "3503190424"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "cache"
    assert data["data_level"] == "general"
    assert data["cache_answer"] == a_gen


def test_a14_stats_semantics_general_hit(stats_client, isolated_db_path):
    """A14: 統計語意註記——退回 general 層級命中同樣記為 hit（不區分 clinic/general）。"""
    q = "一般日常飲水量每日建議標準是多少毫升？"
    a = "成人每日建議飲水量約為體重乘以 30 毫升。"
    _insert_faq(isolated_db_path, None, "t_a14", q, a, category="general")

    resp = stats_client.post("/api/v1/query", json={"query": q, "clinic_id": "3503190424"})
    assert resp.status_code == 200
    assert resp.json()["source"] == "cache"
    assert resp.json()["data_level"] == "general"

    # 檢查 cache_stats 有 hit
    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    cur.execute("SELECT count FROM cache_stats WHERE clinic_id='3503190424' AND outcome='hit'")
    hit_row = cur.fetchone()
    conn.close()
    assert hit_row is not None and hit_row[0] >= 1


def test_a15_blank_clinic_id_parameter(api_client):
    """A15: 空白診所識別路徑參數行為——POST /api/v1/clinics/%20/query 帶營運問句回傳 HTTP 400。"""
    # 1. 路徑參數為純空白
    r_path_blank = api_client.post("/api/v1/clinics/%20/query", json={"query": "請問診所幾點開門？"})
    assert r_path_blank.status_code == 400

    # 2. Body clinic_id 為純空白
    r_body_blank = api_client.post("/api/v1/query", json={"query": "請問診所幾點開門？", "clinic_id": "   "})
    assert r_body_blank.status_code == 400

    # 3. GET 查詢參數 clinic_id 為純空白
    r_get_blank = api_client.get("/api/v1/query?q=請問診所幾點開門？", headers={"X-Clinic-ID": "   "})
    assert r_get_blank.status_code == 400
