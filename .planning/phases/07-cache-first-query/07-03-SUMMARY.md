# 07-03-SUMMARY: API 回應來源標記、二次價格遮蔽與匿名統計記錄 (CACHE-01 ~ CACHE-04)

## 執行成果摘要

本階段已完成 API 查詢層之快取短路結果整合、二次價格遮蔽與失敗隔離之匿名統計記錄：

1. **回應模型擴充 (`src/api/models/query.py`)**：
   - `QueryResponseModel` 新增向後相容欄位：
     - `source: Literal["cache", "pageindex", "llm"] = Field("pageindex", ...)`
     - `cache_answer: Optional[str] = Field(None, ...)`
   - 保持純加法設計，既有 10 個欄位完全不變。

2. **核心查詢路徑整合與價格遮蔽 (`src/api/routes/query.py`)**：
   - `_execute_query` 將 `raw_response.source` 與 `raw_response.cache_answer` 納入 `response_dict`。
   - 所有欄位（含 `cache_answer`）統一經由 `deep_mask_prices()` 進行深度遞迴遮蔽，杜絕價格外洩。
   - 三個端點（`POST /query`、`POST /clinics/{clinic_id}/query`、`GET /query`）一致輸出 `source` 與 `cache_answer`。

3. **讀寫分離架構與統計寫入取捨（D-09）**：
   - 主查詢維持使用 `Depends(get_read_db)`（`PRAGMA query_only = ON`）唯讀連線，守護底層安全性。
   - 統計寫入使用獨立短寫入連線（`sqlite3.connect(..., timeout=0.5)`），於回應資料組裝完成後同步觸發。
   - 失敗隔離：任何例外（資料庫鎖定、尚未建表等）皆在 `try/except` 中被吞除，不影響查詢回應狀態碼（維持 200）。
   - 日誌隱私：例外發生時僅記錄例外類別名稱，絕不於日誌中輸出使用者問句、`clinic_id` 或任何關鍵字。

4. **不可短路查詢排除與 hit_rate 語意（D-12）**：
   - 僅當 `raw_response.cache_eligible` 為真時記錄快取統計。
   - 含診所營運關鍵字（如營業時間、地址等）或關閉短路之查詢不計入 `miss`，避免壓低快取命中率或污染未來 BATCH-04 來源。

5. **測試配置與自動化驗收 (`tests/conftest.py`, `tests/test_api_cache_first.py`)**：
   - `conftest.py` 新增 autouse fixture `_disable_cache_stats_by_default`，既有測試預設關閉統計寫入，防範意外污染。
   - `test_api_cache_first.py`（18 個測試）：完整覆蓋端點短路、回退、價格掃描（0 價格格式命中）、對抗案例、400 阻斷、連發計數累加、全表文字掃描隱私驗證、資料庫鎖定/缺表異常隔離。

---

## ⚠️ 重要運作與部署說明

1. **正式庫尚未遷移前之行為**：
   在使用者手動對正式庫執行 `scripts/migrate_cache_stats.py` 前，正式資料庫尚未存在 `cache_stats` 表。在此狀態下：
   - API 查詢請求將正常進行並回傳 200（短路或檢索皆不受影響）。
   - 統計寫入會引發 `sqlite3.OperationalError: no such table: cache_stats`，該例外會被 `_record_cache_stats` 捕捉並在日誌記錄單次警告後安全略過。
2. **正式庫未被修改**：
   經驗證 `prod_cache_stats_tables = 0`，正式庫於本計畫執行期間保持零寫入。

---

## 驗證結果

- `tests/test_api_cache_first.py`: 18 passed
- 既有 `tests/test_api_query.py`: 零修改、全數通過
- 全量回歸測試：`276 passed, 1 warning in 8.30s`
- 正式庫未被寫入。
