# Phase 28 Plan 08: AGENTS.md 2.25 與規範補述執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `28-08-PLAN.md` 規格，於所有程式與測試計畫完成後，依真實實作與 28-PROBE.md 實測數據撰寫專案規範與目錄結構補充：
1. **AGENTS.md 2.25 節新增**：
   - 完整記錄 Phase 28 實作之對話式組稿、24 小時預生成與非同步作業架構。
   - 耗時根因與實機探測數據（28-PROBE.md）：記錄本機 llama-server (Qwen3.8-27B-UD-Q4_K_XL) 實測解碼速度為 22.17 ～ 22.54 tok/s（平均約 22.5 tok/s，舊版 90 tok/s 實為 prompt 處理速度）；記錄 `chat_template_kwargs: {"enable_thinking": false}` 能 100% 關閉思考（reasoning 歸零，耗時從 33.7 秒降至 4.6 秒），而 `reasoning_effort: "none"` 完全無效；病人端單次呼叫不重試；取樣上限設為 800（組稿）與 1500（未審說明），未驗證項目明確標記「待驗證」；`finish_reason: "length"` 拋出 `LLMTruncatedError`。
   - 句界截斷 (`clip_at_sentence`) 與就醫警訊優先保留、總長上限 `CONTEXT_TOTAL_CHARS = 2000`。
   - 三段式結構（價值 2～4 句 ＋ 單一追問 ＋ 固定預約 CTA 常數）與獨立四層合規檢核。
   - 完整查詢路由與降級序列（紅旗 → 已核准直答 → LLM 組稿 → 確定性降級 → 同題重用 → 未審說明 → 固定文字）。
   - 跨執行緒共用生成鎖 `GENERATION_LOCK`、夜間批次排程互斥探測 `nightly_batch_running()`、測試雙層真實 LLM 阻擋防護。
   - 非同步作業佇列（`POST /consult/jobs` 與 `GET /consult/jobs/{job_id}`）：安全票券、`RESULT_TTL_SECONDS = 300`、`MAX_JOBS = 20`、`MAX_RUNNING = 4`、單次讀後即刪、不存問句、輪詢零資料庫連線。
   - 夜間批次階段 8 預生成：五意圖模板、`FRESHNESS_HOURS = 24`、`REFRESH_GRACE_HOURS = 2`、`topic_key` 與 `metadata` 追蹤、簽章變更驅動、保護列略過、永不自動核准、時鐘注入與資源防禦、摘要統計欄位（含 `prefill_protected_skipped`、`prefill_skipped_budget`、`prefill_skipped_no_title`、`prefill_backlog`）與 CLI `--skip-patient-prefill`。
   - 伺服器固定單一診所設定例外（P28-CLINIC）：`CLINICBRAIN_PATIENT_CLINIC_ID` 無預設值、`resolve_patient_clinic` Fail-Closed、忽略請求內 `clinic_id` 與 `X-Clinic-ID`、雙重跨診所隔離、營運關鍵字保護、不存問句與日誌安全。
   - 已知限制與測試清單（11 個實際存在的測試檔案）。
2. **2.6、2.9 與 2.24 例外補述**：
   - 嚴格遵守「只准在該節或該行下方新增獨立一行（或子項目），不得改動、刪除或在原行尾追加，原行逐字保留」，`git diff -U0 AGENTS.md | grep -c '^-[^-]'` 確實驗收為 0。
   - 2.6、2.9、2.24 皆出現 `patient_clinic_id` 字樣並明確指向 2.25 節。
3. **第 4 節目錄結構補充**：
   - 純新增 Phase 28 所有新模組、腳本（`scripts/probe_patient_thinking.py`）與測試檔，無任何舊行刪除。

## 2. 改動檔案

- `AGENTS.md`（修改）：專案內規範文件，純新增 93 行，0 行刪除。
- `.planning/phases/28-patient-conversational-consult/28-08-SUMMARY.md`（新增）：本執行摘要。

## 3. 驗收指令執行結果

1. `test "$(grep -c '^### 2.25' AGENTS.md)" = "1"` -> 通過（唯一 2.25 節）。
2. `git diff -U0 AGENTS.md | grep -c '^-[^-]'` -> 輸出 0（完全無刪除或修改舊行）。
3. `git diff --stat` -> 僅 `AGENTS.md`（93 insertions(+)）。
4. 關鍵字檢查：`FRESHNESS_HOURS`、`topic_key`、`prefill_skipped_budget`、`GENERATION_LOCK`、`MAX_RUNNING` 五個關鍵字皆存在。
5. 核心模組與腳本存在性檢查：
   - `src/pageindex/llm_lock.py`：存在
   - `src/general/answer_compose.py`：存在
   - `src/general/patient_compose.py`：存在
   - `src/general/consult_jobs.py`：存在
   - `src/batch/patient_prefill_plan.py`：存在
   - `src/batch/patient_prefill.py`：存在
   - `src/general/patient_clinic.py`：存在
   - `scripts/probe_patient_thinking.py`：存在
6. 引用測試檔案存在性檢查：2.25 與目錄結構所提及之測試檔案全數存在於 `tests/`。
7. 隱私守門測試：`uv run pytest -q -p no:cacheprovider tests/test_general_privacy.py` -> 6 passed in 1.40s。
8. 正式資料庫防護：`sha256sum clinic.db` -> `0b9548af8601c32dd1b884b54e34b3bd6fbc82609b08372c3e9d5212b8626084  clinic.db`（完全未受影響）。

## 4. 偏離與特別說明

- 嚴格遵守使用者指示，未碰觸專案外的 `/home/hsu/AGENTS.md`，所有規範變更僅限於本專案倉庫根目錄之 `AGENTS.md`。
- 數值與參數完全依據 `28-PROBE.md` 實測紀錄撰寫（平均 22.5 tok/s 解碼速率、enable_thinking 生效、reasoning_effort 無效、800/1500 取樣上限），未經真實組稿分布驗證之進一步收緊可能性明確標記為「待驗證」。
