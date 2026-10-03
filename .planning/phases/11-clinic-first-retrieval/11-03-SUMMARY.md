# Phase 11 Plan 03 Summary: API 層加 data_level 欄位與端對端回歸驗證

## 執行成果概述
本計畫（11-03）完成 API 層資料層級（`data_level`）傳遞與結構宣告，並以端對端測試鎖定向後相容性、快取統計語意與一般民眾匿名端點之隔離：
1. **RED 階段驗證**：
   - 建立 `tests/test_api_clinic_first.py`，模型未加入欄位前執行 `pytest -q -x` 如預期在 `test_a1_backward_compatibility` 失敗（`AttributeError`），pytest 結束碼恰為 1。
2. **GREEN 階段實作**：
   - **`src/api/models/query.py`（純加法）**：
     - `SearchHitModel`：新增 `data_level: Optional[Literal["clinic", "general"]] = Field(None, ...)`，僅對 `faq_hits` 填值。
     - `QueryResponseModel`：新增 `data_level: Optional[Literal["clinic", "general"]] = Field(None, ...)`，說明 'clinic' 表示答案來自該診所自身資料，'general' 表示來自已審核之一般衛教內容，null 表示無 FAQ 命中；非短路時表示首筆 FAQ 之層級。
     - 兩者均具預設值 `None`，不破壞既有客戶端結構反序列化。
   - **`src/api/routes/query.py`**：
     - 自 `src.query.router` 匯入 `faq_hit_level`（雙路徑匯入均支援）。
     - `_execute_query` 在 `response_dict` 注入 `data_level = raw_response.data_level`。
     - 格式化 `faq_hits` 時，為每筆命中物件追加 `'data_level': faq_hit_level(h)`。
     - 既有 `_record_cache_stats`、`cache_eligible` 邏輯、`deep_mask_prices` 與 400 錯誤轉換完全不變。
   - **一般民眾匿名端點完全隔離**：
     - `src/general`、`src/api/routes/general.py` 與 `src/api/models/general.py` 維持 0 行修改（`git diff` 為空）。
     - 即使問句吻合診所 FAQ 且夾帶 `clinic_id` / `X-Clinic-ID`，匿名端點保證不出現診所答案、不含 `data_level` 鍵。
3. **API 邊界行為鎖定**：
   - 三大入口（POST `/api/v1/query`、POST `/api/v1/clinics/{id}/query`、GET `/api/v1/query`）在診所 FAQ 命中時皆一致標示 `data_level=='clinic'`。
   - 退回 general 時標示 `data_level=='general'`。
   - 無診所代碼查詢時，`data_level` 保證僅能為 `'general'` 或 `None`。
   - 空白診所代碼路徑參數（`POST /api/v1/clinics/%20/query`）在營運問句下回傳 HTTP 400（由 router 入口正規化攔截）。

## 測試覆蓋與驗證
- `tests/test_api_clinic_first.py`：共 15 個端對端測試全數 PASS：
  - A1: 向後相容（required 不含 data_level，舊 dict 相容）。
  - A2: POST /api/v1/query 診所 FAQ 短路帶 clinic 層級。
  - A3: 退回 general FAQ 帶 general 層級。
  - A4: 三個 API 查詢入口一致性。
  - A5: 無 clinic_id 查詢安全限制。
  - A6: 非短路時的層級標示（各 hit 與整體）。
  - A7: 價格二次遮蔽安全保證。
  - A8: 匿名快取統計語意與隱私保證。
  - A9: 匿名一般諮詢端點隔離保證。
  - A10: OpenAPI Schema 宣告含 data_level。
  - A11: Blocker 回歸鎖定（API 層）。
  - A12: 決策 1 外洩修復（API 層）。
  - A13: 決策 2 special 路由退 general（API 層）。
  - A14: 統計語意註記（general 命中計入 hit）。
  - A15: 空白路徑參數行為（W4 回傳 400）。
- 組合驗證指令（包含 7 個測試檔共 86 個測試）全綠，一般諮詢模組與 4 個既有 API 測試檔零變動。
- 正式庫 `clinic.db` SHA-256 驗證完全不變。
