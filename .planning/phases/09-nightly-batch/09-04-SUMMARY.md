# Phase 09 Plan 04 執行總結：FAQ 預生成與樹重建引擎

## 1. 執行目標達成情況
- [x] **FAQ 預生成引擎**：新增 `src/batch/faq_generator.py`，嚴格比對問句原文逐字符合種子清單；重用四層醫療法規合規檢查 (`parse_and_validate_faq`)；所有違規原因映射為安全固定代碼 (`REJECT_CODES`)，日誌與結果絕不回顯未過濾原文；已存在於 `faq_cache` 的問句自動跳過不重複呼叫 LLM；寫入一律經由 `upsert_faqs(source_type='llm_generated')`，預設為 `pending`。
- [x] **臨床推理樹重建引擎**：新增 `src/batch/tree_rebuild.py`，僅處理手動標記 (`needs_regeneration=1`) 的樹；核心保護 4 個 `*_physician_notes` 欄位（以原值覆寫並執行後置校驗與自動還原，測試對照組證明保護之必要性）；寫庫前落盤 JSON 快照；未變更內容時自動清除標記；違規輸出拒絕入庫且旗標維持 1。
- [x] **零外部連線與防禦**：測試套件全面設置 autouse fixture 封鎖 `urllib.request.urlopen`，保證 100% 採用 Mock LLM 進行測試驗證。
- [x] **單元與回歸測試**：新增 `tests/test_batch_faq_generator.py`（330 行）與 `tests/test_batch_tree_rebuild.py`（326 行），測試覆蓋率 100%。

## 2. 測試與驗證結果
- **本計畫後全量測試**：554 passed, 0 failed（自基線 492 新增 62 個測試全數通過）
- **正式資料庫校驗**：
  - SHA-256：`c51cc4d039379fe00f70d7864b29a952928233fa6caa6e72954900f4c28c65ad`（完全未受更動，零位元組變更）
- **程式碼合規檢查**：
  - `src/batch/faq_generator.py` 內無手寫 `INSERT INTO faq_cache`
  - `src/batch/tree_rebuild.py` 內無手寫 `UPDATE page_index_trees`
  - `git diff --stat src/ingestion/generate_faq.py` 為空（四層驗證器未遭修改）

## 3. 產出檔案清單
- `src/batch/faq_generator.py` (NEW)
- `src/batch/tree_rebuild.py` (NEW)
- `tests/test_batch_faq_generator.py` (NEW)
- `tests/test_batch_tree_rebuild.py` (NEW)
