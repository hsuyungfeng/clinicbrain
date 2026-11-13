# Phase 46: 系統衛生、安全加固與回歸修復 (System Hygiene, Security Hardening & Regression Recovery)

> **所屬里程碑**：v1.5 / v1.6  
> **關聯依據**：`hydrogenimprovement.md`（專案全維度體檢報告）  
> **核心目標**：解決專案在 Phase 43–45 演進過程中累積的立即性回歸 Bug、API 安全漏洞、資料庫結構缺口、事件迴圈阻塞與缺少套件管理基建之問題，並透過 herdr 調度獨立 Agent Hermes (`wA:p3`) 進行端到端獨立測試驗收。

---

## 1. 背景與體檢發現

依據 `hydrogenimprovement.md` 之深度靜態分析與實機回歸測試，專案發現以下關鍵隱患：

1. **P0 既有測試回歸（Regression）**：
   - `tests/test_admin_ask.py::test_ui_has_ask_tab_and_no_html_injection` 失敗：`src/web/static/app.js:1675` 違規插入 `emptyBox.innerHTML = ...`，且按鈕寫死 `(88 筆)`，違反了第 7 區純 `textContent` 安全不變量。
   - `tests/test_batch_runner.py::test_rejected_items_do_not_cause_topic_failure` 失敗：Phase 43 新增之 Stage 9 影片佇列渲染預設啟用，在測試環境或無 ffmpeg 環境失敗時，將 `videos_failed` 計入 `summary.errors`，破壞了批次總錯誤統計契約。
2. **P0 資料庫結構與連線健全性**：
   - 正式 `clinic.db` 遺漏 `sync_logs` 資料表（`src/db/clinic_schema.sql:309` 有定義），導致 `GET /api/v1/sync/logs` 唯讀查詢拋出 500。
   - 寫入連線缺少 `busy_timeout` 設定，在高並發時容易拋出 `database is locked`。
3. **P0/P1 安全漏洞與並發風險**：
   - `src/api/app.py` 中 `CORSMiddleware` 同時啟用 `allow_origins=["*"]` 與 `allow_credentials=True`，存在高風險反射憑證漏洞。
   - `src/api/dependencies.py` 的 `verify_admin_key` 使用非固定時間比較符 `!=`，易受時序側信道攻擊（Timing Attack），需升級為 `secrets.compare_digest`。
   - `src/api/routes/admin.py:upload_admin_file` 為 `async def`，但在事件迴圈內直接執行 CPU 密集型解析（MarkItDown/DOCX/OpenCC）與 SQLite 寫入，阻塞整個 Uvicorn 行程。
   - 影片背景渲染端點 `POST /visuals/videos/{topic_key}/render` 缺少 per-topic 防重入鎖，且 `ffmpeg` 呼叫缺少 `timeout`。
4. **P1 工程基礎設施**：
   - 根目錄缺乏標準 `pyproject.toml` / `requirements.txt` / linter 配置，環境難以確定性還原。
   - `clinicbrain-api.service` 與 `clinicbrain-nightly.service` 寫死過期路徑 `/home/hsu/Desktop/clinicbrain`。

---

## 2. 核心架構與分階段計畫

Phase 46 劃分為三個循序漸進的執行計畫（Plans）：

- **46-01-PLAN.md (Wave 1: P0 回歸修復與資料庫同步)**：
  - 修復 `app.js` 空狀態卡片改用 DOM API（`createElement` + `textContent`），修復寫死筆數。
  - 修復 `runner.py` 影片渲染階段配置（預設停用或錯誤統計解耦），修復批次錯誤斷言。
  - 為正式 `clinic.db` 補建 `sync_logs` 資料表與索引，並在 `get_write_db` 注入 `PRAGMA busy_timeout = 5000;`。
- **46-02-PLAN.md (Wave 2: P0/P1 安全防禦與並發加固)**：
  - 收緊 CORS 配置，支援環境變數白名單，禁止 `*` 與憑證並存。
  - 使用 `secrets.compare_digest` 強制常數時間金鑰驗證。
  - 使用 `run_in_threadpool` 解除 `upload_admin_file` 事件迴圈阻塞。
  - 影片渲染加入防重入鎖與 `ffmpeg` 180s 逾時機制與原子寫入。
- **46-03-PLAN.md (Wave 3: P1 工程基建與 Herdr Hermes 獨立測試)**：
  - 建立標準 `pyproject.toml` 與 `requirements.txt`。
  - 修正 systemd 服務範本檔路徑。
  - 透過 herdr 協同調度獨立 Agent Hermes (`wA:p3`) 執行全套回歸測試與端到端獨立審查。
