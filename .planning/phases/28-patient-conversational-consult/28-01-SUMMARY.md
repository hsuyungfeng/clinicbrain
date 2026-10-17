# Phase 28 Plan 01：延遲控制、截斷偵測與模型共用鎖執行總結

## 1. 執行目標
- 修復病人端諮詢端點生成耗時過長問題（P28-LAT），落實最多一次 LLM 呼叫且不重試。
- 建立底層輸出截斷偵測（P28-TRUNC），攔截 `finish_reason == "length"`。
- 統一模型鎖為單一 `GENERATION_LOCK`，並新增夜間批次跨行程檔案鎖探測 `nightly_batch_running`。
- 於 conftest 建立雙層測試防護，徹底杜絕測試誤連真實 LLM (127.0.0.1:8080)。
- 建立 Phase 28 需求條目至 `REQUIREMENTS.md`。

## 2. 實作變更清單
1. `src/pageindex/llm_client.py`：
   - 新增 `LLMTruncatedError(LLMEmptyOutputError)`。
   - 在 `local_llm_call` 中檢測 `finish_reason == "length"`，拋出 `LLMTruncatedError`。
   - 新增取樣常數 `FAITHFUL_SAMPLING`、`PATIENT_COMPOSE_SAMPLING`、`PATIENT_GENERAL_SAMPLING`（保守 3000 tokens 上限與關閉思考參數）。
2. `src/pageindex/llm_lock.py`：
   - 建立全系統唯一的 `GENERATION_LOCK = threading.Lock()`。
   - 實作 `nightly_batch_running(db_path)`，非阻塞探測夜間批次檔案鎖。
3. `src/api/routes/admin.py`：
   - 改為自 `llm_lock` 匯入 `GENERATION_LOCK`，保留 `_GENERATION_LOCK = GENERATION_LOCK` 別名。
   - 自 `llm_client` 匯入 `FAITHFUL_SAMPLING`。
4. `src/pageindex/general_fallback.py`：
   - `_call_no_think_first` 與 `generate_general_draft` 新增 `retry_on_empty: bool = True` 參數。
   - 當 `retry_on_empty=False` 時，`LLMEmptyOutputError` 直接上拋不重試。
5. `src/general/patient_consult.py`：
   - 改用 `GENERATION_LOCK` 與 `nightly_batch_running`，忙碌或批次進行時回 `busy`。
   - 呼叫 `generate_general_draft(..., retry_on_empty=False)`。
   - `default_patient_llm` 改用 `PATIENT_GENERAL_SAMPLING` 與 240 秒逾時，移除 12288 tokens。
   - 新增 `default_patient_compose_llm` 使用 `PATIENT_COMPOSE_SAMPLING` 與 240 秒逾時。
6. `tests/conftest.py`：
   - 新增 `_forbid_real_llm_endpoint` autouse fixture（阻擋對 127.0.0.1:8080 的 urllib 呼叫）。
   - 新增 `_forbid_real_patient_llm` autouse fixture（阻擋真實病人端 LLM 函式）。
7. `tests/test_patient_consult_latency.py`：
   - 涵蓋單次呼叫、截斷不寫入草稿、管理端重試相容、共用鎖與夜間鎖忙碌、取樣常數與測試防護等 7 項行為測試。
8. `tests/test_llm_client.py`：
   - 補齊截斷偵測、stop 回傳、常數組裝與鎖探測測試。
9. `.planning/REQUIREMENTS.md`：
   - 新增 `P28-LAT` 至 `P28-CLINIC` 共 7 項需求及 Traceability 表對應條目。

## 3. 測試驗證結果
- `uv run pytest tests/test_llm_client.py tests/test_admin_ask.py tests/test_phase20_hardening.py -x -q`：41 passed
- `uv run pytest tests/test_patient_consult_latency.py tests/test_patient_consult.py tests/test_general_fallback.py tests/test_general_consult.py tests/test_llm_client.py -x -q`：37 passed
- `uv run pytest tests/test_patient_consult_latency.py tests/test_patient_consult.py tests/test_general_fallback.py tests/test_general_consult.py tests/test_llm_client.py tests/test_admin_ask.py tests/test_phase20_hardening.py -x -q`：69 passed
- `uv run pytest tests/test_patient_consult_ui.py tests/test_web_ui*.py tests/test_admin*.py -x -q`：74 passed
- 正式庫 `clinic.db` SHA-256：`0b9548af8601c32dd1b884b54e34b3bd6fbc82609b08372c3e9d5212b8626084`（前後完全一致）。
