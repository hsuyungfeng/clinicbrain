# Phase 48 Context: 診斷碼高頻統計、每日網路趨勢與衛教覆蓋率檢查

> 建立日期：2026-11-16
> 目標介面：「📝 待審衛教草稿簽核」（`#tab-review` / `faq_cache` `review_status='pending'`）

## 1. 核心需求與範圍
1. **診斷碼擷取與排行模組（`src/soap/icd10_stats.py`）**
   - 支援從 `soap_records`（`assessment` / `raw_text`）擷取 ICD-10-CM 診斷碼，或讀取外部同步匯入之去識別化聚合頻率資料（不依賴單一來源）。
   - 產出診所高頻診斷碼排行，並與 `nhi_catalog_1_400`（優先精確比對 `icd10`，次之比對 3 碼大類或 FTS5 trigram / LIKE 名稱關鍵字）對齊，取得標準中文疾病名稱、`topic_key`、`clinical_feature` 與 `visual_available`。
2. **每日趨勢與覆蓋率檢查模組（`src/batch/gap_checker.py`）**
   - 結合「診所高頻 ICD-10 疾病」與「每日網路最新討論醫療主題」（須遵守 `src/scraper/policy.py` 安全政策與 `to_traditional()` / `deidentify_text()` / `deep_mask_prices()` 清洗，且測試/離線模式可注入 fetcher）。
   - 針對每個目標疾病與其推演出的病人常見問題（5 大標準意圖 + 趨勢新問題），盤點 `faq_cache`（`category='general'` 且 `review_status IN ('approved', 'pending')`）與 `page_index_trees` 的覆蓋情況，產出結構化 `covered` / `partial` / `uncovered` 報表與待補題單。
   - 僅針對 `partial` 與 `uncovered` 的缺漏題目，透過唯一權威寫入路徑 `faq_writer.upsert_faqs(conn, faqs, source_type='llm_generated')` 送入「📝 待審衛教草稿簽核」待審隊列（`review_status='pending'`），並於 `metadata` JSON 標註來源（`icd10`、`trend_source`、`gap_status`）。

## 2. 強制性安全與合規不變量（Invariants）
- **Fail-Closed 審核隔離**：所有自動產出的草稿 `source_type` 一律為 `'llm_generated'`，寫入後恆為 `pending`，絕不自動核准，必須經醫師於「📝 待審衛教草稿簽核」簽核後方可對外生效。
- **單一寫入路徑**：禁止自寫 `INSERT INTO faq_cache`，必須呼叫 `src/pageindex/faq_writer.py:upsert_faqs()`。
- **零個資與零價格洩漏**：診斷碼統計僅保留聚合次數與代碼，不得保留病患姓名/身分證/電話；任何網路擷取或生成文字一律經 `deidentify_text()`、`deep_mask_prices()` 與四層合規檢查（繁體、無價格、無政治詞、無保證療效）。
- **FTS5 中文鐵則**：查詢 `faq_cache_fts` / `nhi_catalog_fts` 時，3 字以上走 `MATCH`，小於 3 字走 `LIKE ... ESCAPE '\'`（重用 `escape_like`）。
- **不污染正式庫**：所有單元與整合測試必須使用隔離連線 / 暫存複本，禁止寫入正式 `clinic.db`。

## 3. 協同測試角色
- 透過 `herdr` 指派獨立 Agent **Hermes (`wA:p3`)** 擔任 Phase 48 **Tester**，負責檢視 Plan 可行性、執行基線測試與實作完成後的獨立回歸驗收，產出 `.planning/phases/48-icd10-trend-gap-checker/48-HERMES-TESTER-REPORT.md`。
