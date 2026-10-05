# Phase 12 Plan 03: 被駁回 FAQ 標記重生成與審核增強 總結 (DEBT-03, GC-02, GC-03)

## 執行概述

- **執行日期**：2026-10-05
- **目標需求**：DEBT-03（被駁回 FAQ 人工標記指令與重生成流程）、GC-02（審核時劑量處方檢測）、GC-03（general 類別審核就醫警訊檢測）
- **狀態**：完成 (PASSED)
- **測試通過情況**：全量 831 passed, 0 failed, 1 warning (21.07s)
- **正式資料庫完整性**：`clinic.db` SHA-256 維持 `ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e` 未受任何寫入污染

---

## 關鍵架構決策與實作

1. **「一次標記，一次嘗試」原則 (Single-Attempt Policy)**：
   - 批次嘗試重新生成後，無論結果為成功、內容相同（unchanged）或被驗證器拒絕（failed），重新生成旗標 `needs_regeneration` 都會被清除（成功時由 `faq_writer` 於 UPDATE 內容時自動清零；其餘由 `settle_regen_flags` 清除並記錄計數），徹底杜絕夜間批次無限迴圈每晚重試消耗 LLM 資源。
   - 例外隔離：若遇 `LocalLLMUnavailableError`（本地模型不可用），旗標完整保留供下一批次再試；其餘一般例外則視為 failed 並清除旗標。

2. **標記重生成之安全限制 (`mark_for_regeneration`)**：
   - 僅允許標記 `source_type='llm_generated'` 且 `review_status='rejected'` 之列。
   - 手寫（manual）與診所上傳（clinic_upload）列回報 `not_llm_generated`，旗標維持 0。
   - 待審核（pending）列回報 `not_rejected`。
   - 已標記列再次標記回報 `already_marked`。
   - 標記操作不變更 `content_version`，亦不變更 `review_status`。

3. **重生成流程與現有問題排除 (`existing_questions`)**：
   - `existing_questions` 增加關鍵字參數 `exclude_regen_marked: bool = False`。
   - 為 True 時排除 `needs_regeneration=1 AND source_type='llm_generated' AND review_status='rejected'` 之列，允許該被標記問題重新進入生成候選。
   - `TopicGenResult` 增加 `regen_questions: list[str]` 欄位追蹤本批待生成之標記問題。

4. **夜間批次優先規劃 (`run_batch`)**：
   - runner 於規劃階段先以 `regen_marked_rows` 取得被標記之主題，若該主題存在於種子清單中，以 `reason='regen_marked'` 排在候選清單最前方，確保非常駐（always=False）或未達熱門門檻之主題亦能被即時規劃。
   - `BatchSummary` 新增 `faq_regen_regenerated`、`faq_regen_unchanged`、`faq_regen_failed` 三個計數欄位。

5. **審核核准前驗證增強 (`set_review_status`)**：
   - 查詢欄位增加 `category`（7 欄解包）。
   - 核准時全面套用第 5 層劑量處方檢測（`check_dosage=True`）。
   - 新增關鍵字參數 `enforce_general_warning: bool = False`（預設關閉以維持既有測試相容性；開啟且 `category='general'` 時要求就醫警訊）。

---

## 程式碼變更清單

1. **`src/pageindex/faq_review.py`**
   - 新增 `mark_for_regeneration(conn, faq_ids) -> ReviewResult`
   - 新增 `clear_regeneration_flag(conn, faq_ids) -> int`
   - 新增 `regen_marked_rows(conn) -> list[dict]`
   - `set_review_status` 支援 `enforce_general_warning` 與劑量處方檢核。

2. **`src/batch/faq_generator.py`**
   - `existing_questions` 支援 `exclude_regen_marked: bool = False`。
   - `TopicGenResult` 增加 `regen_questions` 欄位。
   - `generate_topic_faqs` 填入 `batch_regen_questions`。
   - `write_topic_faqs` 回傳 `WriteResult`（相容 3-tuple 與屬性存取）。
   - 新增 `settle_regen_flags(conn, topic, result) -> dict`。

3. **`src/batch/runner.py`**
   - `BatchSummary` 增加三個 `faq_regen_*` 欄位。
   - FAQ 規劃階段優先納入標記主題，使用 `exclude_regen_marked=True`。
   - FAQ 執行階段呼叫 `settle_regen_flags` 並累計統計。

4. **`tests/test_faq_regen.py`**
   - 涵蓋標記安全限制、清除旗標、現有問題排除、三種重生成結果、runner 優先規劃與審核新驗證等 8 個完整測試。

---

## 驗收結果

- RED 測試成功驗證（未實作前 exit 1）。
- `test_faq_regen.py` 8 個測試全數通過。
- 既有 `test_faq_review_gate.py`、`test_review_gate_retrieval.py`、`test_batch_runner.py` 零修改通過。
- 全量回歸測試：831 passed, 0 failed, 1 warning。
