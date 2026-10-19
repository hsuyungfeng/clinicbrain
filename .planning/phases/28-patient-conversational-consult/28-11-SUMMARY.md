# Phase 28 Plan 11: 通用衛教與療程專屬追問情境分流執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `28-11-PLAN.md` 規格，解決 2.24 未審醫學說明與通用衛教資料被誤配為「術後／療程」專用追問之違和感，達成情境分流防護：
1. **中性通用追問常數表與 assemble_answer 的 scope 支援（Task 1, P28-11-01）**：
   - 定義 `PROCEDURE_ONLY_TERMS: tuple[str, ...] = ("術後", "療程", "手術", "治療", "施作")`。
   - 定義 `GENERAL_FOLLOWUPS: dict[str, str]`，包含六大意圖（what, recovery, risk, suitable, when_to_see_doctor, other）之中性追問句，長度介於 10~45 字、恰一個中文問號、結尾為完整標點，通過醫療法規安全檢驗，且絕不包含任何療程專用術語。
   - 擴充 `assemble_answer(..., scope: str = "procedure")`：
     - 預設維持 `"procedure"`（向下相容既有呼叫端）。
     - 當 `scope == "general"` 時，若候選追問包含 `PROCEDURE_ONLY_TERMS` 任一詞彙，立即攔截並安全退回 `GENERAL_FOLLOWUPS`。
     - 模組底端載入時自我驗證迴圈納入 `GENERAL_FOLLOWUPS` 與 `PROCEDURE_ONLY_TERMS` 防禦斷言。
2. **依情境選用追問與文檔補述（Task 2, P28-11-02）**：
   - `decorate_general_answer(answer, query)`：2.24 未審說明裝飾一律傳入 `scope="general"`。
   - `_deterministic_fallback`：增補 `scope: str = "procedure"` 參數，內部呼叫 `assemble_answer` 一致傳遞 `scope`。
   - `compose_from_approved`：
     - 計算 `scope = "procedure" if (clinic_evidence and (clinic_evidence.faq_hits or clinic_evidence.guide_hits)) else "general"`。
     - 命中直答、LLM 組稿組裝與所有確定性降級路徑（共 8 處）皆一致傳入 `scope=scope`。
   - `AGENTS.md`：於 2.25 節純新增 28-11 架構補述（被刪除行數嚴格為 0）。

---

## 2. 改動檔案

- `src/general/answer_compose.py`：新增 `PROCEDURE_ONLY_TERMS`、`GENERAL_FOLLOWUPS`，擴充 `assemble_answer(..., scope="procedure")` 支援通用情境過濾，並於模組底部增加載入自我驗證。
- `tests/test_answer_compose.py`：新增 `GENERAL_FOLLOWUPS` 鍵與合規性驗證、`assemble_answer` 的 `scope` 行為切換、以及 `scope='general'` 攔截模型自帶療程追問之測試。
- `src/general/patient_compose.py`：`_deterministic_fallback` 增加 `scope` 參數；`compose_from_approved` 依據有無診所專屬證據（`faq_hits` 或 `guide_hits`）動態計算 `scope` 並傳遞至直答、組稿與降級；`decorate_general_answer` 強制傳入 `scope="general"`。
- `tests/test_patient_compose.py`：新增 `test_decorate_general_answer_uses_general_scope`、`test_deterministic_fallback_scope_param` 與 `test_compose_from_approved_scope_selection`。
- `tests/test_patient_consult.py`：新增 `test_patient_consult_followup_no_procedure_terms_when_general_only`，驗證 2.24 未審說明產出之追問無療程術語。
- `AGENTS.md`：於 2.25 節純新增 28-11 通用衛教與療程專屬追問情境分流說明（被刪除行數嚴格為 0）。
- `.planning/phases/28-patient-conversational-consult/28-11-SUMMARY.md`：執行摘要報告。

---

## 3. 驗收指令執行結果

1. **Task 1 驗收測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_answer_compose.py tests/test_patient_compose.py`
   -> **35 passed** in 0.88s。
2. **Task 2 驗收測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_answer_compose.py tests/test_patient_compose.py tests/test_patient_consult.py tests/test_general_privacy.py tests/test_patient_clinic_scope.py tests/test_consult_jobs.py`
   -> **90 passed**, 1 warning in 3.25s。
3. **AGENTS.md 純新增驗收**：
   `git diff -U0 AGENTS.md | grep -c '^-[^-]'`
   -> **0**（被刪除或改動行數嚴格為 0）。
4. **既有測試斷言守門**：
   `tests/test_patient_consult.py` 第 109 至 114 行維持原樣通過。
5. **隱私守門測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_general_privacy.py`
   -> **6 passed** in 1.30s。
6. **正式資料庫雜湊不變守門**：
   `sha256sum clinic.db`
   -> `0b9548af8601c32dd1b884b54e34b3bd6fbc82609b08372c3e9d5212b8626084  clinic.db`（完全未變）。

---

## 4. 偏離與特別說明

- 無任何偏離計畫之處。所有既有測試皆未放寬或刪除，新測試皆嚴格遵循 TDD 流程（RED -> GREEN）。
