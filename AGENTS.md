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
單一 SQLite 資料庫 `clinic.db`（**gitignored，不進版控**，由腳本重建）：
- `drugs`：377K+ 藥品項目來源 CSV，實際匯入 7,573 筆（CSV 換行數 ≠ 記錄數，勿用 `wc -l` 估算）
- `service_items`：2,669 筆醫療服務給付項目
- `page_index_trees` + `page_index_fts`：PageIndex 臨床推理樹（見 2.2）
- `faq_cache` + `faq_cache_fts`：文件擷取/夜間批次產出的常見問答快取（見 2.4）
- `cache_stats`：快取優先查詢之匿名聚合命中統計（見 2.8）
- `sync_logs`：雙向資料同步契約審計紀錄（見 2.5）
- `soap_records` + `soap_records_fts`：臨床語音與 SOAP 紀錄及全文檢索（見 2.13）
- `clinic_info` / `clinic_hours` / `clinic_custom_notes`：診所專屬層

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

### 2.9 一般醫療諮詢入口（Phase 08 新增）
為提供民眾安全、匿名且合規之一般醫療衛教諮詢管道，自 Phase 08 起建立專屬一般諮詢架構：
- **獨立匿名端點 (`POST /api/v1/general/query`)**：
  - 匿名無綁定：不要求 `X-API-Key`，不接受亦不需 `clinic_id`；若客戶端夾帶 `clinic_id` 或 `X-Clinic-ID` 標頭一律靜默忽略。
  - 資料庫隔離（GENERAL-04）：僅檢索 `category='general' AND clinic_id IS NULL` 之 `faq_cache` 與 `page_index_trees`；嚴格隔離診所私有資訊，絕不查詢藥品、健保服務給付項目與診所營運資料表；完全不呼叫外部 LLM 模型。
  - 目前資料現況：正式資料庫內 general 類資料目前為 0 筆，所有非紅旗問句皆會誠實回傳 `no_match`（不捏造醫療內容）；general 衛教內容須另經醫師審核後始得入庫。
- **急重症紅旗偵測 (`src/general/red_flags.py`)**：
  - 單一權威詞表：定義 13 條規則（E01~E08, U01~U05），分為 `emergency`（立即撥打 119/急診）與 `urgent`（當日儘速就醫）兩級。
  - 優先短路：問句命中紅旗時立即回傳固定就醫指示，完全不進行分詞、不存取資料庫。
  - 保守醫療策略：否定語境（如「沒有胸痛」）刻意仍觸發；填充劑血管阻塞徵兆（E08）須與注射語境同句才觸發，並附加「聯絡施作診所」提示。
  - 邊界決策：依使用者決策，精神心理類不在本表範圍；新增或修改詞表須經使用者審閱並補漏報導向正例與誤觸發負例測試。
- **免責聲明與就醫提示 (`src/general/disclaimer.py`)**：
  - 本模組為固定文字唯一權威來源。所有對外回覆（包含回答、無資料、紅旗警示）一律強制附帶法定醫療免責宣告，明確告知無法取代醫師面對面親自診察。
- **傳輸層與日誌隱私承諾（GENERAL-03）**：
  - 零日誌與無狀態：不寫入任何資料庫資料表、不記錄 `cache_stats`、回應模型刻意不回顯 `query` 欄位。
  - 僅提供 POST 方法：問句置於請求主體，不進入 URL；同路徑之 GET 請求回傳 405 Method Not Allowed。
  - 存取日誌過濾 (`src/api/access_log_filter.py`)：`ExcludeGeneralPathFilter` 自動攔截並整行丟棄 `uvicorn.access` 中所有 `/api/v1/general` 開頭之路徑紀錄（含 IP 與 query string）；反向代理（如 Nginx）若另有存取日誌，須自行對此路徑關閉記錄。
- **輸入驗證與錯誤防禦**：
  - 自訂路由 `AnonymousRoute(APIRoute)` 攔截所有 `RequestValidationError`，一律回傳固定繁體中文 `{"detail": "請求格式不正確"}`（HTTP 422），防範 FastAPI 預設錯誤在 `detail[].input` 回顯使用者敏感問句。
  - 單次請求成本受限於問句長度（1-300 字元）與數量上限（`limit <= 10`）。
- **認證決策與速率限制建議**：
  - 本端點作為大眾匿名入口，刻意不加管理員金鑰。潛在濫用風險為唯讀計算負載。
  - 建議於反向代理層使用 `limit_req` 實施速率限制；若未來於應用層實作，僅得使用純記憶體計數，嚴禁持久化病患 IP 或問句。
- **已知限制與後續項目（不在本 Phase 處理）**：
  1. 既有 `GET /api/v1/query?q=` 仍會在存取日誌中留下問句，且 `POST /api/v1/query` 走 `handle_query` 流程，不屬本端點之匿名承諾範圍，一般民眾入口請一律使用 `/api/v1/general/query`。
  2. `consult_general` 沿用既有 `extract_search_terms`，長問句若未含停用詞可能切出過長片段影響 FTS 命中率；後續可考慮評估 2~3 字滑動窗口詞彙。
- **測試慣例**：
  - general 樹無專用寫入路徑（`upsert_trees` 需機構代碼），測試在暫存複本以 raw INSERT 建立 `clinic_id IS NULL` 的 general 樹；general FAQ 則透過權威寫入函式 `faq_writer.upsert_faqs` 寫入。

### 2.10 夜間批次生成與審核閘門（Phase 09 新增）
為達成離峰預先生成常見問答、減輕醫師日常重複解答負擔，並自動更新過期臨床推理樹，自 Phase 09 起導入夜間批次與審核閘門架構：
- **醫師審核閘門語意 (`faq_cache.review_status`)**：
  - 狀態列舉：`pending`（待審核）、`approved`（已核准）、`rejected`（已駁回）。
  - 可見性規則：`manual`（手寫）與 `clinic_upload`（CLI／同步匯入之院所權威來源）恆常對外可見；由本地模型生成之 `llm_generated` 資料預設寫入為 `pending`，在未獲醫師核准前對外完全隱蔽。
  - 單一權威讀取與寫入路徑：
    - `src/pageindex/faq_review.py:visible_faq_sql` 為所有 FAQ 查詢可見性過濾條件的唯一來源；新增任何 FAQ 讀取邏輯一律須經 `search_faq_cache` 或引用此條件。
    - `src/pageindex/faq_review.py:set_review_status` 為修改審核狀態之唯一寫入路徑；核准前強制重跑四層醫療合規檢核；可見性改變時自動遞增 `content_version`。
  - 消費端全面套用：自然語言查詢（含快取短路 `handle_query`）與同步匯出（`POST /api/v1/sync/export`）皆已無條件套用審核閘門，確保未核准項目零洩漏。
- **資料庫遷移與 Fail-Closed 防禦**：
  - 正式庫遷移指令：先手動備份 `cp clinic.db clinic.db.bak-$(date +%Y%m%d)`，後執行 `python3 scripts/migrate_faq_review_status.py --confirm-prod-backup`。
  - 未遷移庫防禦：未完成遷移之舊庫在寫入 `llm_generated` 時一律拋錯拒絕（Fail-Closed）；檢索端則退化為完全排除 `llm_generated` 內容。
  - **遷移 DDL 單一來源（Phase 10）**：`scripts/migrate_faq_review_status.py` 的 `ALTER TABLE ... ADD COLUMN` 不再手寫，由 `src/db/clinic_schema.sql` 的 `faq_cache` CREATE TABLE 區塊依欄位名稱擷取（`extract_column_definition`）。約束：`review_status`、`reviewed_at` 的欄位定義必須單行、定義文字內不得含 `--`；解析失敗在連線前即拋 `RuntimeError`（fail-closed）。修改這兩欄定義只需改 schema。
- **批次執行器與資源防禦 (`src/batch/runner.py`)**：
  - 執行入口：`python3 scripts/run_nightly_batch.py`。
  - 多重資源保護：`--max-faq-topics`（預設 5）、`--max-trees`（預設 3）、`--max-pending`（預設 200，保護醫師審核負擔）、`--time-budget-seconds`（預設 3600.0，超時優雅中斷）、`--llm-timeout`（單次推論逾時 120 秒）。
  - 單筆失敗隔離：單一主題或單一推理樹處理失敗不影響同批其他項目。
  - 本地 LLM 離線降級：健康檢查或中途遇到 `LocalLLMUnavailableError` 時優雅中止，保留已完成項目並記錄日誌，以結束碼 0 退出，不造成排程失敗。
- **臨床推理樹重建與【重建會覆蓋手寫內容】重要警示**：
  - 唯一標記入口：`src/pageindex/db_writer.py:set_needs_regeneration`，提供 CLI 工具 `scripts/mark_tree_regen.py`。
  - 繞過閘門取捨與後果：臨床推理樹重建**不走審核閘門**；被標記重建的手寫樹（`manual` 或 `clinic_upload`）其四段臨床內容與摘要將直接被 LLM 覆蓋，`source_type` 變更為 `llm_generated`。
  - 補償防護機制：
    1. 醫師權威註記保護：四段之 `*_physician_notes` 覆寫既有值，寫入後一致性校驗，若被清空自動執行前像還原。
    2. 自動前像快照：重建前將既有內容以 JSON 格式儲存於 `logs/nightly_batch/tree_snapshots/`。
    3. 審核警告事件：覆蓋手寫內容時於日誌發出醒目的 `tree_overwrote_handwritten` 警告並累計至摘要。
- **主題種子清單 (`data/batch/faq_seeds.json`)**：
  - 結合熱門未命中關鍵字（過去 14 天累計未命中次數達門檻）與 `always` 候選分流。
  - 所有問題由人撰寫，載入時強制四層醫療合規檢查；全部題目皆已存在的主題自動跳過且不佔名額（不餓死其他主題）。
- **非阻塞檔案鎖與日誌隱私保證**：
  - 鎖檔位置：固定位於目標資料庫同目錄（`<db_path>.nightly.lock`），跨不同 log 目錄皆具互斥性，不重疊執行。
  - 預設 log-dir 解析為專案絕對路徑 `logs/nightly_batch`。
  - 日誌隱私範圍：`RunLogger` 嚴禁記錄 `query/question/answer/prompt/raw` 等鍵名；批次期間透過 `content_loggers_silenced()` 靜音內部 logger，保證程式產生日誌無問句與模型原文；第三方 logger 不在保證內。
- **結束碼定義**：0 = 完成或優雅跳過（含 dry-run、LLM 不可用、持鎖略過、預算用盡）；1 = 未預期例外；2 = 參數/前置檢查拒絕。
- **排程服務與啟用規範**：
  - 提供 `clinicbrain-nightly.service`（oneshot）與 `clinicbrain-nightly.timer`（凌晨 02:30，含 Persistent 補跑）範本。
  - 專案依規範絕不代為啟用或啟動任何 systemd 服務，由使用者自行規劃啟用。
- **已知限制（架構決策接受）**：
  1. `/api/v1/sync/import` 以 `clinic_upload` 寫入，若與既有 pending/rejected 的 `llm_generated` 列同鍵，會覆寫並變更為 approved（外部匯入視為院所權威來源）。
  2. `local_llm_call` 逾時會轉為 `LocalLLMUnavailableError`，單次逾時即讓批次提前優雅結束（結束碼 0），留待下一晚繼續。
  3. 樹重建繞過審核閘門（如上述，以快照與註記還原為補償防線）。
  4. 未命中關鍵字僅記錄標準化白名單字詞，無法獲知病患真實具體問法。
  5. 批次的 `existing_questions` 去重（`src/batch/faq_generator.py`）不分審核狀態與資料來源，被駁回（`rejected`）的題目仍視為已存在，因此永遠不會被重新生成；如需重生須由人工另行處理（例如改寫題目文字或人工刪除該列；Phase 12 起可由 review_faq mark-regen 明確觸發重生成，見 2.12）。
- **真實本地模型批次驗證（Phase 13 DEBT-04 完成）**：
  - 於完全隔離之資料庫複本上，以真實本機推論引擎（`llama-server` + Qwen3.8-27B-UD-Q4_K_XL）完成端到端全流程實跑驗證（測試：`tests/test_real_llm_batch.py`）。
  - 實測單題 FAQ 生成耗時約 32 秒，通過五層醫療合規檢核並寫入 `review_status='pending'`，對外檢索維持零洩漏；臨床推理樹重建耗時約 140 秒，自動建立前像快照並完整保護既有醫師權威註記；`RunLogger` 經白名單審核確認日誌完全無病患個資或模型內容洩漏。
  - 正式 `clinic.db` 全程以唯讀保護並比對 SHA-256 雜湊值（`ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e`），驗收確認正式庫零寫入零污染。
  - `llm_client.local_llm_call` 現參數：`max_tokens=6144`、`reasoning_effort="low"`、預設逾時 420 秒；回傳前對模型輸出套用 `to_traditional`（簡轉繁）。**取捨**：模型偶發的簡體輸出會被悄悄轉成繁體，下游四層驗證的「簡體字」檢查對 LLM 輸出不再觸發也不留痕；其餘四層驗證仍獨立把關。
  - 日誌新增 `faq_regen_unchanged_ids`／`faq_regen_failed_ids`（列 id，非敏感資訊，不含題目或答案）。

### 2.12 一般疾病內容生成與審核（Phase 12 新增）
為使系統能以合規且安全的方式提供常見疾病（如感冒、流感、急性腸胃炎、過敏性鼻炎）之衛教問答，自 Phase 12 起導入一般疾病內容生成、多層合規防禦與審核增強機制：
- **擴充疾病種子清單 (GC-01)**：
  - 種子清單支援擴充主題與可選之 `question_tags` 標籤，分類包含 what、symptoms、when_to_see_doctor、home_care（程式：`src/batch/topic_sources.py:QUESTION_TAGS`；測試：`tests/test_disease_seeds.py::test_question_tags_constant`）。
  - 簽核四項常見疾病（感冒、流感、急性腸胃炎、過敏性鼻炎）共 17 題繁體中文問答種子入庫，所有項目皆通過格式與分類檢驗（程式：`src/batch/topic_sources.py:load_seed_file`；測試：`tests/test_disease_seeds.py::test_seed_file_structure_and_disease_coverage`）。
  - 夜間批次預設採用簽核之種子清單，端到端驗收確認 4 主題與 17 題正確載入（程式：`src/batch/runner.py:BatchConfig`；測試：`tests/test_phase12_acceptance.py::test_01_preflight_seed_topics`）。
- **用藥劑量與處方建議攔截層 (GC-02)**：
  - 實作劑量與處方安全規則（DX-1~DX-6），攔截阿拉伯數字劑量、中文數字劑量、處方用藥建議，並保留「請遵照醫囑」「請勿自行增減」之免責豁免（程式：`src/ingestion/medical_safety.py:check_dosage_prescription`；測試：`tests/test_medical_safety.py::test_validate_single_faq_default_disabled`）。
  - **2026-10-06 複審補強（`5714714`）**：① DX-2 涵蓋「只有數量、句中無藥名」的劑量句（「每次吃2顆」「小孩一次吃半顆」「吃3片就夠了」，「吃N片」排除吐司、水果等食物）；② DX-4/DX-5 的否定豁免改為**否定詞必須緊鄰給藥動詞**（`請勿自行服用…` 豁免，`請勿擔心可吃止痛藥` 不豁免）；③ 詞庫補糖漿、栓劑、噴劑、針劑、口服液、止瀉劑、退燒貼／針與 acetaminophen、tylenol 等英文學名。**詞庫為封閉式，未列名的藥與劑型仍可能漏攔，最終仰賴醫師審核。**
  - 實測精確度（封閉語料，不代表泛化能力；複審另以 50 句獨立正例實測曾漏 20 句，補強後以獨立新語料測試）：劑量正例 47/47 攔截、負例 50/50 放行；正式庫既有 40 筆診所 FAQ 回掃 0 誤拒（包含診所 FAQ id 6 之「給予抗生素」描述性敘述）（程式：`src/ingestion/medical_safety.py:check_dosage_prescription`；測試：`tests/test_medical_safety.py::test_backscan_clinic_upload_faqs`）。
  - 批次生成管線全面啟用劑量攔截，違規項目分類為 `dosage_prescription` 拒絕代碼（程式：`src/batch/faq_generator.py:generate_topic_faqs`；測試：`tests/test_medical_safety.py::test_classify_dosage_prescription_code`）。
- **就醫警訊強制檢驗與免責聲明欄位 (GC-03)**：
  - General 類別問答之 answer 強制要求具體症狀或數值條件之就醫警訊收尾句，實測正例 15/15 通過、負例 17/17 攔截；單純「若症狀加重請回診」單獨出現視為不合規。**複審補強**：勸人別就醫的反向句（「胸痛時不要去醫院」「無需前往醫院」）不算警訊；條列式「請儘速就醫：1. 高燒超過3天 2. 呼吸困難」會併入前一行判斷（LLM 回答「何時就醫」最常見的格式）。已知寬鬆：「出現高燒時應就醫」（單獨一個危險症狀即算具體條件）視為合格（程式：`src/ingestion/medical_safety.py:has_doctor_warning`；測試：`tests/test_medical_safety.py::test_classify_missing_doctor_warning_code`）。
  - 批次生成針對 general 主題注入第 9 條 Prompt 就醫警訊收尾規則，違規者以 `missing_doctor_warning` 剔除（程式：`src/batch/faq_generator.py:build_seed_faq_prompt`；測試：`tests/test_medical_safety.py::test_prompt_build_seed_faq_prompt_rules`）。
  - 雙向資料同步匯入（`/api/v1/sync/import`）對 general FAQ 實施前置合規檢核，劑量違規或缺警訊者以 HTTP 400 整批原子性阻斷；special 類別維持豁免（程式：`src/api/routes/sync.py:import_sync_data`；測試：`tests/test_sync_general_validation.py::test_sync_import_general_faq_dosage_blocked_and_atomic`）。
  - 自然語言查詢回應結構純加法擴充 `disclaimer: Optional[str] = None` 欄位；當 `data_level == 'general'` 時自動附帶法定醫療免責宣告文字，診所層級為 null（程式：`src/query/router.py:handle_query`；測試：`tests/test_query_disclaimer_field.py::test_query_response_disclaimer_general_shortcut`）。
  - 匿名諮詢端點與自然語言查詢端點在 general 題目命中時皆附帶免責聲明（程式：`src/api/routes/query.py:_execute_query`；測試：`tests/test_query_disclaimer_field.py::test_api_query_endpoint_disclaimer`）。
- **醫師審核工具增強與衝突比對 (GC-04)**：
  - 提供共用覆蓋率純函式，沿用與快取短路同一套標準化與覆蓋率計算（程式：`src/query/faq_shortcut.py:faq_coverage`；測試：`tests/test_faq_conflicts.py::test_faq_coverage_measurements`）。
  - 審核 general 問答時自動檢索相近診所 FAQ，門檻引用 `CLINIC_RELATED_FLOOR = 0.4`，嚴格隔離未核准之 LLM 生成診所問答，支援 mode=ro 唯讀連線（程式：`src/pageindex/faq_conflicts.py:find_similar_clinic_faqs`；測試：`tests/test_faq_conflicts.py::test_find_similar_clinic_faqs_retrieval`）。
  - 審核工具 `review_faq.py list` 支援 `--topic` 主題篩選與來源/驗證結果顯示；`show` 顯示生成來源、驗證結果與相近診所問答；`approve` 強制檢驗 general 警訊（程式：`scripts/review_faq.py:main`；測試：`tests/test_review_faq_cli.py::test_cli_show_general_similar_clinic_faqs`）。
- **被駁回題目手動標記重生成 (DEBT-03)**：
  - 唯一標記函式 `mark_for_regeneration` 僅允許標記 `rejected` 狀態之 `llm_generated` 項目（程式：`src/pageindex/faq_review.py:mark_for_regeneration`；測試：`tests/test_faq_regen.py::test_mark_for_regeneration_restrictions`）。
  - 批次生成 `existing_questions` 支援 `exclude_regen_marked=True`，優先處理被標記之主題（程式：`src/batch/faq_generator.py:existing_questions`；測試：`tests/test_faq_regen.py::test_existing_questions_exclude_regen_marked`）。
  - CLI `mark-regen` 子命令提供醫師標記入口，未帶 `--allow-prod-db` 於連線前以 code 2 阻斷正式庫操作；新增 `--seed`（預設 `data/batch/faq_seeds.json`），**題目不在人寫種子清單內者回報 `not_in_seed` 並拒絕標記**（夜間批次只重生成種子內題目，種子外的旗標會永遠殘留）；種子檔載入失敗時僅警告並略過此檢查。`list` 新增「重生」欄顯示「待重生」（程式：`scripts/review_faq.py:main`；測試：`tests/test_review_faq_cli.py::test_cli_mark_regen_subcommand`）。
  - 端到端重生成生命週期：標記重生成後新答案以 `pending` 入庫且版號遞增；若模型回傳相同答案則清除重生成旗標並維持 `rejected`，避免無限生成（程式：`src/batch/runner.py:run_batch`；測試：`tests/test_phase12_acceptance.py::test_04_regeneration_lifecycle_debt03`）。
- **端到端驗收保證**：
  - 17 題正式種子批次生成後預設 pending 隱蔽；醫師 CLI 核准後自然語言與一般諮詢皆正確命中；正式庫 SHA-256 全程未變（程式：`tests/test_phase12_acceptance.py`；測試：`tests/test_phase12_acceptance.py::test_02_e2e_generation_approval_and_consultation`）。
  - 同步匯出閘門：未核准前不外洩 17 筆 general FAQ，核准後包含於匯出資料（程式：`src/api/routes/sync.py:export_sync_data`；測試：`tests/test_phase12_acceptance.py::test_05_sync_export_gate`）。
- **已知限制（架構決策接受）**：
  1. **詞彙守衛非主題守衛**：覆蓋率相近比對（`find_similar_clinic_faqs`）為詞彙重疊守衛；17 題一般疾病種子對院所既有 40 筆醫美外科 FAQ 最高詞彙覆蓋率皆 $\le 0.30$（$< 0.4$），衝突清單為空不代表臨床無指示衝突，審核工具 show 一律附帶醒目警語提示醫師自行比對。
  2. **免責聲明範圍**：僅自然語言查詢 `/api/v1/query`（在 `data_level == 'general'` 時）與匿名諮詢端點 `/api/v1/general/query` 附帶免責聲明；雙向同步匯出（`/api/v1/sync/export`）與審核工具（`review_faq.py`）維持純淨資料結構，不額外附加免責字串。
  3. **重生成採一次標記一次嘗試**：為防範模型死循環，被標記之題目在批次中僅嘗試生成一次；若產出實質新內容則更新入庫回到 `pending`，若產出內容未變則清除重生成旗標並維持 `rejected`（計入 `faq_regen_unchanged`），不重複消耗推論配額。
  4. **劑量／處方層為條件式檢驗**：用藥安全檢核透過 `check_dosage` 與 `require_doctor_warning` 參數啟用，文件擷取（`run_stage1_ingestion.py`）與院所特殊上傳項目預設不強制套用；DX-4/DX-5 對「遵照醫囑」「請勿自行」具有豁免；「給予抗生素」描述性敘述不予攔截；「若醫師開立藥物，請依指示服用」則採保守攔截策略。
  5. **就醫警訊之結構要求**：警訊收尾必須同時具備「具體症狀或數值條件」與「就醫動作」；單獨「若症狀加重請回診」因缺乏具體辨識指引，視為不合規。
  6. **審核狀態變更之警訊檢核預設關閉**：`faq_review.set_review_status` 底層預設 `enforce_general_warning=False`，僅醫師審核 CLI（`review_faq approve`）明確傳入 `enforce_general_warning=True` 進行強制把關。

### 2.13 臨床語音與 SOAP 紀錄擷取（Phase 14 新增）
為接收外部雲端推播（如 `https://doctor-toolbox.com/`）或院內語音聽寫逐字稿，並將臨床資料分析擷取應用於醫療輔助與檢索，自 Phase 14 起導入 SOAP 紀錄接收、去識別化與專屬醫師檢索架構：
- **結構化與純文字雙重相容 (`src/soap/section_parser.py`)**：
  - 支援傳入已結構化之 S/O/A/P 欄位，或從 `raw_text` / `transcript` 純文字中依臨床常見中英標記（S/主訴/病史、O/客觀檢查/理學檢查、A/評估/診斷、P/處置/計畫/醫囑）自動正則切分；無明顯標記時安全退化歸入主訴（`subjective`）。
  - **一般醫學特徵擷取 (`extract_general_medical_insights`)**：從臨床文本中自動辨識常見病症、症狀與衛教照護指示，歸納為一般醫學特徵並回傳摘要與標籤。
- **病患個資去識別化與二次防禦 (`src/soap/deid.py`)**：
  - 身分證字號遮蔽（支援台灣身分證驗證與掩碼）、行動電話（09xx-xxx-xxx）、市話、病患姓名標籤遮蔽為 `[已遮蔽]`。
  - 價格數字全面套用 `deep_mask_prices()` 遮蔽為 `[請致電診所確認]`，杜絕未核定金額寫入。
  - `patient_token` 衍生：未提供 token 且有外部病患識別時，以 HMAC-SHA256 結合環境變數 `CLINICBRAIN_DEID_KEY`（退回 `CLINICBRAIN_ADMIN_API_KEY`）與診所代碼生成偽名化 token；**程式碼內不得有預設金鑰**（身分證搜尋空間小，公開 salt 可被字典攻擊還原），未設定金鑰時帶 `patient_id` 的推播回 503（Fail-Closed）。
  - 遮蔽正則不得使用 `\b`（Unicode 下中文字視為 `\w`，「身分證A123456789」會漏遮蔽），改用 `(?<![A-Za-z0-9])`／`(?<!\d)` 前後斷言。
  - 外部傳入的 `patient_token`／`external_id` 須為安全字元集且不得形似身分證或電話，`tags` 一併去識別化。
  - **已知限制**：自由文本中沒有「姓名／病患：」等標籤的人名無法可靠偵測，不會被遮蔽；推播來源應在上游去識別化，本層僅為二次防線。
- **單一權威寫入函式 (`src/soap/soap_writer.py:upsert_soap_records`)**：
  - 以 `(clinic_id, external_id)` 為唯一約束進行冪等 UPSERT；內容未變則安全跳過，更新時自動更新 `updated_at`。
- **醫師專屬 FTS 檢索與嚴格權限隔離 (`src/api/routes/soap.py`)**：
  - `POST /api/v1/soap/records`、`POST /api/v1/soap/search`、`GET /api/v1/soap/records/{external_id}` 掛載 `verify_admin_key` 認證。
  - 強制綁定 `clinic_id`，落實嚴格診所隔離；公開自然語言查詢端點（`/api/v1/query` 與 `/api/v1/general/query`）完全無法存取 `soap_records`。
- **資料庫遷移單一來源 (`scripts/migrate_soap_schema.py`)**：
  - 從 `src/db/clinic_schema.sql` 動態解析 `soap_records` 表、`soap_records_fts` trigram 虛擬表與 3 個同步觸發器 DDL，支援 `--confirm-prod-backup` 與 `--dry-run`。

### 2.14 臨床 SOAP 衛教提煉與審核流（Phase 15 新增）
為將去識別化之 SOAP 臨床紀錄轉化為合規安全之衛教問答，並提供醫師權威簽核流程，自 Phase 15 起導入臨床衛教提煉與草稿審核架構：
- **衛教草稿提煉 (`src/soap/distiller.py:distill_soap_records`)**：
  - 依疾病（`condition`）分組聚合相同診所 SOAP 紀錄之居家照護重點，只採納出現次數達門檻（`min_occurrences`，預設 2）之照護敘述。
  - 生成標準化問答對（問題為 `【照護指引】罹患{condition}應注意哪些居家照護事項？`），強制附加「何時該就醫」警訊與醫療免責宣告。
  - 提煉產物通過 `deep_mask_prices()` 價格清洗、禁詞攔截與 DX 劑量/處方建議檢驗，違規項目安全跳過。
  - `metadata` 保存溯源資訊（`record_count` 參考病歷筆數、標的疾病、診所代碼），不得含病患個資。
- **草稿暫存與權威寫入 (`src/pageindex/faq_writer.py`)**：
  - 擴充 `source_type='soap_distilled'`，寫入 `faq_cache` 時強制設定 `review_status='pending'`。
  - **寫入路徑絕不自動 ALTER**：`upsert_faqs` 不會替資料庫新增 `metadata` 欄位（任何來源皆然，含 `/api/v1/sync/import`），避免未經確認變更正式庫。寫入 `soap_distilled` 時若缺 `metadata` 欄位（或缺審核欄位），一律拋 `RuntimeError`（Fail-Closed）。
  - **遷移單一來源**：`faq_cache.metadata` 欄位定義在 `src/db/clinic_schema.sql`，由 `scripts/migrate_faq_metadata.py` 擷取並冪等套用（沿用 `migrate_faq_review_status.py` 的 `extract_column_definition`，欄位定義須單行、不含 `--`）。正式庫遷移須先手動備份：
    ```bash
    cp clinic.db clinic.db.bak-$(date +%Y%m%d)
    python3 scripts/migrate_faq_metadata.py --confirm-prod-backup
    ```
    未帶 `--confirm-prod-backup` 於連線前以結束碼 2 拒絕；`--dry-run` 僅預覽 DDL。測試複本由 `tests/conftest.py` 顯式套用此遷移。
  - **重跑冪等**：內容（問題/答案/類別/主題）未變時，只刷新 `metadata`，不遞增 `content_version`、不重設審核狀態（已核准草稿不會被重跑打回 `pending`）；內容實質變更才遞增版號並回到 `pending`。
  - 在未獲醫師審核核准前，`visible_faq_sql` 確保待審（`pending`）與已駁回（`rejected`）草稿對公開查詢端點（`/api/v1/query` 與 `/api/v1/general/query`）、快取短路與同步匯出絕對隱蔽不可見（Fail-Closed 隔離）。條件為 `source_type IS NULL OR source_type NOT IN ('llm_generated','soap_distilled') OR review_status='approved'`；**必須保留 `IS NULL` 分支**——SQL 的 `NOT IN` 遇 NULL 結果為 unknown，會讓 `source_type` 為 NULL 的既有列誤被隱藏。
- **醫師審核工具擴充 (`scripts/review_faq.py` 與 `src/pageindex/faq_review.py`)**：
  - `list` 命令支援 `--source soap_distilled` 篩選專用提煉草稿。
  - `show` 命令自動解析 `metadata` 並顯示 `[臨床病歷溯源]` 區塊（參考病歷數與標的疾病）。
  - `approve` / `reject` 命令支援核准與駁回，核准時自動重跑醫療合規檢核，核准後始開放對外短路命中。`set_review_status` 對非 `llm_generated`／`soap_distilled` 之列回報跳過碼 `not_reviewable`（原 `not_llm_generated`）；`mark_for_regeneration` 仍僅限 `llm_generated`（`soap_distilled` 無重生成流程）。
- **批次執行 CLI 腳本 (`scripts/distill_soap_faqs.py`)**：
  - 提供 `--clinic-id`、`--min-occurrences`、`--dry-run` 與 `--confirm-prod-backup`。
  - 對正式庫操作若未帶 `--dry-run` 且未帶 `--confirm-prod-backup` 於連線前回退結束碼 2。
  - `--dry-run` 以唯讀連線（SQLite `mode=ro` URI）開啟資料庫，零資料庫變更，且不要求資料庫已遷移 `metadata` 欄位。
  - 實際寫入時若資料庫尚未遷移（缺 `metadata` 或審核欄位），印出中止訊息並以結束碼 2 退出，不會自動補欄位。
- **測試慣例**：`tests/test_faq_review_soap.py` 含「寫入路徑不自動 ALTER」與「重跑不重設已核准」回歸測試；`tests/test_faq_review_gate.py::test_visible_faq_sql` 把關 `IS NULL` 分支。

### 2.15 定時自動化同步與批次提煉排程（Phase 16 新增）
將 Phase 14（SOAP 擷取）與 Phase 15（衛教提煉）接進夜間批次，形成「前置同步 → 提煉草稿 → 晨間醫師審核」閉環：
- **批次階段順序（`src/batch/runner.py:run_batch`）**：0a 前置增量同步（選用）→ 0b SOAP 提煉（`distill_soap_records`）→ FAQ 預生成 → 推理樹重建。`--skip-soap` 與 `--soap-only` 互斥（argparse mutually exclusive）；預設啟用提煉、不啟用前置同步。
- **Fail-Closed 保證**：提煉產物一律經 `faq_writer.upsert_faqs(source_type='soap_distilled')` 寫入 `review_status='pending'`；`visible_faq_sql` 使 pending／rejected 草稿對快取短路、`/api/v1/query`、`/api/v1/general/query` 與同步匯出絕對隱蔽，醫師 `approve` 前不可見。批次本身永不核准任何草稿。
- **連線模式**：`--dry-run` 以 `mode=ro` 唯讀連線開庫且不執行前置同步（不連網、不寫入）；非 dry-run 才取得 `<db>.nightly.lock` 非阻塞檔案鎖並以可寫連線執行。正式庫非 dry-run 仍須 `--allow-prod-db`。`review_faq.py pending-summary` 為唯讀（`mode=ro`），且未遷移庫（缺審核欄位）回結束碼 2。
- **前置同步（`src/sync/soap_sync_runner.py`，以 `--soap-sync-url` 啟用）**：
  - 失敗策略＝**降級繼續**：拉取或寫入失敗時 `soap_sync_status` 為 `degraded`／`failed`、`errors` 加 1，並對連線 `rollback()`，批次仍以既有本機病歷繼續提煉；不因網路問題讓整晚批次落空。日誌與錯誤訊息只記例外類別，不記 URL 與回應內容（URL 可能夾帶憑證）。
  - 遠端 URL 僅允許 `https`（或 `http://localhost|127.0.0.1|::1` 供本機測試），拒絕 `file://`、`ftp://` 與明文遠端；回應上限 10 MB；API 金鑰只從環境變數 `CLINICBRAIN_SOAP_SYNC_API_KEY` 讀取，**不接受命令列傳入**（避免出現在 `ps`／shell history），且 `BatchConfig.soap_sync_api_key` 設 `repr=False`。
  - 提煉階段中途失敗同樣 `rollback()`，避免未提交交易被後續階段一併提交。
- **去識別化與二次防護（`process_soap_records`，比照 `/api/v1/soap/records`）**：S/O/A/P 與 `raw_text` 一律經 `deidentify_text()`（內含身分證／電話／姓名標籤遮蔽與 `deep_mask_prices()`）；`tags` 逐項去識別化後以逗號串接。`external_id` 與外部 `patient_token` 必須通過 `is_safe_identifier`，否則略過該筆（計入 `skipped_unsafe`）。僅有 `patient_id`（或兩者皆無）時一律以 HMAC 衍生 token，**未設定 `CLINICBRAIN_DEID_KEY` 即略過該筆（Fail-Closed）**；嚴禁把原始病患識別碼當 token，也不得以 `PTK-{external_id}` 等可預測值備援。
- **晨間審核通報**：`python3 scripts/review_faq.py pending-summary` 彙整待審草稿（SOAP 提煉／LLM 預生成／其他，依疾病分組並顯示參考病歷筆數）。簽核指引刻意不產生批次 `approve` 指令，要求先逐筆 `show` 檢視。
- **Systemd**：正式排程單元為專案根目錄 `clinicbrain-nightly.service`／`.timer`（凌晨 02:30，見 2.10 節）。Phase 16 曾重複產生 `templates/systemd/` 另一組範本（03:00，與根目錄單元衝突），已於複審後移除，排程單元以根目錄為唯一來源；專案依規範不代為啟用任何 systemd 服務。
- **已知限制**：① 提煉為詞彙級關鍵字統計，草稿品質仰賴醫師審核；② 前置同步目前只支援單一遠端端點與 POST `{clinic_id, since_days}` 契約；③ 同一病患多筆病歷會重複計入 `record_count`（以病歷筆數而非病患數計）。
- **測試**：`tests/test_phase16_hardening.py`（Fail-Closed 略過、URL 限制、rollback、旗標互斥、草稿隱蔽、前置同步失敗不中斷）、`tests/test_nightly_soap_batch.py`、`tests/test_soap_sync_runner.py`、`tests/test_nightly_full_schedule_e2e.py`。

### 2.16 定時一般醫學知識補充與批次擴充（Phase 17 新增）
讓夜間批次能分批、可續跑地擴充「一般醫學（`category='general'`、`clinic_id IS NULL`）」衛教草稿，供醫師晨間簽核：
- **種子擴充（`data/batch/faq_seeds.json`）**：除 Phase 12 的 4 個常見疾病外，新增 8 個一般醫學主題（高血壓、第二型糖尿病、蕁麻疹、氣喘、胃食道逆流、痛風、帶狀皰疹、偏頭痛，各 4 題，共 32 題，皆帶 `question_tags`）。題目全為人工撰寫的「什麼是／常見症狀／何時就醫／居家照護」四型，不含價格數字、不含藥名與劑量、不含療效保證字樣；載入時仍強制通過 `load_seed_file` 四層檢驗。**題目刻意不問用藥**，慢性病（高血壓、糖尿病、氣喘、痛風）的用藥細節屬處方範疇，不由批次預生成。
- **Fail-Closed 保證**：批次生成之 general 草稿一律走 `faq_writer.upsert_faqs(source_type='llm_generated')`，`review_status` 恆為 `pending`；經 `visible_faq_sql` 對 `/api/v1/general/query`、`/api/v1/query` 快取短路與同步匯出完全隱蔽，直到醫師 `review_faq approve`（核准時重跑四層檢驗＋就醫警訊強制檢驗）。生成階段另強制 general 答案含具體症狀／數值條件的就醫警訊收尾句（見 2.12）。
- **批次旗標（`scripts/run_nightly_batch.py`，`src/batch/runner.py`）**：
  - `--general-only`：只做 general 主題 FAQ 預生成；不做 SOAP 前置同步與提煉，也不重建推理樹。
  - `--skip-general`：略過 general 主題（保留診所專屬主題）。
  - 互斥：`--general-only` 與 `--skip-general`（argparse 互斥群組）、`--general-only` 與 `--soap-only`（CLI 結束碼 2）、`--general-only` 與 `--skip-faq`（矛盾，結束碼 2）。`BatchConfig.__post_init__` 對程式化呼叫同樣拒絕這三種矛盾組合（`ValueError`），不靜默擇一。
- **斷點續跑精確度**：規劃階段與生成階段共用 `existing_questions(..., exclude_regen_marked=True)` 並同樣以 `strip()` 比對——已存在（含 pending／rejected）的題目跳過；僅「`rejected` 且 `needs_regeneration=1` 的 `llm_generated`」題目會重新進入待生成清單。全部題目皆已存在的主題不佔 `--max-faq-topics` 名額，因此預設每晚 5 主題、約兩晚即可補齊 12 個 general 主題。`max_pending`（預設 200）仍保護醫師審核負擔。
- **摘要與可觀測性**：`BatchSummary.general_generated_count`（新增＋重生成更新）與 `general_skipped_count`（已存在而略過）；日誌仍遵守不記錄問句／答案原文。
- **審核工具**：`review_faq.py list --category general|special` 與 `pending-summary --category ...`；pending-summary 將 LLM 草稿分為「診所專屬」與「通用衛教」兩區，仍不提供批次核准指令。`faq_review.list_faqs` 新增 `category` 篩選。
- **已知限制**：① 被駁回且未標記重生成的題目永不重新生成（見 2.10 已知限制 5）；② general 草稿的醫學正確性完全仰賴醫師審核，四層檢驗僅攔截格式／合規類風險；③ 慢性病主題的衛教不涵蓋用藥，若醫師需要用藥說明須人工撰寫（`manual` 來源）。
- **測試**：`tests/test_general_faq_seeds.py`、`tests/test_nightly_general_batch.py`（含複審新增的矛盾旗標與 pending 隱蔽測試）、`tests/test_general_expansion_e2e.py`。

### 2.17 診所資料上傳與管理 Web App（Phase 18 新增）
讓診所人員與醫師以瀏覽器完成「文件上傳 → 待審草稿 → 醫師簽核 → 對外生效」，免用 CLI：
- **審核閘門來源集中定義**：`src/pageindex/faq_review.py:REVIEW_GATED_SOURCES = ('llm_generated','soap_distilled','web_upload')` 是「未核准前對外隱蔽」來源的唯一定義，`visible_faq_sql`、`list_faqs`、`set_review_status` 與 `faq_writer`（預設 `pending`、缺審核欄位時 Fail-Closed 拒寫）皆引用它；新增受控來源只改這一處。
- **為何新增 `web_upload` 而非沿用 `clinic_upload`**：`clinic_upload`（CLI 擷取、`/api/v1/sync/import`）被定義為院所權威來源，**恆為可見**；若 Web 上傳沿用它，即使 `review_status='pending'` 也會被公開端點查到（Fail-Open）。Web 上傳因此使用獨立的 `web_upload`，由 `upsert_faqs` 直接以 `pending` 寫入（無「先 approved 再改回 pending」的競態窗口）。
- **管理 API（`src/api/routes/admin.py`，前綴 `/api/v1/admin`，全部掛 `verify_admin_key`）**：
  - `POST /upload`：僅 `.docx/.xlsx/.pdf`、上限 15MB（最多多讀 1 byte 判斷超限）；檔名取 basename 防路徑穿越；驗證檔頭（zip `PK\x03\x04`／`%PDF-`）；診所代碼須存在於 `clinic_info`（否則 404）；內文依序 `to_traditional` → `deidentify_text` → `deep_mask_prices`；單檔最多 200 段、單段答案 3000 字；每段再過 `validate_single_faq` 四層驗證，違規段落單筆剔除並回報 `rejected_paragraphs`；`preview_only=true` 不寫庫。暫存檔於 `finally` 刪除。
  - `GET /review/faqs`（`status`／`category` 以 pattern 驗證，`clinic_id`、`source_type`、分頁；回傳含 `metadata` 溯源）、`POST /review/faqs/{id}/approve|reject`（走唯一權威 `set_review_status`，核准前重跑合規驗證）、`GET /review/summary`（唯讀連線）。
- **前端（`src/web/static/`，純 HTML／Vanilla JS，掛載於 `/admin`）**：所有動態內容以 `textContent` 寫入（防儲存型 XSS）；API Key 存 `sessionStorage`（分頁關閉即失效），經 `X-API-Key` 標頭送出，不用 Cookie（故無 CSRF 面）；SOAP 檢索使用 `POST /api/v1/soap/search`（需金鑰與機構代碼，問句不進 URL）。`/admin` 回應帶 CSP（`script-src 'self'`、`frame-ancestors 'none'`）、`X-Frame-Options: DENY`、`no-store`。樣式使用 jsdelivr CDN 的 Tailwind CSS（僅樣式，無第三方腳本）；離線部署時樣式會退化但功能不受影響。
- **正式庫保護**：測試全程用 `isolated_db_path` 複本；Web 服務使用的資料庫由 `config.db_path` 決定，部署時才指向正式庫。
- **已知限制**：① 文件段落轉草稿的規則簡單（以空行分段、`問：／答：` 或問號結尾辨識問答），醫師須逐筆檢視；同一檔案改段落順序重傳會產生不同「指示 N」題目；② 相同診所＋主題＋題目重傳且內容有變時，既有已核准項目會回到 `pending`（需重新簽核）；③ 全域 CORS 為 `allow_origins=["*"]`（沿用既有設定），管理端點仰賴金鑰標頭而非來源限制；④ OCR 不支援，掃描版 PDF 會被拒絕。
- **測試**：`tests/test_admin_api.py`（含複審回歸：web_upload＋pending 隱蔽、檔頭／診所／段落數／保證療效剔除／過濾參數／路徑穿越）、`tests/test_web_ui.py`（含安全標頭）、`tests/test_webapp_e2e.py`（上傳→pending→公開端點隱蔽→核准→快取短路命中）。

### 2.18 Web 臨床操作體驗與 AI 協同工作流（Phase 19 新增）
解決醫師實機反饋的兩個痛點：上傳「只有問題清單」的文件缺答案、逐筆簽核太繁瑣。三個新端點皆掛 `verify_admin_key`：
- **批量簽核 `POST /api/v1/admin/review/batch`**：`{action: approve|reject, faq_ids: [int]}`（`extra=forbid`、`StrictInt`、1～100 筆，布林與字串被拒；後端 `batch_review_faqs` 先對 ID 去重）。走唯一權威 `set_review_status` 的**單一次 commit**：逐筆合規檢驗失敗者（含 `not_reviewable`，即 `manual`／`clinic_upload` 等權威來源）列入 `failed_ids`／`failed_reasons`，其餘於同一交易生效；任何非預期例外一律 `rollback`，不留半提交。回傳 `success_count`／`failed_count`／`processed_ids`／`failed_ids`。
- **內聯修訂 `PATCH /api/v1/admin/review/faqs/{id}`**（`faq_review.update_faq_content`）：僅限審核閘門來源（`REVIEW_GATED_SOURCES`）且**非 approved** 的列——已核准內容不得被靜默改寫（須先退回待審）；文字先 `deidentify_text` ＋ `deep_mask_prices`，再過四層驗證＋劑量檢驗（general 另需就醫警訊）；修訂後狀態一律回到 `pending`（被駁回的草稿修訂後重新進入待審）、`content_version` +1、`metadata.answer_source='manual_edit'`；題目與同診所同主題重複回 422，找不到 404、不可編輯 409。
- **本機 LLM 生成 `POST /api/v1/admin/review/faqs/{id}/generate-answer`**（`src/pageindex/answer_generator.py`）：
  - 僅走本機 `llama-server`（`admin._local_llm_call`，逾時 300 秒；實測 Qwen3.8-27B 單題 68～122 秒，故前端提示「約 1～3 分鐘」），內容不外流雲端；`_GENERATION_LOCK` 非阻塞鎖使同時只處理一題（忙碌回 429），鎖於 `finally` 釋放；LLM 離線回 503 並給繁中處置提示。
  - 「真正的問題」判定：題目欄為實際問句則直接使用；題目欄是上傳佔位題（`【診所文件】… - 指示 N`）且答案欄僅為**單行問句**（問題清單型文件）時，以該行為問句，生成成功後把題目欄改寫為真正問句（否則公開查詢無法比對）。佔位題但答案是多行指示內容者視為已有實質內容，未明確 `overwrite=true` 不得覆蓋（409）；答案已完整（≥30 字且非問題清單）同樣需 `overwrite`。
  - 輸出檢驗（全部通過才寫入）：移除 `<think>` 區塊與「答：」前綴 → `sanitize_faq_text`（去識別化＋價格屏蔽）→ 長度 100～600 字 → `validate_single_faq(check_dosage=True, require_doctor_warning=True)`（簡體／政治立場／保證療效／價格／劑量／具體症狀的就醫警訊）。未通過回 422 並**不寫入**。Prompt 注入（題目要求忽略規則、輸出價格）無法繞過輸出端檢驗。
  - 寫入以樂觀鎖（`WHERE answer IS ? AND review_status != 'approved'`）防並行修改；狀態維持 `pending`，`metadata.answer_source='local_llm'`，前端標示「本機 LLM 生成・待醫師確認」。
- **列表 `GET /review/faqs`** 新增 `needs_answer`（`answer_generator.is_answer_thin`）供前端標示「⚠️ 答案待補齊」，判定邏輯只在後端一處。
- **前端（`src/web/static/`）**：全選／反選／清除與「已選取 X / Y 筆」計數、底部浮動操作列（選取時滑入，批量核准／駁回，每 100 筆分批送出，失敗項目保留於清單並提示原因）、卡片 checkbox 與點擊卡片空白處切換、單題「🤖 本地 LLM 生成解答」（有答案時改為「🔄 重新生成」並二次確認 overwrite）、「✏️ 編輯」內聯編輯、Spinner／骨架屏／Toast。來源篩選補上 `web_upload`（先前遺漏，網頁上傳草稿原本無法篩出）。**所有伺服器或使用者資料一律以 `textContent` 寫入**；`tests/test_web_ui_v2.py` 以靜態掃描確認審核區塊不含 `innerHTML`／`insertAdjacentHTML`／`document.write`／`eval`（SOAP 區塊僅剩固定字串）。
- **不做批量 AI 生成**：本機模型一次只能處理一題且單題需 1～2 分鐘，批量生成會長時間佔用推論並與夜間批次爭用；醫師逐題決定是否生成。
- **已知限制**：① AI 生成內容的醫學正確性仍完全仰賴醫師逐筆確認，檢驗僅攔截格式／合規類風險；② 生成不會參考診所既有 FAQ 或推理樹，屬一般性衛教；③ 單次列表最多載入 200 筆，超過時提示處理後重新整理；④ 批量核准不會阻擋「答案待補齊」的列（醫師可能刻意核准純指示文字），僅在介面標示警示。
- **測試**：`tests/test_admin_batch_and_ai.py`（批量／編輯／生成／認證）、`tests/test_phase19_hardening.py`（權威來源不可被批量改動、鎖釋放、think 區塊、prompt 注入、XSS 純文字、欄位白名單）、`tests/test_web_ui_v2.py`、`tests/test_clinical_ux_e2e.py`（問題清單上傳 → 生成 → 全選／反選 → 批量核准 → 公開查詢短路命中，未生成者仍隱蔽）。

### 2.19 管理端「向 LLM 提問」檢驗頁籤（Phase 20 新增）
讓醫師／管理者對本機模型實際提問，觀察它如何「只根據系統資料」作答，用來評估資料覆蓋度與回答品質：
- **端點 `POST /api/v1/admin/ask`**（`verify_admin_key`，`{question<=300 字, clinic_id}`，`extra=forbid`；診所須存在否則 404）。使用 `get_read_db` 唯讀連線，**不寫入任何資料**；與 AI 生成共用 `_GENERATION_LOCK`（本機模型一次只服務一件事，忙碌回 429，離線回 503）。
- **模組 `src/pageindex/rag_ask.py`**：
  - 檢索走 `handle_query(..., cache_shortcut=False)`，因此只取得**對外可見**資料（已核准 FAQ、推理樹、診所備註、診所基本資料），與公開端點共用同一審核閘門——**未核准草稿絕不進入模型 context**（`tests/test_admin_ask.py` 以待審「答案」不得出現在 prompt 驗證）。
  - 紅旗急重症問句（`detect_red_flag`）不呼叫模型，直接回固定就醫指示；檢索不到任何資料時**不呼叫模型、不憑空作答**，回報 `no_evidence`。
  - Prompt 要求：僅依資料作答、資料不足須明說、句末標示來源編號（`[F1]`／`[T1]`／`[N1]`）、禁金額／藥名劑量／療效保證、涉及不適須給具體就醫警訊。
  - 輸出經 `sanitize_faq_text`（去識別化＋價格屏蔽）與 `validate_single_faq(check_dosage=True)`；結果以 `compliance.ok/reason` 回報。**管理端為了評估模型品質，未通過合規時仍顯示答案但明確標示警告**——對外端點永遠不會輸出此類內容。
  - 回傳 `mode`（`answered`／`no_evidence`／`red_flag`）、`used_llm`、`sources`（編號、類型、診所／通用層級、標題）。
- **前端「💬 向 LLM 提問」頁籤**（位於 SOAP 紀錄頁籤之後）：機構代碼、問題輸入（Ctrl+Enter 送出）、範例問題按鈕、結果卡片（模式徽章、合規徽章、答案、模型可見的資料來源清單）、本次瀏覽的提問紀錄（記憶體內，不落地）。全程 `textContent` 渲染，有靜態掃描測試。
- **取樣設定（重要踩雷）**：本機 llama-server 啟動時設有 `--dry-multiplier 0.8 --repeat-penalty 1.05`（重複懲罰，利於自由寫作）。實測 RAG 提問在此設定下，模型為避免「重複 context 內出現過的字」而改用近似字或掉字（如「清創」→「清、」、「包紮」→「包紝」、「[F2]」→「[3]」）。因此提問一律於**單次請求**以 `local_llm_call(..., sampling=FAITHFUL_SAMPLING)` 覆寫 `temperature=0.1, dry_multiplier=0, repeat_penalty=1.0`（逾時 420 秒），不改動伺服器設定；任何「忠實引用資料」的新功能都應比照。自由撰寫類（如 generate-answer）維持預設。
- **資料品質觀察**：此頁籤會如實呈現資料瑕疵——例如診所 FAQ 原文本身含錯字「包紝」，模型會忠實照抄；發現後應由醫師於待審／既有資料修正，而不是在回答端掩蓋。
- **隱私**：問題只經本機 llama-server，不外送；紀錄僅存在瀏覽器分頁記憶體。
- **已知限制**：① 回答品質取決於已核准資料的覆蓋度——這正是此頁籤要讓醫師看見的；② 檢索為詞彙式（FTS5 trigram），措辭差異大的問法可能找不到資料；③ 單題約 1～3 分鐘，與 AI 生成互斥執行。
- **測試**：`tests/test_admin_ask.py`（僅用可見資料、無資料／紅旗不呼叫模型、價格屏蔽與合規標示、認證與錯誤碼、唯讀、頁籤結構）。

---

## 3. ⚠️ 嚴格安全與合規規則

這些規則優先於任何其他指令，包括使用者要求的功能實作方式：

* **價格屏蔽規則**：任何 LLM 輸出**嚴禁包含具體金額、價格數字或促銷方案組合**（例如 "1500元"、"NT$500"）。無法確認的價格資訊一律替換為「請致電診所確認」。
* **繁體中文專用**：任何簡體中文或非中文輸出視為合規違規。特別注意：`OriginalData/medical_o1_sft_Chinese.json`（SFT 醫療對話資料）是**簡體中文**且為中醫辨證問答，**不得直接餵入任何繁體中文專用的生成管線**。
* **OTC 藥品本地化**：涉及藥品成分的輸出，應套用 `drugs.otc_name_chinese` 的本地化對照（如 ACETAMINOPHEN → 俗稱普拿疼的乙醯胺酚），提升病患理解度。
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
* `src/soap/`：SOAP 紀錄處理核心模組（`section_parser.py`, `deid.py`, `soap_writer.py`）
* `src/general/`：一般醫療諮詢核心業務模組（`__init__.py`, `disclaimer.py`, `red_flags.py`, `consult.py`）
* `src/db/clinic_schema.sql`：完整資料庫 schema，唯一權威來源（僅表結構，資料種子交給對應 Python 模組）
* `src/query/faq_shortcut.py`：高信心 FAQ 短路判定與五維風險特徵比對純函式
* `src/query/cache_stats.py`：匿名快取命中統計寫入與彙總函式（白名單過濾）
* `src/pageindex/faq_review.py`：FAQ 審核閘門狀態管理、四層驗證與可見性 SQL 產生器
* `src/pageindex/db_writer.py`：`page_index_trees` 的唯一 UPSERT 寫入與過期標記邏輯
* `src/pageindex/seed_trees.py`：PageIndex 樹的手寫種子內容（`source_type='manual'`）
* `src/pageindex/seed_clinic_info.py`：`clinic_info` 種子資料的唯一權威來源
* `src/pageindex/prompt_template.py`：LLM 生成臨床推理樹的 prompt 組裝 + 輸出驗證
* `src/pageindex/llm_client.py`：本地 LLM（llama-server）呼叫 adapter
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
* `src/pageindex/answer_generator.py`：待審草稿 AI 輔助答案生成（本機 LLM、輸出端四層檢驗、樂觀鎖寫入）
* `src/soap/distiller.py`：SOAP 衛教提煉與草稿生成模組
* `scripts/run_nightly_batch.py`：夜間批次自動化排程 CLI 工具
* `scripts/review_faq.py`：醫師審核命令列互動工具（支援 list --topic、show 來源與相近診所 FAQ 檢視、approve、reject、reset 與 mark-regen 重生成標記）
* `scripts/mark_tree_regen.py`：臨床推理樹待重建手動標記工具
* `scripts/ocr_draft.py`：手動 OCR 草稿 CLI（單張圖片、固定警語、預設印到標準輸出）
* `scripts/run_stage1_ingestion.py`：文件擷取 Stage 1 端到端執行入口，僅寫入隔離測試複本
* `scripts/run_api_server.py`：FastAPI 服務啟動入口腳本（支援 CLI 參數）
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
* `OriginalData/`：NHI 原始資料（gitignored，261MB，唯讀參考）
* `.planning/`：GSD 工作流程狀態（`HANDOFF.json`、`phases/`、`VISION-EXPANSION.md` 願景規劃）

---

## 5. 開發原則

* 每個 Phase 任務完成後，先用真實查詢/資料驗證（不是只看程式碼跑完沒報錯），再提交 commit。
* 修改 FTS5 相關 schema 後，必須實際執行一次中文關鍵字查詢驗證分詞正常，不能只信任「schema 語法正確」。
* 新資料來源在用於生成用途前，先確認語言與領域是否吻合（見 2.2 節的踩雷案例：SFT 資料語言不對、`service_items.payment_rules` 只是給付範本無臨床細節）。
* 任務範圍要守住邊界：不要因為手邊在做某個任務，就順手把後續任務（如查詢層、LLM 生成邏輯）的工作也做掉，會混淆任務追蹤與驗收界線。
* 完整的未來願景與待決策事項見 `.planning/VISION-EXPANSION.md`，不要重複在這裡展開。
