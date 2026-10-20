# Phase 31 Plan 01: 視覺解說卡支援診所專屬、無損遷移與診所優先選取執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `31-01-PLAN.md` 規格，完成 `visual_assets` 資料表支援診所專屬（`clinic_id`）與一般醫學共用（`clinic_id IS NULL`）並存架構、實作無損資料表重建遷移（Table Rebuild Migration），並在比對與病人端諮詢層實作「診所有相關服務時優先調用診所專屬動畫、否則調用一般醫學動畫」之選取邏輯：

1. **Task 1: clinic_schema.sql 與 migrate_visual_assets.py 無損重建遷移（P31-MIGRATE）**：
   - 更新 [`src/db/clinic_schema.sql`](file:///home/hsu/Desktop/clinicbrain/src/db/clinic_schema.sql)：
     * `visual_assets` 新增 `clinic_id TEXT REFERENCES clinic_info(clinic_id)` 欄位（置於 `id` 之後、`topic_key` 之前）。
     * `topic_key` 移除單欄 UNIQUE 約束，表尾新增 `UNIQUE(clinic_id, topic_key)`。
     * 新增部分唯一索引 `idx_visual_assets_general_topic ON visual_assets(topic_key) WHERE clinic_id IS NULL;`（防止 SQLite 在多筆 `(NULL, topic_key)` 重複插入）。
     * 新增外鍵查詢索引 `idx_visual_assets_clinic_id ON visual_assets(clinic_id);`。
   - 更新 [`scripts/migrate_visual_assets.py`](file:///home/hsu/Desktop/clinicbrain/scripts/migrate_visual_assets.py)：
     * `apply_visual_schema` 支援舊版表（無 `clinic_id` 欄）在單一交易內安全無損重建：`ALTER TABLE visual_assets RENAME TO _visual_assets_old_p29` -> 執行新 DDL -> 複製既有欄位資料至新表（`clinic_id` 填入 `NULL`，保留既有 `review_status` 與 `content_version`） -> `DROP TABLE _visual_assets_old_p29`。
     * 若已為新版表結構，直接執行 DDL 確保索引齊全，既有資料毫髮無傷，具備完全冪等性。
   - 更新 [`tests/test_migrate_visual_assets.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_migrate_visual_assets.py)：
     * 更新 DDL 與欄位結構斷言（驗證 `clinic_id` 與兩組新索引存在）。
     * 新增 `test_table_rebuild_migration_from_old_schema`：驗證舊表升級、既有資料完整保留、一般醫學與診所專屬可擁有相同 `topic_key`，但同為 `NULL` 或同 `clinic_id` 插入相同 `topic_key` 會正確觸發 `sqlite3.IntegrityError`。

2. **Task 2: writer.py 與 review.py 支援 clinic_id 與 CRUD 輔助函式（P31-SCOPE）**：
   - 更新 [`src/visual/writer.py`](file:///home/hsu/Desktop/clinicbrain/src/visual/writer.py)：
     * `upsert_assets` 解析 `raw_clinic = a.get("clinic_id")`，若為空字串或 None 則正規化為 `None`；若為非空字串則 strip 後使用（若非 str 拋出 `ValueError`）。
     * 支援以 `clinic_id IS ? AND topic_key = ?` 進行既有列比對、INSERT 與 UPDATE。
   - 更新 [`src/visual/review.py`](file:///home/hsu/Desktop/clinicbrain/src/visual/review.py)：
     * `set_review_status(conn, topic_key, status, commit=True, *, clinic_id=None, asset_id=None)`：支援以 `asset_id` 或 `(clinic_id, topic_key)` 更新狀態，核准前重新執行 `validate_ir`。
     * `visible_assets(conn, clinic_id=None)`：
       - `clinic_id is None`：僅查 `review_status = 'approved' AND clinic_id IS NULL`。
       - `clinic_id` 有值：查詢 `review_status = 'approved' AND (clinic_id = ? OR clinic_id IS NULL)`。
       - Python 層再次執行 `row_clinic_id in (clinic_id, None)` 雙重防禦檢查，絕不外洩他院資產。
       - 回傳 dict 包含 `"clinic_id": row_clinic_id`。
   - 更新 [`scripts/export_visual_bundle.py`](file:///home/hsu/Desktop/clinicbrain/scripts/export_visual_bundle.py) 與 [`scripts/review_visual.py`](file:///home/hsu/Desktop/clinicbrain/scripts/review_visual.py)：
     * 新增選填參數 `--clinic-id`（預設 `None` 查一般醫學資產）。
   - 更新 [`tests/test_visual_writer.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_visual_writer.py)：
     * 既有斷言更新為 `item["clinic_id"] is None`。
     * 新增 `test_upsert_and_review_with_clinic_id`：驗證同 `topic_key` 在一般醫學與診所專屬各自獨立寫入、獨立審核、跨診所隔離與 `asset_id` 審核更新。

3. **Task 3: match.py 診所優先選取與 patient_consult 串接（P31-SCOPE）**：
   - 更新 [`src/visual/match.py`](file:///home/hsu/Desktop/clinicbrain/src/visual/match.py)：
     * `find_visual(conn, query, clinic_id: str | None = None)`：
       - 呼叫 `visible_assets(conn, clinic_id=clinic_id)` 並於 Python 層雙重檢查診所範圍。
       - 排序鍵設為 `(tier, -hits, topic_key)`，其中 `tier = 0 if (clinic_id and asset_clinic == clinic_id) else 1`。
       - **診所專屬資產（tier 0）永遠優先於一般醫學資產（tier 1）**；同層比關鍵字命中數（多者優先），同分比 `topic_key` 字典序。
       - `_shape_public_visual` 輸出維持 `{"topic_key", "title", "scenes"}`，不暴露 `clinic_id`。
       - 維持純 SELECT、零 logging、零 print（通過 AST 掃描）。
   - 更新 [`src/general/patient_consult.py`](file:///home/hsu/Desktop/clinicbrain/src/general/patient_consult.py)：
     * `_safe_find_visual(conn, query, clinic_id=clinic_id)` 支援並將 `clinic_id` 傳遞至 `find_visual`。
     * `patient_consult` 中 4 處 `_safe_find_visual` 呼叫皆帶入 `clinic_id=clinic_id`。
   - 更新 [`tests/test_visual_match.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_visual_match.py) 與 [`tests/test_visual_serving.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_visual_serving.py)：
     * `test_find_visual_clinic_priority_and_isolation`：驗證即使一般醫學命中 2 個關鍵字、診所 A 僅命中 1 個關鍵字，帶 `clinic_id='3503190424'` 仍優先選取診所 A 資產；帶診所 B 時安全退回一般醫學資產，不外洩診所 A 資產。
     * `test_consult_endpoint_prioritizes_server_configured_clinic_visual`：驗證 `/api/v1/general/consult` 與 `/consult/jobs` 在設定 `config.patient_clinic_id = '3503190424'` 時優先回傳該診所專屬動畫，且忽略請求夾帶之 `X-Clinic-ID`。

---

## 2. 測試與驗證結果

1. **Task 1 驗證**：
   `uv run pytest -q -p no:cacheprovider tests/test_migrate_visual_assets.py`
   -> **10 passed in 0.68s**。

2. **Task 2 驗證**：
   `uv run pytest -q -p no:cacheprovider tests/test_visual_writer.py tests/test_visual_cli.py tests/test_visual_bundle.py`
   -> **23 passed in 1.12s**。

3. **Task 3 驗證**：
   `uv run pytest -q -p no:cacheprovider tests/test_visual_match.py tests/test_visual_serving.py tests/test_general_privacy.py`
   -> **24 passed, 1 warning in 2.03s**。

4. **31-01 完整回歸驗證套件**：
   `uv run pytest -q -p no:cacheprovider tests/test_migrate_visual_assets.py tests/test_visual_writer.py tests/test_visual_match.py tests/test_visual_serving.py tests/test_visual_cli.py tests/test_visual_bundle.py tests/test_general_privacy.py`
   -> **57 passed, 1 warning in 2.88s**。

5. **全視覺與諮詢測試回歸驗證**：
   `uv run pytest -q -p no:cacheprovider tests/test_visual_*.py tests/test_consult_*.py`
   -> **138 passed, 1 skipped, 1 warning in 11.46s**。

6. **正式資料庫保護**：
   `sha256sum clinic.db`：
   `2f66cd1b42fd927bca22a847b537c4cc43fb80c6a139aafb67669caaf25daf66  clinic.db`
   -> 正式資料庫維持完全未受修改與遷移。

---

## 3. 改動檔案清單

- `src/db/clinic_schema.sql`：`visual_assets` 新增 `clinic_id`、複合唯一約束與部分唯一索引。
- `scripts/migrate_visual_assets.py`：實作無損資料表重建遷移（table rebuild）與冪等執行。
- `src/visual/writer.py`：`upsert_assets` 支援 `clinic_id` 欄位寫入與比對。
- `src/visual/review.py`：`set_review_status` 與 `visible_assets` 支援 `clinic_id` 與診所隔離。
- `scripts/export_visual_bundle.py`：支援 `--clinic-id` 選填參數。
- `scripts/review_visual.py`：支援 `--clinic-id` 選填參數。
- `src/visual/match.py`：`find_visual` 支援 `clinic_id`，實作診所專屬優先（tier 0 > tier 1）。
- `src/general/patient_consult.py`：`_safe_find_visual` 串接伺服器解析之 `clinic_id`。
- `tests/test_migrate_visual_assets.py`：新增資料表無損重建遷移與約束測試。
- `tests/test_visual_writer.py`：新增多診所獨立寫入與審核隔離測試。
- `tests/test_visual_match.py`：新增診所專屬優先與隔離比對測試。
- `tests/test_visual_serving.py`：新增 API 端點診所專屬優先與伺服器固定診所範圍測試。
- `.planning/phases/31-visual-autodraft-and-approval/31-01-SUMMARY.md`：本執行摘要。

---

## 4. 遵守規則聲明

1. 僅執行 `31-01-PLAN.md` 指定範圍，完成後建立 `31-01-SUMMARY.md` 即停。
2. 嚴格遵守規定，未執行任何 `git reset`, `git checkout`, `git stash`, `git clean`, `git restore`。
3. 嚴禁修改或遷移正式庫 `clinic.db`，所有測試皆使用 `isolated_db_path` 隔離複本，`clinic.db` SHA-256 毫無變更。
4. 依指示**未自行執行 git commit**，保留工作區改動等待 hermes 測試與 argon 審查。
