"""Phase 28 Plan 09: 伺服器固定單一診所設定 (patient_clinic_id) 範圍與解析測試。

涵蓋：
Task 1:
- Test 1: 未設定環境變數 CLINICBRAIN_PATIENT_CLINIC_ID -> patient_clinic_id 為 None。
- Test 2: 設定為純空白 -> 視為 None。
- Test 3: resolve_patient_clinic 在 clinic_info 存在時回傳代碼，不存在或非 10 碼數字回 None。
- Test 4: clinic_info 資料表缺失時回 None (Fail-Closed)，不拋例外。
- Test 4b: monkeypatch.setenv 後新建 APIConfig() 實例可讀到新值，delenv 後為 None。
- Test 4c: 連續測試驗證 _reset_patient_clinic_id 避免設定殘留。
- Test 5: 函式在 PRAGMA query_only = ON 下可執行，純 SELECT 不寫庫。
"""

import os
import sqlite3
import pytest

from src.api.config import APIConfig, config
from src.general.patient_clinic import resolve_patient_clinic


def test_1_config_patient_clinic_id_default_none(monkeypatch):
    """Test 1: 環境變數 CLINICBRAIN_PATIENT_CLINIC_ID 未設定 -> config.patient_clinic_id 為 None。"""
    monkeypatch.delenv("CLINICBRAIN_PATIENT_CLINIC_ID", raising=False)
    cfg = APIConfig()
    assert cfg.patient_clinic_id is None


def test_2_config_patient_clinic_id_blank_is_none(monkeypatch):
    """Test 2: 設定為純空白字串 -> 視為 None。"""
    monkeypatch.setenv("CLINICBRAIN_PATIENT_CLINIC_ID", "   ")
    cfg = APIConfig()
    assert cfg.patient_clinic_id is None


def test_3_resolve_patient_clinic_validation(isolated_conn):
    """Test 3: resolve_patient_clinic 驗證有效代碼、不存在代碼、格式不合與 None。"""
    # 建立測試診所資料
    isolated_conn.execute("INSERT OR IGNORE INTO clinic_info (clinic_id, name) VALUES ('3503190424', '緻妍外科診所')")
    isolated_conn.commit()

    # 1. 存在於 clinic_info 且為 10 碼數字
    assert resolve_patient_clinic(isolated_conn, "3503190424") == "3503190424"

    # 2. 不存在於 clinic_info
    assert resolve_patient_clinic(isolated_conn, "0000000000") is None

    # 3. 格式不合（少於 10 碼、多於 10 碼、含英文）
    assert resolve_patient_clinic(isolated_conn, "12345") is None
    assert resolve_patient_clinic(isolated_conn, "35031904240") is None
    assert resolve_patient_clinic(isolated_conn, "ABC1234567") is None

    # 4. None 或空字串
    assert resolve_patient_clinic(isolated_conn, None) is None
    assert resolve_patient_clinic(isolated_conn, "") is None


def test_4_resolve_patient_clinic_fail_closed_on_missing_table():
    """Test 4: clinic_info 資料表缺失或損毀時回 None (Fail-Closed)，不拋例外、不改查他院。"""
    mem_conn = sqlite3.connect(":memory:")
    # 空資料庫，無 clinic_info 表
    assert resolve_patient_clinic(mem_conn, "3503190424") is None
    mem_conn.close()


def test_4b_config_monkeypatch_reactivity(monkeypatch):
    """Test 4b: monkeypatch.setenv 後新建 APIConfig() 實例即可讀到新值；delenv 後為 None。"""
    monkeypatch.setenv("CLINICBRAIN_PATIENT_CLINIC_ID", "3503190424")
    cfg1 = APIConfig()
    assert cfg1.patient_clinic_id == "3503190424"

    monkeypatch.delenv("CLINICBRAIN_PATIENT_CLINIC_ID", raising=False)
    cfg2 = APIConfig()
    assert cfg2.patient_clinic_id is None


def test_4c_fixture_isolation_step_1(monkeypatch):
    """Test 4c 第 1 步：故意污染全域 config.patient_clinic_id。"""
    monkeypatch.setattr(config, "patient_clinic_id", "DIRTY_TEST_VALUE")
    assert config.patient_clinic_id == "DIRTY_TEST_VALUE"


def test_4c_fixture_isolation_step_2():
    """Test 4c 第 2 步：驗證上一測試的污染已被 _reset_patient_clinic_id 自動清除為 None。"""
    assert config.patient_clinic_id is None


def test_5_resolve_patient_clinic_read_only(isolated_conn):
    """Test 5: 函式在 PRAGMA query_only = ON 唯讀模式下可正常執行，無寫入語句。"""
    isolated_conn.execute("INSERT OR IGNORE INTO clinic_info (clinic_id, name) VALUES ('3503190424', '緻妍外科診所')")
    isolated_conn.commit()

    isolated_conn.execute("PRAGMA query_only = ON")
    res = resolve_patient_clinic(isolated_conn, "3503190424")
    assert res == "3503190424"
    isolated_conn.execute("PRAGMA query_only = OFF")


# =============================================================================
# Task 2 測試：診所範圍證據檢索與組稿整合
# =============================================================================

CLINIC_A = "3503190424"
CLINIC_B = "3503264627"
DOCTOR_WARN = "若出現胸痛、呼吸困難或體溫超過38.5度達3天，請立即就醫。"


@pytest.fixture
def scoped_env(isolated_conn):
    """設定兩家診所的 basic info、special FAQ 與指引樹。"""
    conn = isolated_conn
    conn.execute("INSERT OR IGNORE INTO clinic_info (clinic_id, name) VALUES (?, '緻妍外科診所')", (CLINIC_A,))
    conn.execute("INSERT OR IGNORE INTO clinic_info (clinic_id, name) VALUES (?, '凡登整形外科診所')", (CLINIC_B,))

    # 1. 診所 A 已核准 special FAQ
    conn.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, review_status)
        VALUES (?, 'a-bleph', '雙眼皮縫線拆線需要幾天？', ?, 'special', 'approved')
        """,
        (CLINIC_A, f"雙眼皮縫線處置一般於術後5天回診拆線，請維持傷口乾燥清潔。{DOCTOR_WARN}"),
    )

    # 2. 診所 A 待審 pending special FAQ（含專屬字串，source_type='llm_generated'）
    conn.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, review_status, source_type)
        VALUES (?, 'a-pending-rhino', '隆鼻手術保固期多久？', 'SECRET_PENDING_A_CONTENT 隆鼻保固二年。', 'special', 'pending', 'llm_generated')
        """,
        (CLINIC_A,),
    )

    # 3. 診所 B 已核准 special FAQ（含專屬字串）
    conn.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, review_status)
        VALUES (?, 'b-bleph', '雙眼皮縫線拆線需要幾天？', ?, 'special', 'approved')
        """,
        (CLINIC_B, f"凡登雙眼皮拆線為術後7天回診處置。SECRET_CLINIC_B_CONTENT 凡登專屬照護。{DOCTOR_WARN}"),
    )

    # 4. 診所 A 已核准預生成列（metadata origin=patient_prefill）
    import json
    meta = json.dumps({"origin": "patient_prefill", "intent": "what"}, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, review_status, metadata)
        VALUES (?, 'prefill-tree-a-what', '音波緊膚拉皮是什麼療程？', ?, 'special', 'approved', ?)
        """,
        (CLINIC_A, f"音波緊膚拉皮是利用聚焦超音波刺激筋膜層達到收縮緊緻效果。{DOCTOR_WARN}", meta),
    )

    # 5. 通用已核准 FAQ (clinic_id IS NULL)
    conn.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, review_status)
        VALUES (NULL, 'general-diet', '手術前飲食禁忌有哪些？', ?, 'general', 'approved')
        """,
        (f"術前應避免活血保健食品如銀杏與魚油至少一週。{DOCTOR_WARN}",),
    )

    conn.commit()
    return conn


def test_t2_1_unset_clinic_id_matches_28_03(scoped_env):
    """Test 1（未設定不變）: clinic_id 為 None 時，行為與 28-03 完全相同，不命中任何 special 資料。"""
    from src.general.patient_consult import patient_consult

    llm_calls = 0

    def _counting_llm(p):
        nonlocal llm_calls
        llm_calls += 1
        return "答：未審一般回覆。\n" + DOCTOR_WARN

    # 問診所 A 的題目，但 clinic_id 為 None
    res = patient_consult(scoped_env, "雙眼皮縫線拆線需要幾天？", llm_call=_counting_llm, clinic_id=None)
    # 不命中 special，因無 general 資料故往下走到 2.24/no_match
    assert res.status in ("llm_general", "no_match")
    assert "SECRET_CLINIC_B_CONTENT" not in res.message


def test_t2_2_clinic_direct_shortcut(scoped_env):
    """Test 2（診所直答）: clinic_id 為診所 A，吻合 A 的已核准 special FAQ，0 次 LLM 直答。"""
    from src.general.patient_consult import patient_consult

    llm_calls = 0

    def _forbidden_llm(p):
        nonlocal llm_calls
        llm_calls += 1
        raise AssertionError("直答時不得呼叫 LLM！")

    res = patient_consult(scoped_env, "雙眼皮縫線拆線需要幾天？", llm_call=_forbidden_llm, clinic_id=CLINIC_A)
    assert res.status == "answered"
    assert llm_calls == 0
    assert "5天" in res.message
    assert "？" in res.message
    assert "預約" in res.message
    assert "SECRET_CLINIC_B_CONTENT" not in res.message


def test_t2_3_pending_invisible(scoped_env):
    """Test 3（pending 不可見）: 同一診所 A 的 pending special FAQ 絕不出現在回覆或 prompt。"""
    from src.general.patient_consult import patient_consult

    captured_prompt = ""

    def _capturing_llm(p):
        nonlocal captured_prompt
        captured_prompt = p
        return "答：一般醫學回覆。\n" + DOCTOR_WARN

    res = patient_consult(scoped_env, "隆鼻手術保固期多久？", llm_call=_capturing_llm, clinic_id=CLINIC_A)
    assert "SECRET_PENDING_A_CONTENT" not in res.message
    assert "SECRET_PENDING_A_CONTENT" not in captured_prompt


def test_t2_4_cross_clinic_isolation(scoped_env):
    """Test 4（絕不跨診所）: 診所 B 有已核准內容，設定 A 時絕不出現 B，反之亦然。"""
    from src.general.patient_consult import patient_consult

    # 設定為 A -> 命中 A（5天），無 B（7天、SECRET_CLINIC_B_CONTENT）
    res_a = patient_consult(scoped_env, "雙眼皮縫線拆線需要幾天？", llm_call=lambda p: "", clinic_id=CLINIC_A)
    assert "5天" in res_a.message
    assert "SECRET_CLINIC_B_CONTENT" not in res_a.message
    assert "7天" not in res_a.message

    # 設定為 B -> 命中 B（7天），無 A（5天）
    res_b = patient_consult(scoped_env, "雙眼皮縫線拆線需要幾天？", llm_call=lambda p: "", clinic_id=CLINIC_B)
    assert "7天" in res_b.message
    assert "SECRET_CLINIC_B_CONTENT" in res_b.message
    assert "5天" not in res_b.message


def test_t2_5_risk_mismatch_and_ambiguity(scoped_env):
    """Test 5（風險檢查）: 數字不對稱不直答；查詢過短不直答。"""
    from src.general.patient_consult import patient_consult

    llm_calls = 0

    def _counting_llm(p):
        nonlocal llm_calls
        llm_calls += 1
        return "答：處置回覆說明。\n" + DOCTOR_WARN

    # 1. 數字不對稱：問 3 天 vs FAQ 的 5 天 -> risk_mismatch 不直答
    res1 = patient_consult(scoped_env, "雙眼皮縫線拆線需要3天嗎？", llm_call=_counting_llm, clinic_id=CLINIC_A)
    # 直答被阻擋，走組稿或降級
    assert res1.status in ("answered", "llm_general", "no_match")

    # 2. 查詢過短（少於 4 字元）不直答
    res2 = patient_consult(scoped_env, "拆線？", llm_call=_counting_llm, clinic_id=CLINIC_A)
    assert res2.status in ("answered", "llm_general", "no_match")


def test_t2_6_clinic_ops_keywords(scoped_env):
    """Test 6（營運關鍵字）: 問句含地址、電話、營業時間時不使用診所證據。"""
    from src.general.patient_consult import patient_consult

    captured_prompt = ""

    def _capturing_llm(p):
        nonlocal captured_prompt
        captured_prompt = p
        return "答：說明。\n" + DOCTOR_WARN

    # 問句含營運關鍵字「地址」
    res = patient_consult(scoped_env, "診所地址在哪裡？雙眼皮縫線拆線需要幾天？", llm_call=_capturing_llm, clinic_id=CLINIC_A)
    # 不得使用診所 special 證據直答或送入 prompt
    assert "雙眼皮縫線處置一般於術後5天回診拆線" not in captured_prompt


def test_t2_7_compose_with_clinic_evidence(scoped_env):
    """Test 7（組稿帶診所證據）: 診所 FAQ 未達直答門檻但有相關資料時，prompt 含診所層級與通用內容。"""
    from src.general.patient_consult import patient_consult

    captured_prompt = ""

    def _capturing_llm(p):
        nonlocal captured_prompt
        captured_prompt = p
        return "答：雙眼皮拆線後請維持良好清潔。\n追問：您想了解護理嗎？\n" + DOCTOR_WARN

    # 相關問句，含「雙眼皮縫線」關鍵字但覆蓋率僅約 0.4～0.5，未達 0.9 雙門檻故不直答
    res = patient_consult(scoped_env, "雙眼皮縫線的詳細照護說明？", llm_call=_capturing_llm, clinic_id=CLINIC_A)
    assert res.status == "answered"
    assert "診所" in captured_prompt or "雙眼皮" in captured_prompt


def test_t2_8_special_tree_prefill_hit(scoped_env):
    """Test 8（樹來源）: 診所 A 已核准的 special 預生成列可被直答命中。"""
    from src.general.patient_consult import patient_consult

    llm_calls = 0

    def _forbidden_llm(p):
        nonlocal llm_calls
        llm_calls += 1
        raise AssertionError("預生成核准後命中不得呼叫 LLM！")

    res = patient_consult(scoped_env, "音波緊膚拉皮是什麼療程？", llm_call=_forbidden_llm, clinic_id=CLINIC_A)
    assert res.status == "answered"
    assert llm_calls == 0
    assert "超音波" in res.message
    assert "？" in res.message
    assert "預約" in res.message


def test_t2_10_no_data_does_not_return_answered(scoped_env):
    """Test 10（無資料不得以 answered 回覆）: clinic_id 有效但無相關資料，走草稿或 no_match。"""
    from src.general.patient_consult import patient_consult

    llm_calls = 0

    def _counting_llm(p):
        nonlocal llm_calls
        llm_calls += 1
        return "答：完全無關問題之未審回覆。\n" + DOCTOR_WARN

    res = patient_consult(scoped_env, "外太空星際航行重力推進器如何保養？", llm_call=_counting_llm, clinic_id=CLINIC_A)
    assert res.status != "answered"
    assert res.status in ("llm_general", "no_match")


def test_t2_9_privacy_no_db_changes_or_logging(scoped_env, caplog):
    """Test 9（隱私）: 查詢前後 faq_cache 列數不變，日誌不含問句原文。"""
    from src.general.patient_consult import patient_consult

    cur = scoped_env.cursor()
    cur.execute("SELECT count(*) FROM faq_cache WHERE category = 'special'")
    count_before = cur.fetchone()[0]

    SECRET_Q = "極度機密的私人諮詢問句_XYZZY_888"
    patient_consult(scoped_env, SECRET_Q, llm_call=lambda p: "答：回覆。\n" + DOCTOR_WARN, clinic_id=CLINIC_A)

    cur.execute("SELECT count(*) FROM faq_cache WHERE category = 'special'")
    assert cur.fetchone()[0] == count_before  # special 列數絕不增加（不寫草稿）

    all_logs = caplog.text + "\n" + "\n".join(r.getMessage() for r in caplog.records)
    assert SECRET_Q not in all_logs


# ==============================================================================
# Task 3: 路由與 job 接線、忽略請求夾帶、端點純記憶體特性
# ==============================================================================

@pytest.fixture
def http_client(scoped_env, isolated_db_path, monkeypatch):
    """建立指向含有 scoped_env 測試資料庫的 TestClient。"""
    import json
    from fastapi.testclient import TestClient
    from src.api.app import app
    from src.api.routes import general as general_route
    from src.general import consult_jobs
    from src.general import patient_consult as pc

    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)

    mock_warning = "若出現胸痛、呼吸困難或體溫持續超過38.5度達3天，請立即前往急診或儘速就醫。"
    mock_body = "一般醫學衛教說明內容。" + mock_warning

    def _mock_llm(prompt):
        return json.dumps([{"question": "雙眼皮縫線拆線需要幾天？", "answer": mock_body}], ensure_ascii=False)

    monkeypatch.setattr(general_route, "default_patient_llm", _mock_llm)
    monkeypatch.setattr(pc, "default_patient_llm", _mock_llm)

    consult_jobs.reset_for_tests()
    with TestClient(app) as client:
        yield client
    consult_jobs.wait_idle(timeout=5.0)
    consult_jobs.reset_for_tests()


def test_t3_1_sync_and_jobs_use_configured_patient_clinic_id(http_client, monkeypatch):
    """Test 1: 同步 /consult 與 POST /consult/jobs 皆使用 config.patient_clinic_id 經 resolve 解析。"""
    from src.general import consult_jobs

    # 1. 設定為有效診所 A
    monkeypatch.setattr(config, "patient_clinic_id", CLINIC_A)

    # 1a. 同步 /consult 端點直答
    r_sync = http_client.post("/api/v1/general/consult", json={"query": "雙眼皮縫線拆線需要幾天？"})
    assert r_sync.status_code == 200
    sync_data = r_sync.json()
    assert sync_data["status"] == "answered"
    assert "5天" in sync_data["message"]
    assert "SECRET_CLINIC_B_CONTENT" not in sync_data["message"]

    # 1b. 非同步 /consult/jobs 端點
    r_job = http_client.post("/api/v1/general/consult/jobs", json={"query": "雙眼皮縫線拆線需要幾天？"})
    assert r_job.status_code == 200
    job_id = r_job.json()["job_id"]
    assert consult_jobs.wait_idle(timeout=5.0)

    r_poll = http_client.get(f"/api/v1/general/consult/jobs/{job_id}")
    assert r_poll.status_code == 200
    poll_data = r_poll.json()
    assert poll_data["status"] == "answered"
    assert "5天" in poll_data["message"]
    assert "SECRET_CLINIC_B_CONTENT" not in poll_data["message"]

    # 2. 未設定診所 (None)
    monkeypatch.setattr(config, "patient_clinic_id", None)
    r_unset = http_client.post("/api/v1/general/consult", json={"query": "雙眼皮縫線拆線需要幾天？"})
    assert r_unset.status_code == 200
    unset_data = r_unset.json()
    assert unset_data["status"] != "answered"
    assert "5天" not in unset_data["message"]

    # 3. 設定無效診所
    monkeypatch.setattr(config, "patient_clinic_id", "0000000000")
    r_invalid = http_client.post("/api/v1/general/consult", json={"query": "雙眼皮縫線拆線需要幾天？"})
    assert r_invalid.status_code == 200
    invalid_data = r_invalid.json()
    assert invalid_data["status"] != "answered"
    assert "5天" not in invalid_data["message"]


def test_t3_2_ignore_request_payload_and_header(http_client, monkeypatch):
    """Test 2（忽略請求）: 設定診所為 A；請求帶 clinic_id: B 與 X-Clinic-ID: B，回覆仍只來自 A。"""
    from src.general import consult_jobs

    monkeypatch.setattr(config, "patient_clinic_id", CLINIC_A)

    # 1. 同步端點帶 B 的 Header 與 body
    r_sync = http_client.post(
        "/api/v1/general/consult",
        json={"query": "雙眼皮縫線拆線需要幾天？", "clinic_id": CLINIC_B},
        headers={"X-Clinic-ID": CLINIC_B},
    )
    assert r_sync.status_code == 200
    sync_data = r_sync.json()
    assert sync_data["status"] == "answered"
    assert "5天" in sync_data["message"]
    assert "SECRET_CLINIC_B_CONTENT" not in sync_data["message"]
    assert "7天" not in sync_data["message"]

    # 2. 非同步端點帶 B 的 Header 與 body
    r_job = http_client.post(
        "/api/v1/general/consult/jobs",
        json={"query": "雙眼皮縫線拆線需要幾天？", "clinic_id": CLINIC_B},
        headers={"X-Clinic-ID": CLINIC_B},
    )
    assert r_job.status_code == 200
    job_id = r_job.json()["job_id"]
    assert consult_jobs.wait_idle(timeout=5.0)

    r_poll = http_client.get(f"/api/v1/general/consult/jobs/{job_id}")
    assert r_poll.status_code == 200
    poll_data = r_poll.json()
    assert poll_data["status"] == "answered"
    assert "5天" in poll_data["message"]
    assert "SECRET_CLINIC_B_CONTENT" not in poll_data["message"]
    assert "7天" not in poll_data["message"]


def test_t3_3_unset_clinic_ignores_request_payload_and_header(http_client, monkeypatch):
    """Test 3（無設定忽略請求）: 未設定診所；請求夾帶 clinic_id A 與標頭 A 時，仍只命中一般資料，A 的 special 內容不出現。"""
    monkeypatch.setattr(config, "patient_clinic_id", None)

    r = http_client.post(
        "/api/v1/general/consult",
        json={"query": "雙眼皮縫線拆線需要幾天？", "clinic_id": CLINIC_A},
        headers={"X-Clinic-ID": CLINIC_A},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] != "answered"
    assert "5天" not in data["message"]
    assert "SECRET_CLINIC_B_CONTENT" not in data["message"]


def test_t3_4_job_resolution_in_worker_endpoints_no_db_connection(http_client, monkeypatch):
    """Test 4（job 解析在 worker）: submit_job 傳入 config 原始值，worker 以自身連線解析；GET 輪詢端點純記憶體。"""
    from src.general import consult_jobs

    monkeypatch.setattr(config, "patient_clinic_id", CLINIC_A)

    # 提交 job
    r_post = http_client.post("/api/v1/general/consult/jobs", json={"query": "雙眼皮縫線拆線需要幾天？"})
    assert r_post.status_code == 200
    job_id = r_post.json()["job_id"]

    # 等待 worker 完成
    assert consult_jobs.wait_idle(timeout=5.0)

    # 驗證 GET 輪詢端點純記憶體運作，不連線資料庫
    orig_connect = sqlite3.connect
    connect_called = False

    def _no_connect(*args, **kwargs):
        nonlocal connect_called
        connect_called = True
        return orig_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", _no_connect)

    r_poll = http_client.get(f"/api/v1/general/consult/jobs/{job_id}")
    assert r_poll.status_code == 200
    assert connect_called is False, "GET 輪詢端點不應呼叫 sqlite3.connect！"
    poll_data = r_poll.json()
    assert poll_data["status"] == "answered"
    assert "5天" in poll_data["message"]


