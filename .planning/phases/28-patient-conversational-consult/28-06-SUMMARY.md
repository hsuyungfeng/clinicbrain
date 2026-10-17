# Phase 28 Plan 06: 24 小時預先生成主體醫學資訊生成與寫入階段（夜間批次階段 8 接入）執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `28-06-PLAN.md` 規格，完成夜間批次「階段 8：24 小時預先生成主體醫學資訊（Phase 28 P28-PRE / P28-FRESH）」之生成、寫入與批次整合：
1. **生成與寫入階段 (`src/batch/patient_prefill.py`)**：
   - 實作 `run_prefill_stage`，串接 `enumerate_prefill_topics` 與 `plan_prefill`。
   - 採用 `build_compose_prompt` 生成問答，嚴格只組裝純價值回答段落（去除追問與預約 CTA），寫入 `faq_cache`。
   - 唯一權威寫入路徑：一律呼叫 `faq_writer.upsert_faqs(..., source_type='llm_generated')`，新寫入列恆為 `pending`，夜間批次絕不自動核准任何列。
   - 保證純時鐘注入：不直接呼叫 `datetime.now()` 或 `time.time()`，由外部注入 `now` 與 `clock`。
   - 嚴格隔離與防護：單題失敗隔離、LLM 離線捕捉、時間預算逾時中止、`--max-pending` 上限防護、RunLogger 日誌絕不記錄任何問答原文或 prompt。
2. **批次執行器與腳本整合 (`src/batch/runner.py`, `scripts/run_nightly_batch.py`)**：
   - `BatchConfig` 新增 `enable_patient_prefill`（預設 True）、`prefill_seed_path`、`prefill_llm_call`、`now_fn`（預設 `_utc_now`）。
   - `BatchSummary` 新增 `prefill_topics_planned`、`prefill_generated`、`prefill_refreshed`、`prefill_rejected`、`prefill_protected_skipped`、`prefill_skipped_budget`、`prefill_skipped_no_title`、`prefill_backlog` 等欄位。
   - `run_batch` 於階段 7 之後接入階段 8，並支援 `dry_run` 規劃模式。
   - `scripts/run_nightly_batch.py` 新增 CLI 旗標 `--skip-patient-prefill`，LLM 呼叫設為 240 秒超時。
3. **測試套件 (`tests/test_patient_prefill_batch.py`, `tests/test_patient_prefill_e2e.py`)**：
   - 涵蓋 12 項 Task 1 行為測試與 9 項 Task 2 端到端情境測試（跨日 10h/23h 邊界、版本變更觸發重排與 pending 回退、無中文標題樹計數、general 樹核准後直答 0 次模型呼叫、互斥旗標、dry_run 等）。

## 2. 改動檔案

- `src/batch/patient_prefill.py`（新增）：階段 8 生成與寫入核心函式及資料結構。
- `src/batch/runner.py`（修改）：新增預生成設定、摘要欄位、`_utc_now` 唯一 UTC 時間取得、階段 8 執行與 dry_run 規劃。
- `scripts/run_nightly_batch.py`（修改）：新增 `--skip-patient-prefill` 旗標與 prefill 模型呼叫接線。
- `tests/test_patient_prefill_batch.py`（新增）：11 項階段單元測試。
- `tests/test_patient_prefill_e2e.py`（新增）：9 項端到端與跨日模擬測試。
- `.planning/phases/28-patient-conversational-consult/28-06-SUMMARY.md`（新增）：執行摘要。

## 3. 驗收指令執行結果

1. `grep -n "upsert_faqs" src/batch/patient_prefill.py` -> 輸出第 37 行 import 與第 254 行呼叫。
2. `grep -v '^#' src/batch/patient_prefill.py | grep -c "INSERT INTO faq_cache\|UPDATE faq_cache"` -> 輸出 0。
3. `grep -v '^#' src/batch/patient_prefill.py | grep -c "review_status.*approved"` -> 輸出 0。
4. `grep -n "local_llm_call\|urllib" src/batch/patient_prefill.py` -> 無輸出。
5. `grep -n "run_prefill_stage" src/batch/runner.py` -> 輸出第 337、341、558、564 行。
6. `grep -n "skip-patient-prefill" scripts/run_nightly_batch.py` -> 輸出第 108 行。
7. `grep -c "datetime.now(" src/batch/runner.py` -> 輸出 1（僅 `_utc_now`）。
8. `grep -c "datetime.now(\|time.time(" src/batch/patient_prefill.py src/batch/patient_prefill_plan.py` -> 皆輸出 0。
9. `git diff --stat -- '*.service' '*.timer'` -> 無輸出。
10. `uv run pytest tests/test_patient_prefill_batch.py -x -q` -> 11 passed。
11. `uv run pytest tests/test_patient_prefill_e2e.py -x -q` -> 9 passed。
12. `uv run pytest tests/test_nightly_soap_batch.py tests/test_nightly_full_schedule_e2e.py -x -q` -> 5 passed。
13. `uv run pytest -q -p no:cacheprovider tests/test_general_privacy.py` -> 6 passed。
14. `sha256sum clinic.db` -> `0b9548af8601c32dd1b884b54e34b3bd6fbc82609b08372c3e9d5212b8626084  clinic.db`（完全未變）。

## 4. 偏離與特別說明

- 在 `test_patient_prefill_e2e.py` 的 `test_3_max_faq_topics_truncation_and_backlog` 中，原本標題命名為 `f"測試項目第{i}號"`，因 28-05 的 `_is_valid_chinese_title` 明確禁止標題含任何阿拉伯數字，故改為不含數字的標準繁體中文療程名稱（如「玻尿酸豐潤注射」等）。
- `tests/test_nightly_general_batch.py` 之 `test_skip_general_batch` 為基線已知失敗（正式庫於 2026-10-16 包含 3 筆既有 general 列，未跑 batch 前查詢即命中），本計畫未修改該計畫外測試檔案。
