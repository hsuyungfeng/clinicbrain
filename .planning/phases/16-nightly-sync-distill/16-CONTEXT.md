# Phase 16 Context: 定時自動化同步與批次提煉排程

## 一、 階段目標

本階段旨在將 Phase 14（SOAP 紀錄入庫）、Phase 15（臨床居家照護提煉）與 Phase 09（夜間批次架構）串接為高度自動化的「夜間排程流水線」：

1. **夜間批次擴充 (Nightly Batch Integration)**：
   - 擴充 `scripts/run_nightly_batch.py` 與 `src/batch/runner.py`，新增 SOAP 臨床衛教提煉子任務。
   - 支援夜間離峰時段全自動執行：掃描當日入庫之 `soap_records`，聚合頻率 $\ge 2$ 之居家照護要點，產出 `pending` 衛教草稿。
   - 支援任務獨立旗標：`--skip-soap`、`--soap-only`、`--soap-min-occurrences`。
2. **外部同步銜接 (Incremental Sync & Push)**：
   - 整合 `POST /api/v1/soap/records` 與定時同步腳本，支援夜間批次執行前安全拉取/同步最新去識別化病歷。
   - 遵循 Phase 05 REST JSON 契約，徹底摒棄 MITM 透明代理。
3. **排程自動化與系統守護 (Systemd & Cron)**：
   - 提供標準 Systemd 定時器範本（`clinicbrain-nightly.service` 與 `clinicbrain-nightly.timer`，預設每日 03:00 AM 觸發）。
   - 保留非阻塞檔案鎖互斥機制（`clinic.db.nightly.lock`），防範與手動執行或日誌維護衝突。
4. **晨間醫師簽核通報 (Morning Review Notification)**：
   - 擴充 `review_faq` 工具，提供 `pending-summary` 摘要檢視命令，讓醫師於晨間門診前快速掌握「昨夜新產出待審草稿總數、標的疾病與病歷筆數」，實現一鍵批次簽核。

---

## 二、 邊界與安全鐵則（遵循 AGENTS.md）

1. **唯讀 Dry-Run 絕對隔離**：
   - 排程 CLI 支援 `--dry-run`，一律以 SQLite `mode=ro` 唯讀 URI 開啟資料庫，保證零資料庫寫入。
2. **正式庫安全防護**：
   - 非排程環境手動對正式庫執行實質寫入時，維持 `--confirm-prod-backup` 旗標把關；在自動化服務環境中則由專屬 Service 定義環境變數明確放行。
3. **Fail-Closed 審核隔離**：
   - 夜間提煉出的草稿恆為 `pending`，未獲醫師於晨間簽核核准前，公開端點（`/api/v1/query`、`/api/v1/general/query`）絕對隱蔽不可見。
4. **零 GPU 與離峰資源保護**：
   - SOAP 提煉為純規則特徵聚合，不耗用 GPU VRAM；可與 Qwen 27B 大模型批次生成交錯或獨立執行，避免資源競爭。
5. **測試衛生與資料庫隔離**：
   - 所有測試皆在 `tmp_path` 隔離複本執行，正式庫 `clinic.db` SHA-256 恆定受保。
