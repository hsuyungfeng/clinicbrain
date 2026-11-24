"""Phase 56-03: raea_pipeline.py 與 run_raea_reel_batch.py 單元測試（純 CPU/mock 可跑）。"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.visual import raea_pipeline


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE visual_assets (id INTEGER PRIMARY KEY, topic_key TEXT, title TEXT, ir_json TEXT, edu_json TEXT, clinic_id TEXT)"
    )
    conn.execute("CREATE TABLE clinic_info (clinic_id TEXT PRIMARY KEY, name TEXT, phone TEXT)")
    conn.execute("INSERT INTO clinic_info VALUES ('c1', '緻妍外科診所', '04-2382-0888')")
    ir = {"scenes": [{"title": "機轉", "caption": "胃酸侵蝕黏膜說明"}]}
    conn.execute(
        "INSERT INTO visual_assets (topic_key, title, ir_json, edu_json, clinic_id) VALUES (?, ?, ?, ?, ?)",
        ("icd-k279-peptic-ulcer", "消化性潰瘍", json.dumps(ir), "{}", "c1"),
    )
    return conn


def test_run_raea_check_parses_pass_and_fail(tmp_path: Path) -> None:
    mp4 = tmp_path / "a.mp4"
    mp4.write_bytes(b"fake")

    with patch("subprocess.run") as mrun:
        mrun.return_value = MagicMock(returncode=0, stdout="ok loudness: -14.0 LUFS\nraea check: 0 errors, 0 warns, 0 notes\n", stderr="")
        res = raea_pipeline.run_raea_check(mp4)
        assert res["passed"] is True
        assert res["errors"] == []

        mrun.return_value = MagicMock(returncode=1, stdout="error blotching: dark\nraea check: 1 errors, 0 warns, 0 notes\n", stderr="")
        res2 = raea_pipeline.run_raea_check(mp4)
        assert res2["passed"] is False
        assert len(res2["errors"]) == 1


def test_render_reel_cache_hit_skips_render(tmp_path: Path) -> None:
    conn = _make_db()
    video_dir = tmp_path / "videos"
    out_dir = tmp_path / "reels"
    video_dir.mkdir()
    src_mp4 = video_dir / "icd-k279-peptic-ulcer_portrait.mp4"
    src_mp4.write_bytes(b"dummy-mp4")

    def fake_subprocess(cmd, **kwargs):
        if cmd[0] == "raea" and cmd[1] == "render":
            out_idx = cmd.index("-o") + 1
            Path(cmd[out_idx]).write_bytes(b"rendered-mp4")
            return MagicMock(returncode=0, stdout="", stderr="")
        if cmd[0] == "raea" and cmd[1] == "check":
            return MagicMock(returncode=0, stdout="raea check: 0 errors, 0 warns, 0 notes\n", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch.object(raea_pipeline, "is_raea_available", return_value=True),
        patch.object(raea_pipeline, "_probe_video", return_value=(24, 10.0)),
        patch.object(raea_pipeline, "_generate_bgm_wav", side_effect=lambda p, d: p.write_bytes(b"wav")),
        patch("subprocess.run", side_effect=fake_subprocess) as mrun,
    ):
        r1 = raea_pipeline.render_reel_with_raea(conn, "icd-k279-peptic-ulcer", output_dir=out_dir, video_dir=video_dir, use_llm=False)
        assert r1["status"] == "rendered"
        calls_after_first = mrun.call_count

        r2 = raea_pipeline.render_reel_with_raea(conn, "icd-k279-peptic-ulcer", output_dir=out_dir, video_dir=video_dir, use_llm=False)
        assert r2["status"] == "cached"
        assert mrun.call_count == calls_after_first
    conn.close()


def test_batch_cli_dry_run() -> None:
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "scripts/run_raea_reel_batch.py", "--topic-key", "icd-k279-peptic-ulcer", "--skip-llm", "--dry-run"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    assert len(data) == 1
    assert data[0]["topic_key"] == "icd-k279-peptic-ulcer"
    assert data[0]["dry_run"] is True
    assert data[0]["script_source"] == "fallback"
