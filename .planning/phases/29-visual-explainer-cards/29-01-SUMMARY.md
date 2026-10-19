# Phase 29 Plan 01: 視覺解說卡資料層、IR 規格與審核寫入路徑執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `29-01-PLAN.md` 規格，建立一般醫學視覺解說卡的底層資料架構、Typed IR 規格與唯一審核寫入路徑：
1. **資料表定義與單一來源遷移腳本（Task 1, P29-SCHEMA）**：
   - 於 `src/db/clinic_schema.sql` 檔案最末端（`-- Sample Data` 標記之後）以專用 `-- ===== visual_assets BEGIN =====` 與 `-- ===== visual_assets END =====` 起訖註解新增 `visual_assets` 與 `visual_stats` 資料表及 `idx_visual_stats_date` 索引定義。
   - `visual_assets` 嚴格不含 `clinic_id` 欄位（全診所共用資產），`source_type` 與 `review_status` 具備 CHECK 約束。
   - 實作單一來源遷移腳本 `scripts/migrate_visual_assets.py`，支援 `--db`、`--dry-run` 與正式庫保護旗標 `--confirm-prod-backup`（未帶時在連線前以結束碼 2 拒絕）。
   - 回歸防護：經測試驗證 `extract_cache_stats_ddl`、`extract_soap_ddl` 與 `conftest._ensure_faq_cache` 擷取範圍皆不含 `visual_`；`tests/conftest.py` 隔離副本預設不含 visual 表，僅新增 `apply_visual_migration` 輔助函式。
2. **IR 規格與醫療法規驗證（Task 2, P29-IR）**：
   - 建立 `src/visual/ir.py`，定義三種固定場景模板（`process_diagram`, `contrast`, `timeline`）與三種標籤語調（`neutral`, `warning`, `optimal`）。
   - 實作 `validate_visual_text` 與唯一權威驗證函式 `validate_ir`：
     - 重用既有 `validate_single_faq` 檢核簡體字、政治爭議、通用保證療效禁詞與用藥劑量處方。
     - 整合 `deep_mask_prices` 價格深度防禦。
     - 增補視覺卡專屬禁詞 `VISUAL_EXTRA_FORBIDDEN`（含「永久」「終身」「一輩子」「存活率」「保證」「絕對」「零風險」等，且排除單獨「一定」防誤殺自然用語）與百分比正則。
     - 結構化反查：驗證失敗一律回傳結構化英文代碼（`schema_error`, `text_unsafe`, `forbidden_phrase`, `price_leak`, `simplified_chinese`, `dosage_prescription`, `unknown_blueprint`），徹底丟棄 reason 原文，絕不外洩機敏資訊。
3. **唯一寫入路徑與審核函式（Task 3, P29-SCHEMA, P29-REVIEW）**：
   - 建立 `src/visual/writer.py`，提供唯一權威寫入函式 `upsert_assets`：
     - 寫入前對整批 IR 強制執行 `validate_ir`，任一不合規即拋出 `ValueError` 並整批拒絕。
     - Fail-Closed：未遷移庫直接拋出 `RuntimeError`，絕不自動建表。
     - 增量 UPSERT：新列狀態恆為 `pending`，內容實質變更回 `pending` 並遞增 `content_version`、清空 `reviewed_at`；內容未變冪等跳過。
   - 建立 `src/visual/review.py`：
     - `set_review_status`：醫師審核變更狀態，核准前重新執行 `validate_ir`，遭竄改者拒絕核准。
     - `visible_assets`：唯一對外可見查詢（`review_status='approved'`），缺表安全回傳空清單，輸出前逐筆由 Python 重新檢核 IR，遭竄改者自動略過。

---

## 2. 改動檔案

- `src/db/clinic_schema.sql`：於 Sample Data 之後追加 `visual_assets`、`visual_stats` 與索引定義。
- `scripts/migrate_visual_assets.py`：單一來源結構遷移工具。
- `tests/conftest.py`：新增 `apply_visual_migration` 輔助函式（既有 fixture 行為完全不變）。
- `tests/test_migrate_visual_assets.py`：遷移腳本、單一來源擷取、舊遷移回歸防護單元測試。
- `src/visual/__init__.py`：視覺模組套件初始化。
- `src/visual/ir.py`：Typed IR 規格常數與 `validate_ir`、`validate_visual_text` 實作。
- `tests/test_visual_ir.py`：IR 結構與醫療法規驗證單元測試（正例、負例與自然語言防誤殺）。
- `src/visual/writer.py`：唯一寫入路徑 `upsert_assets` 與 `has_visual_assets_table`。
- `src/visual/review.py`：審核函式 `set_review_status` 與對外可見查詢 `visible_assets`。
- `tests/test_visual_writer.py`：寫入、審核、可見性與竄改防護單元測試。
- `.planning/phases/29-visual-explainer-cards/29-01-SUMMARY.md`：本執行摘要。

---

## 3. 驗收指令執行結果

1. **Task 1 驗收測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_migrate_visual_assets.py`
   -> **9 passed in 0.59s**。
2. **Task 2 驗收測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_visual_ir.py`
   -> **11 passed in 0.42s**。
3. **Task 3 驗收測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_visual_writer.py tests/test_visual_ir.py tests/test_migrate_visual_assets.py`
   -> **28 passed in 0.87s**。
4. **既有模組與隱私守門測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_general_privacy.py`
   -> **6 passed in 1.24s**。
5. **正式資料庫雜湊不變守門**：
   `sha256sum clinic.db`
   -> `ae1a3763d17f212ec99dbc53264db6828df6897a3a62e964f348c1b02d545bc2  clinic.db`（完全未變）。

---

## 4. 偏離與特別說明

- 無任何偏離計畫之處。所有任務嚴格遵循 TDD（先寫失敗測試再實作），新表定義完全隔離於 Sample Data 之後，舊遷移與預設隔離副本皆不受影響，正式資料庫未被修改。
