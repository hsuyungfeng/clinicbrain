# Phase 09 Plan 03 執行總結：主題來源、種子清單與手動標記工具

## 1. 執行目標達成情況
- [x] **手動種子清單檔**：建立 `data/batch/faq_seeds.json`（schema_version 1、UTF-8 繁體中文），包含 6 個療程中文名對照與 4 個主題（涵蓋甲溝炎、音波、玻尿酸及通用感冒照護），全部問題皆通過四層醫療合規驗證。
- [x] **主題來源與選題引擎**：新增 `src/batch/topic_sources.py`，提供 `load_seed_file`、`validate_seed_data` 與 `select_topics`。嚴格依循隱私規範，僅讀取 `cache_stats` 的聚合未命中關鍵字（miss_keyword）計數，絕不存取使用者問句；支援熱門門檻與 `always: true` 手動主題，未匹配關鍵字輸出為 `unmapped_keywords` 提示。
- [x] **唯一標記寫入函式**：在 `src/pageindex/db_writer.py` 實作 `set_needs_regeneration`，為全專案把 `needs_regeneration` 設為 1 的唯一入口，任一 doc_id 不存在時整批中斷零寫入，不碰觸內容與版本欄位。
- [x] **手動標記 CLI**：新增 `scripts/mark_tree_regen.py`，支援 `mark`、`unmark` 與 `list`。對正式庫寫入未加 `--allow-prod-db` 時在連線前即以結束碼 2 拒絕；`list` 支援正式庫但強制採用 SQLite 唯讀模式 (`mode=ro`) 連線；無手寫 `UPDATE page_index_trees` 語句。
- [x] **單元與回歸測試**：新增 `tests/test_batch_topic_sources.py`（233 行）與 `tests/test_mark_tree_regen.py`（185 行），測試通過率 100%。

## 2. 測試與驗證結果
- **本計畫後全量測試**：522 passed, 0 failed（自基線 492 新增 30 個測試全數通過）
- **正式資料庫校驗**：
  - SHA-256：`c51cc4d039379fe00f70d7864b29a952928233fa6caa6e72954900f4c28c65ad`（完全未受更動，零位元組變更）
- **程式碼合規檢查**：
  - `grep -rn 'medical_o1_sft' src/batch data/batch` 為 0 筆（無簡體資料混入）
  - `scripts/mark_tree_regen.py` 內無手寫 `UPDATE page_index_trees`
  - mark CLI 連線前拒絕測試通過（結束碼 2）

## 3. 產出檔案清單
- `data/batch/faq_seeds.json` (NEW)
- `src/batch/__init__.py` (NEW)
- `src/batch/topic_sources.py` (NEW)
- `src/pageindex/db_writer.py` (MODIFIED)
- `scripts/mark_tree_regen.py` (NEW)
- `tests/test_batch_topic_sources.py` (NEW)
- `tests/test_mark_tree_regen.py` (NEW)
