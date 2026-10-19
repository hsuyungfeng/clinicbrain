# Phase 30 Plan 01: 視覺場景參數規格、IR 向後相容驗證與骨架生成器執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `30-01-PLAN.md` 規格，建立一般醫學視覺解說卡的 blueprint 參數規格單一來源，並使 IR 驗證與生成器支援選填之 `params` 與 `duration_sec`（完全向後相容）：

1. **參數規格註冊表與檢驗函式（Task 1, P30-PARAMS）**：
   - 建立 `src/visual/blueprints.py` 作為參數規格的唯一權威單一來源：
     - `PALETTE_TOKENS`：固定調色盤代號清單（`fat`, `oil`, `blood`, `skin`, `neutral`, `accent`, `warn`, `ok`, `gel`, `pale`），資料層只存代號，不含任何 CSS 顏色。
     - `BLUEPRINTS`：定義 `process_diagram`、`contrast`、`timeline` 之參數結構規格與預設值（`defaults`），精確對齊 Phase 29 現有畫面。
     - `default_params`：深複本回傳各 blueprint 之預設參數。
     - `merge_defaults`：實作遞迴合併語意（物件遞迴合併、list 整體覆寫、None 視為全預設）。
     - `validate_params`：嚴格驗證型別、邊界、列舉與調色盤代號；文字重用 `validate_visual_text`；失敗回傳固定英文代碼，絕不洩漏原文。
   - 建立共用測試向量 `tests/fixtures/visual_merge_vectors.json`（共 10 組，涵蓋 None、空物件、巢狀部分缺省、list 整個取代等）。
   - 建立單元測試 `tests/test_visual_blueprints.py`（14 項測試，涵蓋各邊界、安全負例、向量驗證與深複本安全）。

2. **validate_ir 支援選填 params 與 duration_sec（Task 2, P30-PARAMS）**：
   - 修改 `src/visual/ir.py` 的 `validate_ir`：
     - scene 允許選填鍵 `params`（物件）與 `duration_sec`（4..12 整數），未知鍵仍一律拒絕（`schema_error`）。
     - 若提供 `params`，委派 `blueprints.validate_params` 進行驗證，不符回傳對應代碼；非法 `duration_sec` 回傳 `param_error`。
     - 缺省時完全向後相容，既有 Phase 29 IR 驗證行為零變動。
   - 在 `tests/test_visual_ir.py` 新增 4 項測試，既有斷言零刪改。
   - 測試夾具修復：正式庫套用 visual 遷移後，`isolated_db_path` 因複製正式庫而預設帶有 visual 表，導致未遷移與空表相關測試失敗；在 `tests/conftest.py` 加入 `_reset_visual_tables` 確保隔離副本預設維持未遷移狀態，恢復夾具隔離保證。

3. **骨架檔與生成器支援 params（Task 3, P30-PARAMS）**：
   - 修改 `src/visual/generator.py`：
     - `load_skeleton`：允許 scene 包含選填 `params` 與 `duration_sec`，並以 `validate_params` 嚴格把關。
     - `generate_ir`：組裝 IR 時原樣帶入骨架的 `params` 與 `duration_sec`；模型輸出僅負責填寫 caption，無法改動結構或參數。
   - 更新骨架檔 `data/visual/skeletons/autologous-fat-grafting.json`，三個場景皆補上等同於 `default_params` 的明確參數。
   - 在 `tests/test_visual_generator.py` 新增 3 項測試，驗證骨架載入、非法拒絕與模型輸出不可篡改性，既有斷言零刪改。

---

## 2. 改動檔案清單

- `src/visual/blueprints.py`：新增 blueprint 參數規格註冊表、`PALETTE_TOKENS`、`default_params`、`merge_defaults` 與 `validate_params`。
- `tests/fixtures/visual_merge_vectors.json`：新增 10 組跨語言合併測試向量。
- `tests/test_visual_blueprints.py`：新增 blueprints 模組與合併向量測試。
- `src/visual/ir.py`：`validate_ir` 支援選填 `params` 與 `duration_sec`。
- `tests/test_visual_ir.py`：新增 IR 參數驗證與邊界測試。
- `tests/conftest.py`：於 `isolated_db_path` 新增 `_reset_visual_tables` 確保測試副本隔離。
- `src/visual/generator.py`：`load_skeleton` 驗證參數，`generate_ir` 原樣帶入骨架參數。
- `data/visual/skeletons/autologous-fat-grafting.json`：補上三個場景之明確 `params`。
- `tests/test_visual_generator.py`：新增骨架參數載入與模型輸出不可篡改性測試。
- `.planning/phases/30-visual-scene-engine/30-01-SUMMARY.md`：本執行摘要。

---

## 3. 驗收指令執行結果

1. **Task 1 驗證測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_visual_blueprints.py`
   -> **14 passed in 0.48s**。

2. **Task 2 驗證測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_visual_ir.py tests/test_visual_blueprints.py tests/test_visual_writer.py tests/test_visual_match.py tests/test_visual_serving.py`
   -> **51 passed, 1 warning in 1.30s**。

3. **Task 3 驗證測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_visual_generator.py tests/test_visual_cli.py tests/test_visual_ir.py tests/test_visual_blueprints.py`
   -> **45 passed in 0.65s**。

4. **全視覺相關模組綜合驗證**：
   `uv run pytest -q -p no:cacheprovider tests/test_visual_blueprints.py tests/test_visual_ir.py tests/test_visual_writer.py tests/test_visual_match.py tests/test_visual_serving.py tests/test_visual_generator.py tests/test_visual_cli.py`
   -> **67 passed, 1 warning in 1.48s**。

5. **正式資料庫雜湊保護**：
   `sha256sum clinic.db`
   -> `e28dc0089b01d59a03456bcced7974254c7986697d12dc0fb50da1e4a17ba6e1  clinic.db`（完全未被變動或寫入）。

---

## 4. 偏離與特別說明

1. **測試夾具隔離修復（`tests/conftest.py`）**：
   正式庫在 commit `f4758de` 經使用者授權套用 visual 遷移與資產後，`tests/conftest.py` 的 `isolated_db_path` 在複製正式庫時同步帶入了 `visual_assets` 表與資料，違反了 Phase 29 設計中「隔離副本預設不含 visual 表，各測試需要時顯式呼叫 `apply_visual_migration`」的契約。比照過往 `_reset_cache_stats` 與 `_reset_tree_titles` 之模式，在 `isolated_db_path` 中新增 `_reset_visual_tables(target_path)` 刪除副本中的 visual 表，使 Phase 29 與 Phase 30 測試完全重現乾淨未遷移的起始狀態。
2. **零既有斷言刪改**：
   既有測試檔案（`test_visual_ir.py`、`test_visual_writer.py`、`test_visual_match.py`、`test_visual_serving.py`、`test_visual_generator.py`、`test_visual_cli.py`）中的任何既有斷言無一被刪除或放寬，完全符合向後相容規定。
