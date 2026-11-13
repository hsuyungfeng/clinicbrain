"""
Phase 43 Plan 01 Task 2: 影片佇列渲染核心單元與端到端測試 (test_visual_video_queue.py)。

驗證目標：
1. compute_ir_sha256: 鍵值順序無關之確定性 SHA-256 計算。
2. get_asset_bundle_data: 正確從資料庫組合 bundle，包含繁體中文法定免責聲明與診所電話。
3. 增量快取機制: 現存 MP4 與一致之 SHA-256 sidecar 時，秒級跳過（skipped）。
4. 雙尺寸參數校驗: landscape (16:9) 與 portrait (9:16) 輸出合規。
5. 端到端真實渲染測試: 在隔離暫存環境進行快速錄製，驗證產出之 H.264 MP4 具備合法尺寸與可播性。
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import pytest

from src.visual.video_queue import (
    compute_ir_sha256,
    get_asset_bundle_data,
    render_asset_to_video,
    batch_render_queue,
)


def test_compute_ir_sha256_determinism():
    """驗證 JSON 鍵值排列不同時，雜湊計算依然 100% 相同。"""
    ir_a = {"title": "音波拉皮", "scenes": [{"id": 1, "type": "energy"}], "fps": 24}
    ir_b = {"fps": 24, "scenes": [{"type": "energy", "id": 1}], "title": "音波拉皮"}

    hash_a = compute_ir_sha256(ir_a)
    hash_b = compute_ir_sha256(ir_b)
    hash_c = compute_ir_sha256(json.dumps(ir_a, ensure_ascii=False))

    assert hash_a == hash_b, "格式化後 SHA-256 必須一致"
    assert hash_a == hash_c
    assert len(hash_a) == 64


def test_get_asset_bundle_data_and_disclaimer():
    """驗證資料庫查詢與法定免責聲明。"""
    conn = sqlite3.connect("clinic.db")
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT topic_key FROM visual_assets WHERE review_status = 'approved' LIMIT 1")
        row = cursor.fetchone()
        assert row is not None, "資料庫中必須有 approved 視覺資產"
        topic_key = row[0]

        bundle = get_asset_bundle_data(conn, topic_key)
        assert bundle["topic_key"] == topic_key
        assert "scenes" in bundle
        assert "clinic" in bundle
        assert "本解說僅供衛教參考" in bundle["clinic"]["disclaimer"]
        assert len(bundle["_ir_sha256"]) == 64
    finally:
        conn.close()


def test_render_incremental_cache_skip(tmp_path: Path):
    """驗證當 MP4 與 SHA-256 meta 吻合時，不啟動瀏覽器直接命中快取跳過。"""
    conn = sqlite3.connect("clinic.db")
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT topic_key, ir_json FROM visual_assets WHERE review_status = 'approved' LIMIT 1")
        topic_key, ir_raw = cursor.fetchone()
        sha = compute_ir_sha256(ir_raw)

        # 預先在 tmp_path 建立假 MP4 與 meta.json
        fake_mp4 = tmp_path / f"{topic_key}_landscape.mp4"
        fake_mp4.write_bytes(b"FAKE_MP4_CONTENT")
        fake_meta = tmp_path / f"{topic_key}_landscape.meta.json"
        fake_meta.write_text(json.dumps({"topic_key": topic_key, "aspect": "landscape", "sha256": sha}), encoding="utf-8")

        res = render_asset_to_video(
            conn=conn,
            topic_key=topic_key,
            output_dir=tmp_path,
            aspect="landscape",
            force=False,
        )

        assert res["status"] == "skipped"
        assert res["reason"] == "cache_hit_ir_unchanged"
        assert res["sha256"] == sha
    finally:
        conn.close()


def test_render_e2e_fast_landscape_and_portrait(tmp_path: Path):
    """端到端快速錄製測試：使用低 fps 與短 hold 驗證 landscape 與 portrait 實體 MP4 合成。"""
    conn = sqlite3.connect("clinic.db")
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT topic_key FROM visual_assets WHERE review_status = 'approved' LIMIT 1")
        topic_key = cursor.fetchone()[0]

        # 1. 測試橫屏 landscape
        res_l = render_asset_to_video(
            conn=conn,
            topic_key=topic_key,
            output_dir=tmp_path,
            aspect="landscape",
            fps=6,        # 低幀率加速測試
            hold_sec=0.5,
            force=True,
        )
        assert res_l["status"] == "rendered"
        mp4_l = Path(res_l["path"])
        assert mp4_l.exists()
        assert mp4_l.stat().st_size > 1000

        # 用 ffprobe 檢查影片寬高為 1920x1080
        probe_l = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(mp4_l)],
            capture_output=True,
            text=True,
            check=True
        )
        assert "1920,1080" in probe_l.stdout.strip()

        # 2. 測試豎屏 portrait
        res_p = render_asset_to_video(
            conn=conn,
            topic_key=topic_key,
            output_dir=tmp_path,
            aspect="portrait",
            fps=6,
            hold_sec=0.5,
            force=True,
        )
        assert res_p["status"] == "rendered"
        mp4_p = Path(res_p["path"])
        assert mp4_p.exists()
        assert mp4_p.stat().st_size > 1000

        probe_p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(mp4_p)],
            capture_output=True,
            text=True,
            check=True
        )
        assert "1080,1920" in probe_p.stdout.strip()

    finally:
        conn.close()
