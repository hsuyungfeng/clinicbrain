"""
Phase 29 Task 2: 病人諮詢回應與非同步作業帶出視覺解說卡測試 (test_visual_serving.py)。

驗證目標：
1. 核准資產 + 問句含關鍵字 -> answered 與 llm_general 回應皆附帶 visual。
2. 同題但資產為 pending 或 rejected -> visual 為 None。
3. 紅旗問句即使含資產關鍵字 -> 絕不附帶 visual（為 None）。
4. no_match / busy 狀態即使問句含資產關鍵字 -> visual 一律為 None。
5. 未遷移的資料庫（缺 visual_assets 表）-> visual 為 None，不報錯、不影響原有回答。
6. /api/v1/general/consult 端點回應含 "visual" 鍵且經 deep_mask_prices。
7. /api/v1/general/consult/jobs 非同步路徑完成結果含 "visual" 鍵，且 GET 輪詢期間零資料庫連線，registry 序列化不含問句原文與診所代碼。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.config import config
from src.general import consult_jobs
from src.general import patient_consult as pc
from src.pageindex.faq_writer import upsert_faqs
from src.pageindex.llm_client import LocalLLMUnavailableError
from src.visual.review import set_review_status
from src.visual.writer import upsert_assets
from tests.conftest import apply_visual_migration

WARNING = "若出現持續性疼痛或異常腫脹，請立即回診尋求醫師評估。"


def _sample_visual_ir(
    topic_key: str = "autologous-fat-grafting",
    keywords: list[str] | None = None,
    title: str = "自體脂肪移植原理與照護",
) -> dict[str, Any]:
    if keywords is None:
        keywords = ["自體脂肪", "補脂"]
    return {
        "topic_key": topic_key,
        "title": title,
        "keywords": keywords,
        "scenes": [
            {
                "blueprint": "process_diagram",
                "title": "脂肪抽取與純化",
                "caption": "自供脂區溫和取出脂肪組織，經純化處理去除雜質與油脂，保留健康脂肪細胞。",
                "labels": [
                    {"text": "溫和抽取", "tone": "neutral"},
                    {"text": "純化處理", "tone": "optimal"},
                ],
            },
            {
                "blueprint": "contrast",
                "title": "適量分層填補",
                "caption": "採取多點分層方式均勻植入，有助於移植組織獲得足夠養分供應並降低硬塊風險。",
                "labels": [
                    {"text": "單點過量", "tone": "warning"},
                    {"text": "多層微量", "tone": "optimal"},
                ],
            },
            {
                "blueprint": "timeline",
                "title": "術後恢復與穩定",
                "caption": "初期會有自然腫脹反應，部分脂肪會被吸收，待組織穩定後呈現自然柔和的輪廓。",
                "labels": [
                    {"text": "初期腫脹", "tone": "neutral"},
                    {"text": "穩定自然", "tone": "optimal"},
                ],
            },
        ],
    }


def _seed_visual(conn: sqlite3.Connection, status: str = "approved") -> None:
    ir = _sample_visual_ir()
    upsert_assets(
        conn,
        [
            {
                "topic_key": ir["topic_key"],
                "title": ir["title"],
                "keywords": ir["keywords"],
                "ir": ir,
            }
        ],
        source_type="manual",
    )
    if status != "pending":
        set_review_status(conn, ir["topic_key"], status)


def _seed_approved_general_faq(conn: sqlite3.Connection, q: str) -> None:
    upsert_faqs(
        conn,
        [
            {
                "clinic_id": None,
                "topic_key": "fat-care-faq",
                "category": "general",
                "question": q,
                "answer": f"自體脂肪補脂術後請避免按壓填補部位並保持正常作息。{WARNING}",
            }
        ],
        source_type="manual",
    )


def test_answered_faq_without_tree_citation_has_no_visual(isolated_db_path: Path):
    """2.32：問句含核准資產關鍵字，但回答只引用 FAQ、未引用任何推理樹 -> 不附動畫。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        q = "請問自體脂肪補脂術後如何照護？"
        _seed_approved_general_faq(conn, q)
        _seed_visual(conn, status="approved")

        res = pc.patient_consult(conn, q)
        assert res.status == "answered"
        assert res.visual is None
    finally:
        conn.close()


def test_llm_general_never_attaches_visual_both_new_and_reused(isolated_db_path: Path):
    """2.32：llm_general（新生成與同題草稿重用）不引用推理樹，即使問句含關鍵字也不附動畫。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        _seed_visual(conn, status="approved")
        q = "我想了解自體脂肪移植的常見生活作息調整？"

        def _fake_llm(prompt: str) -> str:
            return json.dumps(
                [
                    {
                        "question": q,
                        "answer": f"術後初期建議保持充足睡眠與均衡飲食，避免劇烈運動。{WARNING}",
                    }
                ],
                ensure_ascii=False,
            )

        # 1. 新生成 llm_general
        res1 = pc.patient_consult(conn, q, llm_call=_fake_llm)
        assert res1.status == "llm_general"
        assert res1.visual is None

        # 2. 同題重用 pending 草稿 llm_general
        def _boom(prompt: str) -> str:
            raise AssertionError("不應再次呼叫模型")

        res2 = pc.patient_consult(conn, q, llm_call=_boom)
        assert res2.status == "llm_general"
        assert res2.visual is None
    finally:
        conn.close()


def test_pending_or_rejected_visual_not_attached(isolated_db_path: Path):
    """同題但視覺資產為 pending 或 rejected 時，visual 為 None。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        q = "請問自體脂肪補脂術後如何照護？"
        _seed_approved_general_faq(conn, q)
        _seed_visual(conn, status="pending")

        res_pending = pc.patient_consult(conn, q)
        assert res_pending.status == "answered"
        assert res_pending.visual is None

        set_review_status(conn, "autologous-fat-grafting", "rejected")
        res_rejected = pc.patient_consult(conn, q)
        assert res_rejected.status == "answered"
        assert res_rejected.visual is None
    finally:
        conn.close()


def test_red_flag_no_match_busy_never_attach_visual(isolated_db_path: Path):
    """紅旗、no_match、busy 回應即使問句含關鍵字，visual 永遠為 None。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        _seed_visual(conn, status="approved")

        # 1. red_flag 含「自體脂肪」關鍵字
        res_rf = pc.patient_consult(conn, "做完自體脂肪補脂後現在胸痛呼吸困難")
        assert res_rf.status == "red_flag"
        assert res_rf.visual is None

        # 2. no_match 含「自體脂肪」關鍵字（模型離線）
        def _down(prompt: str) -> str:
            raise LocalLLMUnavailableError("offline")

        res_nm = pc.patient_consult(conn, "請問自體脂肪罕見問題測試？", llm_call=_down)
        assert res_nm.status == "no_match"
        assert res_nm.visual is None

        # 3. busy 含「自體脂肪」關鍵字
        assert pc.GENERATION_LOCK.acquire(blocking=False)
        try:
            res_busy = pc.patient_consult(conn, "請問自體脂肪罕見問題測試二？", llm_call=_down)
        finally:
            pc.GENERATION_LOCK.release()
        assert res_busy.status == "busy"
        assert res_busy.visual is None
    finally:
        conn.close()


def test_unmigrated_db_returns_visual_none_without_error(isolated_db_path: Path):
    """未遷移的資料庫（無 visual_assets 表）：不顯示動畫、不報錯、不影響原有回答。"""
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        q = "請問自體脂肪補脂術後如何照護？"
        _seed_approved_general_faq(conn, q)

        res = pc.patient_consult(conn, q)
        assert res.status == "answered"
        assert res.visual is None
    finally:
        conn.close()


def test_api_consult_and_jobs_serve_visual_and_preserve_poll_privacy(
    isolated_db_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """API /consult 與 /consult/jobs 皆回傳 visual；輪詢期間零資料庫連線，registry 不含問句。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    q = "請問自體脂肪補脂術後如何照護？"
    try:
        _seed_approved_general_faq(conn, q)
        _seed_visual(conn, status="approved")
    finally:
        conn.close()

    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    consult_jobs.reset_for_tests()

    with TestClient(app) as client:
        # 1. 同步 /api/v1/general/consult
        r_sync = client.post("/api/v1/general/consult", json={"query": q})
        assert r_sync.status_code == 200
        d_sync = r_sync.json()
        assert d_sync["status"] == "answered"
        # FAQ-only 回答未引用推理樹，欄位存在但為 None（2.32）
        assert "visual" in d_sync
        assert d_sync["visual"] is None

        # 2. 非同步 /api/v1/general/consult/jobs
        r_job = client.post("/api/v1/general/consult/jobs", json={"query": q})
        assert r_job.status_code == 200
        job_id = r_job.json()["job_id"]
        assert consult_jobs.wait_idle(timeout=5.0)

        # 確認 registry 序列化不含問句原文
        with consult_jobs._lock:
            reg_repr = repr(consult_jobs._jobs)
            assert q not in reg_repr

        # 輪詢期間監視 sqlite3.connect 確保零資料庫連線
        db_connect_calls = 0
        orig_connect = sqlite3.connect

        def _spy_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
            nonlocal db_connect_calls
            db_connect_calls += 1
            return orig_connect(*args, **kwargs)

        monkeypatch.setattr(sqlite3, "connect", _spy_connect)

        r_poll = client.get(f"/api/v1/general/consult/jobs/{job_id}")
        assert r_poll.status_code == 200
        assert db_connect_calls == 0
        d_poll = r_poll.json()
        assert d_poll["status"] == "answered"
        assert d_poll["visual"] is None

    consult_jobs.reset_for_tests()


def test_consult_endpoint_prioritizes_server_configured_clinic_visual(
    isolated_db_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """驗證 /consult 與 /consult/jobs 在設定 config.patient_clinic_id 時優先帶出診所專屬動畫，並忽略 X-Clinic-ID。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    q = "請問自體脂肪補脂手術？"
    try:
        _seed_approved_general_faq(conn, q)

        # 1. 一般醫學資產
        gen_ir = _sample_visual_ir(topic_key="gen-fat", keywords=["自體脂肪", "補脂"])
        upsert_assets(
            conn,
            [{"clinic_id": None, "topic_key": gen_ir["topic_key"], "title": gen_ir["title"], "keywords": gen_ir["keywords"], "ir": gen_ir}],
            source_type="manual",
        )
        set_review_status(conn, gen_ir["topic_key"], "approved", clinic_id=None)

        # 2. 診所專屬資產 (3503190424)
        c_ir = _sample_visual_ir(topic_key="clinic-fat", keywords=["自體脂肪"], title="緻妍專屬補脂")
        upsert_assets(
            conn,
            [{"clinic_id": "3503190424", "topic_key": c_ir["topic_key"], "title": c_ir["title"], "keywords": c_ir["keywords"], "ir": c_ir}],
            source_type="manual",
        )
        set_review_status(conn, c_ir["topic_key"], "approved", clinic_id="3503190424")
    finally:
        conn.close()

    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "patient_clinic_id", "3503190424")
    consult_jobs.reset_for_tests()

    with TestClient(app) as client:
        # (a) 同步 /consult，夾帶惡意 X-Clinic-ID: 3503264627，但伺服器固定為 3503190424 -> 優先回傳 3503190424 的 clinic-fat
        res_sync = client.post(
            "/api/v1/general/consult",
            json={"query": q},
            headers={"X-Clinic-ID": "3503264627"},
        )
        assert res_sync.status_code == 200
        d_sync = res_sync.json()
        # FAQ-only 回答不引用推理樹，不附動畫；診所優先規則由 _cited_visual 單元測試覆蓋
        assert d_sync["visual"] is None

        # (b) 非同步 /consult/jobs，同樣夾帶 X-Clinic-ID: 3503264627 -> 優先回傳 clinic-fat
        res_job = client.post(
            "/api/v1/general/consult/jobs",
            json={"query": q},
            headers={"X-Clinic-ID": "3503264627"},
        )
        assert res_job.status_code == 200
        job_id = res_job.json()["job_id"]
        assert consult_jobs.wait_idle(timeout=5.0)

        res_poll = client.get(f"/api/v1/general/consult/jobs/{job_id}")
        assert res_poll.status_code == 200
        d_poll = res_poll.json()
        assert d_poll["visual"] is None


# ----------------------------------------------------------------------------
# 2.32：依引用推理樹附上動畫（_cited_visual）
# ----------------------------------------------------------------------------

_CLINIC = "3503190424"


def _seed_tree_visual(conn: sqlite3.Connection, topic_key: str, clinic_id: str | None, title: str) -> None:
    ir = _sample_visual_ir(topic_key=topic_key, keywords=["自體脂肪"], title=title)
    upsert_assets(
        conn,
        [{"clinic_id": clinic_id, "topic_key": topic_key, "title": title, "keywords": ir["keywords"], "ir": ir}],
        source_type="manual",
    )
    set_review_status(conn, topic_key, "approved", clinic_id=clinic_id)


def test_cited_visual_prefers_clinic_version_then_general(isolated_db_path: Path):
    """引用同一棵樹時：診所上下文取診所專屬版；一般上下文取一般共用版；回傳不含 clinic_id。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        _seed_tree_visual(conn, "tree-fat-care", None, "一般脂肪照護")
        _seed_tree_visual(conn, "tree-fat-care", _CLINIC, "緻妍脂肪照護")
        groups = [[{"doc_id": "fat-care"}]]

        clinic_res = pc._cited_visual(conn, groups, clinic_id=_CLINIC)
        assert clinic_res is not None
        assert clinic_res["title"] == "緻妍脂肪照護"
        assert "clinic_id" not in clinic_res

        general_res = pc._cited_visual(conn, groups, clinic_id=None)
        assert general_res is not None
        assert general_res["title"] == "一般脂肪照護"
    finally:
        conn.close()


def test_cited_visual_none_without_citation_or_unapproved_tree(isolated_db_path: Path):
    """沒有引用任何樹、或引用的樹尚未核准動畫 -> None（Fail-Closed）。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        _seed_tree_visual(conn, "tree-fat-care", None, "一般脂肪照護")
        assert pc._cited_visual(conn, [[]], clinic_id=None) is None
        assert pc._cited_visual(conn, [[{"doc_id": "other-tree"}]], clinic_id=None) is None

        ir = _sample_visual_ir(topic_key="tree-pending-one", keywords=["自體脂肪"], title="待審")
        upsert_assets(
            conn,
            [{"clinic_id": None, "topic_key": "tree-pending-one", "title": "待審", "keywords": ir["keywords"], "ir": ir}],
            source_type="manual",
        )
        assert pc._cited_visual(conn, [[{"doc_id": "pending-one"}]], clinic_id=None) is None
    finally:
        conn.close()


def test_cited_visual_faq_hits_match_treatment_slug(isolated_db_path: Path):
    """病患端 FAQ 也對應動畫：FAQ topic_key（療程 slug）引用時附上同療程動畫，且診所版優先。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        _seed_tree_visual(conn, "tree-fat-care", None, "一般脂肪照護")
        _seed_tree_visual(conn, "tree-fat-care", _CLINIC, "緻妍脂肪照護")
        faq_hits = [{"topic_key": "fat-care", "question": "q", "answer": "a"}]

        clinic_res = pc._cited_visual(conn, [faq_hits], clinic_id=_CLINIC)
        assert clinic_res is not None and clinic_res["title"] == "緻妍脂肪照護"

        general_res = pc._cited_visual(conn, [faq_hits], clinic_id=None)
        assert general_res is not None and general_res["title"] == "一般脂肪照護"

        # 無對應療程 slug 的 FAQ 不附動畫
        assert pc._cited_visual(conn, [[{"topic_key": "no-such-topic"}]], clinic_id=None) is None
    finally:
        conn.close()


def test_patient_consult_general_faq_attaches_its_treatment_visual(isolated_db_path: Path):
    """端到端：回答引用的已核准一般 FAQ，其 topic_key 對應療程時，patient_consult 附上該動畫。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        q = "請問自體脂肪移植術後如何照護？"
        upsert_faqs(
            conn,
            [
                {
                    "clinic_id": None,
                    "topic_key": "autologous-fat-grafting",
                    "category": "general",
                    "question": q,
                    "answer": f"自體脂肪移植術後請保持正常作息並避免按壓。{WARNING}",
                }
            ],
            source_type="manual",
        )
        _seed_visual(conn, status="approved")

        res = pc.patient_consult(conn, q)
        assert res.status == "answered"
        assert res.visual is not None
        assert res.visual["topic_key"] == "autologous-fat-grafting"
    finally:
        conn.close()

    consult_jobs.reset_for_tests()
