# clinicbrain 專案深度體檢與改善建議報告 (`hydrogenimprovement.md`)

> **分析基準**：以 `/home/hsuyungfeng/DevSoft/clinicbrain`（commit `9c80015`）為準，結合 `codebase-memory-mcp` 程式碼知識圖譜分析（6,155 節點、22,405 邊）、SQLite 實庫結構檢查、安全與並發靜態稽核，以及實際執行 `pytest` 測試套件之實測結果撰寫。

---

## 總覽與優先級矩陣

`clinicbrain` 已具備極為紮實的醫療合規防線（繁體中文、價格遮蔽、劑量／處方攔截、紅旗優先分流、SSRF 防護與唯讀連線隔離），但隨著專案快速演進至 Phase 43–45，累積了**立即性的測試回歸、安全組態漏洞、單體巨型檔案、無依賴清單／CI、以及資料庫遷移碎片化**等問題。

| 優先級 | 類別 | 核心問題摘要 |
| :--- | :--- | :--- |
| **P0（立即修復）** | 回歸 Bug / 資料缺失 | 2 項既有單元測試實際失敗（`app.js` 違規 `innerHTML`、`runner.py` 影片階段連坐失敗）；正式 `clinic.db` 缺少 `sync_logs` 表 |
| **P0（立即修復）** | API 安全組態 | `CORSMiddleware` 同時開 `allow_origins=["*"]` 與 `allow_credentials=True`；`verify_admin_key` 使用 `!=` 非常數時間比對 |
| **P1（高優先）** | 並發與穩定性 | `async def upload_admin_file` 阻塞事件迴圈；影片背景渲染缺防重入鎖與 `ffmpeg` 逾時；多 worker 下記憶體 job 狀態分裂 |
| **P1（高優先）** | 工程基礎設施 | 根目錄完全缺少 `pyproject.toml` / `requirements.txt` / CI / Linter；`systemd` 服務檔寫死已失效路徑；`clinic.db` (49 MB) 造成 Git 膨脹 (~88 MiB) |
| **P2（中優先）** | 架構與複雜度重構 | `admin.py` (1,888 行)、`autodraft.py` (1,744 行，認知複雜度 444)、`runner.py` (認知複雜度 256)、前端 JS 巨型單體 (8,300+ 行) |
| **P2（中優先）** | 資料庫與搜尋安全 | 9 支零散 `migrate_*.py` 缺統一版控；`search.py` / `nhi_index.py` 的 `LIKE` 查詢未跳脫 `%` 與 `_` |
| **P3（長期優化）** | 效能、離線化與文件 | `index.html` 依賴外部 Tailwind v2 CDN；`llm_client.py` 寫死 endpoint 且無連線池；`AGENTS.md` 膨脹至 184 KB |

---

## 一、P0：立即修復項目（實測已確認之回歸與漏洞）

### 1.1 既有測試套件存在確定性失敗（Regression）

實際執行測試時發現以下明確失敗，顯示近期提交（Phase 43 / 45）未跑完整回歸即合併：

1. **前端安全不變量遭破壞**
   - **失敗測試**：`tests/test_admin_ask.py::test_ui_has_ask_tab_and_no_html_injection`
   - **根因**：[app.js](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/web/static/app.js#L1675-L1683) 在「第 7 區（向 LLM 提問，明定一律使用 `textContent`、禁止拼接 HTML）」中插入了 `emptyBox.innerHTML = ...`，且按鈕文字寫死 `(88 筆)`（實際 `page_index_trees` 已有 91 筆）。
   - **改善建議**：改以 `document.createElement` / `el(...)` + `textContent` 組裝該空狀態卡片，並動態顯示計數或移除寫死數字。

2. **夜間批次 Stage 9 影片渲染預設啟用導致既有批次測試失敗**
   - **失敗測試**：`tests/test_batch_runner.py::test_rejected_items_do_not_cause_topic_failure`
   - **實測輸出**：`BatchSummary(..., videos_failed=1, errors=1)` 導致 `assert summary.errors == 0` 失敗。
   - **根因**：[runner.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/batch/runner.py#L607-L629) 在 `run_batch()` 新增第 9 階段影片佇列時，`BatchConfig.skip_video_render` 預設為 `False`，導致無瀏覽器／ffmpeg 環境或既有測試執行 `run_batch()` 時將影片階段失敗計入 `summary.errors`。
   - **改善建議**：將影片渲染失敗與主知識庫錯誤統計分離（或讓 `BatchConfig` 明確由 CLI 啟用 `--enable-video-render`，測試環境預設不觸發 Playwright/ffmpeg）。

### 1.2 正式 `clinic.db` 缺少 `sync_logs` 資料表

- **現象**：透過 Python 比對 [clinic_schema.sql](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/db/clinic_schema.sql#L309-L323) 與現行 `clinic.db`，發現 `sync_logs` 表存在於 schema 檔卻**不存在於 `clinic.db`**。
- **風險**：[sync.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/api/routes/sync.py#L89-L108) 雖在寫入端點透過 `_ensure_sync_logs_table(conn)` 補建表，但 `GET /api/v1/sync/logs` 使用 `get_read_db`（`PRAGMA query_only = ON`）且未建表，直接查詢將觸發 `sqlite3.OperationalError: no such table: sync_logs`（HTTP 500）。
- **改善建議**：建立統一資料庫遷移檢查，確保 `clinic.db` 與 `clinic_schema.sql` 完全同步，並停止在 HTTP handler 內執行 DDL。

### 1.3 CORS 與 API 金鑰認證安全漏洞

1. **CORS 過寬組態**
   - **位置**：[app.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/api/app.py#L44-L50)
   - **問題**：同時設定 `allow_origins=["*"]` 與 `allow_credentials=True`。在 Starlette 中這會將任何請求的 `Origin` 原封不動反射至 `Access-Control-Allow-Origin` 並允許攜帶憑證，屬於高風險 CORS 組態錯誤。
   - **改善建議**：預設改為明確的本機來源清單（如 `["http://127.0.0.1:8000", "http://localhost:8000"]`），並透過環境變數 `CLINICBRAIN_CORS_ORIGINS` 供部署端白名單設定；若不需跨網域 Cookie，應設 `allow_credentials=False`。

2. **API 金鑰時序側信道攻擊風險（Timing Attack）**
   - **位置**：[dependencies.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/api/dependencies.py#L47-L53)
   - **問題**：`if not x_api_key or x_api_key != config.admin_api_key:` 使用一般字串比較（`AGENTS.md` 亦註記 AUTH-04 尚未完成）。
   - **改善建議**：改用 `secrets.compare_digest(x_api_key.encode("utf-8"), config.admin_api_key.encode("utf-8"))`。

---

## 二、P1：並發安全性、穩定性與工程基礎設施

### 2.1 FastAPI 非同步事件迴圈阻塞

- **位置**：[admin.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/api/routes/admin.py#L308-L400)
- **問題**：`upload_admin_file` 宣告為 `async def`，在 `await file.read(...)` 之後，直接於主事件迴圈中同步執行 `convert_to_markdown`、`extract_docx_text`、`opencc` 繁簡轉換與 `sqlite3` 寫入，會卡死整個 Uvicorn worker 的所有並發請求（包含 `/health` 與 `/api/v1/query`）。
- **改善建議**：將檔案解析與資料庫寫入抽離為純同步函式，透過 `await run_in_threadpool(...)`（`starlette.concurrency`）執行，或改為同步 `def` 端點配合串流讀取。

### 2.2 背景任務狀態隔離、競爭條件與逾時缺失

1. **多 Worker 模式下記憶體狀態分裂**：
   - [consult_jobs.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/general/consult_jobs.py#L41-L43)（`_jobs` 字典）、[batch_answer_job.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/pageindex/batch_answer_job.py) 皆將作業狀態存於行程內記憶體。若啟動 `scripts/run_api_server.py --workers 2` 以上，提交 job 與輪詢 job 會落在不同 worker 而回傳 404。
   - [query.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/api/routes/query.py#L27-L51) 的全域 `_warned_error_types: set[str]` 在多執行緒寫入時未加鎖。
   - **改善建議**：若刻意維持單行程（因本機 `llama-server` 僅單 slot），應在 `run_api_server.py` 對 `--workers > 1` 發出明確警告或改將匿名 job 狀態存於具 TTL 的 SQLite 暫存表／`tmpfs`。

2. **影片背景渲染競爭條件與 `ffmpeg` 無逾時**：
   - [admin.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/api/routes/admin.py#L1828-L1861) 的 `trigger_admin_visual_video_render` 未對同一 `(topic_key, aspect)` 做去重鎖定，連點兩次會同時啟動兩個 Playwright + `ffmpeg` 行程寫入同一個 `.mp4` 檔案導致損毀。
   - [video_queue.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/visual/video_queue.py#L260) 呼叫 `subprocess.run(ffmpeg_cmd, check=True)` 未設定 `timeout` 參數，若編碼卡死將永久佔用背景執行緒。
   - **改善建議**：加入 per-`(topic_key, aspect)` 的渲染中集合／鎖，並為 `ffmpeg` 加上合理 `timeout`（如 180 秒）與原子寫入（先寫 `.tmp.mp4` 成功後再 `os.replace`）。

### 2.3 完全缺乏套件管理、CI/CD 與靜態分析

- **現況**：專案根目錄**無 `pyproject.toml`、`requirements.txt`、`uv.lock`、`.github/workflows/`、`.ruff.toml` 或 `mypy.ini`**。環境重建完全仰賴既有的 `.venv`（一旦損毀或換機部署將無法精確還原套件版本）。
- **改善建議**：
  1. 補齊 `pyproject.toml`（明確區分 `core`、`ocr`、`scraper`、`video`、`dev` 等 optional-dependencies）。
  2. 引入 `ruff`（統一代碼風格與捕捉未使用的 import、潛在 bug）與 `mypy`/`pyright`（針對 `src/query`、`src/api`、`src/ingestion` 核心模組做型別檢查）。
  3. 建立最小化本機或 GitHub Actions CI pipeline，且使用 `pytest` markers（如 `@pytest.mark.browser`、`@pytest.mark.slow`）將快速單元測試與耗時的 Playwright 測試分流（目前 `pytest` 收集 2,023 筆測試，全跑會被少數瀏覽器測試拖慢數分鐘）。

### 2.4 Systemd 服務範本路徑失效與 Git 倉庫膨脹

1. **Systemd 範本寫死舊路徑**：
   - [clinicbrain-api.service](file:///home/hsuyungfeng/DevSoft/clinicbrain/clinicbrain-api.service#L9-L22) 與 [clinicbrain-nightly.service](file:///home/hsuyungfeng/DevSoft/clinicbrain/clinicbrain-nightly.service#L9-L22) 寫死 `/home/hsu/Desktop/clinicbrain` 及 `/home/hsu/.local/bin/python3`、`/usr/bin/python3`，與現行工作區 `/home/hsuyungfeng/DevSoft/clinicbrain` 及 `.venv/bin/python3` 不符。
   - **改善建議**：改為範本檔（`.service.template`）並提供安裝檢查腳本動態帶入 `PROJECT_ROOT` 與 `.venv/bin/python3`，同時補齊 `AUTH-03` 規劃的權限 `600` `EnvironmentFile` 指引。

2. **二進位資料庫納入版控導致 Git 膨脹**：
   - `clinic.db`（49 MB）直接受 Git 追蹤，目前 `.git` 物件已達 **~88 MiB**（`size: 43.68 MiB`、`size-pack: 44.28 MiB`），且資料夾 `data/`（736 MB）、`scratch/`（852 MB）體積龐大。
   - **改善建議**：長期應將 `clinic.db` 移出 Git 主線，改採「`clinic_schema.sql` + 確定性種子／JSONL 匯出檔（可 diff、可 code review）」或 Git LFS / 獨立物件備份；短期內至少將 `clinic.db` 更新頻率降至最低並定期 `git gc`。

---

## 三、P2：架構重構、複雜度治理與資料庫衛生

### 3.1 高認知複雜度與單體巨型檔案（知識圖譜量化分析）

透過 `codebase-memory-mcp` 圖譜查詢，專案中存在多個嚴重超過維護門檻的函式與檔案（全 `src/` 共 26,645 行 Python）：

| 模組／函式 | 行數 / 指標 | 問題與重構建議 |
| :--- | :--- | :--- |
| [admin.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/api/routes/admin.py) | **1,888 行**（單檔 76 KB） | 單一 router 混雜上傳、FAQ 審核、LLM 提問、自動補齊、推理樹、診所 CRUD、視覺審核、影片佇列 8 大領域。應拆分為 `routes/admin/` 子套件（如 `upload.py`、`faq_review.py`、`trees.py`、`visuals.py`、`videos.py`）。 |
| [autodraft.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/visual/autodraft.py#L913-L1490) `parse_and_build_tree_ir` | **577 行**、認知複雜度 **444** | 單一函式內含多層巢狀條件、內嵌 helper 及 3 幕 IR 塑形。應將 Scene 1 / Scene 2 / Scene 3 驗證與塑形拆分為獨立策略函式或 Pydantic schema 驗證器；同檔 `infer_scene1_blueprint` 亦達 **356 行**，建議改為資料驅動的規則表。 |
| [runner.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/batch/runner.py#L130-L633) `run_batch` | **503 行**、認知複雜度 **256**、跨函式迴圈深度 **10** | 9 個批次階段全寫在單一函式內。應抽象為 `BatchStage` 介面／清單管線（統一處理 `dry_run`、`time_budget` 檢查、例外隔離與 `summary` 統計）。 |
| [patient_prefill.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/batch/patient_prefill.py) `run_prefill_stage` | 認知複雜度 **160**、迴圈深度 **3** | 應拆分候選篩選、單題生成與進度持久化。 |
| [sync.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/api/routes/sync.py) `import_sync_data` | 認知複雜度 **115** | 建議將 trees / faqs / notes / hours 四種實體的合規檢驗與寫入拆為獨立 handler。 |
| [fetch.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/scraper/fetch.py#L165) `fetch_page` | **9 個參數**、認知複雜度 **85** | 應封裝為 `FetchOptions` / `FetchDeps` dataclass。 |

### 3.2 前端靜態資源單體化與無架構管理

- **現況**：[src/web/static/](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/web/static/) 累計超過 **10,500 行**手寫原生 JS/HTML/CSS，包含：
  - `visual_engine.js`：**3,919 行**（207 KB）
  - `app.js`：**2,916 行**（130 KB）
  - `anatomy_viewer.js`：**1,468 行**（54 KB）
  - 未壓縮版 `three.js`（1.3 MB、53,223 行）直接作為靜態檔提供。
- **問題**：無 ES Modules 分割、無型別檢查、依賴手動版本號破除快取（如 `v=20261113-5`），極易出現全域命名衝突或安全回歸（如本次抓到的 `innerHTML` 誤用）。
- **改善建議**：至少改用原生 ES Modules（`<script type="module">`）依頁籤拆檔，將 `three.js` 換為 `.min.js`（體積可縮減 50%+），並抽出共用的安全 DOM builder 與 API client（統一處理 `401` 提示重輸金鑰）。

### 3.3 資料庫遷移碎片化與連線參數不一致

1. **9 支獨立遷移腳本缺乏版本追蹤**：
   - [scripts/](file:///home/hsuyungfeng/DevSoft/clinicbrain/scripts/) 目錄下累積了 `migrate_cache_stats.py`、`migrate_faq_metadata.py`、`migrate_faq_review_status.py`、`migrate_page_index_review.py`、`migrate_pageindex_clinic_id.py`、`migrate_soap_schema.py`、`migrate_to_nhi_code.py`、`migrate_visual_assets.py`、`migrate_visual_template_override.py` 共 9 支腳本，缺乏統一的 `schema_migrations` 表或 `PRAGMA user_version` 機制，無法自動判斷現有資料庫處於哪一版結構。
   - **改善建議**：收斂為單一編號式遷移機制（如 `src/db/migrations/001_...` + `scripts/migrate.py --status / --apply`）。

2. **寫入連線缺少 `busy_timeout`**：
   - [dependencies.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/api/dependencies.py#L26-L34) 的 `get_write_db()` 未設定 `PRAGMA busy_timeout = 5000;`（或連線 `timeout`），在背景統計寫入、夜間批次或管理員上傳同時發生時，較容易觸發 `database is locked`。

### 3.4 `LIKE` 查詢未跳脫 SQL 萬用字元

- **問題**：[soap.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/api/routes/soap.py#L60) 正確實作了 `ESCAPE '\\'` 跳脫 `%` 與 `_`，但 [search.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/query/search.py#L99) 與 [nhi_index.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/query/nhi_index.py#L72) 的 `LIKE ?` fallback 皆未跳脫 `%` 與 `_`。若使用者輸入 `%` 或 `_%`，將退化為全表匹配，繞過 3 字以下過濾與限流語意。
- **改善建議**：抽出共用 `escape_like(term: str)` helper 至 `src/query/search.py` 並統一套用 `ESCAPE '\\'`。

### 3.5 廣泛的靜默例外捕捉（109 處 `except Exception`）

- **現象**：全 `src/` 共有 **109 處** `except Exception` 或裸 `except:`，其中多處（如 `admin.py`、`nhi_index.py`、`patient_compose.py`）直接 `pass` 或吞掉錯誤細節。
- **改善建議**：區分「預期可降級的例外」（如 `json.JSONDecodeError`、`sqlite3.OperationalError`）與程式錯誤（`KeyError`、`TypeError`），至少記錄結構化警告日誌（含 `exc_info` 或錯誤碼，注意不含個資），避免掩蓋系統性 Bug。

---

## 四、P3：效能熱點、離線韌性與專案整理

### 4.1 迴圈內線性掃描與 Regex 熱點

透過圖譜的 `linear_scan_in_loop` 與 `alloc_in_loop` 偵測，以下函式存在重複線性掃描開銷：
- [medical_safety.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/ingestion/medical_safety.py#L103) `check_dosage_prescription`（`linear_scan_in_loop = 15`）：於每個句子／子句迴圈內重複執行多組大型 regex 比對與清單檢查，可於模組載入時預編譯合併或做前置快速關鍵字過濾。
- [review.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/visual/review.py) `update_visual_asset_by_id`（`linear_scan_in_loop = 4`）。
- [drafts.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/scraper/drafts.py) `build_faq_drafts`（`linear_scan_in_loop = 3`, `alloc_in_loop = 6`）。

### 4.2 本機 LLM 連線與組態彈性

- **位置**：[llm_client.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/pageindex/llm_client.py#L21-L110)
- **問題**：
  1. `LLM_ENDPOINT` 與 `MODELS_ENDPOINT` 寫死 `http://127.0.0.1:8080`，無法透過環境變數（如 `CLINICBRAIN_LLM_BASE_URL`）切換至內網 GPU 主機或測試 mock port。
  2. 每次 `local_llm_call()` 前都固定先打一次 `/v1/models` 健康檢查，且使用 `urllib.request.urlopen`（無 TCP/HTTP keep-alive 連線池），增加不必要的往返延遲。
- **改善建議**：支援環境變數覆寫 `base_url`，改用 `httpx.Client`（專案 `.venv` 已因 FastAPI TestClient 安裝）提供連線池，並僅在連線失敗時做診斷性健康檢查或改用快取 TTL 探測。

### 4.3 診所內網完全離線韌性（移除外部 CDN）

- **位置**：[index.html](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/web/static/index.html#L8)
- **問題**：管理後台載入 `https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css`。除了 Tailwind v2 已停止維護外，若診所主機處於斷網或嚴格防火牆環境，整個管理介面排版將完全崩壞。
- **改善建議**：將所需 CSS（或編譯後的最小化 Tailwind CSS）本地化至 `src/web/static/`，並同步收緊 `app.py` 中 `/admin` 的 CSP `style-src 'self'`（移除 `https://cdn.jsdelivr.net`）。

### 4.4 專案目錄與文件膨脹治理

1. **`scripts/` 與根目錄整理**：
   - `scripts/` 目前混雜了 55+ 支檔案（正式營運排程、9 支遷移腳本、一次性截圖腳本 `capture_*.py`、101 KB 的 `distill_vendome_trees_and_faqs.py` 以及資料檔 `phase02_generated_trees.json`）。建議分層為 `scripts/ops/`、`scripts/migrations/`、`scripts/oneoff/`。
   - 根目錄尚有 `plan32_gallery.html`、`plan33_gallery.html` 可移入 `docs/` 或 `demo/`。
2. **文件與狀態同步**：
   - [STATE.md](file:///home/hsuyungfeng/DevSoft/clinicbrain/.planning/STATE.md) 同時存在衝突的進度描述（頂部標示 `milestone: v1.4 completed`、中間標示 `Phase 43`、底部卻寫 `Last session: Phase 21`）。
   - [AGENTS.md](file:///home/hsuyungfeng/DevSoft/clinicbrain/AGENTS.md) 達 **184 KB**，每次載入會被截斷，建議將歷史 Phase 規格歸檔至 `docs/architecture/`，讓 `AGENTS.md` 維持在 20 KB 以內的精煉核心規範。

---

## 五、建議執行順序（Roadmap）

1. **第一階段（1–2 天內，止血與安全）**：
   - 修復 `app.js:1675` 的 `innerHTML`（改用 DOM API）與 `runner.py` 影片階段錯誤計數隔離，恢復單元測試全綠。
   - 修正 `app.py` CORS 組態與 `dependencies.py` `secrets.compare_digest`。
   - 為 `clinic.db` 補齊 `sync_logs` 表，並替 `get_write_db` 加上 `busy_timeout`。
2. **第二階段（1 週內，工程化與穩定性）**：
   - 補齊 `pyproject.toml`、`ruff`、pytest markers 分流與修復 `clinicbrain-*.service` 路徑。
   - 修復 `upload_admin_file` 事件迴圈阻塞、影片背景渲染鎖與 `ffmpeg` 逾時。
   - 統一 `escape_like` 並為 `llm_client.py` 加上環境變數組態。
3. **第三階段（中期重構，可維護性）**：
   - 拆分 `admin.py`、`autodraft.py` (`parse_and_build_tree_ir`) 與 `runner.py`。
   - 前端 CSS 本地化、模組化 JS、建立統一資料庫遷移器與 `AGENTS.md` 瘦身。
