---
phase: 43-automated-video-queue
plan: 02
wave: 2
status: completed
completed_at: 2026-11-12T10:10:30+08:00
---

# 43-02-SUMMARY: 夜間批次離峰排程整合、增量快取跳過與 CLI 工具

## 執行成果
1. **命令列影片渲染 CLI 工具 (`scripts/run_video_render_queue.py`)**：
   - 支援 `--topic-key`（單筆特定主題）與 `--all`（全庫已審核 approved 主題）。
   - 支援 `--aspect` (`landscape` 16:9, `portrait` 9:16, 或 `both`)。
   - 支援 `--limit`、`--force`（略過快取強制重產）、`--dry-run`（唯讀預檢盤點待渲染項目）。
   - 提供結構化終端進度輸出、耗時與容量統計報表。
2. **夜間批次排程整合 (`src/batch/runner.py` & `scripts/run_nightly_batch.py`)**：
   - `BatchConfig` 新增 `skip_video_render`、`video_render_limit`、`video_render_aspect` 配置。
   - `BatchSummary` 新增 `videos_rendered`、`videos_skipped`、`videos_failed` 統計。
   - 於夜間批次流程尾端整合第 9 階段（動態醫學解說動畫影片佇列渲染），在深夜離峰無人看診時段自動補齊新核准主題的 MP4。
   - `scripts/run_nightly_batch.py` 提供 `--skip-video-render` 旗標供使用者選擇性跳過。
3. **整合測試覆蓋 (`tests/test_video_queue_cli_and_batch.py`)**：
   - 4/4 測試全數通過（互斥組校驗、主題不存在防呆、`--dry-run` 盤點、批次 Runner 欄位與旗標配置驗證）。
