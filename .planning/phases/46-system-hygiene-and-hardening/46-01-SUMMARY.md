---
phase: 46-system-hygiene-and-hardening
plan: 01
wave: 1
status: completed
completed_at: 2026-11-13T15:13:00+08:00
---

# 46-01-SUMMARY: P0 回歸修復、安全 DOM 重構與資料庫結構同步

## 執行成果
1. **前端安全純 DOM 重構 (`src/web/static/app.js`)**：
   - 徹底修正第 7 區（向 LLM 提問）空狀態卡片，將原違規之 `emptyBox.innerHTML = ...` 改寫為純原生 DOM API（`el(...)` + `textContent`），消除 XSS 潛在隱患。
   - 移除寫死之「👉 立即查看已發布決策樹 (88 筆)」文字，改為語意化標籤，恢復與實庫 91 筆推理樹狀態解耦。
   - 回歸驗證 `tests/test_admin_ask.py`：8/8 測試全數通過（PASS）。
2. **夜間批次錯誤統計解耦 (`src/batch/runner.py`)**：
   - `BatchConfig` 將 `skip_video_render` 預設值調整為 `True`，避免單元測試與非顯式啟用環境自動觸發沉重的無頭瀏覽器逐格錄製。
   - 將第 9 階段影片渲染失敗與核心醫療知識庫錯誤統計解耦（影片失敗僅計入 `summary.videos_failed`，不再污染核心 `summary.errors`）。
   - 回歸驗證 `tests/test_batch_runner.py`：14/14 測試全數通過（PASS，含 `test_rejected_items_do_not_cause_topic_failure`）。
3. **資料庫結構與並發防禦補齊 (`clinic.db` & `src/api/dependencies.py`)**：
   - 對正式 `clinic.db` 執行 DDL，補齊與 `clinic_schema.sql` 權威定義一致的 `sync_logs` 資料表與雙索引（`idx_sync_logs_clinic_id`, `idx_sync_logs_started_at`）。
   - 在 `src/api/dependencies.py:get_write_db()` 啟用 `conn.execute("PRAGMA busy_timeout = 5000;")` 與 `timeout=5.0`，降低鎖競爭風險。
