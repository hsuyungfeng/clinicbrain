# Phase 28 Plan 04：病人端非同步作業登錄與輪詢執行總結

## 1. 執行目標
- 實作病人端非同步背景作業與輪詢機制（P28-ASYNC、P28-LAT），解決公開諮詢端點連線長時間掛住、反向代理逾時與 FastAPI threadpool 耗盡問題。
- 嚴格隱私性：問句置於請求主體，記憶體 registry 絕不儲存問句原文，問句不進入 URL、不記錄於存取日誌，結果單次讀取即刪除，未讀取最長保留 5 分鐘。
- 急重症紅旗問句於提交當下同步回傳就醫指示，不建立作業、不呼叫模型。
- 容量防護：worker 上限 `MAX_RUNNING = 4`、總作業上限 `MAX_JOBS = 20`，超出直接回傳 busy，不排隊。模型序列化由 `GENERATION_LOCK` 控管。
- 前端 `consult.html` 以單一 `setTimeout` 鏈輪詢結果，所有文字使用 `textContent`，不使用 `setInterval`、`innerHTML` 或瀏覽器端 storage。

## 2. 實作變更清單
1. `src/general/consult_jobs.py`（全新建立）：
   - 常數：`RESULT_TTL_SECONDS = 300`、`MAX_JOBS = 20`、`MAX_RUNNING = 4`。
   - `submit_job(db_path, query, patient_llm, compose_llm)`：紅旗同步回傳、容量檢查、不可預測之安全票券（`secrets.token_urlsafe(16)`）、啟動 daemon worker。
   - `_worker(...)`：背景執行緒連線資料庫並呼叫 `patient_consult`，輸出經 `deep_mask_prices`，例外轉為 `no_match` 固定文字。
   - `get_job_result(job_id)`：純記憶體輪詢，不連線資料庫，pending 回傳狀態，done 回傳完整結果並立即自記憶體刪除（單次讀取即刪除）。
   - `sweep_expired()`、`wait_idle()`、`reset_for_tests()`、`snapshot()` 測試與維護輔助。
   - 符合 `test_general_privacy.py` 規範：無 logging、無 print、無非 SELECT 語句。
2. `src/api/routes/general.py`（更新）：
   - 新增 `POST /consult/jobs` 端點：接收問句並呼叫 `submit_job`，不使用資料庫 Depends。
   - 新增 `GET /consult/jobs/{job_id}` 端點：純記憶體讀取，無 Depends，找不到統一回傳 404 `{"detail": "找不到結果"}`。
   - 更新既有同步 `/consult` 端點傳入 `compose_llm_call=default_patient_compose_llm`。
3. `src/web/static/consult.html`（更新）：
   - 送出諮詢改為 POST `/api/v1/general/consult/jobs`。
   - 回應含 `job_id` 則顯示等待文字並以 `setTimeout` 鏈依 `POLL_INTERVAL_MS = 2500` 輪詢結果；逾時上限 `POLL_MAX_MS = 240000`。
   - 文案改為「整理中，通常需 20 秒至 2 分鐘，請稍候」。
   - 保持所有安全規範：不使用 `innerHTML`、`setInterval`、`localStorage`、`sessionStorage`。
4. `tests/test_consult_jobs.py`（全新建立）：
   - 包含 12 項單元測試，涵蓋 pending 結構、紅旗同步無 job、輪詢讀後即刪、404 固定文字、300 秒 TTL、registry 零問句洩漏、容量上限、worker 例外隔離、輪詢零 DB 連線、價格屏蔽、422 固定錯誤與 access log 排除、正式庫路徑防護守門。
5. `tests/test_patient_consult_ui.py`（更新）：
   - 配合新文案將「整理中，約 1～3 分鐘」更新為「整理中，通常需 20 秒至 2 分鐘，請稍候」。
   - 補充對非同步端點 `/api/v1/general/consult/jobs` 與輪詢常數之斷言。

## 3. 驗收結果
- **Task 1 驗收 criteria**：
  - `grep -n "secrets.token_urlsafe" src/general/consult_jobs.py` -> 第 109 行。
  - `grep -c "import random" src/general/consult_jobs.py` -> 輸出 `0`。
  - `grep -n "RESULT_TTL_SECONDS = 300\|MAX_JOBS = 20" src/general/consult_jobs.py` -> 兩常數皆存在。
  - `grep -n "/consult/jobs" src/api/routes/general.py` -> 至少 2 行（第 111 行與第 130 行）。
  - `grep -n "Depends" src/api/routes/general.py` 之 GET jobs 端點函式內無 Depends。
  - `tests/test_consult_jobs.py` 12 項行為測試全部通過。
- **Task 2 驗收 criteria**：
  - `grep -c "setInterval" src/web/static/consult.html` -> 輸出 `0`。
  - `grep -c "innerHTML" src/web/static/consult.html` -> 輸出 `0`。
  - `grep -n "POLL_MAX_MS\|POLL_INTERVAL_MS" src/web/static/consult.html` -> 兩常數皆存在。
  - `grep -c "localStorage\|sessionStorage" src/web/static/consult.html` -> 輸出 `0`。
  - `tests/test_patient_consult_ui.py` 與 `tests/test_web_ui.py` 全部通過。
- **隱私守門測試**：
  - `uv run pytest -q -p no:cacheprovider tests/test_general_privacy.py` -> `6 passed, 1 warning in 1.31s`。
- **正式資料庫防護**：
  - `sha256sum clinic.db`：`0b9548af8601c32dd1b884b54e34b3bd6fbc82609b08372c3e9d5212b8626084`，維持不變。
