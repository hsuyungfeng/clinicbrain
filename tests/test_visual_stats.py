"""
Phase 29 Task 3: 視覺解說卡匿名事件計數與端點測試 (test_visual_stats.py)。

驗證目標：
1. 核准主題之 shown / completed 事件各累加；同日重複累加為 count 遞增而非新增列。
2. 未核准主題（pending / rejected / 不存在）、未知事件、未遷移資料庫（缺表）皆不寫入。
3. POST /api/v1/general/visual/event：
   - 合法請求（不論主題是否存在或資料庫是否遷移）一律回傳 200 {"ok": True}，不洩漏主題存在性。
   - 未知事件、缺欄位或夾帶額外欄位（extra="forbid"）由 AnonymousRoute 回傳固定 422 {"detail": "請求格式不正確"}。
   - GET 請求回傳 405 Method Not Allowed。
4. 隱私驗證：
   - visual_stats 表內容不含任何問句哨兵字串與標頭哨兵。
   - 日誌（caplog）無主題以外資訊，不含標頭與輸入哨兵。
   - /api/v1/general/visual/event 路徑被 ExcludeGeneralPathFilter 整行丟棄。
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.access_log_filter import ExcludeGeneralPathFilter
from src.api.app import app
from src.api.config import config
from src.visual.review import set_review_status
from src.visual.stats import record_event
from src.visual.writer import upsert_assets
from tests.conftest import apply_visual_migration


def _sample_ir(topic_key: str = "autologous-fat-grafting") -> dict[str, Any]:
    return {
        "topic_key": topic_key,
        "title": "自體脂肪移植原理與照護",
        "keywords": ["自體脂肪", "補脂"],
        "scenes": [
            {
                "blueprint": "process_diagram",
                "title": "脂肪抽取與純化",
                "caption": "自供脂區溫和取出脂肪組織，經純化處理去除雜質與油脂，保留健康脂肪細胞。",
                "labels": [{"text": "溫和抽取", "tone": "neutral"}],
            },
            {
                "blueprint": "contrast",
                "title": "適量分層填補",
                "caption": "採取多點分層方式均勻植入，有助於移植組織獲得足夠養分供應並降低硬塊風險。",
                "labels": [{"text": "多層微量", "tone": "optimal"}],
            },
            {
                "blueprint": "timeline",
                "title": "術後恢復與穩定",
                "caption": "初期會有自然腫脹反應，部分脂肪會被吸收，待組織穩定後呈現自然柔和的輪廓。",
                "labels": [{"text": "穩定自然", "tone": "optimal"}],
            },
        ],
    }


def _seed_asset(conn: sqlite3.Connection, topic_key: str = "autologous-fat-grafting", status: str = "approved") -> None:
    ir = _sample_ir(topic_key)
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
        set_review_status(conn, topic_key, status)


def test_record_event_increments_approved_topic_same_day(isolated_db_path: Path):
    """核准主題 shown 與 completed 各累加；同日重複呼叫為 count 遞增而非新增列。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        _seed_asset(conn, "autologous-fat-grafting", status="approved")
    finally:
        conn.close()

    assert record_event(isolated_db_path, "autologous-fat-grafting", "shown") is True
    assert record_event(isolated_db_path, "autologous-fat-grafting", "shown") is True
    assert record_event(isolated_db_path, "autologous-fat-grafting", "completed") is True

    conn = sqlite3.connect(str(isolated_db_path))
    try:
        rows = conn.execute(
            "SELECT topic_key, event, count FROM visual_stats ORDER BY event ASC"
        ).fetchall()
        assert rows == [
            ("autologous-fat-grafting", "completed", 1),
            ("autologous-fat-grafting", "shown", 2),
        ]
    finally:
        conn.close()


def test_record_event_rejects_unapproved_unknown_or_unmigrated(isolated_db_path: Path):
    """未核准主題、不存在主題、未知事件、未遷移資料庫皆回傳 False 且不寫入。"""
    # 1. 未遷移資料庫（缺表）
    assert record_event(isolated_db_path, "autologous-fat-grafting", "shown") is False

    # 2. 遷移後測試 pending、rejected、不存在主題、未知事件
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        _seed_asset(conn, "pending-topic", status="pending")
        _seed_asset(conn, "rejected-topic", status="rejected")
        _seed_asset(conn, "approved-topic", status="approved")
    finally:
        conn.close()

    assert record_event(isolated_db_path, "pending-topic", "shown") is False
    assert record_event(isolated_db_path, "rejected-topic", "shown") is False
    assert record_event(isolated_db_path, "nonexistent-topic", "shown") is False
    assert record_event(isolated_db_path, "approved-topic", "clicked") is False

    conn = sqlite3.connect(str(isolated_db_path))
    try:
        cnt = conn.execute("SELECT COUNT(*) FROM visual_stats").fetchone()[0]
        assert cnt == 0
    finally:
        conn.close()


def test_api_visual_event_endpoint_behavior_and_privacy(
    isolated_db_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """驗證 POST /api/v1/general/visual/event 端點行為、422 固定訊息、405、不洩漏存在性與隱私。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        _seed_asset(conn, "autologous-fat-grafting", status="approved")
        _seed_asset(conn, "pending-topic", status="pending")
    finally:
        conn.close()

    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)

    sentinel_header_val = "SENTINEL_HEADER_SECRET_9988"
    sentinel_query_val = "請問我私密哨兵問題甲乙丙丁"
    headers = {
        "X-Forwarded-For": "203.0.113.55",
        "X-Custom-Sentinel": sentinel_header_val,
        "User-Agent": "SentinelBrowser/1.0",
    }

    caplog.set_level(logging.DEBUG)

    with TestClient(app) as client:
        # 1. 核准主題 shown -> 200 {"ok": True}
        r1 = client.post(
            "/api/v1/general/visual/event",
            json={"topic_key": "autologous-fat-grafting", "event": "shown"},
            headers=headers,
        )
        assert r1.status_code == 200
        assert r1.json() == {"ok": True}

        # 2. 未核准或未知主題 -> 同樣回傳 200 {"ok": True}（不洩漏是否存在），但資料庫不寫入
        r2 = client.post(
            "/api/v1/general/visual/event",
            json={"topic_key": "pending-topic", "event": "shown"},
            headers=headers,
        )
        assert r2.status_code == 200
        assert r2.json() == {"ok": True}

        r3 = client.post(
            "/api/v1/general/visual/event",
            json={"topic_key": "unknown-topic-xyz", "event": "completed"},
            headers=headers,
        )
        assert r3.status_code == 200
        assert r3.json() == {"ok": True}

        # 3. 未知事件或夾帶額外欄位（如 query）-> 422 固定錯誤訊息，不回顯輸入
        r_bad_ev = client.post(
            "/api/v1/general/visual/event",
            json={"topic_key": "autologous-fat-grafting", "event": "invalid_event_sentinel"},
            headers=headers,
        )
        assert r_bad_ev.status_code == 422
        assert r_bad_ev.json() == {"detail": "請求格式不正確"}
        assert "invalid_event_sentinel" not in r_bad_ev.text

        r_extra = client.post(
            "/api/v1/general/visual/event",
            json={
                "topic_key": "autologous-fat-grafting",
                "event": "shown",
                "query": sentinel_query_val,
            },
            headers=headers,
        )
        assert r_extra.status_code == 422
        assert r_extra.json() == {"detail": "請求格式不正確"}
        assert sentinel_query_val not in r_extra.text

        # 4. GET 方法回 405
        r_get = client.get("/api/v1/general/visual/event")
        assert r_get.status_code == 405

    # 檢查資料庫內容僅有 1 筆核准主題紀錄，且 dump 無任何哨兵字串
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        rows = conn.execute("SELECT topic_key, event, count FROM visual_stats").fetchall()
        assert rows == [("autologous-fat-grafting", "shown", 1)]
        dump_str = "\n".join(conn.iterdump())
    finally:
        conn.close()

    for s in (sentinel_header_val, sentinel_query_val, "203.0.113.55", "SentinelBrowser"):
        assert s not in dump_str
        assert s not in caplog.text


def test_api_visual_event_unmigrated_db_returns_200(
    isolated_db_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """未遷移資料庫呼叫 /api/v1/general/visual/event 仍回 200 {"ok": True}（Fail-Safe）。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/general/visual/event",
            json={"topic_key": "autologous-fat-grafting", "event": "shown"},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}


def test_access_log_filter_drops_visual_event_path():
    """確認 ExcludeGeneralPathFilter 整行丟棄 /api/v1/general/visual/event 存取日誌。"""
    f = ExcludeGeneralPathFilter()
    rec = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("198.51.100.88:54321", "POST", "/api/v1/general/visual/event", "1.1", 200),
        exc_info=None,
    )
    assert f.filter(rec) is False
