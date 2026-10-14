# Plan 24-02 總結：網址解析端點 POST /api/v1/admin/upload-url 與 Phase 23 適配器

## 執行成果

- **完成日期**：2026-10-14
- **成果狀態**：全部測試通過（82/82 passed：url_guard 23 項、upload_url_endpoint 31 項、upload_name_field 16 項、admin_api 12 項），零外部依賴、純標準庫，嚴格符合正體中文規範與雙層 SSRF 防禦。
- **Commit**：
  - `228ab80`：`feat(ingestion): 實作 SSRF 前置安全檢查 validate_public_url (Plan 24-02 Task 1)`
  - `f75bb21`：`feat(admin): 實作網址解析端點 POST /api/v1/admin/upload-url 與 Phase 23 適配器 (Plan 24-02)`

## 產出與變更檔案

1. `src/ingestion/url_guard.py`：
   - 實作前置 SSRF 防禦第一層 `validate_public_url(url, *, resolver)`。
   - 嚴格限制：僅允許 `https` 協議、連接埠僅允許 443（未指定視為 443）、禁止 userinfo、長度上限 2048。
   - IP 位址判定完全委派 Phase 23 `resolve_public_addresses`（單一來源，排除 CGNAT、私有、迴圈、IPv4-mapped）。
   - 違規時拋出 `UnsafeUrlError`，錯誤訊息為固定字串，不包含任何 URL、主機名或 IP。
   - 零日誌、零 print。
2. `src/pageindex/web_source_adapter.py`：
   - 實作 Phase 23 介面適配器，解耦 API 端點與底層抓取邏輯。
   - 行程內單例 `DomainThrottle`（預設 5.0 秒）與 `RobotsPolicy`。
   - 實作 `build_service_text(page)`：首段為營業時間（若非空），其餘每段為服務項目名稱與描述；**機構名稱、地址、電話、醫師資訊嚴禁進入文字管線**。
   - 實作 `optional_missing_fields(page)`：回傳固定順序 `address`、`phone`、`business_hours`、`doctors` 之缺失鍵清單。
3. `src/api/routes/admin.py`：
   - 新增唯一的依賴注入點 `get_url_fetch_deps() -> UrlFetchDeps`（載入 `data/scraper/sources.json`，不讀取任何環境變數）。
   - 新增 `_URL_FETCH_LOCK = threading.Lock()` 防止併發抓取過載（忙碌時非阻塞回傳 429）。
   - 新增端點 `POST /api/v1/admin/upload-url`（同步 `def`）：
     - 診所存在性檢查（不存在回 404）。
     - 目標檢查（非 "faq" 回 400）。
     - 名稱必填與驗證（`validate_display_name` 違規回 400）。
     - 提早檢查 metadata 欄位（未遷移回 503，在 fetch 前中斷）。
     - SSRF 前置檢查（違規回 400）。
     - 抓取並結構化抽取（錯誤映射：白名單/私網/協議違規回 400，robots 拒絕回 403，改版回 422，網路/未知回 502）。
     - 縱深防禦：身分資訊比對，若機構名稱/地址/電話字串進入 Q&A 則剔除該 FAQ。
     - 溯源 metadata 產生：含 `origin="web_scrape"`、去除 query 的 `source_url`、`fetched_at`、`schema_version`、四鍵 `extracted`（電話經 deidentify 遮蔽，不持久化任何 doctors 資訊）。
     - 預覽模式不寫庫；寫入模式以 `source_type="web_upload"` 寫入審核佇列（`review_status="pending"`）。
4. `src/soap/deid.py`：
   - 擴充 `_LANDLINE_PATTERN`，支援 `02-2500-1234` 這類包含中間短橫線之標準台灣市話格式自動遮蔽。
5. `tests/test_url_guard.py`：
   - 23 項 SSRF 前置防禦單元測試。
6. `tests/test_upload_url_endpoint.py`：
   - 31 項端點整合、依賴注入、預覽/寫入、日誌隱私、Phase 23 契約測試（涵蓋 pinned_addresses、白名單與重導向防禦）。

## 契約檢查與依賴規格清單

1. **Phase 23 簽章與 Task 2 a contract 檢查**：
   - `fetch_page` 具備 `pinned_addresses`、`http_get`、`resolver` 參數，且無 `opener` 參數。檢查完全通過。
2. **CR-23-1..4 採納狀態**：
   - CR-23-1（pinned_addresses）：已採納並在 `fetch_clinic_page` 傳入，端點通過 `test_contract_pinned_addresses_connects_only_to_pinned` 測試。
   - CR-23-2（localhost 測試旗標）：未採納，不允許任何 localhost 例外。
   - CR-23-3（is_public_address 單一來源）：已採納，位址判定完全委派 Phase 23 `resolve_public_addresses`。
   - CR-23-4（port 80 允許）：未採納，僅允許 443。
3. **資料型別與欄位清單**：
   - `ValidatedUrl`：`url: str`（去 fragment 保留 query）、`host: str`、`port: int`（443）、`addresses: tuple[str, ...]`。
   - `UrlFetchDeps`：`allowlist: dict`、`throttle: DomainThrottle`、`robots: RobotsPolicy`、`user_agent: str`、`resolver: Any`、`http_get: Optional[Callable]`。
   - `UrlPageResult`：`page: ExtractedClinicPage`、`source_url: str`（原始 URL strip query）、`fetched_at: str`。
   - `UrlFetchError`：`reason: str`（無任何額外例外訊息字串）。
4. **相對 D-07 / D-09 的偏離確認**：
   - metadata origin 固定為 `web_scrape`。
   - metadata extracted 恰含四鍵：`institution_name`、`address`、`phone`、`business_hours`。
   - 醫師資訊（`doctors`）嚴禁寫入任何持久化欄位或 metadata。
   - 適配器直接使用 Phase 23 的 `ExtractedClinicPage`，不額外宣告重疊型別。
5. **DNS Rebinding 實際防線狀態**：
   - 經由 CR-23-1 之 `pinned_addresses`，前置檢查通過之 IP 位址被直接釘住並傳遞至底層連線，杜絕 DNS Rebinding 威脅。

## 驗證指標

- `python3 -m pytest tests/test_url_guard.py tests/test_upload_url_endpoint.py tests/test_upload_name_field.py tests/test_admin_api.py -q`：82 passed in 3.01s。
- 安全指令檢查：`grep -rn "urlopen\|build_opener\|requests\|httpx\|CLINICBRAIN_SCRAPER_CONTACT\|CLINICBRAIN_URL_ALLOW_LOCALHOST\|get_url_resolver" ...` 命中數為 0。
- 正式庫 `clinic.db`：SHA-256 維持 `0089ca28795fd0f0f2a41e9fa6b16f840ae794bfaf4e5597576410e9f0cf23db`，零變更零污染。
