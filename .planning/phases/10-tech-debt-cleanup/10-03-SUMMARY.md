# Phase 10 Plan 03 Summary: 文件對齊、全量回歸與複本驗收

## 執行成果概述
本計畫（10-03）完成 Phase 10 之收尾工作，涵蓋核心規範文件（`AGENTS.md`）對齊與端到端回歸驗證：
1. **規範文件精準對齊 (`AGENTS.md`)**：
   - **2.6 節**：診所識別解析順序更正為「Path/Body `clinic_id` > Header `X-Clinic-ID`，**無預設值**」，明確指出 `config` 已無預設診所代碼（Phase 10 移除）；special 路由未提供時由 `handle_query` 拋出 `ValueError`、API 回傳 HTTP 400；徹底刪除 Phase 5 遺留之「⚠️ 已知落差」整段歷史註記。
   - **2.10 節**：新增「遷移 DDL 單一來源（Phase 10）」條目，闡明 `scripts/migrate_faq_review_status.py` 透過 `extract_column_definition` 自 `clinic_schema.sql` 衍生 ALTER TABLE 語句，並記載單行定義與無 `--` 註解之解析約束。
   - **全專案守門檢驗**：全文完全不含 `default_clinic_id`、`DEFAULT_CLINIC_ID` 或 `CLINICBRAIN_DEFAULT_CLINIC_ID`，全專案 grep 計數為 0。
2. **正式資料庫零接觸保證**：
   - 執行當下實測 BEFORE SHA-256：`ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e`
   - 執行收尾實測 AFTER SHA-256：`ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e`
   - 比對結果：完全一致（0 位元組變更）。
3. **複本端到端遷移驗收**：
   - 使用 `sqlite3 clinic.db ".backup ..."` 複製至 scratchpad 隔離目錄產生複本。
   - 模擬舊庫（刪除 `review_status` 與 `reviewed_at`）後執行 `--dry-run`：預覽 ALTER 語句精確匹配 schema 定義，複本未被寫入。
   - 實跑遷移：新增欄位 `['review_status', 'reviewed_at']`，現有 40 筆上傳資料維持 approved。
   - 與 schema 全新庫比對：`PRAGMA table_info(faq_cache)` 兩欄之 `(type, notnull, dflt_value)` 三元組完全相同。
   - 冪等性驗證：二次執行顯示「新增欄位：無（欄位已存在）」，結束碼 0。
   - 負向防禦：無旗標對正式庫執行立即回傳結束碼 2，於連線前安全拒絕。
4. **全量測試通過**：
   - 實測 collected：589 個測試（578 既有基線 + 10-01 新增 6 個 + 10-02 新增 5 個）。
   - 實測結果：589 passed, 0 failed, 1 warning (15.20s)。

## 待使用者確認與留意事項
依 Phase 10 邊界與安全約束，以下事項本計畫未代為修改，提請使用者知悉：
1. **AGENTS.md 第 137 行 Systemd 敘述**：
   - 文件現記載「Systemd 守護單元：`clinicbrain-api.service`（相依於 `llama-server.service`，支援開機自啟與故障重啟）」。
   - 使用者先前於討論中提及「API 服務目前手動啟動、disabled、不開機自啟」之營運現況；本計畫恪守不越權修改非指定章節原則，未改動該行措辭。
2. **實機 Systemd 單元環境變數**：
   - 本計畫僅移除 repo 根目錄之 `clinicbrain-api.service` 範本中的 `Environment=CLINICBRAIN_DEFAULT_CLINIC_ID=3503190424`。
   - 使用者實機目錄 `~/.config/systemd/user/clinicbrain-api.service` 若仍保有此行，因程式碼已完全不再讀取該環境變數，該設定已無任何作用；使用者若欲保持乾淨可自行手動移除。
3. **查詢路由層零改動**：
   - `src/api/routes/query.py`、`src/query/router.py`、`src/query/faq_shortcut.py`、`src/api/dependencies.py` 均維持 0 行變更，後續診所資料優先與查詢重構將依路線圖於 Phase 11 展開。
