# Phase 14: 臨床語音與 SOAP 紀錄擷取 - Context

**Gathered:** 2026-10-06
**Status:** Ready for planning

<domain>
## Phase Boundary

本階段交付由外部系統（包含 `https://doctor-toolbox.com/`）經由官方 RESTful API 推播接收臨床文字紀錄，在本地 SQLite 資料庫（`clinic.db`）建立專屬 SOAP 資料結構（`soap_records` 與 FTS5 虛擬表 `soap_records_fts`），並提供專供院所內部醫師安全檢索病歷歷史案例的查詢介面。

本階段核心範疇：
- SOAP 資料表與 FTS5 全文檢索結構設計（支援 S/O/A/P 四段劃分、外部 ID、去識別化病患代號、處置/診斷標籤）。
- API 接收端點（`POST /api/v1/soap/records`）與彈性輸入格式處理（支援直接傳入已拆分 S/O/A/P 或純文本自動結構化剖析）。
- 嚴格醫療法規與隱私守衛：入庫前全面執行 `deep_mask_prices()` 價格清洗、病患敏感個資去識別化（以 `patient_token` 取代明文身分證字號與姓名）。
- 專屬醫師查詢介面與權限隔離（僅供管理員金鑰與同診所隔離查詢，完全杜絕公開自然語言端點非授權存取）。

</domain>

<decisions>
## Implementation Decisions

### SOAP 資料庫結構與儲存設計 (Schema)
- **D-01 (唯一識別與防重):** 支援外部 ID（`external_id`，由 doctor-toolbox.com 產生）與去識別化病患代號（`patient_token`）；設定 `UNIQUE(clinic_id, external_id)` 約束，支援基於 `external_id` 的冪等 UPSERT 與增量更新。
- **D-02 (欄位劃分與原始文本):** 資料表包含 `id`, `clinic_id`, `external_id`, `patient_token`, `subjective`, `objective`, `assessment`, `plan`, `raw_text`, `tags`, `created_at`, `updated_at`；強制保留原始推播字串 `raw_text` 以供臨床稽核校對，並保留 `tags` 儲存處置、科別或 ICD-10 診斷標籤。
- **D-03 (全文檢索 FTS5):** 建立專屬虛擬表 `soap_records_fts`，嚴格指定 `tokenize='trigram'`（遵循專案中文檢索鐵則），同步索引 S/O/A/P 與 tags，支援醫師進行繁體中文臨床症狀與處置檢索。

### API 接收端點與格式剖析 (Ingestion)
- **D-04 (API 端點與權限):** 提供 `POST /api/v1/soap/records` 端點；強制需 `X-API-Key`（管理員金鑰）與有效 `clinic_id` 綁定驗證，寫入連線採用 `get_write_db`。
- **D-05 (彈性輸入支援):** Request Payload 支援彈性結構：若已包含 `subjective`, `objective`, `assessment`, `plan` 則直接清洗入庫；若僅提供 `raw_text` 或 `transcript`，則由後端以規則/標籤關鍵字（S/O/A/P 前綴）自動切分四段內容入庫。

### 醫療法規與隱私守衛 (Compliance & Privacy)
- **D-06 (價格自動清洗):** 所有寫入 SOAP 內容在入庫前全面經由 `deep_mask_prices()` 遞迴字串清洗，將具體金額數字遮蔽為 `[請致電診所確認]`，防範未經核定之價格寫入資料庫。
- **D-07 (病患個資去識別化):** 原始身分證字號、真實姓名、聯絡電話、病歷號禁止以明文存入資料庫；一律以去識別化之雜湊代號 `patient_token` 儲存，日誌嚴格禁止記錄敏感個資。

### 知識庫整合與權限邊界 (Integration Boundary)
- **D-08 (內部醫師專用查詢):** 提供專用查詢端點（如 `GET /api/v1/soap/records` 與 `POST /api/v1/soap/search`），僅限帶管理者金鑰之同診所人員查詢；公開大眾端點（`/api/v1/query`、`/api/v1/general/query`）嚴格隔離，絕不直接讀取 `soap_records`。
- **D-09 (階段聚焦與知識沉澱後續路線):** Phase 14 聚焦於「安全接收、結構化儲存、FTS5 內部檢索」；大眾查詢引用去識別化 Assessment 衛教建議或由 LLM 將 SOAP Plan 轉化為 PageIndex 推理樹/FAQ 之功能，列為後續階段演進目標。

### the agent's Discretion
- 本地文本切分器（Text Chunking / Section Parser）若遇到無標籤純文本，預設以換行與標準臨床段落符號（如「S:」「O:」「診斷:」「處置:」）優先切分，無法識別部分歸入 `subjective`。
- 遷移腳本沿用 Phase 10 單一來源規範，於 `src/db/clinic_schema.sql` 定義表結構並透過遷移工具套用。

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 系統規範與資料架構
- `AGENTS.md` §2.1 — 資料庫架構與唯讀/寫入連線分離原則
- `AGENTS.md` §2.3 — FTS5 全文檢索 trigram 中文分詞鐵則（所有虛擬表必須指定 `tokenize='trigram'`）
- `AGENTS.md` §2.5 — 官方雙向資料同步契約與醫療法規合規防禦（價格清洗、禁詞過濾）
- `AGENTS.md` §2.7 — API 認證強制化（`verify_admin_key`、`X-API-Key` 驗證）
- `AGENTS.md` §3 — 嚴格安全與合規規則（價格屏蔽、繁體中文專用）

### 既有同步與 API 實作
- `src/api/routes/sync.py` — doctor-toolbox.com 雙向同步既有路由、`deep_mask_prices()` 調用方式
- `src/api/dependencies.py` — `get_write_db`、`get_read_db`、`verify_admin_key`
- `src/db/clinic_schema.sql` — 資料庫 DDL 唯一權威來源

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/api/dependencies.py:get_write_db`: 寫入連線注入點，支援交易與外鍵檢查。
- `src/api/dependencies.py:verify_admin_key`: 管理者 API 金鑰防護相依項，防止非授權推播。
- `src/api/routes/query.py:deep_mask_prices`: 遞迴價格清洗工具，保證入庫資料零價格洩漏。
- `src/ingestion/convert_chinese.py:to_traditional`: 繁體中文正規化工具。

### Established Patterns
- 單一權威寫入函式：`upsert_trees`、`upsert_faqs`、`upsert_clinic_note` 皆集中於專屬 writer 模組；SOAP 寫入應遵循此模式建立 `src/soap/soap_writer.py:upsert_soap_records`。
- FTS5 trigram 建立範本：參照 `src/db/clinic_schema.sql` 之 `page_index_fts` 與 `faq_cache_fts`，觸發器自動維護同步。
- 測試複本防護慣例：測試全程使用暫存資料庫複本或 memory DB，正式 `clinic.db` 全程保持 SHA-256 不變。

### Integration Points
- `src/db/clinic_schema.sql`: 新增 `soap_records`、`soap_records_fts` 與觸發器。
- `src/api/app.py`: 掛載新路由 `src/api/routes/soap.py`（前綴 `/api/v1/soap`）。
- `scripts/`: 提供資料庫遷移腳本 `scripts/migrate_soap_schema.py`。

</code_context>

<specifics>
## Specific Ideas

- 使用者明確指示：來源為 `https://doctor-toolbox.com/` 推播之臨床文字（POST），需支援彈性 JSON 與純文字自動切分。
- 使用者偏好：大眾查詢未來可匿名引用去識別化之 Assessment，但 Phase 14 務必先以內部安全儲存與專屬檢索為先，待機制穩健後再開放外網引用。

</specifics>

<deferred>
## Deferred Ideas

- **大眾查詢引用 Assessment:** 於大眾端點（`/api/v1/query`）檢索命中時，引用去識別化 Assessment 衛教段落之功能（留待 Phase 15 或後續階段，需搭配醫師審核閘門）。
- **SOAP 自動轉化為 PageIndex 推理樹 / FAQ:** 由背景本地 LLM 將歷史 SOAP 案例提煉為診所知識庫之工作流程（留待後續階段）。
- **音訊原始檔 (Audio/WAV) 直傳與 Whisper 本地轉錄:** 目前確定由 doctor-toolbox.com 端完成語音轉文字後 POST 文本至 API，clinicbrain 本機不需額外引入 Whisper 音訊解碼依賴。

</deferred>

---

*Phase: 14-soap*
*Context gathered: 2026-10-06 via discuss-phase*
