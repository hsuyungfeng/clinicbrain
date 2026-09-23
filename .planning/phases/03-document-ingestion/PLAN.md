# Phase 03：文件擷取管線

> **Stage 1 已完成並套用到正式環境**（2026-09-22，commit `625593d` + 後續補做的正式
> `clinic.db` schema 套用/資料寫入，commit `35a71a5`）。完整驗收紀錄見
> `.planning/phases/03-document-ingestion/TASK-PLAN.md` 與 `.planning/HANDOFF.json`。
> 本文件以下內容維持原始規劃紀錄，**Stage 2 已於 2026-09-23 完成人工抽查並結案**
> （見下方「Stage 2 抽查結論」），不再列入待辦。

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

### Stage 2：圖片 OCR（png/jpg/jpeg/jfif）—— ⛔ 已結案，不展開完整 OCR 管線

**Stage 2 抽查結論（2026-09-23，人工視覺抽查 6 張跨類別代表圖片後定案）**

依原規劃先人工抽查幾張圖片判斷 OCR 投資報酬率，抽查涵蓋 `每月活動單/`、
`衛教文章/`、`儀器/`、`EMFACE臉部磁波電波/` 四個子目錄，結果如下：

| 類別 | 樣本 | 內容 | OCR 價值判斷 |
|---|---|---|---|
| Logo（`每月活動單/緻妍logo-橘色.png`） | 純品牌圖形 | 無文字可擷取 | 無 |
| 門診公告（`每月活動單/10月門診公告.png`） | 診所看診時段、電話 | 與 `clinic_hours`/`clinic_info` 資料**完全重複** | OCR 是白做工 |
| 促銷單（`每月活動單/母親節A4-02.jpg`） | 產品價目表（`$4980`、`$2640`... 等原始價格） | 內容是促銷折扣方案，非病患衛教資料 | 就算 OCR 進來，也會被驗證層的價格屏蔽規則全數剔除，等於做了也白做 |
| 衛教文章（`衛教文章/顴骨班2年8次.jpg`） | 術前術後對比照片 | 只有極短標題文字（如「顴骨班2年8次」），無實質內容 | 無 |
| 廠商圖片（`EMFACE臉部磁波電波/da640985...png`） | 產品形象照 | 零文字 | 無 |
| 儀器參數表（`儀器/BBA76E38...jpeg`） | 音波儀器能量等級、探頭規格、禁忌區域圖表 | **唯一真正有實質內容的一張**——但文字混雜在多欄位圖表/示意圖裡，非純文字段落 | OCR 準確度風險高；且內容性質屬於醫師操作參考（禁忌症、能量設定），比較接近未來 `page_index_trees.physician_notes` 欄位的定位，不是病患衛教用的 `faq_cache` 內容——即使真的需要，人工謄寫也優於冒風險做 OCR |

**結論**：47 張圖片裡，`每月活動單/`（約 30+ 張）與 `衛教文章/` 絕大多數是行銷圖或
無實質文字的照片，`EMFACE臉部磁波電波/`、`廠商PPT/` 底下的圖片同樣多為產品形象照。
`儀器/` 目錄下可能還有其他同類參數表（此次只抽查 1 張），若未來真的需要這類內容，
建議**人工謄寫關鍵參數表**存進 `clinic_custom_notes` 或 `physician_notes`，而非建置
完整 OCR 管線——OCR 開發與維護成本，換來的實質可用內容占比太低，不符合投資報酬率。

**本 Stage 正式結案，不再列入 Phase 03 待辦**。若未來因為新上傳的診所文件（例如
Phase 04 願景草案提到的「診所自行上傳文件」情境）出現大量真正需要 OCR 的圖片型
文件，屆時應該重新盤點該批新文件、重新走一次同樣的人工抽查流程再決定，不要直接
沿用這次「不值得做」的結論套用到未來完全不同的資料。

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

## 目前狀態（2026-09-23）

- **Stage 1**：✅ 已完成並套用到正式 `clinic.db`（見文件頂部說明）
- **Stage 2**：⛔ 已結案，判定不值得展開完整 OCR 管線（見上方「Stage 2 抽查結論」）
- **Stage 3**（影片/複雜 PDF）：尚未評估，優先度最低，維持原規劃「視 Stage 1/2
  結果決定是否需要」——鑑於 Stage 2 已判定圖片類資料投資報酬率低，Stage 3 的
  mp4 影片與複雜排版 PDF 大機率也是類似情況（低文字密度、高處理成本），建議
  比照 Stage 2 先做同等的人工抽查/評估，再決定是否投入
- **`OriginalData/一般醫學/`**（2.0G）：整個 Phase 03 至今**尚未觸碰**，只處理過
  `緻妍外科診所/` 底下的三份優先檔案。這是目前 Phase 03 唯一還有實質待辦價值的
  方向——如果要繼續擴大文件擷取範圍，`一般醫學/美容醫學/`（PDF 衛教資料，如
  《完美皮膚保養指南》《肉毒桿菌毒素美容》）會是下一個合理的候選，因為屬於
  `general` 路由內容來源，且是真正的衛教文字資料，不是行銷圖片
