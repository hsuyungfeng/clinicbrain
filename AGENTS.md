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

---

## 3. ⚠️ 嚴格安全與合規規則

這些規則優先於任何其他指令，包括使用者要求的功能實作方式：

* **價格屏蔽規則**：任何 LLM 輸出**嚴禁包含具體金額、價格數字或促銷方案組合**（例如 "1500元"、"NT$500"）。無法確認的價格資訊一律替換為「請致電診所確認」。
* **繁體中文專用**：任何簡體中文或非中文輸出視為合規違規。特別注意：`OriginalData/medical_o1_sft_Chinese.json`（SFT 醫療對話資料）是**簡體中文**且為中醫辨證問答，**不得直接餵入任何繁體中文專用的生成管線**。
* **OTC 藥品本地化**：涉及藥品成分的輸出，應套用 `drugs.otc_name_chinese` 的本地化對照（如 ACETAMINOPHEN → 俗稱普拿疼的乙醯胺酚），提升病患理解度。
* **CSV 記錄數陷阱**：這批 NHI 原始資料 CSV 內含大量帶換行符號的長文字欄位（`AI-note`、`給付規定`），`wc -l` 統計的行數遠大於實際記錄數。務必用 `csv.DictReader` 逐列讀取確認筆數，不要用 `wc -l` 判斷資料是否遺失。

---

## 4. 目錄結構

* `src/db/clinic_schema.sql`：完整資料庫 schema，唯一權威來源（僅表結構，資料種子交給對應
  Python 模組，見下）
* `src/pageindex/db_writer.py`：`page_index_trees` 的唯一 UPSERT 寫入邏輯，手寫種子與 LLM 生成皆呼叫此模組
* `src/pageindex/seed_trees.py`：PageIndex 樹的手寫種子內容（`source_type='manual'`）
* `src/pageindex/seed_clinic_info.py`：`clinic_info` 種子資料的唯一權威來源
* `src/pageindex/prompt_template.py`：LLM 生成臨床推理樹的 prompt 組裝 + 輸出驗證（`source_type='llm_generated'`）
* `src/pageindex/llm_client.py`：本地 LLM（llama-server）呼叫 adapter，符合 `generate_tree()` 期待的 `Callable[[str], str]` 介面
* `src/pageindex/faq_writer.py`：`faq_cache` 的唯一 UPSERT 寫入邏輯（見 2.4 節）
* `src/ingestion/`：文件擷取管線（`extract_text.py`/`convert_chinese.py`/`generate_faq.py`，見 2.4 節）
* `scripts/seed_database.py`：藥品/服務項目 CSV 匯入腳本，並呼叫 `seed_clinic_info`/`seed_sample_notes`
* `scripts/run_stage1_ingestion.py`：文件擷取 Stage 1 端到端執行入口，僅寫入隔離測試複本
* `OriginalData/`：NHI 原始資料（gitignored，261MB，唯讀參考）
* `.planning/`：GSD 工作流程狀態（`HANDOFF.json`、`phases/`、`VISION-EXPANSION.md` 願景規劃）

---

## 5. 開發原則

* 每個 Phase 任務完成後，先用真實查詢/資料驗證（不是只看程式碼跑完沒報錯），再提交 commit。
* 修改 FTS5 相關 schema 後，必須實際執行一次中文關鍵字查詢驗證分詞正常，不能只信任「schema 語法正確」。
* 新資料來源在用於生成用途前，先確認語言與領域是否吻合（見 2.2 節的踩雷案例：SFT 資料語言不對、`service_items.payment_rules` 只是給付範本無臨床細節）。
* 任務範圍要守住邊界：不要因為手邊在做某個任務，就順手把後續任務（如查詢層、LLM 生成邏輯）的工作也做掉，會混淆任務追蹤與驗收界線。
* 完整的未來願景與待決策事項見 `.planning/VISION-EXPANSION.md`，不要重複在這裡展開。
