# Phase 03：文件擷取管線

## 背景

使用者指出 `OriginalData/` 下有兩個**真實既有資料夾**，尚未被納入任何匯入流程：

- `OriginalData/一般醫學/`（2.0G）→ 對應 `general` 路由內容來源
- `OriginalData/緻妍外科診所/`（782M）→ 對應 `special` 路由內容來源（診所專屬）

這比 `VISION-EXPANSION.md` 原本設想的「診所未來可能上傳文件」更急迫——資料已經存在，
只是還沒有管線把它們轉成 `page_index_trees` 可用的內容。

## 實測盤點結果（2026-09-22）

### `一般醫學/`（2.0G，現況 — `soapclass/` 已依使用者決定移除，見下方決策 3）
- 子目錄：`健保相關/`（NHI 資料，已確認就是 Phase 01 依賴的那批資料，見下方
  「路徑修正記錄」）、`美容醫學/`（PDF 衛教資料，如《完美皮膚保養指南》
  《肉毒桿菌毒素美容》）
- 檔案類型：22 docx、19 pdf、12 doc、4 csv、3 md、2 ods、1 ppt、1 json、1 odt，
  另有 1 個非副檔名資料夾「解剖学治疗学及化学分类系统」（簡體字命名，內容待查）

### `緻妍外科診所/`（782M）
- 子目錄：`儀器/`（設備操作手冊）、`EMFACE臉部磁波電波`、`列印表單 (ALL)/`、
  `衛教文章/`、`廠商PPT/`、`每月活動單/`
- 檔案類型：90 docx、41 pdf、25 png、20 jpg、7 pptx、5 xlsx、5 jpeg、4 doc，
  另有 mp4 影片 1 支、`.lnk` 捷徑檔 1 個（無實質內容，應排除）
- **至少 10 個檔名含「培训」「操作」等簡體字**（例如「大气泡Hydrafacial培训手册.pdf」
  「黄金射频微针-台式操作教育.pdf」），確認這批儀器手冊多數是原廠簡體中文文件，
  匯入時**必須做簡體→繁體轉換**，不能直接餵給繁體中文專用的 PageIndex 生成管線
  （違反 AGENTS.md 的繁體中文專用 CONSTRAINT）
- `客服回覆話術.xlsx`、`緻妍可自費門診手術...docx`、`緻妍自費門診手術內容.docx`
  這幾份特別關鍵——很可能含有實際的療程項目清單與衛教內容，是 `clinic_custom_notes`
  或新療程 `page_index_trees` 的絕佳資料來源
- `Thumbs.db` 只是 Windows 縮圖快取，非資料庫，可忽略

## 目標

建立一條「原始文件 → 文字擷取 → （必要時）簡繁轉換 → （必要時）OCR → LLM 生成
PageIndex 樹（走 Phase 02 剛打通的 `local_llm_call`）→ 人工審核 → 寫入資料庫」的
管線，但**分階段、非一次到位**。

## 建議分期（避免一次吃下 2.7G 全部資料）

### Stage 1：文字型文件擷取（docx/pdf 文字層/pptx/xlsx）
不含圖片 OCR，先處理有原生文字層的格式。Python 生態已有成熟套件
（`python-docx`、`PyPDF2`/`pdfplumber`、`python-pptx`、`openpyxl`），這部分技術
風險低，可以先做。

- 優先處理 `緻妍外科診所/客服回覆話術.xlsx`、`緻妍可自費門診手術...docx`、
  `緻妍自費門診手術內容.docx` 這幾份高價值檔案，驗證整條管線可行後再擴大範圍
- 簡體字文件（如儀器手冊）需要先做簡繁轉換（建議用 `opencc` 這類成熟函式庫，
  而非自己刻規則）

### Stage 2：圖片 OCR（png/jpg/jpeg/jfif）
25+20+2 = 47 張圖片，多數可能是操作介面截圖或衛教圖卡，非纯文字內容。這部分
需要先人工抽查幾張圖片，確認 OCR 是否真的能擷取到有意義的文字，還是大多數
只是示意圖（若是後者，OCR 投資報酬率低，可能只需要保留檔名/描述做索引，不需要
真的做 OCR 文字擷取）。

### Stage 3（視 Stage 1/2 結果決定是否需要）：影片/複雜 PDF
`mp4` 影片與部分排版複雜的 PDF（廠商教學簡報）較難處理，優先度最低。

## CONSTRAINT

- 沿用 `AGENTS.md` 全部既有規則
- 簡體字來源文件轉換後的內容，一樣要通過 `prompt_template.py` 既有的
  `_SIMPLIFIED_CHAR_SAMPLE` 檢測層才能算數，不能假設轉換工具 100% 正確
- 任何自動擷取/生成的內容寫入 `page_index_trees` 時，`source_type` 應標記為
  `'clinic_upload'`（schema 已預留這個值，見 `AGENTS.md` 2.2 節），不要跟手寫
  （`manual`）或純 LLM 生成無來源依據（`llm_generated`）混淆
- 大量原始檔案不應該被複製進 git 版控（`OriginalData/` 已在 `.gitignore`），
  擷取後的中繼產物（純文字、JSON）也要評估是否該進版控或只留在本地

## 使用者決策（2026-09-22）

1. **診所業務資料（`緻妍外科診所/`）先經 LLM 轉成 Q&A 對，再進知識庫**——不是
   直接生成 `page_index_trees` 四段式結構。擷取出的文字（儀器手冊、衛教文章、
   客服話術、自費門診項目）先用 LLM（Phase 02 的 `local_llm_call`）改寫成
   「病患可能會問的問題 + 答案」，存進一個新的 FAQ 快取表，作為知識庫的中間
   產物。這與 `VISION-EXPANSION.md` 先前提到的夜間常見問答預生成機制相通，
   差別在於這裡的來源是文件擷取而非通用醫學常識——**技術設計上應該共用同一套
   FAQ 表結構，不要為文件擷取另外設計一套**。

   **`faq_cache` 表結構（2026-09-22 確認）**：新增獨立資料表，不與
   `page_index_trees` 共用同一張表（欄位模式比照，但 Q&A 是「一問一答」的
   扁平結構，跟 `page_index_trees` 的「四段式療程樹」結構本質不同，硬塞進
   同一張表會讓兩種內容形狀混在一起、查詢層要判斷「這筆到底是摘要還是
   Q&A」，不划算）：

   ```sql
   CREATE TABLE faq_cache (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       clinic_id TEXT REFERENCES clinic_info(clinic_id),
       topic_key TEXT,           -- 對應療程/主題 slug，NULL = 通用醫療（呼應
                                  -- general 路由；有值時對應 page_index_trees
                                  -- 的療程 doc_id，但不是外鍵，因為 general
                                  -- 類 FAQ 沒有對應的療程樹）
       question TEXT NOT NULL,
       answer TEXT NOT NULL,
       category TEXT NOT NULL,   -- 'special' or 'general'，沿用既有路由分流
       source_type TEXT DEFAULT 'manual',  -- 'manual' | 'llm_generated' |
                                  -- 'clinic_upload'，語意與 page_index_trees
                                  -- 完全一致（見 AGENTS.md 2.2 節）
       content_version INTEGER NOT NULL DEFAULT 1,
       needs_regeneration BOOLEAN NOT NULL DEFAULT 0,
       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
       updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
   );
   -- + faq_cache_fts（trigram tokenizer，比照 drugs_fts/service_items_fts/
   --   page_index_fts 的既有模式，問題與答案都要能被中文全文檢索到）
   ```

   `content_version`/`source_type`/`needs_regeneration` 三個欄位語意完全
   沿用 `page_index_trees` 既有設計（見 `AGENTS.md` 2.2 節），這樣夜間批次
   維護邏輯（Phase 04 願景草案提到的「先查資料庫、沒中才即時生成」）可以對
   兩張表用同一套「找 `needs_regeneration=1` 的列」邏輯，不需要為 FAQ 另外
   刻一套。寫入路徑應該仿照 `src/pageindex/db_writer.py` 的模式，新增
   `src/pageindex/faq_writer.py`（或併入同一個 `db_writer.py`，交給實際
   展開 TASK-PLAN 時決定）提供唯一的 UPSERT 入口，不要讓文件擷取管線與夜間
   批次各自重新實作寫入邏輯——這正是 `AGENTS.md` 2.2 節記載過、TASK-003 時
   踩過的重複寫入路徑教訓。
2. **匯入前必須做簡繁轉換**——確認採用，見下方「簡繁轉換」小節。
3. **`健保相關/` 已確認與 Phase 01 依賴的資料同源**（見下方「路徑修正記錄」，
   不是重複資料而是同一批資料被移動位置，已修正 `scripts/seed_database.py`
   的路徑指向）。**`soapclass/`（SOAP 病歷自動分類 JS 工具）判斷與本專案（病患
   衛教內容 RAG）關聯不大，已於 2026-09-22 移除**（用 `gio trash` 移進系統
   垃圾桶，非永久刪除，可從桌面環境垃圾桶還原）。不再列入 Phase 03 範圍。

## 路徑修正記錄（2026-09-22）

`OriginalData/` 根目錄已被使用者重新整理，Phase 01 依賴的藥品/服務項目 CSV
從根目錄移到 `一般醫學/健保相關/` 底下，導致 `scripts/seed_database.py` 一度
重建失敗（找不到來源檔案）。已修正 `DATA_DIR` 指向新位置並重新驗證整條
pipeline（匯入筆數與修正前一致，100 個既有 pytest 測試全數通過），見 commit
`d796f24`。**這代表 `健保相關/` 就是 Phase 01 原本用的那批資料，不是另一份
待比對的重複資料**——先前待決事項第 1 點已經有解。

## 簡繁轉換技術方向（待展開，非本次決策範圍）

至少 10 份儀器手冊確認是簡體字原廠文件。建議用成熟的 `opencc`（OpenCC）函式庫
做簡繁轉換，而非自行刻規則；轉換後的內容仍要通過 `prompt_template.py` 既有的
`_SIMPLIFIED_CHAR_SAMPLE` 檢測層才算數，不能假設轉換工具 100% 正確。

## 待確認

- 是否現在就展開 Stage 1 詳細任務（可比照 Phase 02 模式交給 Antigravity）
  ——`faq_cache` schema 設計已於 2026-09-22 確認（見上方使用者決策 1），
  不再是阻塞項；但 Stage 1（純文字擷取）本身不依賴 `faq_cache` 存在，理論上
  可以先獨立展開，`faq_cache` 的建表 + 寫入邏輯留到 Stage 1 擷取出真實文字
  後、真的要轉 Q&A 時再一併做（即 Stage 1.5，串接 Phase 02 的
  `local_llm_call`）
