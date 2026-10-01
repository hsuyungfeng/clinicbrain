# Phase 09 Plan 02 執行總結：檢索與匯出套用閘門、審核 CLI

## 1. 執行目標達成情況
- [x] **檢索端閘門整合**：`src/query/search.py` 之 `search_faq_cache` 函式全面無條件加入 `visible_faq_sql(conn)` 審核過濾，保證 FTS trigram (3+ 字) 與 LIKE (<3 字) 分流下未核准 LLM FAQ 均對外不可見；`faq_shortcut.py` 與 `router.py` 零修改。
- [x] **雲端同步匯出閘門**：`src/api/routes/sync.py` 匯出 `faqs` 區段加入 `visible_faq_sql(conn)`，未核准（pending/rejected）項目不外送雲端，新核准項目於遞增 `content_version` 後能正確由 `since_version` 增量匯出。
- [x] **零回歸保證**：以對照組證明正式庫複本既有 40 筆 `clinic_upload` FAQ 在閘門開啟前後的檢索 id 序列完全相同。
- [x] **靜態代碼守衛**：新增 `tests/test_faq_read_guard.py`，靜態掃描專案內所有存取 `faq_cache` / `faq_cache_fts` 的語句，除白名單授權檔案外嚴禁任何繞過閘門的讀取路徑。
- [x] **醫師審核 CLI 工具**：新增 `scripts/review_faq.py`，支援 `list`、`show`、`approve`、`reject`、`reset`。`list` 與 `show` 強制採用 SQLite 唯讀模式 (`mode=ro`)；寫入操作一律呼叫唯一權威函式 `set_review_status`，核准前四層醫療合規驗證，且對正式庫未帶 `--allow-prod-db` 時在連線前即以結束碼 2 拒絕。
- [x] **單元與回歸測試**：新增 `tests/test_review_gate_retrieval.py`（381 行）與 `tests/test_review_faq_cli.py`（199 行），覆蓋率與回歸測試 100% 通過。

## 2. 測試與驗證結果
- **本計畫後全量測試**：539 passed, 0 failed（自基線 492 新增 47 個測試全數通過）
- **正式資料庫校驗**：
  - SHA-256：`c51cc4d039379fe00f70d7864b29a952928233fa6caa6e72954900f4c28c65ad`（完全未受更動，零位元組變更）
- **程式碼合規檢查**：
  - `git diff --stat src/query/faq_shortcut.py src/query/router.py` 為空（零觸碰）
  - `git diff src/query/search.py` 僅含 import 與 search_faq_cache
  - `scripts/review_faq.py` 內無手寫 `UPDATE faq_cache`
  - review CLI 連線前拒絕測試通過（結束碼 2）

## 3. 產出檔案清單
- `src/query/search.py` (MODIFIED)
- `src/api/routes/sync.py` (MODIFIED)
- `scripts/review_faq.py` (NEW)
- `tests/test_review_gate_retrieval.py` (NEW)
- `tests/test_faq_read_guard.py` (NEW)
- `tests/test_review_faq_cli.py` (NEW)
