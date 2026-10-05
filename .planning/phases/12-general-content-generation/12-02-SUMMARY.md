# Phase 12 Plan 02: 疾病種子清單擴充與簽核硬閘門 總結 (GC-01)

## 執行概述

- **執行日期**：2026-10-05
- **目標需求**：GC-01（擴充疾病種子清單並建立使用者簽核硬閘門）
- **狀態**：完成 (PASSED)
- **測試通過情況**：全量 823 passed, 0 failed, 1 warning (20.89s)
- **正式資料庫完整性**：`clinic.db` SHA-256 維持 `ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e` 未受任何寫入污染

---

## 使用者簽核紀錄

- **簽核日期**：2026-10-05
- **簽核項目**：全部 17 題種子問題全文（見 `.planning/phases/12-general-content-generation/12-SEED-PROPOSAL.md` 與 `.planning/REQUIREMENTS.md`）
- **核准疾病涵蓋**：
  1. 感冒（`common-cold-home-care`，5 題，含既有 2 題照護與飲水問答）
  2. 流感（`influenza-basics`，4 題）
  3. 急性腸胃炎（`acute-gastroenteritis`，4 題）
  4. 過敏性鼻炎（`allergic-rhinitis`，4 題）
- **四類題型標籤 (question_tags)**：
  - `what`（這是什麼）
  - `symptoms`（常見症狀）
  - `when_to_see_doctor`（何時就醫）
  - `home_care`（居家日常照護）
- **醫療安全邊界防線**：
  - 所有題目不含「藥」「抗生素」「吃什麼」等處方邊界關鍵詞。
  - 既有 3 個 special 主題與 6 個 tree_procedure_names 完整保留。

---

## 程式碼變更清單

1. **`src/batch/topic_sources.py`**
   - 定義 `QUESTION_TAGS = frozenset({"what", "symptoms", "when_to_see_doctor", "home_care"})`。
   - `SeedTopic` 增加 `question_tags: tuple[str, ...] = ()` 欄位（置於最後，向下相容）。
   - `validate_seed_data` 增加 `question_tags` 長度、型別與標籤白名單校驗。
   - `load_seed_file` 正確將 `question_tags` 載入為 `tuple`。

2. **`data/batch/faq_seeds.json`**
   - 正式覆蓋為含 17 題一般疾病與 3 個特殊主題之完整種子清單。
   - 通過四層合規檢查與資料結構校驗。

3. **`tests/test_disease_seeds.py`**
   - 建立 `test_question_tags_constant`、`test_validate_seed_data_*`、`test_load_seed_file_*` 單元測試。
   - 建立 `test_hard_gate_no_code_references_proposed`：確保 `src/` 與 `scripts/` 無任何檔案未經簽核即引用 `faq_seeds.proposed`。
   - 建立 `test_seed_file_structure_and_disease_coverage`：全面驗證 4 疾病、17 題全文、四類題型涵蓋與四層合規性。

---

## 驗收結果

- RED 測試成功驗證（未實作前 exit 1）。
- 既有 `test_batch_topic_sources.py`、`test_batch_runner.py`、`test_run_nightly_batch_cli.py` 零修改全數通過。
- `data/batch/faq_seeds.proposed.json` 於簽核確認後改名為正式 `data/batch/faq_seeds.json`。
