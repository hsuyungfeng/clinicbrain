# Phase 10 Plan 01 Summary: 遷移腳本 DDL 單一來源（DEBT-01）

## 執行成果概述
本計畫（10-01）消除了 `scripts/migrate_faq_review_status.py` 與 `src/db/clinic_schema.sql` 之間的 DDL 重複手寫技術債（DEBT-01）：
1. **單一來源解析核心 (`scripts/migrate_faq_review_status.py`)**：
   - 實作純函式 `extract_column_definition(schema_text, table, column)`：精確自 schema 之 `faq_cache` 區塊定位單行欄位定義，剝除行尾註解與結尾逗號，並驗證括號平衡與單引號成對。若格式非法或找不到定義，在連線資料庫前即拋出 `RuntimeError`（fail-closed）。
   - 實作 `build_add_column_sql` 與 `derive_alter_statements`：動態自 `clinic_schema.sql` 衍生出 `review_status` 與 `reviewed_at` 的 `ALTER TABLE ... ADD COLUMN` 語句。
   - 移除原始碼中所有手寫欄位關鍵字（`DEFAULT 'approved'`、`CHECK (review_status`、`TIMESTAMP`），腳本不再有雙寫風險。
2. **交易性與相容介面維持**：
   - 保留模組級常數 `ALTER_REVIEW_STATUS_SQL` 與 `ALTER_REVIEWED_AT_SQL`（由 schema 在 import 時衍生），相容既有測試之 monkeypatch 交易回滾驗證。
   - `apply_review_status_migration(db_path, schema_path=None)` 支援自訂 schema 檔案路徑，連線前完成解析，保留 `BEGIN IMMEDIATE ... COMMIT/ROLLBACK` 與半遷移修復邏輯。
   - `main()` 完整保留正式庫連線前拒絕（回傳 2）與 `--dry-run` 行為。

## 測試覆蓋與驗證
- `tests/test_faq_review_migration.py`：原本 8 個測試斷言一行未改全數通過，並新增 6 個測試（共 14 passed）：
  - `test_extract_column_definition_matches_schema`：驗證對真實 schema 擷取結果完全符合預期。
  - `test_extract_column_definition_fail_closed`：驗證缺區塊、缺欄位、單引號內含註解標記、括號不平衡時皆拋出 `RuntimeError`。
  - `test_build_add_column_sql`：驗證產生之 ALTER 語句格式。
  - `test_alter_follows_schema_definition`：證明測試——修改 schema 複本中的 `DEFAULT` 定義，舊庫遷移後欄位預設值隨之改變，腳本不需改動。
  - `test_unparseable_schema_fails_closed_before_connect`：證明測試——schema 不可解析時在 `sqlite3.connect` 之前 fail-closed，目標資料庫零變動。
  - `test_migration_script_has_no_handwritten_column_ddl`：去重守門測試——原始碼不含手寫欄位定義關鍵字。
  - `test_prod_db_sha256_unmodified`：正式資料庫零接觸。
- 正式庫 `clinic.db` SHA-256 驗證完全不變。
