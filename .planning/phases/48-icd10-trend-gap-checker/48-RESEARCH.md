# Phase 48 Research: 診斷碼高頻統計、每日網路趨勢與衛教覆蓋率檢查

> 盤點日期：2026-11-16（透過 `codebase-memory-mcp` 與 `clinic.db` 唯讀實查）

## 1. 資料庫現況 (`clinic.db`)
- `nhi_catalog_1_400`：400 筆目錄，其中 **312 筆**含有 `icd10` 欄位（例如 `J06.9` 急性上呼吸道感染、`J02.9` 急性咽喉炎、`J11.1` 流感），另有 `topic_key`、`keywords`、`clinical_feature`、`visual_available`。
- `nhi_catalog_fts`：已啟用 `tokenize='trigram'` FTS5 索引，由 `src/query/nhi_index.py:search_nhi_catalog()` 負責查詢。
- `faq_cache`：965 筆 `approved` `general` FAQ、64 筆 `approved` `special` FAQ，目前 `pending` 為 0 筆。具備 `metadata` 欄位與 `faq_cache_fts`（trigram）。
- `soap_records`：表結構已存在（含 `clinic_id`, `subjective`, `objective`, `assessment`, `plan`, `raw_text`），目前 formal DB 中為 0 筆。
- `icd10_pcs`：目前為 0 筆，不作為主要對齊來源。

## 2. 可直接重用的現有模組
1. **`src/query/nhi_index.py` (`search_nhi_catalog`)**：已完成 3+ 字 FTS5 trigram 與 `<3` 字 `LIKE ... ESCAPE '\'` 混合查詢，並解析 `alias` / `keywords` JSON。
2. **`src/query/search.py` (`escape_like`)**：Phase 47 新增之 SQL LIKE 跳脫函式。
3. **`src/batch/patient_prefill_plan.py` (`INTENT_TEMPLATES`)**：五大標準病患衛教意圖模板（`what`, `suitable`, `risk`, `recovery`, `when_to_see_doctor`），模組載入時即自我驗證繁體中文與法規合規。
4. **`src/batch/faq_generator.py` (`generate_topic_faqs`, `existing_questions`)**：支援依據主題與指定問題清單生成合規繁體中文解答，並自動去重既有問題。
5. **`src/pageindex/faq_writer.py` (`upsert_faqs`)**：唯一權威寫入路徑；當 `source_type='llm_generated'` 時強制設為 `review_status='pending'`，且 `category='general'` 允許 `clinic_id=None`。
6. **`src/scraper/policy.py`**：提供 SSRF 防護、HTTPS 443 驗證、節流與 `robots.txt` 檢查，可保護每日網路趨勢擷取器。
7. **`src/batch/runner.py` (`BatchStage`, `_BATCH_STAGES`)**：Phase 47 已管線化為階段陣列，可安全擴充非阻塞的選題/Gap Check 階段或供獨立 CLI 呼叫。

## 3. 技術設計要點
- **ICD-10 擷取與多來源支援 (`icd10_stats.py`)**：
  - 正則匹配標準 ICD-10-CM 格式（`[A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?`，如 `J06.9`、`E11.9`、`L20.9`、`K21`）。
  - 支援兩種輸入：(a) 直接掃描 `soap_records`（可選 `clinic_id` 與 `since_days`）；(b) 接收外部同步聚合清單 `[{"icd10": "J06.9", "count": 42}, ...]`（或從 `sync_logs` / JSON 匯入），確保即使 `soap_records` 為空時仍可運作。
  - 對齊策略：精確 `UPPER(icd10)` 比對 `nhi_catalog_1_400` → 前 3 碼大類前綴比對（`icd10 LIKE 'J06%'`）→ 未命中時保留原始代碼與可選中文描述，標記 `catalog_matched=False`。
- **每日趨勢與覆蓋率檢查 (`gap_checker.py`)**：
  - `TrendItem` 資料結構：`topic_name`、`icd10`（可選）、`questions`、`source_url`、`source_name`。支援注入式 `trend_fetcher`（預設可搭配 RSS/白名單公開衛教頁，測試與離線環境免連網）。
  - 覆蓋度判定（對每個主題的候選問題清單逐題比對 `faq_cache` 既有問題）：
    - `covered`：全部候選問題皆已有對應問答（精確正規化比對或高重疊率匹配）。
    - `partial`：主題已存在於 `faq_cache` 或 `page_index_trees`，但仍有部分問題尚未覆蓋。
    - `uncovered`：知識庫中完全無該主題之一般醫學問答。
  - 寫入 `faq_cache` 時，若尚未呼叫 LLM 生成解答，需注意 `faq_writer.upsert_faqs()` 要求 `answer` 非空；因此待補題單可：(1) 若有注入 `llm_call` 則即時生成合規答案；(2) 若無 `llm_call`（如純推題草稿模式），可填入標準佔位提示（如 `"待本地 LLM 自動補齊或醫師編修後發布。"`，標記 `metadata.needs_answer=true`，讓 Web 介面「🚀 一鍵背景自動補齊所有答案」或夜間 `autofill_answers` 接手補齊），維持 `upsert_faqs` 合約不變且不阻塞排程。
