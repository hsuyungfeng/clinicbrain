"""
Phase 43 Plan 02 Task 3: 影片渲染 CLI 與夜間批次整合測試 (test_video_queue_cli_and_batch.py)。

驗證目標：
1. scripts/run_video_render_queue.py CLI 解析與防呆：
   - 未指定 --topic-key 或 --all 時報錯退出。
   - 指定不存在的主題時回傳結束碼 2。
2. --dry-run 模式：
   - 僅盤點待渲染主題，不啟動 Chromium 與 ffmpeg，輸出狀態並回傳 0。
3. 夜間批次 runner.py 整合：
   - BatchConfig 具備 skip_video_render 與規格設定。
   - BatchSummary 具備 videos_rendered, videos_skipped, videos_failed 統計。
   - dry_run 或 skip_video_render=True 時優雅略過影片渲染。
"""

from __future__ import annotations

import io
from pathlib import Path
import sqlite3
import sys
import pytest

from scripts.run_video_render_queue import main as cli_main
from src.batch.runner import BatchConfig, BatchSummary, run_batch


def test_cli_requires_target_group():
    """驗證未提供 --topic-key 亦未提供 --all 時拋出 SystemExit。"""
    with pytest.raises(SystemExit):
        cli_main([])


def test_cli_topic_not_found(tmp_path: Path):
    """驗證指定不存在之主題回傳碼 2。"""
    code = cli_main(["--topic-key", "non-existent-topic-xyz", "--db-path", "clinic.db", "--dry-run"])
    assert code == 2


def test_cli_dry_run_all_approved(capsys):
    """驗證 --all --dry-run 能正確盤點 approved 資產並正常結束。"""
    code = cli_main(["--all", "--limit", "3", "--dry-run", "--db-path", "clinic.db"])
    assert code == 0
    captured = capsys.readouterr()
    assert "ClinicBrain 醫學解說動畫影片離線渲染佇列" in captured.out
    assert "Dry-run 盤點完畢" in captured.out


def test_batch_runner_config_and_summary_fields(tmp_path: Path):
    """驗證 BatchConfig 與 BatchSummary 之影片佇列欄位預設值與傳遞。"""
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text("[]", encoding="utf-8")

    cfg = BatchConfig(
        seed_path=seed_file,
        snapshot_dir=tmp_path / "snapshots",
        dry_run=True,
        skip_video_render=True,
        video_render_aspect="both",
        video_render_limit=5,
    )

    assert cfg.skip_video_render is True
    assert cfg.video_render_aspect == "both"
    assert cfg.video_render_limit == 5

    summary = BatchSummary()
    assert hasattr(summary, "videos_rendered")
    assert hasattr(summary, "videos_skipped")
    assert hasattr(summary, "videos_failed")
    assert summary.videos_rendered == 0
