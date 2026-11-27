# AGENTS.md - clinicbrain 專案大腦與開發規範

本文件定義 **clinicbrain**（緻妍診所 Taiwan PageIndex RAG 系統）的專案架構、資料規範與
強制性安全準則，供任何 LLM/coding agent 在此專案目錄下工作前自動載入並嚴格遵循。

---

## 1. 專案身份與定位

* **專案名稱**：clinicbrain — Taiwan Clinic Medical PageIndex RAG System
* **服務對象**：緻妍外科診所（Zhiyan Aesthetic Clinic，`clinic_id = '3503190424'`，台灣健保
  特約醫事機構代碼。2026-09-22 Phase 04 TASK-01 已完成遷移，取代原本人工命名的 slug
  `'zhiyan-clinic'`，見 commit `f487763`）。
* **語言規範**：所有輸出內容（LLM 回覆、PageIndex 樹內容、程式碼註解、commit 訊息）**必須使用繁體中文**（程式碼識別字、SQL 關鍵字、藥品學名/國際醫療術語除外）。
* **定位關係**：本專案是舊系統 `DrtoolboxLocalServer`（同一診所前一代系統，GitHub `hsuyungfeng/DrtoolboxLocalServer`）的精簡重寫起點，聚焦在 PageIndex 臨床推理樹 + RAG 查詢，逐步擴充舊系統已驗證可行的能力（OCR 擷取、本地 LLM、夜間批次生成等）。詳見 `.planning/VISION-EXPANSION.md`。

---

## 2. 資料架構 (Data Architecture)

### 2.1 資料庫
單一 SQLite 資料庫 `clinic.db`（納入版控，包含實機文件上傳解析、LLM 生成與醫師審核簽核之最新臨床知識庫；亦可由腳本重建基礎種子）：
- `drugs`：377K+ 藥品項目來源 CSV，實際匯入 7,573 筆（CSV 換行數 ≠ 記錄數，勿用 `wc -l` 估算）
- `service_items`：2,669 筆醫療服務給付項目
- `page_index_trees` + `page_index_fts`：PageIndex 臨床推理樹（見 2.2）
- `faq_cache` + `faq_cache_fts`：文件擷取/夜間批次產出的常見問答快取（見 2.4）
- `cache_stats`：快取優先查詢之匿名聚合命中統計（見 2.8）
- `sync_logs`：雙向資料同步契約審計紀錄（見 2.5）
- `soap_records` + `soap_records_fts`：臨床語音與 SOAP 紀錄及全文檢索（見 2.13）
- `clinic_info` / `clinic_hours` / `clinic_custom_notes`：診所專屬層（目前 2 家：緻妍 `3503190424`、凡登整形外科診所 `3503264627`，凡登基本資料來源為 `https://www.nu-vendome.com/location-detail/Taichung/`；`clinic_hours` 目前無凡登資料，門診表寫入規格待確認）

重建指令：
```bash
python3 scripts/seed_database.py       # 建 schema + 匯入藥品/服務項目 + clinic_info/clinic_custom_notes
python3 src/pageindex/seed_trees.py    # 增量寫入 PageIndex 範本
```

**`faq_cache` 已套用到正式 `clinic.db`（2026-09-22 補做，非 Phase 03 Stage 1 交付原始範圍）**：
Stage 1 交付時只在隔離測試複本上驗證過 `faq_cache`，正式 `clinic.db` 當時還沒有這張表；
後續已手動對正式庫執行 `faq_cache`/`faq_cache_fts`/三個觸發器的 schema 更新，並透過
`faq_writer.upsert_faqs()`（唯一權威寫入路徑）把 Stage 1 已驗證的 40 筆真實 FAQ
（`source_type='clinic_upload'`）寫入正式資料庫。**注意**：`isolated_conn` 這類測試 fixture
複製的是正式 `clinic.db`，寫入真實資料後測試若用真實醫療用語（如「甲溝炎」）當 FTS
`MATCH` 關鍵字，可能命中資料庫既有的真實列而非只命中測試自己寫入的那一列——`faq_cache`
相關測試必須用測試專屬的 `topic_key` 過濾，不能只信任裸的 `MATCH` 命中數（見
`tests/test_faq_cache.py` 的既有修正案例）。

**⚠️ `clinic_id` 現在是多數函式的必填參數（2026-09-22 Phase 04 TASK-02 完成，commit
`625593d`）**：`src/query/router.py` 的 `get_clinic_hours`/`get_clinic_info`/
`get_clinic_custom_notes` 與 `src/clinic/custom_notes.py` 的同名函式/`seed_sample_notes`
**沒有預設值**，呼叫端必須明確傳入 `clinic_id`（目前唯一有效值是 `'3503190424'`）。
`handle_query()`（統一查詢入口）是唯一例外，維持 `clinic_id: str | None = None`——
`general` 路由本質上不需要診所上下文；但 `special` 路由查詢診所營運資訊時若沒收到
`clinic_id`，會明確拋出 `ValueError`，不會靜默查到空結果。

### 2.2 PageIndex 臨床推理樹 (`page_index_trees`)
每筆記錄代表一個療程的臨床推理樹，欄位：
- `pre_op` / `procedure` / `post_op_short` / `maintenance`：四段式結構（術前、療程、術後短期、長期維持）
- `*_physician_notes`：對應段落的醫師權威指令，**LLM 不得自行生成內容**，留空待醫師人工審核填入
- `content_version`：內容修訂版號，每次實質內容變更遞增（非 schema 版本，schema 版本是 `version` 欄位）
- `source_type`：`manual`（人工手寫）| `llm_generated`（LLM 生成）| `clinic_upload`（診所上傳擷取）
- `needs_regeneration`：標記過時、待夜間批次重新生成

**`clinic_id` 欄位（2026-09-22 Phase 04 TASK-00/TASK-01 完成，commit `f487763`）**：
`page_index_trees` 現在有真正的 `clinic_id TEXT REFERENCES clinic_info(clinic_id)` 欄位，
`doc_id` 是不含診所前綴的純療程 slug（如 `hifu-lifting`）。`db_writer.py` 的
`upsert_trees()` 在 `tree` dict 缺少 `clinic_id` 時會拋出 `ValueError`；`CONTENT_FIELDS`
刻意不含 `clinic_id`（身份欄位與內容變更語意分開）；UPDATE 分支不會覆寫既有列的
`clinic_id`（換診所必須是明確操作）。`search_page_index_trees()` 支援可選的 `clinic_id`
參數做診所過濾，不傳則向後相容回傳所有診所資料。`clinic_info` 的種子資料唯一權威來源是
`src/pageindex/seed_clinic_info.py`（`clinic_schema.sql` 本身不再內嵌 `clinic_info` 的
`INSERT`，避免重複寫入邏輯）；`clinic_hours` 的種子資料仍在 `clinic_schema.sql` 內
（無重複實作問題）。

**寫入規則**：一律走增量 UPSERT（比對現有內容，未變則跳過、有變才更新並遞增 `content_version`，保留原始 `created_at`）。**禁止使用 `INSERT OR REPLACE` 整批覆寫**——會重置 `created_at`、失去版本追蹤意義。

**單一寫入路徑**：`src/pageindex/db_writer.py` 的 `upsert_trees(conn, trees, source_type)` 是 `page_index_trees` 的唯一權威寫入函式，手寫種子（`seed_trees.py`）與 LLM 生成（`prompt_template.py` + 任何未來的 batch 生成腳本）都必須呼叫它，**不得各自重新實作 INSERT/UPDATE 邏輯**——TASK-003 時 `scripts/seed_database.py` 曾與 `seed_trees.py` 各自維護一份重複範本，造成資料不一致，此後禁止重蹈覆轍。

**LLM 生成流程**：`src/pageindex/prompt_template.py` 提供 `build_prompt()` → `generate_tree()`（接收一個 `llm_call: Callable[[str], str]` 介面，與底層 LLM provider 解耦，Phase 02 本地 LLM 層完成後直接傳入即可）→ `parse_and_validate()`（強制驗證繁體中文、無價格洩漏、無保證療效用語、欄位齊全）→ `to_upsert_row()` → `db_writer.upsert_trees(conn, [row], source_type='llm_generated')`。任何驗證失敗的輸出**絕不能**寫入資料庫。

### 2.3 FTS5 全文檢索 — 中文分詞鐵則
SQLite FTS5 的預設 `unicode61` tokenizer **完全無法分詞中文**（會把整段中文當一個 token，只能全字串完全匹配）。本專案所有 FTS5 虛擬表**必須明確指定 `tokenize='trigram'`**：
- `drugs_fts`、`service_items_fts`、`page_index_fts`、`faq_cache_fts` 皆已採用 trigram
- **新增或修改任何 FTS5 虛擬表時，務必重新指定 `tokenize='trigram'`**——曾發生過遷移時漏改其中一個表，導致該表完全搜不到中文的真實案例（見 git log `cf3dd47`）
- trigram 對 3 字以下的查詢無效（trigram 本身要求最少 3 字元）。查詢層（TASK-005）必須設計「3+ 字用 FTS trigram、少於 3 字用 `LIKE '%term%'`」的混合分流邏輯
- 驗證方式：修改 schema 後務必 `SELECT sql FROM sqlite_master WHERE sql LIKE '%fts5%'` 逐一確認，並跑真實中文關鍵字的 `MATCH` 查詢

### 2.4 FAQ 快取 (`faq_cache`，2026-09-22 Phase 03 Stage 1 新增)
一問一答的扁平結構，服務兩種來源：文件擷取轉 Q&A、未來夜間批次為常見問題預生成。**刻意
不與 `page_index_trees` 共用同一張表**（Q&A 扁平結構與四段式療程樹結構本質不同），但
`content_version`/`source_type`/`needs_regeneration` 三個欄位語意完全沿用 2.2 節的
`page_index_trees` 設計，讓未來維護邏輯可以對兩張表用同一套「找待重生成列」查詢模式。

欄位：`clinic_id`（可為 NULL，代表 `general` 類不綁特定診所）、`topic_key`（對應療程/主題
slug，可為 NULL）、`question`/`answer`、`category`（`'special'`/`'general'`，沿用既有路由
分流）。`UNIQUE(clinic_id, topic_key, question)` 約束搭配 `faq_writer.py` 內部用
`IS ?`（而非 `= ?`）比對，正確處理 `clinic_id`/`topic_key` 為 `NULL` 時的去重語意
（SQLite 的 `= ` 對 `NULL` 比較永遠是 unknown/falsy，用 `= ?` 會讓 general 類資料每次都被
誤判成新資料）。

**單一寫入路徑**：`src/pageindex/faq_writer.py` 的 `upsert_faqs(conn, faqs, source_type)`
是 `faq_cache` 的唯一權威寫入函式，語意比照 `db_writer.py` 的 `upsert_trees()`
（增量 UPSERT，`category='special'` 卻缺 `clinic_id` 時拋出 `ValueError`）。

**文件擷取管線**：`src/ingestion/`（`extract_text.py` 擷取 docx/xlsx、`convert_chinese.py`
用 `opencc` `s2twp` 做簡繁轉換、`generate_faq.py` 組 prompt + 四層驗證：價格洩漏/簡體字/
政治立場/保證療效禁詞，單筆過濾不影響同批其他合格項目）→
`scripts/run_stage1_ingestion.py` 端到端入口。任何自動擷取/生成的內容寫入時
`source_type` 應標記為 `'clinic_upload'`，不要跟手寫或無來源依據的 LLM 生成混淆。

**檔案轉 Markdown 前處理器（`src/ingestion/markdown_convert.py`，選用依賴 markitdown）**：
`convert_to_markdown(path)` 把本機 docx/xlsx/pdf/pptx 轉成保留表格與清單的 Markdown，補強
`extract_text.py`（新增 pdf/pptx、表格保留為 Markdown 表格）。使用順序：`convert_to_markdown` →
`convert_chinese.to_traditional` → 價格屏蔽／去識別化 → 切塊 → `generate_faq`；本模組只負責第一步。
- 純本地推理：只接受本機路徑（拒絕 http/file/data URI），`MarkItDown(enable_plugins=False)`，**不得**傳入
  任何 LLM／雲端 Document Intelligence 客戶端（圖片描述、音訊轉錄皆需外部服務，一律不用）；內嵌 base64 圖片一律濾除。
- 陷阱：markitdown 對格式不符的檔案不報錯而是退回純文字模式吐亂碼（如 `~$xxx.docx` Office 暫存鎖檔），
  因此轉換前先驗檔頭（zip／`%PDF-`）；掃描版 PDF 無文字層會得到空內容並拋 `MarkdownConvertError`（本模組無 OCR）。
- 尚未接進 `run_stage1_ingestion.py`；未安裝 markitdown 時對應測試自動略過。
- docx 轉出的標題數通常為 0（診所文件不用 Word 標題樣式），切塊需改看編號或粗體行，不能假設有 `#` 標題。

**手動 OCR 草稿工具（`scripts/ocr_draft.py` + `src/ingestion/ocr_draft.py`）**：醫師指定**單張**圖片，以本機
Tesseract（chi_tra+eng）輸出草稿供人工對照。固定警語（未經驗證、不得入庫）、含疑似價格字樣會警示、輸出不覆蓋
既有檔（`--force` 才可）。**絕不寫入資料庫**：兩個檔案不得 import `sqlite3`／`db_writer`／`faq_writer`／`faq_review`／
`custom_notes`（`tests/test_ocr_draft.py` 以 AST 掃描把關）。理由：20 張隨機抽樣僅 7 張過粗篩門檻，表格型圖片辨識成亂碼，
Phase 03 Stage 2 的「圖片 OCR 不自動化」結案決策維持不變。

### 2.5 雙向資料同步契約與審計紀錄 (`sync_logs`，2026-09-29 Phase 05 新增)
為達成與雲端平台（如 `doctor-toolbox.com`、院所 HIS/EHR）之資料同步，本專案提供標準官方 RESTful JSON 契約，徹底摒棄舊系統 `DrtoolboxLocalServer` 採用之 mitmproxy 攔截作法。

- **匯出端點 (`POST /api/v1/sync/export`)**：支援 `clinic_id`、`since_version`（增量過濾）與實體篩選（`trees`、`faqs`、`notes`、`hours`）。匯出前全面經由 `deep_mask_prices()` 進行遞迴字串清洗，保證輸出零價格數字洩漏。
- **匯入端點 (`POST /api/v1/sync/import`)**：接收外部推播更新，**嚴格強制走唯一權威寫入路徑**：
  - 臨床推理樹：`src/pageindex/db_writer.py:upsert_trees(conn, trees, source_type='clinic_upload')`（支援部分更新，內容變更遞增 `content_version`，未變則冪等跳過）。
  - FAQ 快取：`src/pageindex/faq_writer.py:upsert_faqs(conn, faqs, source_type='clinic_upload')`。
  - 診所通用備註：`src/clinic/custom_notes.py:upsert_clinic_note(conn, clinic_id, section, note)`。
  - 門診時間：交易內比對更新。
- **多層醫療法規合規防禦**：
  - 保證療效禁詞攔截：檢測到「保證有效」、「保證根除」、「百分之百有效」等違法用詞，立即拋出 HTTP 400。
  - 政治立場爭議詞彙攔截：針對「中國台灣/臺灣」、「台灣/臺灣地區」等詞彙（涵蓋簡繁與台/臺異體字）雙重防禦攔截，拋出 HTTP 400。
  - 繁簡中文處理：預設自動使用 `opencc` 轉為台灣正體中文；若停用自動轉換則檢出簡體即中斷報錯。
  - 價格自動清洗：若非價格文字中包含金額數字，自動清洗遮蔽為 `[請致電診所確認]`，杜絕未經核定之價格寫入資料庫。
- **審計紀錄 (`sync_logs`)**：每次匯出入操作皆記錄至資料庫，記載 `clinic_id`、`sync_type`、`direction`、`status`、`record_count` 與 `payload_summary`（**嚴禁記錄病患個資與具體價格**）。

### 2.6 FastAPI 服務層與系統啟動 (Phase 05 新增)
- **讀寫連線分離設計**：
  - 唯讀連線 (`dependencies.py:get_read_db`)：強制底層執行 `PRAGMA query_only = ON;`，防範任何查詢層面的意外寫入或注入風險。
  - 寫入專用連線 (`dependencies.py:get_write_db`)：僅供同步匯出入使用，開啟 `PRAGMA foreign_keys = ON;`。
- **多診所動態路由查詢**：
  - 統一入口：`POST /api/v1/query`、`POST /api/v1/clinics/{clinic_id}/query` 與 `GET /api/v1/query`。
  - 診所識別解析順序：Path/Body `clinic_id` > Header `X-Clinic-ID`，**無預設值**（`config` 已不含預設診所代碼設定，Phase 10 移除）。special 路由兩者皆未提供時 `handle_query` 拋 `ValueError`，API 回 HTTP 400，不會靜默查到任何診所。單診所部署的呼叫端須帶 `X-Clinic-ID` 或 body `clinic_id`。
  - 匿名端點例外（Phase 28 / P28-CLINIC）：匿名病人諮詢端點（`/api/v1/general/consult*`）一律忽略請求中的 `clinic_id` 與標頭 `X-Clinic-ID`，其診所範圍僅由伺服器環境變數 `CLINICBRAIN_PATIENT_CLINIC_ID`（對應 `config.patient_clinic_id`）固定單一診所（無預設值，無效則 Fail-Closed 視為未設定），詳見 2.25 節。
  - 二次價格防禦：序列化回傳前一律經由 `deep_mask_prices()` 遞迴清洗。
- **服務啟動與守護常駐**：
  - 啟動腳本：`scripts/run_api_server.py`（支援 `--host`, `--port`, `--reload`, `--workers`, `--log-level`）。
  - Systemd 守護單元：`clinicbrain-api.service`（相依於 `llama-server.service`，範本含 `[Install]` 區段可供啟用與故障重啟；**本專案刻意不啟用開機自啟**，由使用者手動啟動）。

### 2.7 API 認證強制化（Phase 06 新增）
為保護院所敏感資料與同步端點安全，自 Phase 06 起實施預設拒絕（Fail-Closed）的認證強制化機制：
- **啟動檢核雙重防線**：未設定（或為純空白）`CLINICBRAIN_ADMIN_API_KEY` 時，`scripts/run_api_server.py` 在啟動 Uvicorn 前以結束碼 `2` 拒絕啟動，並於 `stderr` 輸出繁體中文處置指引；同時 FastAPI `lifespan` 亦共用同一檢核函式 `src/api/security.py:check_auth_config`，即使繞過腳本直接以 `uvicorn src.api.app:app` 啟動亦會因拋出 `AuthConfigError` 阻斷。
- **本機開發放行旗標**：提供 CLI `--allow-no-auth` 或環境變數 `CLINICBRAIN_ALLOW_NO_AUTH=1` 供本機開發關閉認證。腳本啟動時會將 CLI 旗標同步映射至環境變數，確保 `--reload` 或多 worker 子行程皆能一致識別。啟動時於 `stderr` 印出繁體中文警告。若金鑰與開發旗標並存，以金鑰優先（強制驗證，不印警告）。
- **同步與查詢權限劃分**：
  - 同步端點（`POST /api/v1/sync/*`）：掛載 `verify_admin_key`。金鑰未設定且未開啟開發旗標時回傳 HTTP 503（Fail-Closed，拒絕靜默放行）；金鑰設定時比對 `X-API-Key`，未帶或不符回傳 HTTP 401。
  - 自然語言查詢端點與 `/health` 健康檢查端點維持公開開放，不需認證。
- **測試慣例**：`tests/conftest.py` 設有 autouse fixture `_default_allow_no_auth`，既有測試預設視為開發模式放行，維持測試穩定性；專門驗證強制行為與 503 的測試必須自行透過 monkeypatch 將 `allow_no_auth` 覆寫為 `False`。
- **後續規劃（尚未涵蓋）**：權限 600 之 `EnvironmentFile` 將於 AUTH-03 處理；金鑰常數時間比對（`secrets.compare_digest`）將於 AUTH-04 處理。

### 2.8 快取優先查詢與匿名命中統計（Phase 07 新增）
為降低本地 LLM 運算負擔並縮短病患常見問題之回應延遲，自 Phase 07 起導入快取優先（Cache-First）機制與匿名統計：
- **保守短路判定規則 (`src/query/faq_shortcut.py`)**：
  - 覆蓋率雙門檻：問句對 FAQ 覆蓋率 $\ge 0.9$、FAQ 對問句覆蓋率 $\ge 0.7$。
  - 歧義邊界（Ambiguity Margin）：最高分與次高分覆蓋率差距需 $\ge 0.1$。
  - 最小查詢長度：標準化（NFKC、去語助詞、去標點）後的查詢需 $\ge 4$ 字元，否則不短路（`query_too_short`）。
  - 營運資訊關鍵字不短路：問句含診所營運關鍵字（`_CLINIC_OPS_KEYWORDS`，如「營業時間」「地址」「電話」）時，`handle_query` 不啟用快取短路，改走原本營運資訊路由。
  - 風險特徵對稱比對（`extract_risk_features` / `risk_mismatch`）：以原文（僅 NFKC 與轉小寫，不去語助詞、不去標點）對查詢與最佳候選 FAQ 問句各擷取特徵計數，兩者**完全相等**才可短路，任一不對稱即拒絕（`risk_mismatch`）。實際共五個維度：
    1. 阿拉伯數字（含可選單位）：數字後可接 `個月|小時|分鐘|毫克|天|日|週|周|月|年|次|顆|片|mg|ml|cc|g|%`，數字與單位一併比對（如「3天」與「3週」、「5mg」與「5g」不得混淆；數字無單位時亦以數字本身比對）。
    2. 中文數字加量詞：中文數字（`一二三四五六七八九十兩半`）後接 `天|日|週|周|個月|月|年|次|小時|分鐘|顆|片|毫克`（如「三天」）。
    3. 否定/禁忌單字（14 字，逐字計次）：`不無沒別勿禁未非免避忌否戒停`，避免肯定句與否定句語意顛倒。
    4. 時序/方位字（4 字，逐字計次）：`前後內外`，避免「術前」與「術後」顛倒。
    5. 人群/體質限定詞（子字串計次）：`懷孕、孕、哺乳、嬰、兒、童、老、糖尿、男、女、過敏、高血壓、抗凝血、服藥、成人、長者、小孩、孩子、寶寶、小朋友、長輩、高齡`（後六個為 Phase 11 稽核補強的口語人群詞），避免特殊族群適用一般建議。
  - **價格詢問詞並非獨立風險維度**：程式碼中**沒有**「多少錢、費用、價格」等價格詢問詞規則（舊版文件曾誤載此維度，已更正）。含價格詢問的問句不短路，是仰賴既有機制（覆蓋率門檻、上述風險特徵不對稱、歧義邊界）達成，而非明確的價格詞規則；回覆內容之價格數字另由全域價格屏蔽（`deep_mask_prices()` 等）把關。
  - 判定順序與理由碼：`no_clinic` → `no_eligible`（僅考慮 `special` 路由且診所相符、或 `general` 路由且 `clinic_id IS NULL` 之 FAQ）→ `query_too_short` → `low_coverage` → `risk_mismatch` → `ambiguous` → `confident`。標準化問句與答案皆相同的重複項目會先合併（保留最小 row id）。
  - 獨立候選集大小：FAQ 檢索固定取 50 筆候選（`SHORTCUT_CANDIDATE_LIMIT`），不與 pageindex tree 檢索的 `top_k=3` 互相干擾。
  - 命中時直接回傳 FAQ 快取原文（回應 `source='cache'`；`source` 為 `Literal["cache","pageindex","llm"]`），略過 pageindex 推理樹與 LLM 生成。
- **匿名統計表結構 (`cache_stats`，日聚合計數)**：
  - 欄位：`id`, `clinic_id`（`NOT NULL DEFAULT ''`，無效或未提供時為空字串）, `stat_date`, `outcome`（`CHECK IN ('hit','miss','miss_keyword')`）, `keyword`（`NOT NULL DEFAULT ''`）, `count`, `updated_at`；`UNIQUE(clinic_id, stat_date, outcome, keyword)`，同鍵以 UPSERT 累加 `count`，不是逐筆事件紀錄（權威定義見 `src/db/clinic_schema.sql` 與 `src/query/cache_stats.py`）。
  - `outcome` 語意：`hit` = 快取短路命中，每次命中累加一列（`keyword=''`）；`miss` = 有資格短路但未命中的查詢，每個未命中查詢累加一列（`keyword=''`，為命中率分母）；`miss_keyword` = 該未命中查詢所比對到的每個固定路由關鍵字各累加一列。營運關鍵字查詢不啟用短路，因此不記 `miss`（也不計入命中率分母）。
  - `clinic_id` 僅在存在於 `clinic_info` 時採用，否則正規化為空字串，防範自由文字注入。
  - 隱私承諾：**嚴禁記錄問句原文或任何病患個資**。僅記錄透過固定詞表（`ROUTE_KEYWORD_VOCAB`）白名單過濾出之標準化路由關鍵字，詞表外字串一律捨棄。
- **統計指標語意與灌數限制**：
  - 命中率計算：`hit_rate` 定義為 `hit / (hit + miss)`（營運資訊查詢不計入分母；hit + miss 為 0 時回傳 `None`，API 回應為 `null`，而非 0.0；非零時四捨五入至小數第 4 位）。
  - 灌數風險處理：因自然語言查詢端點維持公開開放，有惡意灌數影響統計指標之風險；此風險採「接受（Accept）」處置，統計資料僅供院所營運熱度與 FAQ 補強參考，嚴禁作為計費、授權或醫療決策依據。
- **D-09 連線架構取捨**：
  - 為維持查詢端點唯讀連線 `PRAGMA query_only = ON;` 的嚴格唯讀保證，統計記錄採用獨立寫入連線非同步執行。
  - 統計寫入的所有例外一律全吞（Fail-Safe），確保主查詢回應絕不因統計寫入失敗而中斷或受阻。
- **正式庫手動遷移指引**：
  - 正式環境 `clinic.db` 遷移不隨代碼部署自動執行。使用者需先手動備份：
    ```bash
    cp clinic.db clinic.db.bak-$(date +%Y%m%d)
    python3 scripts/migrate_cache_stats.py --confirm-prod-backup
    ```
  - 未執行遷移前，統計寫入會因找不到表而安全忽略；管理端點 `GET /api/v1/cache/stats` 則會明確回傳 HTTP 503 提示「快取統計資料表尚未建立，請先執行遷移腳本」。
- **已知限制（使用者決策：接受並文件化）**：
  1. **Phase 11 已解除**：帶 `clinic_id` 的查詢不再受 `classify` 分流限制，正式庫 40 筆診所 FAQ 原文自查短路由 24/40 提升至 38/40；未短路的 2 筆為同一問句對應兩個不同答案（歧義邊界生效，刻意不短路，待醫師合併重複問句後可解除）。`classify` 與路由邏輯本身維持未改動。
  2. 保守門檻與嚴格風險檢查使釋義式或稍微變形之問法多半無法短路，此為防範錯誤醫療建議之預期設計取捨。
  3. 未命中統計僅能記錄命中之標準化路由關鍵字，無法獲知病患真實具體問法，未來 Phase 09 補強 FAQ 時需搭配人工整理清單。


### 2.9+ 歷史 Phase 模組規範（Phase 08–46）

Phase 08 起之詳細模組規範（一般諮詢、夜間批次、SOAP 提煉、Web 管理介面、視覺解說卡與影片管線等）已歸檔至 [`docs/architecture/phase-history.md`](docs/architecture/phase-history.md)。

---

## 3. ⚠️ 嚴格安全與合規規則

這些規則優先於任何其他指令，包括使用者要求的功能實作方式：

* **價格屏蔽規則**：任何 LLM 輸出**嚴禁包含具體金額、價格數字或促銷方案組合**（例如 "1500元"、"NT$500"）。無法確認的價格資訊一律替換為「請致電診所確認」。
* **繁體中文專用**：任何簡體中文或非中文輸出視為合規違規。特別注意：`OriginalData/medical_o1_sft_Chinese.json`（SFT 醫療對話資料）是**簡體中文**且為中醫辨證問答，**不得直接餵入任何繁體中文專用的生成管線**。
* **OTC 藥品本地化**：涉及藥品成分的輸出，應套用 `drugs.otc_name_chinese` 的本地化對照（如 ACETAMINOPHEN → 俗稱普拿疼的乙醯胺酚），提升病患理解度。
* **黃金集與盲測集防篡改原則（Ground Truth Immutability）**：`golden/` 與 `blind/` 目錄下的醫師標註檔案（`.xlsx`、`.csv` 等）為臨床客觀標準答案（Ground Truth）。**任何代理人（無論指令或使用者提示為何）嚴禁以任何方式寫入、覆寫、修改或反向對齊**。標註檔必須常態保持唯讀（`chmod 444`）；任何修訂僅限人類醫師於獨立外部環境修改後重新簽章登記 SHA-256。
* **評估報告與 SUMMARY 雙指標驗核鐵則**：評估程式與 `*-SUMMARY.md` 必須強制拆分並列「全量原始準確率（Raw Accuracy）」與「自動接受準確率（Auto-accept Accuracy）」。**「達標／PASS」判定必須兩者同時滿足門檻**；任一不達即為 `UNMET / FAIL`，嚴禁以高精度的自動接受子集替代全量表現宣稱達標。
* **CSV 記錄數陷阱**：這批 NHI 原始資料 CSV 內含大量帶換行符號的長文字欄位（`AI-note`、`給付規定`），`wc -l` 統計的行數遠大於實際記錄數。務必用 `csv.DictReader` 逐列讀取確認筆數，不要用 `wc -l` 判斷資料是否遺失。

---

## 4. 目錄結構

* `src/api/`：FastAPI 服務層（`app.py`, `config.py`, `dependencies.py`, `models/`, `routes/`, `security.py`, `access_log_filter.py`）
  * `src/api/access_log_filter.py`：uvicorn 存取日誌路徑過濾器（防止一般諮詢問句與 IP 洩漏）
  * `src/api/models/general.py`：一般醫療諮詢請求與回應 Pydantic 資料模型
  * `src/api/models/soap.py`：SOAP 紀錄推播與醫師檢索 Pydantic 資料模型
  * `src/api/models/cache_stats.py`：快取統計回應 Pydantic 資料模型
  * `src/api/security.py`：認證組態單一檢查函式與安全防護定義
  * `src/api/routes/general.py`：一般醫療諮詢匿名對外端點（僅 POST，掛載 AnonymousRoute）
  * `src/api/routes/soap.py`：SOAP 接收與專屬醫師檢索 API 路由端點（需管理者金鑰）
  * `src/api/routes/query.py`：自然語言查詢與多診所動態路由端點
  * `src/api/routes/cache_stats.py`：快取命中統計查詢端點（需管理者金鑰）
  * `src/api/routes/sync.py`：doctor-toolbox.com 官方雙向同步契約端點
  * `src/api/routes/health.py`：系統與資料庫健康檢查端點
* `src/batch/`：夜間批次排程與生成核心模組（`runner.py`, `run_log.py`, `topic_sources.py`, `faq_generator.py`, `tree_rebuild.py`）
  * `src/batch/patient_prefill_plan.py`：夜間批次階段 8 預生成意圖規劃、24 小時新鮮度與簽章比對純函式
  * `src/batch/patient_prefill.py`：夜間批次階段 8 主體醫學資訊預生成與唯一權威寫入管線
* `src/soap/`：SOAP 紀錄處理核心模組（`section_parser.py`, `deid.py`, `soap_writer.py`）
* `src/general/`：一般醫療諮詢核心業務模組（`__init__.py`, `disclaimer.py`, `red_flags.py`, `consult.py`）
  * `src/general/answer_compose.py`：病人端三段式回答組裝純函式、句界截斷與警訊句保護
  * `src/general/patient_compose.py`：病人諮詢已核准資料（診所與一般）組稿、層級標示與確定性降級
  * `src/general/patient_clinic.py`：病人諮詢伺服器固定單一診所設定安全驗證函式（純 SELECT，Fail-Closed）
  * `src/general/consult_jobs.py`：病人非同步諮詢作業登錄與管理模組（純記憶體 registry、TTL 讀後即刪）
* `src/db/clinic_schema.sql`：完整資料庫 schema，唯一權威來源（僅表結構，資料種子交給對應 Python 模組）
* `src/query/faq_shortcut.py`：高信心 FAQ 短路判定與五維風險特徵比對純函式
* `src/query/cache_stats.py`：匿名快取命中統計寫入與彙總函式（白名單過濾）
* `src/pageindex/faq_review.py`：FAQ 審核閘門狀態管理、四層驗證與可見性 SQL 產生器
* `src/pageindex/db_writer.py`：`page_index_trees` 的唯一 UPSERT 寫入與過期標記邏輯
* `src/pageindex/seed_trees.py`：PageIndex 樹的手寫種子內容（`source_type='manual'`）
* `src/pageindex/seed_clinic_info.py`：`clinic_info` 種子資料的唯一權威來源
* `src/pageindex/prompt_template.py`：LLM 生成臨床推理樹的 prompt 組裝 + 輸出驗證
* `src/pageindex/llm_client.py`：本地 LLM（llama-server）呼叫 adapter
* `src/pageindex/llm_lock.py`：跨執行緒共用生成鎖（`GENERATION_LOCK`）與夜間批次排程互斥探測模組
* `src/pageindex/faq_writer.py`：`faq_cache` 的唯一 UPSERT 寫入邏輯
* `src/pageindex/faq_conflicts.py`：相近診所問答衝突檢索模組（支援 visible_faq_sql 與唯讀模式）
* `src/ingestion/`：文件擷取管線（`extract_text.py`/`convert_chinese.py`/`generate_faq.py`）
  * `src/ingestion/medical_safety.py`：醫療合規安全驗證器（劑量/處方建議攔截 DX-1~6、就醫警訊收尾句檢驗）
  * `src/ingestion/markdown_convert.py`：markitdown 檔案轉 Markdown 前處理器（僅本機、無外掛、無外部 LLM、濾除內嵌圖片、檔頭檢查）
  * `src/ingestion/ocr_draft.py`：手動單張圖片 OCR 草稿模組（本機 Tesseract，絕不入庫）
* `data/batch/faq_seeds.json`：夜間批次 FAQ 與樹主題繁體中文種子清單（含一般疾病種子與標籤）
* `scripts/seed_database.py`：藥品/服務項目 CSV 匯入腳本，並呼叫 `seed_clinic_info`/`seed_sample_notes`
* `scripts/migrate_cache_stats.py`：`cache_stats` 資料表結構遷移腳本
* `scripts/migrate_faq_review_status.py`：`faq_cache.review_status` 審核欄位交易性遷移腳本
* `scripts/migrate_soap_schema.py`：`soap_records` 與 FTS5 觸發器單一來源 DDL 遷移腳本
* `scripts/migrate_faq_metadata.py`：`faq_cache.metadata` 欄位單一來源遷移腳本（`--confirm-prod-backup`、`--dry-run`）
* `scripts/distill_soap_faqs.py`：SOAP 衛教提煉批次 CLI（dry-run 唯讀）
* `src/pageindex/rag_ask.py`：管理端向 LLM 提問檢驗（僅用對外可見資料、紅旗／無資料不呼叫模型）
* `src/pageindex/batch_answer_job.py`：待審草稿背景批次補齊作業（單一作業、逐題 commit、LLM 離線中止、跨行程鎖）
* `src/batch/db_lock.py`：與夜間批次共用的 `<db>.nightly.lock` 非阻塞 flock 輔助函式
* `src/pageindex/answer_generator.py`：待審草稿 AI 輔助答案生成（本機 LLM、輸出端四層檢驗、樂觀鎖寫入）
* `src/soap/distiller.py`：SOAP 衛教提煉與草稿生成模組
* `scripts/run_nightly_batch.py`：夜間批次自動化排程 CLI 工具
* `scripts/review_faq.py`：醫師審核命令列互動工具（支援 list --topic、show 來源與相近診所 FAQ 檢視、approve、reject、reset 與 mark-regen 重生成標記）
* `scripts/mark_tree_regen.py`：臨床推理樹待重建手動標記工具
* `scripts/ocr_draft.py`：手動 OCR 草稿 CLI（單張圖片、固定警語、預設印到標準輸出）
* `scripts/run_stage1_ingestion.py`：文件擷取 Stage 1 端到端執行入口，僅寫入隔離測試複本
* `scripts/run_api_server.py`：FastAPI 服務啟動入口腳本（支援 CLI 參數）
* `scripts/probe_patient_thinking.py`：本地 LLM 思考關閉與解碼速率實機探測 CLI 腳本（需顯式核准 `--i-approve-live-probe`）
* `clinicbrain-api.service`：API 服務 systemd 配置範本
* `clinicbrain-nightly.service`：夜間批次排程 systemd 配置範本
* `clinicbrain-nightly.timer`：夜間批次排程定時器範本
* `docs/nightly-batch.md`：夜間批次與審核營運維護手冊
* `docs/soap-ingestion.md`：臨床語音與 SOAP 紀錄推播與檢索操作手冊
* `tests/test_clinic_first_acceptance.py`：診所資料優先檢索量測驗收測試（設計題 G，支援 CLINICBRAIN_ACCEPT_DB 指向複本，驗證 38/40 短路率）
* `tests/test_phase12_acceptance.py`：Phase 12 一般疾病內容生成與審核端到端整合驗收測試
* `tests/test_medical_safety.py`：用藥劑量與處方建議、就醫警訊多層醫療合規安全驗證測試
* `tests/test_disease_seeds.py`：一般疾病種子清單結構、標籤與簽核門檻測試
* `tests/test_faq_regen.py`：駁回題目手動標記重生成生命週期與批次優先級測試
* `tests/test_query_disclaimer_field.py`：自然語言查詢免責宣告欄位與資料層級測試
* `tests/test_sync_general_validation.py`：官方雙向同步匯入 general FAQ 前置合規驗證測試
* `tests/test_faq_conflicts.py`：相近診所問答衝突檢索與覆蓋率純函式測試
* `tests/test_real_llm_batch.py`：DEBT-04 本地真機 LLM（Qwen 27B）夜間批次生成、推理樹重建與日誌隱私端到端實跑驗證測試（自動檢測 llama-server，離線則安全跳過）
* `tests/test_soap_writer.py`：SOAP 紀錄權威寫入與 FTS5 觸發器同步驗證測試
* `tests/test_soap_deid_parser.py`：SOAP S/O/A/P 切分、一般醫學特徵擷取與去識別化測試
* `tests/test_soap_api.py`：SOAP API 推播接收、醫師專屬檢索與嚴格權限隔離端到端測試
* `tests/test_soap_hardening.py`：SOAP 去識別化與 API 防護補強測試（中文緊鄰遮蔽、HMAC 金鑰 Fail-Closed、外部識別欄位夾帶個資、錯誤不洩漏、LIKE 跳脫）
* `tests/test_regen_observability.py`：DEBT-03 重生成可觀測性測試（`mark-regen --seed`、`list` 重生欄、settle 回報列 id）
* `tests/test_markdown_convert.py`：markitdown 轉換前處理器測試（選用依賴，未安裝時略過）
* `tests/test_ocr_draft.py`：手動 OCR 草稿工具測試（含「不得 import 資料庫模組」AST 把關）
* `src/scraper/service_detail.py`：服務詳細頁說明擷取與標題取名規則（純函式，不寫入資料庫）
* `src/scraper/timetable.py`：門診表（週次 × 星期）HTML 表格解析（純函式，僅輸出開診狀態，不含醫師）
* `data/scraper/sources.json`：網址擷取白名單（`www.nu-vendome.com` 的 `/location-detail/`、`/service/`、`/service-detail/`）
* `tests/test_service_detail.py`、`tests/test_timetable.py`、`tests/test_clinic_selector.py`、`tests/test_url_deps_resolver.py`：上述模組與診所管理相關測試
* `tests/test_patient_consult_latency.py`、`tests/test_answer_compose.py`、`tests/test_patient_compose.py`、`tests/test_consult_jobs.py`、`tests/test_patient_prefill_plan.py`、`tests/test_patient_prefill_batch.py`、`tests/test_patient_prefill_e2e.py`、`tests/test_probe_patient_thinking.py`、`tests/test_patient_clinic_scope.py`、`tests/test_patient_prefill_special_e2e.py`：Phase 28 病人端對話式諮詢、延遲修復、非同步作業、24 小時預生成與伺服器固定診所範圍測試
* `src/visual/`：一般醫學視覺解說卡核心模組（`__init__.py`, `ir.py`, `writer.py`, `review.py`, `generator.py`, `match.py`, `stats.py`, `blueprints.py`, `autodraft.py`）
  * `src/visual/autodraft.py`：由已核准臨床推理樹自動生成受約束視覺解說卡草稿模組（零預設範本文字污染、永不自動核准）
* `data/visual/skeletons/autologous-fat-grafting.json`：自體脂肪移植視覺解說卡固定場景骨架定義檔
* `scripts/migrate_visual_assets.py`：`visual_assets` 與 `visual_stats` 單一來源 DDL 遷移腳本（`--confirm-prod-backup`、`--dry-run`）
* `scripts/generate_visual_assets.py`：視覺解說卡本地 LLM 預生成 CLI 腳本（寫入狀態恆為 `pending`）
* `scripts/review_visual.py`：視覺解說卡醫師審核 CLI 工具（`list`/`show`/`approve`/`reject`/`reset`）
* `scripts/autodraft_visual_from_trees.py`：由已核准推理樹批次生成視覺動畫草稿 CLI 腳本（`--tree-id`／`--all`，狀態恆為 `pending`）
* `tests/test_migrate_visual_assets.py`、`tests/test_visual_ir.py`、`tests/test_visual_writer.py`、`tests/test_visual_generator.py`、`tests/test_visual_cli.py`、`tests/test_visual_match.py`、`tests/test_visual_serving.py`、`tests/test_visual_stats.py`、`tests/test_consult_visual_ui.py`：Phase 29 一般醫學視覺解說卡資料層、IR 驗證、預生成、審核、比對、事件計數與前端渲染測試
* `src/visual/blueprints.py`：視覺場景 Blueprint 參數規格單一來源、調色盤代號常數、預設值與合併驗證函式
* `src/web/static/visual_engine.js`：視覺場景引擎前端純函式主程式（`ClinicVisual`、進度 $u$ 驅動、零被禁 API）
* `scripts/export_visual_bundle.py`：視覺解說卡 Bundle 唯讀匯出 CLI 腳本（`--allow-pending` 嚴禁用於正式庫）
* `demo/visual/player.html`、`demo/visual/player.js`：通用解說播放器展示頁面與控制腳本（嚴格路徑檢驗、外連預約卡）
* `demo/visual/render_video.py`：泛化 MP4 影片匯出腳本（支援 `--bundle`、無頭 Chromium 截圖、ffmpeg H.264 無聲合成）
* `data/visual/skeletons/hyaluronic-acid-filler.json`：玻尿酸填充原理視覺解說卡固定場景骨架定義檔（第二主題零 JS 改動證明）
* `docs/visual-blueprints.md`：視覺解說卡 Blueprint 規格與新增實作指南
* `tests/test_visual_blueprints.py`、`tests/test_visual_engine_static.py`、`tests/test_visual_engine_browser.py`、`tests/test_visual_bundle.py`、`tests/test_visual_player.py`、`tests/test_visual_video.py`、`tests/test_consult_engine_browser.py`、`tests/test_visual_second_topic.py`：Phase 30 視覺場景引擎規格、靜態安全、瀏覽器契約、Bundle 匯出、通用播放器、MP4 匯出與第二主題測試
* `tests/test_visual_autodraft.py`、`tests/test_visual_admin_api.py`、`tests/test_visual_review_ui.py`：Phase 31 由推理樹自動生成動畫草稿、管理審核 API 與審核介面「🎬 待簽核動畫」分頁測試
* `src/visual/auto_promotion.py`：診所核准資產自動昇華一般醫學核心模組（去診所化、複合唯一鍵無損共存）
* `scripts/promote_clinic_assets_to_general.py`：診所核准資產手動與批次自動昇華 CLI 工具
* `scripts/run_hermes_batch_49.py`：49 筆已核准推理樹專科動畫全自動批次生成與總結報告腳本
* `scripts/capture_plan32_scenes.py`、`scripts/capture_plan33_scenes.py`、`scripts/capture_scene3_evolution.py`：專科解剖圖元與三階段修復歷程無頭瀏覽器抽幀截圖工具
* `plan32_gallery.html`、`plan33_gallery.html`：專科動作、病理對照與修復歷程整合展示藝廊（含 HTML5 MP4 播放器）
* `.agents/skills/clinic-visual-batch/SKILL.md`：本地大模型批次生成與 Hermes Agent 自動化監控規範
* `tests/test_auto_promotion.py`：Phase 32 診所核准即自動昇華一般醫學資料層與邏輯測試
* `src/pageindex/tree_navigator.py`：PageIndex 推理樹節點導航、VectifyAI Schema 無損匯出與長文件依章節 TOC 均衡濃縮模組（`tests/test_tree_navigator.py`）
* `src/visual/icd10_catalog.py`、`src/visual/icd10_enrichment.py`、`data/icd10/primary_care_36_catalog.json`：Phase 35 臺灣基層診所 6 大專科（36 項 ICD-10-CM 常見疾病）器官病理藍圖（`pathology_mechanism`）、非手術誘因對照、三階段病程與四段式臨床知識管線（`scripts/seed_icd10_primary_care.py`、`scripts/enrich_icd10_primary_care.py`、`tests/test_icd10_primary_care.py`）
* `src/visual/harness_optimizer.py`、`data/visual/harness_lessons.json`、`scripts/harness_check.sh`：Phase 36 ClinicBrain Native Harness²（雙層遞迴自進化馬具：跨任務治理經驗記憶庫、臨床語意對齊評分器、`--k` 多候選探索與 V2 審核晉升自動沉澱，`tests/test_harness_optimizer.py`）
* `src/pageindex/text_harness.py`：Phase 37 Text Native Harness²（將雙層遞迴擴展至 FAQ 答案生成與推理樹四段式提煉；支援 36 項基層 ICD-10 疾病升格一般醫學共用推理樹，`tests/test_icd10_trees_and_text_harness.py`）
* `src/scraper/playwright_scraper.py`：Phase 38 Playwright 無頭 Chromium 動態網頁擷取器（`tests/test_playwright_scraper.py`）
* `src/scraper/site_crawler.py`：Phase 38 同網域廣度探索爬蟲、Sitemap 種子與路徑優先級排序（`tests/test_site_crawler.py`）
* `src/scraper/distill_pipeline.py`：Phase 38 智能知識提煉管線，由網頁內文自動生成 pending FAQ 與 PageIndex 推理樹（`tests/test_scraper_distill_pipeline.py`）
* `scripts/dedup_visual_assets.py`：Phase 39 視覺資產全庫去重與歷史舊版淘汰腳本（支援 `--dry-run`）
* `src/visual/nhi_dedup.py`：Phase 39 健保 200 大疾病去重篩檢器（`data/nhi_primary_care_200.json` 目錄比對）
* `data/nhi_primary_care_1_400_index.json`：Phase 40 臺灣健保基層門診 1-400 大疾病標準索引目錄（全景 400 筆，西醫 235、中醫 76、牙醫 48 與專科手術）
* `data/nhi_primary_care_201_400.json`：Phase 40 第 201 至 400 項次級盛行疾病專科目錄（200 筆標準種子）
* `src/query/nhi_index.py`：Phase 40 健保 1-400 疾病全景索引檢索與 LLM 選取模組（FTS5 trigram 混合分流，`tests/test_nhi_index.py`）
* `OriginalData/`：NHI 原始資料（gitignored，261MB，唯讀參考）
* `.planning/`：GSD 工作流程狀態（`HANDOFF.json`、`phases/`、`VISION-EXPANSION.md` 願景規劃）

---

## 5. 開發原則

* 每個 Phase 任務完成後，先用真實查詢/資料驗證（不是只看程式碼跑完沒報錯），再提交 commit。
* 修改 FTS5 相關 schema 後，必須實際執行一次中文關鍵字查詢驗證分詞正常，不能只信任「schema 語法正確」。
* 新資料來源在用於生成用途前，先確認語言與領域是否吻合（見 2.2 節的踩雷案例：SFT 資料語言不對、`service_items.payment_rules` 只是給付範本無臨床細節）。
* 任務範圍要守住邊界：不要因為手邊在做某個任務，就順手把後續任務（如查詢層、LLM 生成邏輯）的工作也做掉，會混淆任務追蹤與驗收界線。
* 完整的未來願景與待決策事項見 `.planning/VISION-EXPANSION.md`，不要重複在這裡展開。

---

## 6. 未來里程碑規劃 (Future Roadmap & Next To Do)

* **Phase 39（已交付）：健保 200 大疾病動畫批次編譯、全景審核矩陣與資產去重**
  - 完成雙模型編譯流程（DeepSeek 提煉部位特徵 + 本地 8080 編譯 24 秒 IR）。
  - 新增牙科 (`dental_oral`)、中醫 (`tcm_meridian`) 等專科圖元藍圖。
  - 後台實裝「臨床知識庫資產審核全景矩陣」與「🎬 醫學動畫管理」快捷膠囊。
  - 實施全庫視覺資產去重，剔除 161 筆歷史舊版，收斂為 198 筆唯一權威 24 秒醫學動畫。
* **Phase 40（已交付）：臺灣健保 201-400 大次級盛行疾病動畫管線與全景索引擴充 (NHI 201-400 Scale & Index Expansion)**
  - 建立 1-400 大基層疾病資料庫全景索引（`nhi_catalog_1_400` + `nhi_catalog_fts`），提供 LLM 在診所諮詢時精準引用。
  - 擴充第 201 至 400 項次專科解剖圖元（眼科黃斑部、耳鼻喉哮吼聲帶、泌尿精索、牙周 GTR、中醫特種針法）。
  - DeepSeek 與本機雙模自癒生成 200 筆 24 秒動畫草稿，完成 Playwright 抽幀審計與 200 筆 pending 入庫（全庫收斂為 400 筆資產）。
* **Phase 41：動態規格標準化與 3D 臨床解剖探索 (Motion-Prompt Integration & BodyVista 3D Anatomy PoC)**
  - 將 `motion-prompt` 動態規格與緩動預設抽取為輕量模組整合至 `clinic-visual-batch`。
  - 本機 clone `FreedomIntelligence/BodyVista` 執行沙盒 PoC，評估 3D 解剖模型檔案體積與醫美專科精細度。
  - 若 PoC 通過，規劃 3D 解剖檢視器前端組件與 PageIndex `doc_id` 自動連動架構。
* **Phase 44：次世代生動向量視覺引擎全面升級 (Next-Gen Dynamic Vector Visual Engine)（優先執行中）**
  - 在 `visual_engine.js` 封裝 `ClinicMotion` 物理數學庫（非線性緩動、果凍回彈、呼吸微律動）。
  - 全量升級 11 大專科藍圖（2.5D 半透明體積漸層、高光掃過、深層環境陰影與同心圓漣漪）。
  - 對照場景顫動與修復時間軸金色粒子綻放演繹。
  - Playwright 確定性渲染驗證，零資料庫遷移，使全庫 398 部動畫立竿見影煥然一新。
* **Phase 43：自動化動態解說動畫影片佇列 (Automated Explainer Video Queue)（Phase 44 完成後接續）**
  - 整合 `demo/visual/render_video.py` 與夜間批次排程，將已升級次世代光影之 24 秒動畫自動渲染為 1080p H.264 MP4（16:9 橫屏與 9:16 豎屏雙規格）。
  - 供診所電視看板、衛教平板離線循環播放與社群媒體短影音推播。
* **Phase 42：病人端多診所聯合諮詢與即時引導 (Multi-Clinic Patient Federated Consultation)**
  - 在病人諮詢端點支援自適應推薦診所與院所特約醫師門診時段。
  - 動態關聯已昇華之基層 ICD-10 解說動畫卡，並強化門診就診預約引導。
* **Phase 51–52（已交付）：NHI400 解剖映射對齊與全庫 398 筆雙層深度稽核**
  - `scripts/build_nhi400_manifest.py`、`scripts/audit_manifest_anatomy.py` 與 `scripts/audit_db_visual_assets.py --strict` 建立「語意器官系統 + `visual_engine.js` `pmPickAnatomyDrawer()`」雙層稽核，確保 398 筆（320 筆 `pathology_mechanism`）零錯配。
  - `src/web/static/visual_engine.js` `PATHO_ORGAN_SYSTEMS` 補齊全部 15 個器官系統，並於 `src/visual/video_queue.py` `compute_ir_sha256()` 納入 `visual_engine.js` SHA-256 salt 連動增量快取。
* **Phase 53（已交付）：雙軌混合衛教系統與全庫 398 筆 `edu_json` 升級**
  - 新增 `care_redflag` 藍圖（`src/visual/blueprints.py`、`src/visual/ir.py`、`src/web/static/visual_engine.js` `drawCareRedflag()`，嚴格限縮於 `y <= 392` 避開字幕區）。
  - `visual_assets` 新增 `edu_json` / `edu_updated_at`（`src/visual/edu_schema.py`、`src/visual/edu_generator.py`、`scripts/generate_edu_batch.py`），鎖定 Phase 52 已核定 `organ_system` 與 `anatomy_target` 並完成全庫 398/398 筆生成與 398 支橫屏 MP4 重渲。
  - 新增 `GET /api/v1/visual/edu/{topic_key}`（`review_status = 'approved'` + `deep_mask_prices()`）與獨立可列印單張 `GET /edu/{topic_key}`（`src/api/app.py`、`src/web/static/edu.html`、`edu.js`）。
