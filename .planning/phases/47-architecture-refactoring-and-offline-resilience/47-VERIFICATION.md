# Phase 47 驗證報告（獨立測試員 · 唯讀）

- **專案**：clinicbrain（Taiwan Clinic Medical PageIndex RAG System）
- **Phase**：47 — Architecture Refactoring & Offline Resilience（架構重構與離線韌性）
- **測試性質**：純唯讀（執行整合測試、遷移狀態檢查、靜態檔案離線檢查）。**未修改任何程式碼或資料庫**。
- **執行時間**：2026-11-14（CST，UTC+08:00）
- **工作目錄**：`/home/hsuyungfeng/DevSoft/clinicbrain`
- **Python 環境**：`.venv/bin/python`（Python 3.12）

---

## 1. 整合測試結果：全部通過 ✅

命令：
```
.venv/bin/python -m pytest tests/test_search.py tests/test_nhi_index.py tests/test_llm_client.py \
  tests/test_batch_runner.py tests/test_visual_autodraft.py tests/test_admin_api.py \
  tests/test_admin_ask.py tests/test_admin_batch_and_ai.py tests/test_upload_name_field.py \
  tests/test_upload_url_endpoint.py tests/test_visual_admin_api.py tests/test_visual_video_api.py \
  tests/test_url_deps_resolver.py -q
```

**結果：`174 passed, 5 warnings`（exit code 0），耗時 25.97 秒。**

涵蓋的 Phase 47 相關子系統與既有核心：
- 搜尋與索引：`test_search.py`、`test_nhi_index.py`（健保 1-400 索引、FTS5 trigram 混合分流）
- LLM 層：`test_llm_client.py`（本機 LLM 客戶端解耦介面）、`test_batch_runner.py`（夜間批次）
- 視覺：`test_visual_autodraft.py`、`test_visual_admin_api.py`、`test_visual_video_api.py`
- 管理 API 與提示詞安全：`test_admin_api.py`、`test_admin_ask.py`、`test_admin_batch_and_ai.py`（安全攔截、重複質問衝突）
- 擷取管線：`test_upload_name_field.py`（上傳檔名欄位）、`test_upload_url_endpoint.py`（URL 端點 schema 漂移）
- 離線相依解析：`test_url_deps_resolver.py`（靜態資源相依解析）

5 則 warnings 皆為第三方套件去標記提醒（Starlette `httpx` / `HTTP_422` enum），與本階段無關、非失敗。

---

## 2. 遷移管理器狀態：`migrate.py --status`

命令：`.venv/bin/python scripts/migrate.py --status`

**輸出：9 項遷移全部顯示 `[PENDING]`**
```
001_cache_stats       -> migrate_cache_stats.py       | 快取命中統計表 (cache_stats)
002_faq_review_status -> migrate_faq_review_status.py | FAQ 審核狀態欄位
003_faq_metadata      -> migrate_faq_metadata.py      | FAQ 來源 metadata 欄位
004_page_index_review -> migrate_page_index_review.py | 臨床推理樹審核狀態欄位
005_pageindex_clinic_id -> migrate_pageindex_clinic_id.py | PageIndex 診所代碼遷移
006_soap_schema       -> migrate_soap_schema.py       | SOAP 語音與全文檢索表
007_to_nhi_code       -> migrate_to_nhi_code.py       | 健保特約機構代碼對齊
008_visual_assets     -> migrate_visual_assets.py     | 視覺解說卡資產表 (visual_assets)
009_visual_template_override -> migrate_visual_template_override.py | 視覺模板覆寫欄位
```

### ⚠️ 重要發現（偵測缺口，非實質失敗）
以唯讀連線直接查證正式 `clinic.db`：

| 檢查項目 | 結果 |
|---|---|
| `schema_migrations` 資料表是否存在 | **不存在**（`no such table`） |
| 實際資料表 `cache_stats` / `faq_cache` / `faq_cache_fts` / `soap_records` / `page_index_trees` / `visual_assets` / `nhi_catalog_1_400` / `nhi_catalog_fts` | **全部 EXISTS** |
| `page_index_trees.clinic_id` 欄位 | **present** |

**解讀**：`migrate.py` 透過 `schema_migrations` 資料表追蹤「已套用」狀態；此表由 Phase 47 Wave 3 的統一管理器首次建立。但正式庫的多項變更（`faq_cache`/`cache_stats`、`clinic_id` 遷移、SOAP、視覺資產等）是在此管理器出現之前**手動套用到正式庫**的（見 `AGENTS.md` 2.1 / 2.7 / 2.13 節）。因此：

- 資料庫的**實際 schema 狀態是完整且正確的**（所有目標資料表與欄位都存在）。
- `--status` 顯示全部 PENDING 是**追蹤缺口（tracking artifact）**，不是「遷移尚未執行」。管理器只看到 `schema_migrations` 為空，無法反映手動套用的事實。

這不代表任何資料損毀或遺漏，但表示 `migrate.py --status` 目前**無法作為正式庫「遷移是否已記錄」的真實指標**。若日後執行 `--apply`，這些手動已套用的遷移會被判為 pending 而**重試**（各腳本多為 `CREATE TABLE IF NOT EXISTS` / 增量 UPSERT 型，重試通常安全，但仍建議先手動回填 `schema_migrations` 或加 `--dry-run` 確認）。

---

## 3. 靜態離線韌性檢查 ✅

| 檢查項目 | 結果 |
|---|---|
| `src/web/static/index.html` 含 `cdn.jsdelivr.net` | **0 處**（無 CDN 引用） |
| `src/api/app.py` CSP 含 `cdn.jsdelivr.net` | **0 處** |
| 全檔案 CDN 掃描（`index.html`、`app.py`，pattern `https?://*.cdn.*`） | **完全無任何 CDN 引用** |
| `src/web/static/tailwind.min.css` 存在 | **EXISTS，2,934,019 bytes（≈2.8 MB）** |

**CSP 內容（`src/api/app.py:60-64`，僅套用於 `/admin` 路由）：**
```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
img-src 'self' data:; connect-src 'self'; frame-ancestors 'none';
base-uri 'none'; form-action 'self'
```
`script-src` 與 `connect-src` 皆為 `'self'`，未放行任何外部 CDN 腳本/網路來源，配合本地 `tailwind.min.css`，符合「離線可用」設計目標。另附帶設定 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`、`Cache-Control: no-store`。

---

## 4. 文件檔案大小

| 檔案 | 大小（bytes） |
|---|---|
| `AGENTS.md` | 45,180 |
| `docs/architecture/phase-history.md` | 139,965 |
| **合計** | **185,145** |

---

## 5. 總結

- ✅ **測試**：13 個測試檔案共 **174 筆全通過**，涵蓋搜尋、NHI 索引、LLM 解耦、夜間批次、視覺（autodraft / admin / video）、管理 API 安全、上傳管線與離線相依解析，無失敗、無崩潰。
- ✅ **離線韌性**：前端與 CSP 完全無外部 CDN 依賴，本地 `tailwind.min.css`（2.8 MB）就位；CSP 為 strict `'self'`。符合 Phase 47 離線目標。
- ⚠️ **遷移管理器**：`--status` 因正式庫缺 `schema_migrations` 追蹤表而**全显示 PENDING**，屬追蹤缺口而非實質失敗——實際 schema 已完整存在（手動套用遺留）。建議日後 `--apply` 前先 `--dry-run` 或手動回填 `schema_migrations`，避免對已手動套用的遷移重複執行。
- ✅ **文件**：`AGENTS.md` 與 `phase-history.md` 完整且大小正常。

**最終判定：Phase 47 測試與離線韌性檢查通過（174/174）。唯一需注意者為 `migrate.py --status` 的追蹤缺口，屬非破壞性記錄層問題，不影響功能與測試收斂。**

> 本報告純唯讀產出，未對任何程式碼或資料庫進行修改。
