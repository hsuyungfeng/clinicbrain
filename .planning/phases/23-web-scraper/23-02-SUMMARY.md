# Plan 23-02 總結：HTML 結構化抽取與 FAQ 草稿建構寫入

## 執行成果

- **完成日期**：2026-10-14
- **成果狀態**：全部測試通過（22/22 passed，全 scraper 測試 50/50 passed），零外部依賴、純標準庫 `html.parser` 實作，合規與醫療防線完全到位。
- **Commit**：`feat(scraper): 實作 HTML 結構化抽取與 FAQ 草稿建構寫入 (Plan 23-02)`

## 產出檔案

1. `tests/fixtures/scraper/clinic_sample_a.html`：合成測試頁面（虛構診所機構、代表電話、營業時間、服務項目、內嵌價格與醫師私人手機 09xx、信箱及 LINE ID）。
2. `tests/fixtures/scraper/clinic_missing_fields.html`：缺少 services 服務區塊之結構漂移頁面。
3. `src/scraper/extract.py`：
   - `SCHEMA_VERSION = "1"` 與 `@dataclass ExtractedClinicPage`。
   - `extract_clinic_page`：使用標準庫 `html.parser.HTMLParser`，排除 script/style 內容，解析機構名稱、地址、電話、營業時間、服務與醫師專長。
   - 價格清洗防禦：在抽取層若偵測到價格模式（`NT$`、`$`、`元`、千分位數字），立即清空描述並標記為無效，絕不以遮蔽字串充當資料。
   - 個資排除防禦：醫師私人 09 開頭手機、電子信箱、LINE ID 一律在抽取層徹底過濾。
   - 結構漂移偵測：缺必填欄位時自動設定 `schema_drift=True` 並列入 `drift_fields`。
4. `src/scraper/drafts.py`：
   - `GUARANTEE_PHRASES`：鏡像自 `src/api/routes/sync.py` 之 13 項保證療效禁詞。
   - `build_faq_drafts`：
     - 正體中文轉換（`to_traditional`）。
     - 去識別化（`deidentify_text`）與價格遮蔽（`deep_mask_prices`）。
     - 前置保證療效禁詞檢查（原因碼 `guarantee_phrase`，獨立於後續驗證）。
     - 身分洩漏檢查（原因碼 `identity_leak`，問句與答案嚴禁包含機構名稱、地址、電話、醫師姓名）。
     - 醫療常規驗證（`validate_single_faq(check_dosage=True, require_doctor_warning=False)`）。
     - 安全 slug 與 `topic_key`（`web-` 開頭）。
     - 機構層級 `metadata`（包含 `origin='web_scrape'`, `source_url`, `fetched_at`, `extracted`；**嚴格排除醫師資料**）。
5. `src/scraper/drafts.py:write_faq_drafts` 與 `src/pageindex/faq_writer.py`：
   - 唯一權威寫入路徑：透過 `upsert_faqs(..., source_type='web_upload', commit=False)` 增量寫入。
   - 支援呼叫端控制交易邊界（`commit=False`），不自動 commit。
   - Fail-Closed 檢驗：檢查 `has_metadata_column`、`has_review_status`，並確認 `clinic_id` 存在於 `clinic_info`。
6. `tests/test_scraper_extract.py`：8 項結構化抽取與漂移偵測單元測試。
7. `tests/test_scraper_drafts.py`：14 項草稿建置、合規檢驗與唯一寫入路徑單元測試。

## 驗證指標

- `python3 -m pytest tests/test_scraper_drafts.py tests/test_scraper_extract.py -x -q`：22 passed in 0.57s。
- `grep -rn "clinic_upload\|INSERT OR REPLACE" src/scraper/ | wc -l`：結果為 0。
- 全套 scraper 測試 `python3 -m pytest tests/test_scraper_*.py`：50 passed in 0.61s。
- 正式庫 `clinic.db`：SHA-256 維持 `0089ca28795fd0f0f2a41e9fa6b16f840ae794bfaf4e5597576410e9f0cf23db`，零變更零污染。
