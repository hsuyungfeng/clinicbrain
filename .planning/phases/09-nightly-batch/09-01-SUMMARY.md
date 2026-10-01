# Phase 09 Plan 01 執行總結：審核閘門資料層與遷移

## 1. 執行目標達成情況
- [x] **schema 欄位唯一權威**：`src/db/clinic_schema.sql` 中的 `faq_cache` 表新增 `review_status`（`TEXT NOT NULL DEFAULT 'approved' CHECK (review_status IN ('pending', 'approved', 'rejected'))`）與 `reviewed_at TIMESTAMP` 欄位。
- [x] **冪等遷移腳本**：新增 `scripts/migrate_faq_review_status.py`，支援 `--db`、`--dry-run`、`--confirm-prod-backup`。目標為正式庫未帶確認旗標時，連線前即以結束碼 2 拒絕；以 `BEGIN IMMEDIATE` / `COMMIT` 控制交易，出錯自動回滾；支援半遷移修復與 llm_generated 回填為 pending。
- [x] **寫入狀態語意與防禦**：`src/pageindex/faq_writer.py` 寫入 `llm_generated` 內容預設為 `pending`；`manual` 與 `clinic_upload` 預設為 `approved`；若目標庫尚未遷移審核欄位且欲寫入 `llm_generated`，依 Fail-Closed 原則拋出 `RuntimeError`。
- [x] **唯一審核寫入函式**：新增 `src/pageindex/faq_review.py`，提供 `set_review_status`（核准前四層醫療合規驗證，可見性改變時遞增 `content_version` 並刷新 `updated_at`）、`visible_faq_sql`、`count_by_status`、`list_faqs`、`get_faq`。
- [x] **測試防護**：`tests/conftest.py` 在 `_ensure_faq_cache` 補上遷移呼叫；新增 `tests/test_faq_review_migration.py`（147 行）與 `tests/test_faq_review_gate.py`（279 行）。

## 2. 測試與驗證結果
- **起始基線測試數**：492 passed, 0 failed
- **本計畫後全量測試**：508 passed, 0 failed（新增 16 個測試全數通過）
- **正式資料庫校驗**：
  - 起始 SHA-256：`c51cc4d039379fe00f70d7864b29a952928233fa6caa6e72954900f4c28c65ad`
  - 結束 SHA-256：`c51cc4d039379fe00f70d7864b29a952928233fa6caa6e72954900f4c28c65ad`（完全未受更動，零位元組變更）
- **程式碼合規檢查**：
  - `grep -c review_status src/db/clinic_schema.sql` >= 2 通過
  - `review_status = ?` 寫入路徑嚴格限於 `faq_review.py` 與 `faq_writer.py`
  - CLI 連線前拒絕測試通過（結束碼 2）

## 3. 產出檔案清單
- `src/db/clinic_schema.sql` (MODIFIED)
- `scripts/migrate_faq_review_status.py` (NEW)
- `src/pageindex/faq_review.py` (NEW)
- `src/pageindex/faq_writer.py` (MODIFIED)
- `tests/conftest.py` (MODIFIED)
- `tests/test_faq_review_migration.py` (NEW)
- `tests/test_faq_review_gate.py` (NEW)
