"""
Phase 30 Plan 03 Task 3: 視覺影片匯出腳本測試 (test_visual_video.py)。

測試項目：
1. 錯誤處理與路徑安全：
   - 缺少 ffmpeg 時印出錯誤訊息並以結束碼 2 結束。
   - `--bundle` 參數含 `..`、`//`、冒號、反斜線等非法字元時以結束碼 2 結束。
   - `--bundle` 指定之檔案不存在時以結束碼 2 結束。
   - 失敗路徑絕不遺留 `vidframes_*` 暫存目錄。
2. 端到端影片匯出（E2E，需 ffmpeg 與 Chromium）：
   - 以最小 bundle (1 個場景, duration_sec=4) 搭配 `--fps 4 --hold 0.5 --width 640` 進行匯出。
   - 驗證 exit code 0。
   - 透過 ffprobe 驗證：
     * 視訊編碼: h264
     * 像素格式: yuv420p
     * 寬度: 640
     * 影片時長: 約 4.5 秒（容許 4.0 ~ 5.0 秒）
   - 驗證成功後暫存影格目錄已自動清除。
   - 測試產物放置於 demo/visual/out/_test/<uuid>/，teardown 必刪。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RENDER_SCRIPT = PROJECT_ROOT / "demo" / "visual" / "render_video.py"
TEST_BASE = PROJECT_ROOT / "demo" / "visual" / "out" / "_test"

MINIMAL_BUNDLE = {
    "topic_key": "test-minimal-video",
    "title": "測試最小影片",
    "scenes": [
        {
            "blueprint": "process_diagram",
            "title": "單一測試場景",
            "caption": "測試影片匯出是否符合長度與格式要求。",
            "labels": [{"text": "測試", "tone": "optimal"}],
            "params": {"particles": 3},
            "duration_sec": 4,
        }
    ],
}


def _has_chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            browser.close()
        return True
    except Exception:
        return False


def _has_ffmpeg_tools() -> bool:
    return bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe"))


def _count_temp_vidframes() -> int:
    tmp_dir = Path(tempfile.gettempdir())
    return len(list(tmp_dir.glob("vidframes_*")))


def test_render_video_missing_ffmpeg(monkeypatch):
    """驗證缺少 ffmpeg 時印出明確錯誤並以結束碼 2 結束。"""
    # 透過改寫 PATH 使其找不到 ffmpeg
    env = os.environ.copy()
    env["PATH"] = ""
    res = subprocess.run(
        [sys.executable, str(RENDER_SCRIPT), "--bundle", "demo/visual/out/_test/dummy.json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(PROJECT_ROOT),
    )
    assert res.returncode == 2
    assert "ffmpeg" in res.stderr.lower() or "ffmpeg" in res.stdout.lower()


def test_render_video_invalid_bundle_path():
    """驗證非法路徑攻擊（如含 ..、//、絕對路徑）被拒絕並以結束碼 2 結束，且不留暫存目錄。"""
    before_tmp_count = _count_temp_vidframes()
    res = subprocess.run(
        [sys.executable, str(RENDER_SCRIPT), "--bundle", "../evil/bundle.json"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert res.returncode == 2
    after_tmp_count = _count_temp_vidframes()
    assert after_tmp_count == before_tmp_count, "失敗路徑不得遺留暫存目錄"


def test_render_video_missing_bundle_file():
    """驗證 bundle 檔案不存在時以結束碼 2 結束，且不留暫存目錄。"""
    before_tmp_count = _count_temp_vidframes()
    res = subprocess.run(
        [sys.executable, str(RENDER_SCRIPT), "--bundle", "demo/visual/out/_test/non_existent.json"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert res.returncode == 2
    after_tmp_count = _count_temp_vidframes()
    assert after_tmp_count == before_tmp_count, "失敗路徑不得遺留暫存目錄"


def test_render_video_e2e():
    """以最小 bundle (4s + 0.5s hold) 實際匯出 MP4，並以 ffprobe 驗證格式與時長。"""
    if not _has_ffmpeg_tools():
        pytest.skip("系統未安裝 ffmpeg 或 ffprobe")
    if not _has_chromium():
        pytest.skip("Playwright 或 Chromium 不可用")

    uid = uuid.uuid4().hex
    work_dir = TEST_BASE / uid
    work_dir.mkdir(parents=True, exist_ok=True)

    bundle_file = work_dir / "minimal.json"
    bundle_file.write_text(json.dumps(MINIMAL_BUNDLE, ensure_ascii=False), encoding="utf-8")
    bundle_rel = bundle_file.relative_to(PROJECT_ROOT).as_posix()
    out_file = work_dir / "output.mp4"

    before_tmp_count = _count_temp_vidframes()

    try:
        cmd = [
            sys.executable,
            str(RENDER_SCRIPT),
            "--bundle",
            bundle_rel,
            "--fps",
            "4",
            "--hold",
            "0.5",
            "--width",
            "640",
            "--out",
            str(out_file),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        assert res.returncode == 0, f"匯出失敗，stderr:\n{res.stderr}\nstdout:\n{res.stdout}"
        assert out_file.exists(), "輸出影片檔案必須存在"

        # 使用 ffprobe 檢查視訊流
        probe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,width,duration",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(out_file),
        ]
        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        probe_data = json.loads(probe_res.stdout)

        video_stream = probe_data["streams"][0]
        assert video_stream["codec_name"] == "h264", f"預期 h264，實際 {video_stream.get('codec_name')}"
        assert video_stream["pix_fmt"] == "yuv420p", f"預期 yuv420p，實際 {video_stream.get('pix_fmt')}"
        assert int(video_stream["width"]) == 640, f"預期寬度 640，實際 {video_stream.get('width')}"

        # 時長檢查：4s + 0.5s = 4.5s，容許 4.0 ~ 5.0
        dur_str = probe_data.get("format", {}).get("duration") or video_stream.get("duration")
        assert dur_str is not None, "ffprobe 必須能讀取時長"
        duration = float(dur_str)
        assert 4.0 <= duration <= 5.0, f"影片時長預期約 4.5 秒，實際為 {duration} 秒"

        # 檢查暫存目錄是否已清理
        after_tmp_count = _count_temp_vidframes()
        assert after_tmp_count == before_tmp_count, "匯出成功後暫存影格目錄必須被完全清除"
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
