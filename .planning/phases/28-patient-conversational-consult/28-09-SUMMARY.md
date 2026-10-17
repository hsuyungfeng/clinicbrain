# Phase 28 Plan 09: 伺服器固定單一診所設定 (patient_clinic_id) 執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `28-09-PLAN.md` 規格，完成病人匿名諮詢端點綁定「伺服器固定單一診所（`patient_clinic_id`）」之設定讀取、安全解析、診所證據檢索、雙重保險隔離與 API 端點接線：
1. **設定層與驗證解析 (`src/api/config.py`, `src/general/patient_clinic.py`)**：
   - `APIConfig` 新增 `patient_clinic_id: Optional[str]`，預設為 `None`，不設任何寫死之字面值。
   - `resolve_patient_clinic(conn, configured)`：純 SELECT 驗證存在於 `clinic_info` 且為 10 碼數字；缺表或無效時安全回傳 `None`（Fail-Closed），純讀取在 `PRAGMA query_only = ON` 下可運作。
   - `tests/conftest.py` 新增 autouse fixture `_reset_patient_clinic_id`，確保測試前後環境完全隔離。
2. **診所證據檢索與雙重保險隔離 (`src/general/patient_compose.py`, `src/general/patient_consult.py`)**：
   - 實作 `retrieve_clinic_evidence(conn, query, clinic_id)`，僅以 `search_faq_cache(..., category='special')` 與 `search_page_index_trees(..., clinic_id=clinic_id)` 檢索已核准資料。
   - 雙重保險防跨診所：對檢索結果以 Python 逐筆核對 `row.clinic_id == clinic_id`，不符一律丟棄。
   - 嚴格守門防護：問句含 `_CLINIC_OPS_KEYWORDS`（地址、電話、營業時間等）時直接回傳空證據；絕不讀取 `clinic_info`、`clinic_hours`、`clinic_custom_notes`。
   - `compose_from_approved` 支援診所證據優先排在候選池前端，標註層級。
   - `patient_consult` 新增參數 `clinic_id: str | None = None`，模組內絕不讀取 `config.`。
3. **路由與 job 接線、忽略請求夾帶、special 預生成 e2e (`src/api/routes/general.py`, `src/general/consult_jobs.py`)**：
   - 同步 `/consult` 端點以 `resolve_patient_clinic(conn, config.patient_clinic_id)` 解析後傳入 `patient_consult`。
   - 非同步 `POST /consult/jobs` 端點呼叫 `submit_job(..., configured_clinic_id=config.patient_clinic_id)`，由背景 worker 連線後自行解析，端點本身不開啟資料庫連線。
   - 絕對不讀取請求主體或標頭中的 `clinic_id` / `X-Clinic-ID`。
   - 完整測試：`tests/test_patient_clinic_scope.py`（22 項測試）與 `tests/test_patient_prefill_special_e2e.py`（4 項端到端測試，覆蓋 pending 不可見、核准後 0 次模型呼叫直答、未設定不命中、錯誤診所不命中等）。

## 2. 改動檔案

- `src/api/config.py`（修改）：新增 `_read_patient_clinic_id()` 與 `patient_clinic_id` 欄位（預設 None）。
- `src/general/patient_clinic.py`（新增）：`resolve_patient_clinic` 安全驗證函式。
- `tests/conftest.py`（修改）：新增 `_reset_patient_clinic_id` autouse fixture。
- `src/general/patient_compose.py`（修改）：新增 `ClinicEvidence`、`retrieve_clinic_evidence`，更新 `_deterministic_fallback` 與 `compose_from_approved`。
- `src/general/patient_consult.py`（修改）：新增 `clinic_id` 參數與診所證據優先整合。
- `src/general/consult_jobs.py`（修改）：`submit_job` 與 `_worker` 支援 `configured_clinic_id` 參數並於 worker 內解析。
- `src/api/routes/general.py`（修改）：同步端點與 job 端點讀取 `config.patient_clinic_id`，補充 description。
- `tests/test_patient_clinic_scope.py`（新增）：22 項設定、驗證、證據檢索、跨診所防禦與 HTTP 路由測試。
- `tests/test_patient_prefill_special_e2e.py`（新增）：4 項 special 推理樹來源預生成問答核准後直答 e2e 測試。
- `.planning/phases/28-patient-conversational-consult/28-09-SUMMARY.md`（新增）：本執行摘要。

## 3. 驗收指令執行結果

1. `grep -h "3503190424\|3503264627" src/api/config.py src/general/patient_clinic.py | wc -l` -> 輸出 0（程式碼無寫死診所代碼字面值）。
2. `grep -n "clinic_id" src/general/patient_consult.py` -> 顯示新參數 `clinic_id: str | None = None`。
3. `grep -h "config\." src/general/patient_consult.py src/general/patient_compose.py` -> 輸出 0 筆（模組內不讀全域設定）。
4. `grep -n "row.clinic_id\|clinic_id ==" src/general/patient_compose.py` -> 輸出 2 處雙重防禦檢查。
5. `grep -v '^#' src/general/patient_compose.py | grep -c "clinic_custom_notes\|clinic_hours\|clinic_info"` -> 輸出 0（絕不碰禁表）。
6. `grep -n "patient_clinic_id" src/api/routes/general.py` -> 輸出第 97、134 行。
7. `grep -h "X-Clinic-ID\|x_clinic_id" src/api/routes/general.py | wc -l` -> 輸出 0（匿名端點不讀診所標頭）。
8. `grep -n "resolve_patient_clinic" src/general/consult_jobs.py src/api/routes/general.py` -> 兩檔案皆有引入與呼叫。
9. 測試指令：`uv run pytest tests/test_patient_clinic_scope.py tests/test_patient_prefill_special_e2e.py tests/test_consult_jobs.py tests/test_patient_consult.py tests/test_patient_prefill_e2e.py -x -q` -> 56 passed。
10. 隱私守門測試：`uv run pytest -q -p no:cacheprovider tests/test_general_privacy.py` -> 6 passed（AST 掃描通過，無 logging/print/非 SELECT execute）。
11. 正式資料庫防護：`sha256sum clinic.db` -> `0b9548af8601c32dd1b884b54e34b3bd6fbc82609b08372c3e9d5212b8626084  clinic.db`（完全未變）。

## 4. 偏離與特別說明

- 在編寫 `tests/test_patient_prefill_special_e2e.py` 時，為徹底避免既有正式資料庫副本中的其他醫療術語（如「超音波」在既有乳腺腫瘤 FAQ 出現）干擾 FTS 檢索，測試推理樹採用專屬標題「測試專利冷凝除疤術」與不重疊之 `summary_text`，確保 pending 時隔離性與核准後直答的因果鏈路完全精確無誤。
