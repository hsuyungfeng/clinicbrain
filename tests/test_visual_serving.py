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
) -> dict[str, Any]:
    if keywords is None:
        keywords = ["自體脂肪", "補脂"]
    return {
        "topic_key": topic_key,
        "title": "自體脂肪移植原理與照護",
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


def test_answered_attaches_approved_visual(isolated_db_path: Path):
    """核准資產 + 問句含關鍵字 -> answered 狀態帶出 visual（含直答與 fallback 兩處）。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        q = "請問自體脂肪補脂術後如何照護？"
        _seed_approved_general_faq(conn, q)
        _seed_visual(conn, status="approved")

        res = pc.patient_consult(conn, q)
        assert res.status == "answered"
        assert res.visual is not None
        assert res.visual["topic_key"] == "autologous-fat-grafting"
        assert len(res.visual["scenes"]) == 3
        for sc in res.visual["scenes"]:
            assert "params" in sc
            assert "duration_sec" in sc
    finally:
        conn.close()


def test_llm_general_attaches_approved_visual_both_new_and_reused(isolated_db_path: Path):
    """llm_general 狀態（新生成與同題草稿重用）在問句含核准資產關鍵字時皆帶出 visual。"""
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
        assert res1.visual is not None
        assert res1.visual["topic_key"] == "autologous-fat-grafting"

        # 2. 同題重用 pending 草稿 llm_general
        def _boom(prompt: str) -> str:
            raise AssertionError("不應再次呼叫模型")

        res2 = pc.patient_consult(conn, q, llm_call=_boom)
        assert res2.status == "llm_general"
        assert res2.visual is not None
        assert res2.visual["topic_key"] == "autologous-fat-grafting"
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
        assert "visual" in d_sync
        assert d_sync["visual"] is not None
        assert d_sync["visual"]["topic_key"] == "autologous-fat-grafting"

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
        assert d_poll["visual"] is not None
        assert d_poll["visual"]["topic_key"] == "autologous-fat-grafting"

    consult_jobs.reset_for_tests()
