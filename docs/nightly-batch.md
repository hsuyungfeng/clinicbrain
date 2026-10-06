# clinicbrain 夜間批次與審核營運手冊

本文件說明 clinicbrain 系統夜間批次（Nightly Batch）自動化排程之核心架構、審核閘門、營運維護與故障排除作業指引。

---

## 1. 概觀與核心職責

夜間批次系統（`scripts/run_nightly_batch.py`）旨在兼顧院所醫師審核負擔、本地 LLM 推論成本與醫療合規安全，於每日離峰夜間執行兩大核心任務：
1. **常見問答（FAQ）預生成**：根據熱門未命中關鍵字與手動種子清單，呼叫本地 LLM 預生成問答。產出之一問一答內容**預設標記為 `pending`（待審核）**，未經醫師審核核准前，對外查詢 API 與快取短路機制完全不可見。
2. **過期臨床推理樹重建**：掃描資料庫中被標記為 `needs_regeneration = 1` 之推理樹，重新呼叫 LLM 生成四段式臨床結構與摘要文字，並在寫入前自動備份前像快照。

---

## 2. 一次性準備（正式資料庫操作）

正式資料庫（`clinic.db`）啟用夜間批次前，必須由系統管理員手動執行以下結構遷移：

1. **手動建立資料庫備份**：
   ```bash
   cp clinic.db clinic.db.bak-$(date +%Y%m%d)
   ```
2. **套用審核閘門欄位遷移**：
   執行遷移腳本，為 `faq_cache` 表安全擴充 `review_status` 與 `reviewed_at` 欄位：
   ```bash
   python3 scripts/migrate_faq_review_status.py --confirm-prod-backup
   ```
3. **驗證既有資料狀態**：
   確認既有 40 筆院所上傳之 FAQ 資料皆已標記為 `approved`：
   ```bash
   sqlite3 clinic.db "SELECT review_status, COUNT(*) FROM faq_cache GROUP BY 1;"
   ```
   預期輸出應顯示既有筆數皆屬於 `approved`。

---

## 3. 維護主題種子清單

種子清單檔案位於 `data/batch/faq_seeds.json`，是批次選題與問答生成的權威來源。

- **檔案結構說明**：
  - `tree_procedure_names`：`doc_id` 對應之繁體中文療程標準名稱（例如 `"hifu-lifting": "音波拉提"`）。樹重建時必須查得此名稱，若缺對照則會略過該樹。
  - `topics`：主題清單，每項包含 `topic_key`（主題識別碼）、`title`（標題）、`category`（`special` 或 `general`）、`clinic_id`（醫療機構代碼）、`keywords`（關聯路由關鍵字）、`always`（是否恆常排入候選）、`tree_doc_id`（關聯之推理樹代碼）、`questions`（標準問句列表）。
- **選題分流規則**：
  - 系統統計過去 14 天內（`--since-days`）累積未命中次數達門檻（`--min-miss-count`，預設 3 次）之熱門關鍵字，優先選出 keywords 涵蓋該關鍵字之主題。
  - 標記為 `always: true` 之主題恆常排入後續候選。
  - 若日誌輸出 `unmapped_keywords` 事件，代表民眾近期頻繁查詢但尚未建立對應主題之關鍵字，建議維護人員適時擴充種子檔。
- **嚴格合規過濾**：
  清單檔案在載入時會經四層合規嚴格驗證。若問題清單內包含簡體中文、價格數字或保證療效禁詞，整份清單檔案將拒絕載入並中斷批次。

---

## 4. 臨床推理樹之過期標記與重建

### ⚠️ 重建會覆蓋手寫內容（重要安全警示）
臨床推理樹重建**刻意不經過審核閘門**。被標記重建的樹，其四段式臨床結構（術前、療程、術後短期、長期維持）與摘要文字將被 LLM 生成的新內容覆蓋，且 `source_type` 會由原本的 `manual` 或 `clinic_upload` 變更為 `llm_generated`。
為保障醫療安全，系統提供以下多重補償防護：
1. **醫師權威註記絕對保護**：四段臨床之 `*_physician_notes` 欄位一律維持原既有值；若偵測到不一致會立即中止並自動復原。
2. **自動寫入前像快照**：重建前強制將既有內容以 JSON 格式儲存於 `logs/nightly_batch/tree_snapshots/`。
3. **審核警報事件**：被覆蓋的手寫或上傳樹會於日誌觸發 `tree_overwrote_handwritten` 警告事件。

### 標記操作指引
使用專用 CLI 標記待重建之推理樹：
```bash
# 檢視目前標記狀態
python3 scripts/mark_tree_regen.py list

# 標記指定樹為待重建（正式庫需帶確認旗標）
python3 scripts/mark_tree_regen.py mark hifu-lifting --allow-prod-db
```

---

## 5. 手動執行與排程維護

### 命令列旗標與資源上限
執行指令：`python3 scripts/run_nightly_batch.py [選項]`

| 參數旗標 | 預設值 | 說明 |
|---|---|---|
| `--db` | `clinic.db` | 目標資料庫檔案路徑 |
| `--seed-file` | `data/batch/faq_seeds.json` | 種子清單檔案路徑 |
| `--dry-run` | `False` | 預演模式：以唯讀方式規劃，不呼叫 LLM 亦不寫入資料庫 |
| `--allow-prod-db` | `False` | 明確同意對正式 `clinic.db` 執行寫入之安全旗標 |
| `--skip-faq` | `False` | 略過 FAQ 預生成階段 |
| `--skip-trees` | `False` | 略過臨床推理樹重建階段 |
| `--max-faq-topics` | `5` | 單次處理之最大 FAQ 主題數量上限 |
| `--max-trees` | `3` | 單次重建之最大臨床推理樹數量上限 |
| `--max-pending` | `200` | 待審核積壓上限，達門檻時自動暫停 FAQ 生成以保護醫師負擔 |
| `--time-budget-seconds` | `3600.0` | 整體時間預算秒數，超時優雅中斷 |
| `--llm-timeout` | `120` | 單次呼叫本地 LLM 之逾時秒數 |
| `--log-dir` | `logs/nightly_batch` | 結構化執行日誌與快照儲存目錄 |

### 結束碼規範
- **0**：批次成功完成，或優雅略過（包含 dry-run 預演、本地 LLM 服務離線、已有另一個批次持有檔案鎖、或時間預算用盡）。
- **1**：未預期之系統例外或嚴重錯誤。
- **2**：前置安全檢查未通過（例如非 dry-run 目標為正式庫卻未帶 `--allow-prod-db`、清單格式錯誤、或資料庫尚未遷移）。

### 互斥檔案鎖與日誌隱私保證
- **非阻塞檔案鎖**：鎖檔固定位於目標資料庫同目錄（`<db_path>.nightly.lock`），跨不同日誌目錄皆具互斥性，杜絕重疊執行。
- **日誌隱私保證**：`RunLogger` 採欄位白名單防禦，嚴格禁止記錄任何問句原型或回答文字；執行期間自動靜音底層可能輸出提示詞之內部 logger。第三方 logger 不在此保證範圍內。

---

## 6. 醫師審核流程 (Review Workflow)

所有由批次生成之 FAQ，在正式對外服務前必須經由醫師審核。

### 審核 CLI 工具 (`scripts/review_faq.py`)
```bash
# 1. 列出所有待審核項目
python3 scripts/review_faq.py list --status pending

# 2. 檢視特定問答完整內容
python3 scripts/review_faq.py show 42

# 3. 核准通過（寫入正式庫需 --allow-prod-db）
python3 scripts/review_faq.py approve 42 --allow-prod-db

# 4. 批次駁回違規或不合適之生成項目
python3 scripts/review_faq.py reject 43 44 --allow-prod-db
```
- **合規再次檢核**：核准操作時系統會重新執行多層醫療合規驗證（含用藥劑量與就醫警訊），杜絕任何違規內容流入。
- **增量同步語意**：當審核狀態由 pending 變更為 approved 時，系統自動遞增 `content_version`，以利外部系統進行增量同步。

### 被駁回題目重新生成（Phase 12 DEBT-03）
指令：`python3 scripts/review_faq.py [--allow-prod-db] mark-regen <id...>`
說明：
- 當醫師駁回（reject）某筆 LLM 生成的 FAQ 後，該題預設不會再次被批次選入生成。
- 醫師可透過 `mark-regen` 子命令將該列標記為 `needs_regeneration = 1`。
- 「一次標記一次嘗試」機制：下次夜間批次時，系統會將該題重新排入生成候選。若生成的新答案不同，將更新答案並重設為 `pending`（版本遞增）；若生成的答案與原駁回內容完全相同，則清除重生成旗標（維持 `rejected`），不再重複耗費 LLM 資源。
- 測試建議：進行正式操作前，請先在測試複本（`--db /tmp/test_nightly.db`）上進行演練確認。

---

## 7. systemd 排程服務與硬體資源考量

專案根目錄下提供兩個 systemd 服務範本檔：
- `clinicbrain-nightly.service`：Type=oneshot 定時批次執行單元。
- `clinicbrain-nightly.timer`：定時觸發器，設定於每日凌晨 02:30 執行，並啟用 `Persistent=true`（錯過排程開機後自動補行執行一次）與 `RandomizedDelaySec=900`（隨機分散延遲）。

### 資源調度與 GPU 考量
- **API 與批次無資源競爭**：clinicbrain 對外自然語言查詢 API 採用快取短路與 PageIndex 推理樹檢索，端點本身**完全不呼叫本地 LLM**，因此夜間批次執行不會與線上民眾查詢爭搶 GPU 資源。
- **優先權調降**：服務單元配置 `Nice=10` 與 `IOSchedulingClass=idle`，確保批次推論以最低系統優先級運作。
- **健康檢查優雅降級**：批次啟動時會先對 `llama-server.service` 執行健康檢查；若本地推論模型尚未載入或服務離線，批次會記錄 warning 並以結束碼 0 優雅略過，不造成 systemd 單元失敗。
- **服務啟用規範**：本專案依安全規範不代為啟用或啟動任何 systemd 服務；系統管理員可依標準 systemd 作業流程自行評估是否將範本檔部署至系統目錄並啟用。

---

## 8. 可選手動冒煙測試與自動化真機驗證（僅限隔離複本）

### 本地推論運算開銷參考（Phase 13 DEBT-04 實測數據）
- **硬體與模型規格**：NVIDIA GeForce RTX 2080 Ti (11GB VRAM) + Qwen3.8-27B-UD-Q4_K_XL（經由 `llama-server`）。
- **推論耗時與吞吐量**：
  - 單題常見疾病 FAQ 生成：約 30~45 秒（推論速度約 18~22 tokens/sec）。
  - 單篇臨床推理樹生成/重建：約 120~150 秒（含深度思考 `<think>` 與四段結構嚴格檢核）。
  - 日誌隱私：批次內部靜音機制生效，`nightly-*.log` 零敏感字元洩漏。
- **超時與參數配置建議**：
  - `src/pageindex/llm_client.py` 預設配置：`timeout=360.0`, `max_tokens=6144`, `reasoning_effort="low"`。
  - 若在低配硬體上運作，建議啟動批次時將 `--llm-timeout` 調高至 180 秒以上。

### 自動化真機驗收測試
專案提供完整端到端真機測試套件，會在隔離暫存複本上驗收真實推論、審核閘門、推理樹前像快照與日誌隱私：
```bash
python3 -m pytest tests/test_real_llm_batch.py -v
```
> **注意**：若本機 `llama-server` 離線，測試將自動優雅跳過（SKIPPED），不影響常規回歸測試。

### 手動演練流程（手動複本）
若需以 CLI 進行人工逐步驗證，**嚴禁於正式 clinic.db 上執行**。請依下列步驟於測試複本操作：
1. 複製資料庫至暫存目錄：
   ```bash
   cp clinic.db /tmp/test_nightly.db
   ```
2. 對複本執行遷移：
   ```bash
   python3 scripts/migrate_faq_review_status.py --db /tmp/test_nightly.db
   ```
3. 對複本進行單筆實跑：
   ```bash
   python3 scripts/run_nightly_batch.py --db /tmp/test_nightly.db --max-faq-topics 1 --max-trees 0 --log-dir /tmp/test_logs
   ```
4. 檢視新生成之 pending 項目並確認對外檢索查無此項目：
   ```bash
   python3 scripts/review_faq.py list --db /tmp/test_nightly.db --status pending
   ```

---

## 9. 已知限制與架構取捨

1. **同步匯入覆寫權威**：`/api/v1/sync/import` 以 `clinic_upload` 寫入；若外部匯入與既有 pending 或 rejected 之 `llm_generated` 項目具相同唯一鍵，會由匯入內容覆寫並視為 approved。
2. **LLM 呼叫單次逾時中斷**：本地推論逾時會轉為 `LocalLLMUnavailableError`，單次逾時將使整個批次提前優雅結束（結束碼 0），保留已完成部分，未完成項目留待下一晚繼續。
3. **未命中關鍵字粒度限制**：`cache_stats` 僅記錄標準化白名單關鍵字，無法獲知病患真實具體問法，需定期由管理人員檢視補強清單。
