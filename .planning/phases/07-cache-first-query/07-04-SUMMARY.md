# Phase 07-04 總結報告：快取統計端點、安全防禦與專案規範文件化

## 執行概述

本任務為 Phase 07（快取優先查詢與匿名統計）之最終收尾計畫（Wave 3）。完成了管理端點 `GET /api/v1/cache/stats`、Pydantic 回應模型、API 認證與狀態防禦、`AGENTS.md` 規範文件化（新增 2.8 節與目錄結構更新），並完成全量回歸與零污染驗證。

---

## 交付成果清單

### 1. 核心實作
- **Pydantic 模型 (`src/api/models/cache_stats.py`)**：
  - `MissKeywordCount`：未命中關鍵字次數結構（`keyword: str`, `count: int`）。
  - `CacheStatsResponse`：統計回應結構（包含 `clinic_id`, `cache_hits`, `cache_misses`, `hit_rate`, `top_miss_keywords`, `since_date`）。
- **統計端點路由 (`src/api/routes/cache_stats.py`)**：
  - `GET /api/v1/cache/stats`：
    - 掛載 Phase 06 `verify_admin_key` 依賴項（未提供金鑰或未開啟開發模式回傳 401/503）。
    - 支援可選查詢參數 `clinic_id` 與 `since`（格式 `YYYY-MM-DD`，含嚴格正則驗證，防範 SQL injection）。
    - 防禦性處理兩種 503 情境：
      1. `cache_stats` 表尚未建立（`sqlite_master` 檢查）：回傳繁體中文指引「快取統計資料表尚未建立，請先執行遷移腳本」。
      2. 資料庫鎖定或暫態異常（`OperationalError`）：回傳「快取統計資料暫時無法讀取，請稍後重試」。
    - 使用唯讀資料庫連線（`get_read_db`），防止任何寫入或竄改風險。
- **FastAPI 主應用程式 (`src/api/app.py`)**：
  - 掛載 `cache_stats_router`，路徑前綴 `/api/v1`，標籤 `["cache"]`。
- **專案規範文件 (`AGENTS.md`)**：
  - 第 2.1 節補入 `cache_stats` 表說明。
  - 新增第 2.8 節《快取優先查詢與匿名命中統計（Phase 07 新增）》：詳細記載保守短路規則、五維風險特徵、匿名統計表結構、`hit_rate` 語意與灌數限制、D-09 異步寫入連線取捨、手動遷移指引與約 60% 命中率等已知限制。
  - 第 4 節目錄結構補入所有 Phase 07 新增檔案。

### 2. 測試套件
- **端點整合測試 (`tests/test_api_cache_stats.py`)**：共 12 個測試案例全數通過：
  - `test_cache_stats_endpoint_requires_admin_key`：未帶金鑰 401 驗證。
  - `test_cache_stats_endpoint_success_with_key`：有效金鑰正常查詢。
  - `test_cache_stats_endpoint_dev_mode`：本機開發模式（`allow_no_auth`）放行。
  - `test_cache_stats_table_missing_returns_503`：未建表時回傳 503 與明確中文訊息。
  - `test_cache_stats_db_locked_returns_503`：資料庫鎖定時回傳 503。
  - `test_cache_stats_invalid_since_format_rejected`：無效日期格式 422 攔截。
  - `test_cache_stats_hit_rate_calculation`：命中率除法與營運/錯誤排除計算驗證。
  - `test_cache_stats_top_miss_keywords_whitelist_only`：回傳關鍵字嚴格限定於白名單。
  - `test_cache_stats_response_fields_strict_privacy`：隱私性驗證（回傳字典鍵嚴格比對，絕無 query 或 PII 欄位）。
  - `test_cache_stats_method_not_allowed`：POST/PUT/DELETE 回傳 405 Method Not Allowed。
  - `test_cache_stats_clinic_filter`：多診所代碼過濾驗證。
  - `test_cache_stats_zero_total_queries`：無查詢資料時 hit_rate=0.0 驗證。

---

## 重要設計決策與指標語意

1. **`hit_rate` 統計語意**：
   $$\text{hit\_rate} = \frac{\text{cache\_hits}}{\text{cache\_hits} + \text{cache\_misses}}$$
   - 營運問句（`bypass`）與錯誤（`error`）不計入分母，專注衡量醫療問答之快取覆蓋效能。
   - 總數為 0 時回傳 `0.0`。
2. **灌數風險處理（Acceptance）**：
   - 自然語言查詢端點維持公開開放，惡意使用者可透過大量查詢刷低或刷高命中率。
   - 本設計將此風險視為「接受（Accept）」，統計數據僅供診所營運熱度評估與 FAQ 擴充方向參考，嚴禁作為計費、授權或醫療決策依據。
3. **已知短路命中率限制（約 60%）**：
   - 正式庫 40 筆真實 FAQ 中，有 16 筆問句因不含療程路由關鍵字，在第一階段被 `classify` 分流為 `general`；而 `general` 路由不檢索 `special` FAQ，導致短路命中率上限約為 60%（24/40）。
   - 其餘問句會正常走原本 pageindex 推理樹回應，不影響病患諮詢體驗。本階段依計畫不改動路由分流與分類器。

---

## 驗收檢查清單

- [x] `AGENTS.md` 包含 `### 2.8`、`faq_shortcut.py`、`migrate_cache_stats.py`、`約 60%`
- [x] 全量測試：288 passed, 0 failed（新增 116 個 Phase 07 測試）
- [x] 既有測試保護：`tests/test_api_query.py` 與 `tests/test_router.py` 未被修改（`git diff --stat` 輸出為空）
- [x] 無禁止指令：`grep -rn "systemctl --user enable"` 無任何命中
- [x] 正式資料庫零污染：`clinic.db` 為 gitignored，且正式庫 `cache_stats` 表數為 0

---

## 正式環境套用指引（需手動執行）

程式碼執行期間**未對正式 `clinic.db` 做任何變更**。在正式環境啟用快取統計功能前，請依序執行以下步驟：

```bash
# 1. 備份正式資料庫
cp clinic.db clinic.db.bak-$(date +%Y%m%d)

# 2. 執行冪等遷移腳本
python3 scripts/migrate_cache_stats.py --confirm-prod-backup
```

遷移完成後：
- 自然語言查詢端點若設定 `cache_stats_enabled=True`，將自動記錄匿名統計。
- 管理員端點 `GET /api/v1/cache/stats` 即可正常回傳聚合統計數據。
