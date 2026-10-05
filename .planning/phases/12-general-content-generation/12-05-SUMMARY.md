# Phase 12 Plan 05: 醫師審核工具增強與衝突比對 總結 (GC-04, DEBT-03)

## 執行概述

- **執行日期**：2026-10-05
- **目標需求**：GC-04（改善審核工具：主題檢視、來源與驗證結果顯示、相近診所 FAQ 衝突清單）、DEBT-03（CLI 人工標記待重新生成 mark-regen）
- **狀態**：完成 (PASSED)
- **測試通過情況**：全量 853 passed, 0 failed, 1 warning (22.38s)
- **正式資料庫完整性**：`clinic.db` SHA-256 維持 `ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e` 未受任何寫入污染

---

## 關鍵架構決策與實作

1. **覆蓋率計算共用定義 (`faq_shortcut.faq_coverage`)**：
   - 新增公開純函式 `faq_coverage(query_text, question_text, stopword_pattern=None)`。
   - 沿用 `normalize_for_match` 與 `score_hit`，與 `select_confident_faq` 的 `query_coverage` / `question_coverage` 完全同一套數學與標準化定義。
   - `faq_shortcut` 既有判定邏輯與門檻常數維持零改動。

2. **相近診所問答衝突檢索 (`src/pageindex/faq_conflicts.py`)**：
   - 實作 `find_similar_clinic_faqs(conn, general_question, *, clinic_id=None, floor=CLINIC_RELATED_FLOOR, limit=5)`。
   - 嚴格引用 `faq_shortcut.CLINIC_RELATED_FLOOR`，原始碼中絕無硬編碼數值 `"0.4"`（經 `test_similar_faqs_floor_unique_and_no_literal` 靜態檢驗）。
   - 審核閘門安全隔離：SQL 檢索條件整合 `visible_faq_sql(conn)`，確保未核准（pending/rejected）之診所 LLM 生成內容絕不列入衝突候選。
   - 唯讀保證：全程支援 SQLite `mode=ro`。
   - 靜態守衛登錄：於 `tests/test_faq_read_guard.py` 白名單中合法登錄。

3. **詞彙守衛與主題守衛的已知限制**：
   - 實測本計畫 17 題 general 疾病種子對正式庫 40 筆醫美診所 FAQ 最高覆蓋率皆 $\le 0.30$（$< 0.4$），因此對疾病種子進行審核時衝突清單預期為空。
   - 詞彙覆蓋率僅為詞彙重疊守衛，非主題衝突守衛；CLI `show` 一律輸出固定警語：「`覆蓋率只是詞彙守衛，不是主題守衛：未列出不代表沒有衝突，請自行比對同主題診所指示。`」

4. **審核核心模組增強 (`src/pageindex/faq_review.py`)**：
   - `list_faqs` 新增 `topic_key` 關鍵字參數，支援依主題批次檢視。
   - 新增 `validation_report(faq)`：調用 `validate_single_faq` 執行多層醫療合規驗證，general 項目強制檢核就醫警訊收尾句，回傳 `{"ok": bool, "reason": Optional[str]}`。
   - `set_review_status` 支援 `enforce_general_warning` 參數，核准時嚴格阻擋無警訊之 general 問答。

5. **審核 CLI 工具全面升級 (`scripts/review_faq.py`)**：
   - `list`：新增 `--topic` 參數；表格擴充「來源」(`source_type`) 與「驗證」(`validation_report` OK/FAIL) 欄位，FAIL 時縮排印出未通過原因；沿用 `mode=ro`。
   - `show`：新增「生成來源」與「驗證結果」區塊；針對 `category == 'general'` 且 `clinic_id IS NULL` 的問答，自動呼叫 `find_similar_clinic_faqs` 顯示相近診所 FAQ 列表與覆蓋率，並附帶固定警語。
   - `approve`：預覽時同步印出驗證結果，傳入 `enforce_general_warning=True`。
   - `mark-regen`：新增寫入子命令，納入 `is_write_cmd`（正式庫未帶 `--allow-prod-db` 於連線前立即以 code 2 阻斷）；使用寫入連線調用 `faq_review.mark_for_regeneration`。
   - 零手寫 SQL UPDATE 規範：腳本內不含任何 `UPDATE faq_cache` 語句（自動化檢查 0 次）。

---

## 程式碼變更清單

1. **`src/query/faq_shortcut.py`**
   - 新增公開純函式 `faq_coverage`。
2. **`src/pageindex/faq_conflicts.py` (新增)**
   - 實作 `find_similar_clinic_faqs`。
3. **`src/pageindex/faq_review.py`**
   - `list_faqs` 擴充 `topic_key` 篩選。
   - 實作 `validation_report`。
4. **`scripts/review_faq.py`**
   - 支援 `list --topic`、來源與驗證欄位顯示。
   - `show` 支援生成來源、驗證結果、相近診所 FAQ 區塊。
   - `approve` 強制檢驗 general 就醫警訊。
   - 新增 `mark-regen` 子命令。
5. **`tests/test_faq_conflicts.py` (新增)**
   - 6 個測試：覆蓋率數值基準、定義一致性、檢索正負例、CLINIC_RELATED_FLOOR 唯一來源、可見性過濾、唯讀連線。
6. **`tests/test_review_faq_cli.py`**
   - 追加 5 個測試（0 行刪除）：主題篩選、show 來源與衝突顯示、唯讀完整性 (SHA256)、approve 警訊強制、mark-regen 正常/拒絕/正式庫阻斷。
7. **`tests/test_faq_read_guard.py`**
   - 白名單註冊 `src/pageindex/faq_conflicts.py`。

---

## 驗收結果

- RED 測試驗證（Task 1 追加測試在實作前失敗 exit 1）。
- `tests/test_review_faq_cli.py` 刪除行數為 0（純追加保證向後相容）。
- `scripts/review_faq.py` 中 `UPDATE faq_cache` 字串計數為 0。
- `test_cli_prod_db_defense_and_mode_ro` 與 `test_prod_db_sha256_unmodified` 全數綠燈。
- 全量回歸測試：853 passed, 0 failed, 1 warning (22.38s)。
