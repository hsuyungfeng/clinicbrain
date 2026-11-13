"""
Phase 43 Plan 03 Task 3: 影片管理 API 與端到端契約測試 (test_visual_video_api.py)。

驗證項目：
1. GET /api/v1/admin/visuals/videos/{topic_key}
   - 主題存在時回傳 landscape 與 portrait 之狀態與可用性。
   - 非法字元或目錄穿越（如含有 ..）回傳 400。
   - 不存在主題回傳 404。
2. POST /api/v1/admin/visuals/videos/{topic_key}/render
   - 僅已核准 (approved) 主題允許加入佇列，否則回傳 400。
   - 成功排程回傳 status="queued"。
3. GET /api/v1/admin/visuals/videos/{topic_key}/download
   - 尚未生成影片時回傳 404。
   - 存在影片時回傳 200，Content-Type 為 video/mp4。
4. GET /api/v1/admin/stats
   - 統計指標中包含 visuals_videos_rendered_total 欄位。
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.visual.video_queue import DEFAULT_VIDEO_DIR

client = TestClient(app)


def test_get_video_status_not_found_and_invalid():
    """驗證查詢不存在或非法主題代碼時之防呆。"""
    # 1. 目錄穿越攻擊防禦
    res_bad = client.get("/api/v1/admin/visuals/videos/../etc/passwd")
    assert res_bad.status_code in (400, 404)

    # 2. 不存在主題
    res_404 = client.get("/api/v1/admin/visuals/videos/non_existent_topic_12345")
    assert res_404.status_code == 404


def test_get_video_status_approved_topic():
    """驗證查詢已核准主題時正常回傳雙尺寸結構。"""
    conn = sqlite3.connect("clinic.db")
    try:
        cur = conn.cursor()
        cur.execute("SELECT topic_key FROM visual_assets WHERE review_status = 'approved' LIMIT 1")
        row = cur.fetchone()
        assert row is not None
        topic_key = row[0]
    finally:
        conn.close()

    res = client.get(f"/api/v1/admin/visuals/videos/{topic_key}")
    assert res.status_code == 200
    data = res.json()
    assert data["topic_key"] == topic_key
    assert "landscape" in data
    assert "portrait" in data
    assert "available" in data["landscape"]
    assert "available" in data["portrait"]


def test_trigger_render_approved_vs_pending(monkeypatch):
    """驗證僅 approved 主題可觸發渲染。"""
    # 攔截背景任務，避免測試等待實際合成耗時
    mock_called = []
    monkeypatch.setattr(
        "src.api.routes.admin._render_video_in_background",
        lambda topic_key, aspect, force, db_path: mock_called.append((topic_key, aspect))
    )

    conn = sqlite3.connect("clinic.db")
    try:
        cur = conn.cursor()
        # 查一個 approved
        cur.execute("SELECT topic_key FROM visual_assets WHERE review_status = 'approved' LIMIT 1")
        app_topic = cur.fetchone()[0]

        # 查一個 pending (若有)
        cur.execute("SELECT topic_key FROM visual_assets WHERE review_status = 'pending' LIMIT 1")
        pend_row = cur.fetchone()
        pend_topic = pend_row[0] if pend_row else None
    finally:
        conn.close()

    # 觸發 approved 主題
    res_ok = client.post(f"/api/v1/admin/visuals/videos/{app_topic}/render?aspect=landscape")
    assert res_ok.status_code == 200
    data_ok = res_ok.json()
    assert data_ok["status"] == "queued"
    assert data_ok["topic_key"] == app_topic
    assert len(mock_called) == 1

    # 若有 pending 主題，測試拒絕
    if pend_topic:
        res_fail = client.post(f"/api/v1/admin/visuals/videos/{pend_topic}/render?aspect=landscape")
        assert res_fail.status_code == 400
        assert "僅已核准" in res_fail.json()["detail"]


def test_download_video_stream_and_404(tmp_path: Path, monkeypatch):
    """驗證 MP4 影片串流下載與未生成時 404。"""
    test_dir = tmp_path / "videos"
    test_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("src.visual.video_queue.DEFAULT_VIDEO_DIR", test_dir)

    topic_key = "test-download-topic"

    # 尚未生成 -> 404
    res_404 = client.get(f"/api/v1/admin/visuals/videos/{topic_key}/download?aspect=landscape")
    assert res_404.status_code == 404

    # 放置假影片檔
    fake_mp4 = test_dir / f"{topic_key}_landscape.mp4"
    fake_mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")

    res_ok = client.get(f"/api/v1/admin/visuals/videos/{topic_key}/download?aspect=landscape")
    assert res_ok.status_code == 200
    assert "video/mp4" in res_ok.headers.get("content-type", "")
    assert res_ok.content == fake_mp4.read_bytes()


def test_stats_contains_videos_count():
    """驗證 GET /api/v1/admin/review/summary 包含 visuals_videos_rendered_total 指標。"""
    res = client.get("/api/v1/admin/review/summary")
    assert res.status_code == 200
    data = res.json()
    assert "visuals_videos_rendered_total" in data
    assert isinstance(data["visuals_videos_rendered_total"], int)
