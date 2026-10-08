# Phase 16 Research: 定時自動化同步與批次提煉排程技術方案

## 一、 現有系統組件分析

### 1.1 現有夜間批次架構 (`src/batch/runner.py` 與 `scripts/run_nightly_batch.py`)
- **檔案鎖互斥**：`fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)` 確保單一實例執行，避免 cron 重複觸發造成資料競爭。
- **快照與日誌**：每次批次執行皆建立以時間戳命名的快照目錄與 `RunLogger` 結構化日誌（記至 `logs/nightly_batch/`）。
- **流程結構**：
  - 目前流程：`Phase 1: Seed FAQ 預生成` ➔ `Phase 2: Tree 臨床推理樹重建` ➔ `Phase 3: 失敗與待重生重試`。
  - **擴充點**：在 `BatchConfig` 與 `BatchSummary` 納入 `soap_distill` 任務，執行順序建議：
    `Step 1: SOAP 衛教提煉` ➔ `Step 2: LLM FAQ 預生成` ➔ `Step 3: Tree 重建`。
    因為 SOAP 提煉為純 CPU/SQLite 運算（耗時極短，約 0.1~0.5s），即使 LLM 離線或故障，SOAP 提煉依然能順利完成。

### 1.2 現有提煉模組 (`src/soap/distiller.py`)
- `distill_soap_records(conn, clinic_id, min_occurrences=2, dry_run=False)`：
  - 輸入：SQLite 連線、診所代碼。
  - 輸出：包含 `distilled_count`、`conditions`、`faqs` 之摘要字典。
  - 寫入：走唯一的 `faq_writer.upsert_faqs(..., source_type='soap_distilled')`，自動帶入 `metadata` 溯源資訊並設為 `pending`。
  - **重跑特性**：已具備重跑冪等性（內容未變不覆寫已核准狀態）。

### 1.3 Linux Systemd Timer vs Crontab
- **Systemd Timer 優勢**：
  - 具備 `Persistent=true`（若凌晨主機休眠或重開機，開機後會自動補跑錯過的排程）。
  - 日誌自動由 `journalctl -u clinicbrain-nightly` 集中收整，便於系統運維。
  - 與現有的 `clinicbrain-api.service` 和 `llama-server.service` 架構體系風格一致。
- **Crontab 支援**：
  - 仍保留標準 crontab 單行指令範例，方便無需 Systemd 權限的一般使用者部署。

---

## 二、 計畫分解與實作路徑

| 計畫編號 | 計畫名稱 | 核心任務 |
| :--- | :--- | :--- |
| **16-01-PLAN** | **夜間批次擴充與 SOAP 提煉子任務** | 擴充 `BatchConfig`、`BatchSummary`、`run_batch()` 與 `run_nightly_batch.py`，支援 `--skip-soap`、`--soap-only` 與 `--soap-min-occurrences` |
| **16-02-PLAN** | **定時增量同步契約模組** | 實作 `src/sync/cron_pull.py` 或增量同步推播整合，提供夜間自動獲取最新 SOAP 紀錄並入庫之防禦性腳本 |
| **16-03-PLAN** | **Systemd 排程單元與晨間審核通報** | 建立 `clinicbrain-nightly.service/timer`，擴充 `review_faq.py pending-summary` 命令，編寫端到端自動化整合測試 |
