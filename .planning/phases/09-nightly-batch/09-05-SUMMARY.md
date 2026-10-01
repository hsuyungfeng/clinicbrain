# Phase 09 Plan 05 Summary: 夜間批次執行器與 CLI 工具

## 執行成果概述
本計畫（09-05）完成了 Phase 09 的核心執行排程本體（BATCH-03）：
1. **執行日誌與 Logger 靜音保護 (`src/batch/run_log.py`)**：
   - 實作結構化日誌記錄器 `RunLogger`，全面防禦問答原型字串外洩，嚴格禁止記錄敏感鍵名（`query/question/answer/prompt/raw/text/content`）。
   - 提供 `content_loggers_silenced()` 語境管理器，在執行批次時自動靜音 `src.ingestion.generate_faq` 與 `src.pageindex.prompt_template` 等內部 logger，防範 LLM raw prompt/output 輸出至 root 或 systemd journal。
2. **批次執行器 (`src/batch/runner.py`)**：
   - 實作 `run_batch` 統一排程邏輯：載入主題清單 -> 規劃主題與樹 -> 判定 dry-run -> （非 dry-run）LLM 健康檢查 -> 逐主題預生成 FAQ 並寫入待審核 -> 逐棵重建臨床推理樹並落盤 JSON 快照。
   - 成本、時間與積壓三重防禦：`max_faq_topics`、`max_trees`、`time_budget_seconds` 與 `max_pending`。
   - 失敗隔離與優雅降級：單一主題或單一樹失敗自動隔離並記錄；LLM 離線時優雅跳過並回傳狀態 `llm_unavailable`。
   - 覆蓋手寫樹警報：被覆蓋的手寫或上傳樹自動發出 `tree_overwrote_handwritten` 警告並累計至摘要。
3. **命令列介面 CLI (`scripts/run_nightly_batch.py`)**：
   - 支援 `--db`、`--seed-file`、`--dry-run`、`--allow-prod-db`、`--skip-faq`、`--skip-trees`、`--max-faq-topics`、`--max-trees` 等完整參數。
   - 正式庫連線前安全攔截：非 dry-run 目標為正式庫且無 `--allow-prod-db` 時以結束碼 2 拒絕，不建立日誌、不發起連線。
   - 資料庫同目錄非阻塞檔案鎖：`<db_path>.nightly.lock`，防止不同 log-dir 之多行程重疊執行。
   - 結束碼規範：0 為正常/優雅略過，1 為未預期例外，2 為參數/前置檢查拒絕。

## 測試覆蓋
- `tests/test_batch_runner.py`：13 個測試，涵蓋 dry-run、LLM 不可用、中途離線、資源上限不餓死、時間預算、單筆失敗隔離、pending 積壓上限、手寫樹覆蓋警告、日誌隱私與靜音、端到端審核閘門、缺療程名稱略過、未遷移前置檢查、檔名序號防覆蓋。
- `tests/test_run_nightly_batch_cli.py`：7 個測試，涵蓋正式庫連線前拒絕、dry-run 唯讀允許、複本端到端執行、LLM 不可用優雅退出、結束碼規範、檔案鎖跨 log-dir 互斥、絕對路徑 log-dir 解析。
- 正式資料庫 `clinic.db` SHA-256 驗證完全不變。
