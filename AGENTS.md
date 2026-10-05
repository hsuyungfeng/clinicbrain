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
  - 可見性規則：`manual`（手寫）與 `clinic_upload`（診所上傳）恆常對外可見；由本地模型生成之 `llm_generated` 資料預設寫入為 `pending`，在未獲醫師核准前對外完全隱蔽。
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
  5. 批次的 `existing_questions` 去重（`src/batch/faq_generator.py`）不分審核狀態與資料來源，被駁回（`rejected`）的題目仍視為已存在，因此永遠不會被重新生成；如需重生須由人工另行處理（例如改寫題目文字或人工刪除該列）。

### 2.11 診所資料優先檢索（Phase 11 新增）
為解決帶 `clinic_id` 的查詢因未含程序關鍵字被 `classify` 分流為 `general` 而無法短路命中診所專屬 FAQ 的問題，自 Phase 11 起導入「診所資料優先（Clinic-First）」跨層級檢索架構：
- **兩階段跨層級（Tiered）檢索規則 (`src/query/faq_shortcut.py:select_confident_faq_tiered`)**：
  - 觸發條件：`clinic_id` 非空（經正規化後非 None）且非診所營運關鍵字查詢時啟用。
  - 第一階段（診所優先）：先以診所 `category='special'` FAQ 進行短路評估；高信心命中（`confident`）立即勝出回傳，general FAQ 絕不作為競爭者（避免一般通則稀釋或覆蓋院所專屬指示）。
  - 阻斷不退規則：診所層若判定為歧義（`ambiguous`）、風險特徵不符（`risk_mismatch`）、問句過短（`query_too_short`），或相近低覆蓋（`low_coverage` 且 `query_coverage >= CLINIC_RELATED_FLOOR = 0.4`），視為「診所有相近內容但不可確認」，整體不短路且嚴格禁止退回 general。
  - 第二階段（退回 general）：僅當診所層為完全無合格候選（`no_eligible`）或低覆蓋且鬆散相鄰（`low_coverage` 且 `query_coverage < CLINIC_RELATED_FLOOR = 0.4`）時，才評估通過審核閘門（approved）且 `clinic_id IS NULL` 之 general FAQ。
- **回應結構新增純加法欄位 (`data_level`)**：
  - 欄位定義：`data_level: Literal["clinic", "general"] | None`，明確標示回答所屬資料層級。
  - 短路命中時：依短路來源賦予 `'clinic'` 或 `'general'`；`route` 欄位維持原本 `classify` 結果（不因跨層級短路而竄改路由分類）。
  - 非短路時：對 `source='pageindex'` 的回應，`data_level` 取首筆 FAQ 命中的層級（`faq_hit_level(faq_hits[0])`，無 FAQ 命中時為 `None`），**僅表示最前端候選 FAQ 之來源層級，不代表回答文本內容與該 FAQ 直接相關**。
  - 列表項目權威性：`faq_hits` 每筆項目皆帶自己的 `data_level`，以該項目自身之 `clinic_id` 是否非空為權威判斷。
- **隔離宣告局部放寬**：
  - 放寬範圍極小化：僅放寬診所自己的 special FAQ 可在 general 路由被檢索（解決無程序關鍵字問句分流至 general 後無法短路之問題）。
  - 其餘隔離維持不變：`clinic_info`、`clinic_hours`、`clinic_custom_notes` 與 `page_index_trees` 對 general 路由之隔離與過濾完全不變；匿名 `/api/v1/general/query` 端點維持完全不變與嚴格隔離。
- **醫療安全檢查與審核閘門貫徹**：
  - 所有 Phase 07 既有安全檢查常數（0.9 / 0.7 / 0.1 / 4）與五維風險特徵檢查完全未改動。
  - 候選集讀取一律經由 `search_faq_cache`，貫徹 `visible_faq_sql` 審核閘門，未獲核准之 `pending`/`rejected` FAQ 永不外洩。
  - 查詢過程中完全不呼叫外部 LLM 模型。
- **行為變更與取捨**：
  - 帶 `clinic_id` 的 special 路由（含程序關鍵字、非營運）：若診所未命中且無相近內容，亦支援退回已審核 general；但若診所有相近內容（覆蓋率 $\ge 0.4$ 的 low_coverage、歧義、風險不符），則不短路且不退 general。
  - 覆蓋率只是詞彙守衛，不是主題守衛：`CLINIC_RELATED_FLOOR = 0.4`（使用者決策）。複審實測數據：自然釋義配對 24 組中，floor 0.4 擋下 11/24（0.5 僅擋 6/24）；誤擋不同主題 general 為 5/40（vs 3/40）；若設為 0.3 以下，相鄰主題誤擋約達 40%，會嚴重傷害 CF-02 退 general 能力。已知邊界：`query_coverage < 0.4` 的相鄰主題（如診所「縫合後的傷口可以碰水洗澡嗎？」對「縫合後飲食注意」約 0.33）仍會退 general。
  - 營運規則：general FAQ 入庫審核時，醫師須人工比對同主題診所 FAQ 是否存在指示衝突（Phase 12 GC-04 審核工具將提供輔助顯示）。
- **修正跨診所外洩**：
  - `clinic_id` 為 `None` 時，`faq_hits` 與短路候選集嚴格只保留 `clinic_id IS NULL` 之項目，他院 FAQ 不再列出亦不再被標示為 `clinic`。
  - 因此無 `clinic_id` 時，回應之 `data_level` 只可能是 `'general'` 或 `None`。原先「沒有 clinic_id 時行為不變」正式更正為「**不會列出任何診所專屬 FAQ，其餘行為不變**」。
- **診所識別正規化 (`clinic_id`) 與 API 行為差異**：
  - 核心層正規化：`None`、空字串 `""` 與純空白字串 `"   "` 一律視為無 `clinic_id`。營運問句若缺少 `clinic_id`（含空字串）一律拋出 `ValueError`。
  - API 入口差異：
    - `POST /api/v1/query` 與 `GET /api/v1/query` 會將空白 `clinic_id` 轉為 `None`。
    - `POST /api/v1/clinics/{clinic_id}/query` 僅對路徑參數執行 `.strip()`；因此原本空白路徑參數帶營運問句會回 HTTP 200 空資料，現在會正確因 `handle_query` 拋出 `ValueError` 而回傳 HTTP 400（僅此路徑參數入口會將空白傳入 `handle_query`）。
- **統計語意**：
  - `cache_eligible`、`hit`、`miss` 記錄規則不變，命中率分母不變；命中率統計包含 general 層級（`cache_stats` 的 `hit` 不區分 `clinic` 或 `general`）。
- **未涵蓋範圍（CF-04）**：
  - 診所臨床推理樹與客製化備註之優先化留待後續 Phase（CF-04）規劃；查詢時維持不呼叫 LLM。

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
  * `src/api/models/cache_stats.py`：快取統計回應 Pydantic 資料模型
  * `src/api/security.py`：認證組態單一檢查函式與安全防護定義
  * `src/api/routes/general.py`：一般醫療諮詢匿名對外端點（僅 POST，掛載 AnonymousRoute）
  * `src/api/routes/query.py`：自然語言查詢與多診所動態路由端點
  * `src/api/routes/cache_stats.py`：快取命中統計查詢端點（需管理者金鑰）
  * `src/api/routes/sync.py`：doctor-toolbox.com 官方雙向同步契約端點
  * `src/api/routes/health.py`：系統與資料庫健康檢查端點
* `src/batch/`：夜間批次排程與生成核心模組（`runner.py`, `run_log.py`, `topic_sources.py`, `faq_generator.py`, `tree_rebuild.py`）
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
* `src/ingestion/`：文件擷取管線（`extract_text.py`/`convert_chinese.py`/`generate_faq.py`）
* `data/batch/faq_seeds.json`：夜間批次 FAQ 與樹主題繁體中文種子清單
* `scripts/seed_database.py`：藥品/服務項目 CSV 匯入腳本，並呼叫 `seed_clinic_info`/`seed_sample_notes`
* `scripts/migrate_cache_stats.py`：`cache_stats` 資料表結構遷移腳本
* `scripts/migrate_faq_review_status.py`：`faq_cache.review_status` 審核欄位交易性遷移腳本
* `scripts/run_nightly_batch.py`：夜間批次自動化排程 CLI 工具
* `scripts/review_faq.py`：醫師審核命令列互動工具
* `scripts/mark_tree_regen.py`：臨床推理樹待重建手動標記工具
* `scripts/run_stage1_ingestion.py`：文件擷取 Stage 1 端到端執行入口，僅寫入隔離測試複本
* `scripts/run_api_server.py`：FastAPI 服務啟動入口腳本（支援 CLI 參數）
* `clinicbrain-api.service`：API 服務 systemd 配置範本
* `clinicbrain-nightly.service`：夜間批次排程 systemd 配置範本
* `clinicbrain-nightly.timer`：夜間批次排程定時器範本
* `docs/nightly-batch.md`：夜間批次與審核營運維護手冊
* `tests/test_clinic_first_acceptance.py`：診所資料優先檢索量測驗收測試（設計題 G，支援 CLINICBRAIN_ACCEPT_DB 指向複本，驗證 38/40 短路率）
* `OriginalData/`：NHI 原始資料（gitignored，261MB，唯讀參考）
* `.planning/`：GSD 工作流程狀態（`HANDOFF.json`、`phases/`、`VISION-EXPANSION.md` 願景規劃）

---

## 5. 開發原則

* 每個 Phase 任務完成後，先用真實查詢/資料驗證（不是只看程式碼跑完沒報錯），再提交 commit。
* 修改 FTS5 相關 schema 後，必須實際執行一次中文關鍵字查詢驗證分詞正常，不能只信任「schema 語法正確」。
* 新資料來源在用於生成用途前，先確認語言與領域是否吻合（見 2.2 節的踩雷案例：SFT 資料語言不對、`service_items.payment_rules` 只是給付範本無臨床細節）。
* 任務範圍要守住邊界：不要因為手邊在做某個任務，就順手把後續任務（如查詢層、LLM 生成邏輯）的工作也做掉，會混淆任務追蹤與驗收界線。
* 完整的未來願景與待決策事項見 `.planning/VISION-EXPANSION.md`，不要重複在這裡展開。
