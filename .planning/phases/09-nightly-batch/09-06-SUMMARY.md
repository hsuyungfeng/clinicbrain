# Phase 09 Plan 06 Summary: systemd 範本、營運手冊與全 Phase 關帳

## 執行成果概述
本計畫（09-06）完成了 Phase 09 的排程服務範本、營運維護手冊、開發規範與最終全 Phase 關帳驗證：
1. **排程服務與定時器範本 (`clinicbrain-nightly.service`, `clinicbrain-nightly.timer`)**：
   - 建立於 repo 根目錄，採 `Type=oneshot`，設定 `Nice=10` 與 `IOSchedulingClass=idle`，排定於每日凌晨 02:30 觸發。
   - 啟用 `Persistent=true`（主機關機或休眠錯過時開機自動補跑一次）與 `RandomizedDelaySec=900`（隨機分散延遲）。
   - 嚴格遵守安全規範：**不安裝到系統目錄、不執行任何 systemctl 指令、範本非註解行零指令**。
2. **夜間批次營運維護手冊 (`docs/nightly-batch.md`)**：
   - 完整繁體中文文件，詳盡說明資料庫結構遷移、種子清單維護、樹重建操作與醫師註記保護、手動執行參數與結束碼、審核 CLI 工具、systemd 範本與 GPU 資源考量、隔離複本冒煙測試流程與已知限制。
3. **專案規格與版本控制更新**：
   - `.gitignore`：加入 `logs/`（日誌與前像快照）與 `*.nightly.lock`（互斥鎖檔）。
   - `AGENTS.md`：新增 `### 2.10 夜間批次生成與審核閘門（Phase 09 新增）`，完整載明審核閘門語意、三處消費端套用、遷移與 Fail-Closed 規範、手動標記與重建覆蓋手寫內容警示、日誌隱私保證範圍；並更新第 4 節目錄結構。
   - `.planning/ROADMAP.md`：將 Phase 9 Plans 展開為 09-01 至 09-06 共 6 份詳細計畫。

## ROADMAP 成功標準對應交付物與測試

| 成功標準 (Success Criteria) | 對應交付物 | 驗證測試檔 |
|---|---|---|
| 1. 批次讀取快取未命中統計與手動清單產生主題，不使用簡體 SFT 資料 | `data/batch/faq_seeds.json`<br>`src/batch/topic_sources.py` | `tests/test_batch_topic_sources.py` (10 passed) |
| 2. 預生成 FAQ 經四層驗證後以 `llm_generated` 寫入，未核准對外隱蔽 | `src/batch/faq_generator.py`<br>`src/pageindex/faq_review.py` | `tests/test_batch_faq_generator.py` (7 passed)<br>`tests/test_review_gate_retrieval.py` (10 passed)<br>`tests/test_faq_review_gate.py` (11 passed) |
| 3. `needs_regeneration=1` 的樹被重建且四段醫師註記欄位前後完全不變 | `src/batch/tree_rebuild.py`<br>`src/pageindex/db_writer.py` | `tests/test_batch_tree_rebuild.py` (9 passed) |
| 4. `--dry-run` 唯讀且不呼叫 LLM；LLM 不可用時批次優雅跳過並記錄日誌 | `src/batch/runner.py`<br>`scripts/run_nightly_batch.py` | `tests/test_batch_runner.py` (13 passed)<br>`tests/test_run_nightly_batch_cli.py` (7 passed) |
| 5. systemd timer 提供夜間排程範本，每次執行留下結構化執行日誌 | `clinicbrain-nightly.service`<br>`clinicbrain-nightly.timer`<br>`src/batch/run_log.py` | `tests/test_nightly_systemd_templates.py` (4 passed) |

## 全量回歸與安全驗證指標
- **全量測試結果**：`578 passed, 1 warning in 16.69s`（Phase 8 基線為 492，Phase 9 共新增 86 個自動化測試，0 失敗）。
- **正式資料庫雜湊不變性**：`clinic.db` SHA-256 驗證為 `c51cc4d039379fe00f70d7864b29a952928233fa6caa6e72954900f4c28c65ad`（整個 Phase 9 期間 0 位元組變更，無任何寫入）。
- **查詢層零改動**：`git diff --stat src/query/faq_shortcut.py src/query/router.py` 為空。
- **無任何 systemd 指令執行或侵入**：
  - `grep -rn 'systemctl' clinicbrain-nightly.service clinicbrain-nightly.timer docs/nightly-batch.md | grep -vc '^[^:]*:[0-9]*:#'` 結果為 0。
  - `~/.config/systemd/user/` 目錄無任何 nightly 相關單元。

---

## 使用者已決策事項與其後果（保持醒目）

> [!WARNING]
> ### ⚠️ 【最需注意】臨床推理樹重建不走審核閘門
> - **後果**：被標記為待重建（`needs_regeneration=1`）的手寫或上傳推理樹（`source_type` 為 `manual` 或 `clinic_upload`），經批次重建後其四段臨床內容與摘要將**直接被 LLM 生成之內容取代**，且 `source_type` 自動變更為 `llm_generated`，對外查詢 API 立即生效，**不會在審核閘門停留或由醫師手動審查**。
> - **補償防禦措施**：
>   1. 醫師權威註記強固保護：四段臨床之 `*_physician_notes` 欄位強制保留原值，寫入後即時重讀校驗，若被抹除立即以備份前像自動復原。
>   2. 前像快照落盤：每次覆寫前一律於 `logs/nightly_batch/tree_snapshots/` 自動備份完整 JSON 檔案供手動還原。
>   3. 審核警告日誌：覆蓋手寫內容時於日誌觸發 `tree_overwrote_handwritten` 警告並累計至摘要。

- **同步匯出排除未核准項目**：`POST /api/v1/sync/export` 僅匯出 `approved`、`manual` 或 `clinic_upload` 項目；醫師審核核准時系統自動遞增 `content_version`，以利增量同步 `since_version` 正確拉取。
- **排程與成本參數預設值**：每日凌晨 02:30 觸發、隨機延遲 900 秒、上限 5 主題 / 3 棵樹 / 時間預算 3600 秒 / pending 積壓上限 200 筆。

---

## 仍需使用者確認事項

1. **初始清單檔審查**：`data/batch/faq_seeds.json` 內預設包含的 4 個主題（音波拉提、肉毒除皺、玻尿酸填補、皮秒雷射）與 8 題問答文字，建議由院所醫師與專業人員親自檢視是否符合臨床衛教口吻。
2. **正式資料庫結構遷移執行時機**：正式資料庫遷移腳本 `scripts/migrate_faq_review_status.py` 需於使用者手動備份 `clinic.db` 後，自行決定執行時機以正式開啟審核欄位支援。
