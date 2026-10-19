# Phase 28 Plan 10: 病人端諮詢驗收缺口修正與品質防禦執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `28-10-PLAN.md` 規格，完成真實服務端到端驗收所發現的三項品質問題與缺口之修正：
1. **證據相關度檢核與資料不足輸出攔截（Task 1, P28-10-01）**：
   - 實作 `is_relevant_evidence` 與 `filter_relevant`，以問句相鄰 CJK 2-gram 扣除泛用詞（`GENERIC_TERMS` 與其 bigram 集合）後比對候選資料，Fail-Closed 防止不相干已核准資料被誤當證據組稿。
   - 實作 `looks_insufficient` 與 `InsufficientEvidenceError`，當模型輸出表示資料不足時，自動拋出例外並跳過資料庫預設答覆，直接放行落入 2.24 未審醫學說明路徑。
   - 保留原物件複本隔離與既有 `test_patient_consult.py` 第 109～114 行之斷言相容。
2. **中性預設追問與提示詞警訊句規則強化（Task 2, P28-10-02）**：
   - `DEFAULT_FOLLOWUPS["other"]` 修改為中性用語（「您目前是否有特定的困擾部位，或想先了解哪方面的照護方式？」），不預設病患諮詢為療程，字數與格式符合既有合規驗證。
   - 修正 `build_compose_prompt` 中的錯字「一工具體」為「一句具體」，並明示警訊句需含具體症狀詞與就醫動作，提供通過 `has_doctor_warning` 之合法示範句。
3. **夜間預生成剔除原因結構化細分與資料不足剔除（Task 3, P28-10-03）**：
   - 實作 `reject_code_for`，將驗證失敗原因精準歸類為 `missing_warning`、`price_leak`、`political_phrase`、`simplified_chinese`、`guarantee_phrase`、`dosage_or_prescription`、`sentence_count`、`insufficient_evidence` 等細分碼。
   - 預生成輸出經 `looks_insufficient` 判定為真時直接剔除不入庫；日誌 payload 嚴格禁止記錄任何問句或答案原文。
   - 於專案內 `AGENTS.md` 2.25 節純新增 28-10 架構決策補述，被刪除行數嚴格為 0。

---

## 2. 改動檔案

- `src/general/patient_compose.py`：新增 `InsufficientEvidenceError`、`GENERIC_TERMS`、`_GENERIC_BIGRAMS`、`is_relevant_evidence`、`filter_relevant` 與 `looks_insufficient`，並於 `compose_from_approved` 檢查資料不足拋出例外。
- `src/general/patient_consult.py`：檢索後呼叫 `filter_relevant` 過濾不相關證據，並攔截 `InsufficientEvidenceError` 跳過 `found.message` 分支落入 2.24 說明。
- `tests/test_patient_compose.py`：新增 `test_10` 至 `test_13` 單元測試。
- `tests/test_patient_consult.py`：新增不相關證據過濾與資料不足跳過一般證據之情境測試。
- `src/general/answer_compose.py`：更新 `DEFAULT_FOLLOWUPS["other"]` 為中性問法；修正 `build_compose_prompt` 錯字並加入合法警訊句示範與規則。
- `tests/test_answer_compose.py`：新增中性追問與 prompt 警訊句規則驗證測試。
- `src/batch/patient_prefill.py`：新增 `reject_code_for`、擴充 `PrefillResult` 統計欄位，於預生成流程加入 `looks_insufficient` 剔除與匿名結構化日誌記錄。
- `src/batch/runner.py`：擴充 `BatchSummary` 的 `prefill_rejected_warning` 與 `prefill_rejected_insufficient` 欄位與映射。
- `tests/test_patient_prefill_batch.py`：新增細分碼對照、資料不足剔除與日誌隱私單元測試。
- `tests/test_nightly_general_batch.py`：最小必要更新，排除正式庫既有之 3 筆歷史草稿（id=924-926），精準驗證本批次新產出列不含 general。
- `AGENTS.md`：於 2.25 節純新增 28-10 架構補述（被刪除行數嚴格為 0）。
- `.planning/phases/28-patient-conversational-consult/28-10-SUMMARY.md`：執行摘要報告。

---

## 3. 驗收指令執行結果

1. **Task 1 驗收測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_patient_compose.py tests/test_patient_consult.py tests/test_general_privacy.py tests/test_patient_clinic_scope.py tests/test_answer_compose.py`
   -> **69 passed** in 2.65s。
2. **Task 2 驗收測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_answer_compose.py tests/test_patient_compose.py tests/test_medical_safety.py`
   -> **236 passed** in 1.02s。
3. **Task 3 驗收測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_patient_prefill_batch.py tests/test_patient_prefill_plan.py tests/test_patient_prefill_e2e.py tests/test_patient_prefill_special_e2e.py tests/test_nightly_general_batch.py`
   -> **50 passed** in 3.09s。
4. **AGENTS.md 純新增驗收**：
   `git diff -U0 AGENTS.md | grep -c '^-[^-]'`
   -> **0**（被刪除或改動行數嚴格為 0）。
5. **隱私守門測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_general_privacy.py`
   -> **6 passed** in 1.37s。
6. **正式資料庫雜湊不變守門**：
   `sha256sum clinic.db`
   -> `0b9548af8601c32dd1b884b54e34b3bd6fbc82609b08372c3e9d5212b8626084  clinic.db`（完全未變）。

---

## 4. 偏離與特別說明

- 在執行 Task 3 verify 指令時，`tests/test_nightly_general_batch.py` 的 `test_skip_general_batch` 失敗，經診斷係因正式資料庫 `clinic.db` 既有 3 筆歷史一般草稿（id=924, 925, 926，`source_type='llm_generated'` 且 `category='general'`，為 28-06 SUMMARY 已記錄之基線現象）。此處依規範執行最小必要斷言更新：在批次執行前記錄 `init_max_id`，僅驗證本次批次產出之新列（`id > init_max_id`）不包含 general，保留既有所有斷言並使測試集完全綠燈。
