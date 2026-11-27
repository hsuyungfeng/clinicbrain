# Phase 55 Verification: 夜間 FAQ 自動生成與動畫管線強化

**Verified:** 2026-11-24
**Status:** PASSED (Herdr `wA:p3` Hermes 獨立 Tester 驗收通過)

## 1. 變更範圍與實作摘要

- **Wave 1 (`55-01-PLAN.md`)**
  - `src/batch/runner.py`、`src/batch/patient_prefill.py`、`scripts/run_nightly_batch.py`：拆開 `max_prefill_topics`（預設 `20`）與 `max_faq_topics`（保留 `5` 供 `_stage_plan_faq` 使用）；暴露 `--video-render-limit`（預設 `15`、`0` 表不限）與 `--video-render-aspect`（預設 `landscape`）。
  - `src/batch/patient_prefill.py`、`src/batch/faq_generator.py`：針對 `missing_warning` / `dosage_or_prescription` 加上帶具體違規原因的**最多 1 次重試**（不放寬任何醫療合規紅線）；`faq_generator` 強化多題微調問句之字元 Jaccard 安全唯一對齊，強制寫回原始 seed 問句。
- **Wave 2 (`55-02-PLAN.md`)**
  - `src/visual/autodraft.py`、`src/batch/runner.py`、`scripts/run_nightly_batch.py`：新增 `find_trees_missing_visual_assets()` 與 `_stage_visual_autodraft`（排於 `patient_prefill` 之後、`video_render` 之前），並為 `autodraft_from_tree()` 新增 `ignore_nightly_lock`（夜間批次內部呼叫傳 `True` 防自鎖，外部 API 維持預設 `False`）；新增 `--skip-visual-autodraft` 與 `--max-visual-autodraft`（預設 `3`）。
  - `src/refresh/sources.py`、`scripts/run_daily_knowledge_refresh.py`：替換失效的 `OFFICIAL_RSS_FEEDS`（原 CDC 404 與 FDA XML ParseError），改為可解析官方 URL（`mohw.gov.tw/rss-16-1.html`、`fda.gov.tw/TC/rssLawMedical.ashx`、`fda.gov.tw/TC/rssNews.ashx`），加入 BOM/空白前導容錯與 Atom `<entry>` 支援，並將靜默 `except Exception` 改為 `logger.warning(...)`。
- **Wave 3 (`55-03-PLAN.md`)**
  - `tests/test_phase55_nightly_hardening.py`：新增 6 項單元與整合測試。

## 2. 獨立驗收結果（Herdr `wA:p3` `hermes-tester`）

- **Pytest：** `tests/test_phase55_nightly_hardening.py`、`tests/test_batch_faq_generator.py`、`tests/test_patient_prefill_batch.py`、`tests/test_run_nightly_batch_cli.py`、`tests/test_refresh_sources.py` — **38 passed**
- **夜間批次 `--dry-run`：** `run_nightly_batch.py --db clinic.db --dry-run --max-prefill-topics 20 --video-render-limit 15 --max-visual-autodraft 3` — `exit 0`, `status: dry_run`, `errors: 0`, `prefill_backlog` 由 `80` 降至 `63`。
- **每日新知 `--dry-run --check-feeds`：** `RSS=20`（修復原 `RSS=0`）。
- **正式庫 SHA-256：** `d8e0b7ebf5f92478d114e93d7391e7ef1b66088490f33a21245a865488809fa3`（全程恆定未變）。
- **Hermes 判定：** `TESTER_VERDICT: PASS`

## 3. Crontab 建議更新

將原本 `03:30` 的 `run_nightly_batch.py` 補上新參數（或直接沿用預設值 `20` / `15` / `3`）：

```cron
30 3 * * * cd /home/hsuyungfeng/DevSoft/clinicbrain && .venv/bin/python3 scripts/run_nightly_batch.py --db /home/hsuyungfeng/DevSoft/clinicbrain/clinic.db --allow-prod-db --max-faq-topics 5 --max-prefill-topics 20 --max-trees 3 --max-visual-autodraft 3 --video-render-limit 15 --time-budget-seconds 3600 --include-pending-web-prefill >> logs/nightly_batch/cron.log 2>&1
```
