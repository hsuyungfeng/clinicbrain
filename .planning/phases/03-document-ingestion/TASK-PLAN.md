# Phase 03 實作計畫：文件擷取管線 Stage 1

> 給執行者（Antigravity）：本文件是完整實作規格，涵蓋 Phase 03 **Stage 1**（文字型文件擷取
> + 簡繁轉換 + `faq_cache` 建表與寫入路徑）。完成後請勿自行 commit — 交回使用者，由
> Claude（此計畫作者）驗證後再決定是否提交。請先讀過 `AGENTS.md`（專案根目錄）、
> `.planning/HANDOFF.json`、`.planning/phases/03-document-ingestion/PLAN.md`（本文件的背景
> 與使用者決策），理解既有規範後再開始。

## 背景（已實測盤點確認，非假設）

`OriginalData/緻妍外科診所/` 底下三份指定優先處理的檔案已確認存在：

```
客服回覆話術.xlsx                              20.7K，4 個工作表
緻妍可自費門診手術 可配合開立診斷書.docx        1.1M
緻妍自費門診手術內容.docx                       1.4M
```

**`緻妍自費門診手術內容.docx` 實測內容含有大量原始價格數字**（已用 `python-docx`
讀取確認，非猜測）：

```
'疤痕美化：矽膠片silicon tape ... $1500 可重複使用...'
'甲溝炎：自費處理，傷口只有一處收費$4500；若2側同手或足趾收費$6000...'
'反覆性甲溝炎:部分甲床切除手術 ... 傷口只有一處收$6000，同趾雙側收費$8000...'
'痣、肉芽、疣或多處皮膚贅生物：小顆且平面的收費$200/一顆...若需病理切片檢驗所收費$2000...'
'*以下自費價格以健保點值X2.5'
```

**這代表 `AGENTS.md` 的價格屏蔽規則在本次任務裡不是理論風險，是這批文件的真實內容主體
之一。** 這份文件本身有 63 段落、28 段非空、5 張表格——表格內容也極可能含價格，Stage 1
的擷取程式必須把表格一併納入（不能只讀 `paragraphs`，見 TASK-01 說明）。

`客服回覆話術.xlsx` 有 4 個工作表：`工作表1`（A1:B92）、`追蹤`（A2:A24）、
`客戶詢問`（A2:M67，欄位數多，可能已經是 Q&A 或客服紀錄的結構化表格）、
`療程關懷`（A2:A40）。實際欄位內容需要在 TASK-01 執行時先讀出來看過再決定怎麼解析
（不要假設固定欄位語意，見 TASK-01 說明）。

Python 環境現況（已實測確認）：`python-docx` 已安裝、`openpyxl` 已安裝；
`pdfplumber`、`python-pptx`、`opencc` **未安裝**，需要在虛擬環境內安裝（不確定專案是否用
`venv`/`uv`/系統 Python，請先確認專案既有慣例再安裝，不要污染系統 Python）。

## 目標（本次 TASK-PLAN 範圍 = PLAN.md 的 Stage 1，不含 Stage 2/3）

1. 建立 `faq_cache` 資料表（schema 已在 PLAN.md 定案，見 TASK-00）
2. 為 docx/xlsx 建立文字擷取工具（pdf/pptx 視 Stage 1 實際遇到的檔案類型決定是否本次一併做，
   見 TASK-01 範圍說明）
3. 簡體字文件簡繁轉換（`opencc`）
4. 擷取出的文字 → LLM（Phase 02 的 `local_llm_call`）→ 轉成 Q&A 對 → 驗證 → 寫入 `faq_cache`
5. 用三份優先檔案（`客服回覆話術.xlsx`、兩份自費門診手術 docx）跑通整條管線，驗證可行後
   才考慮擴大範圍（本次不要求處理 `OriginalData/` 下全部檔案）

## 具體任務

### TASK-00：`faq_cache` 資料表 + 唯一寫入路徑

**1. Schema**（`src/db/clinic_schema.sql`）新增（緊接在 `page_index_trees` 相關區塊之後）：

```sql
CREATE TABLE IF NOT EXISTS faq_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id TEXT REFERENCES clinic_info(clinic_id),
    topic_key TEXT,           -- 對應療程/主題 slug，NULL = 通用醫療
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category TEXT NOT NULL,   -- 'special' or 'general'
    source_type TEXT DEFAULT 'manual',  -- 'manual' | 'llm_generated' | 'clinic_upload'
    content_version INTEGER NOT NULL DEFAULT 1,
    needs_regeneration BOOLEAN NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS faq_cache_fts USING fts5(
    question,
    answer,
    content='faq_cache',
    content_rowid='id',
    tokenize='trigram'
);
```

**FTS5 觸發器**：比照 `page_index_trees`/`page_index_fts` 現有的三個觸發器模式
（`page_index_ai`/`page_index_au`/`page_index_ad`，在 `clinic_schema.sql` 裡搜尋
`page_index_ai` 可以找到範本），為 `faq_cache`/`faq_cache_fts` 建立對應的 AFTER
INSERT/UPDATE/DELETE 觸發器，**確保 `tokenize='trigram'` 沒有遺漏**（`AGENTS.md` 2.3 節
明確警告過這個雷：TASK-003 時 `page_index_fts` 曾經漏改成 trigram，新資料完全搜不到）。
schema 改完後務必執行 `SELECT sql FROM sqlite_master WHERE sql LIKE '%fts5%'` 逐一確認
`faq_cache_fts` 也在 trigram 清單裡，並跑一次真實中文關鍵字 `MATCH` 查詢驗證。

**2. 唯一寫入路徑**（新增 `src/pageindex/faq_writer.py`，比照
`src/pageindex/db_writer.py` 的 `upsert_trees()` 設計）：

```python
CONTENT_FIELDS = ("question", "answer", "category", "topic_key")

def upsert_faqs(conn, faqs, source_type: str):
    """增量寫入 faq_cache。faqs: list of dict，每個 dict 必須含
    'clinic_id'（可為 None，代表 general 類不綁特定診所——但目前 category='special'
    的資料應該都要有值，寫入前應驗證：category='special' 卻 clinic_id 為
    None/空值時拋出 ValueError，比照 db_writer.py 對 page_index_trees.clinic_id
    的驗證方式）。

    邏輯完全比照 db_writer.py 的 upsert_trees()：以 (clinic_id, topic_key, question)
    或其他你判斷合理的唯一鍵去比對既有資料（faq_cache 沒有 UNIQUE 約束像
    page_index_trees.doc_id 那樣天然的唯一鍵，需要你設計比對邏輯，建議在
    schema 加一個 UNIQUE(clinic_id, topic_key, question) 約束，避免同一題被
    重複寫入多次）——新資料 INSERT（content_version=1）；既有資料內容有變
    才 UPDATE 並遞增 content_version；內容相同則跳過。
    """
```

**這是 `faq_cache` 的唯一權威寫入函式**——Stage 1 的文件擷取管線與未來 Phase 04 願景
草案提到的夜間批次都必須呼叫它，不得各自重新實作 INSERT/UPDATE 邏輯（`AGENTS.md` 2.2
節明文警告過的 TASK-003 重複寫入路徑教訓，`faq_cache` 不能重蹈覆轍）。

### TASK-01：docx/xlsx 文字擷取工具

新增 `src/ingestion/` 目錄（新模組，`src/ingestion/extract_text.py`），提供：

```python
def extract_docx_text(path: str) -> str:
    """讀取 .docx 檔案，回傳純文字內容。必須同時涵蓋 document.paragraphs
    與 document.tables——只讀 paragraphs 會漏掉表格內容（本次優先檔案之一
    緻妍自費門診手術內容.docx 確認含 5 張表格，可能也有價格/療程資訊）。
    表格內容建議逐儲存格擷取、用可辨識的分隔方式（如 Tab 或換行）串起來，
    不需要保留表格視覺排版，重點是文字內容不遺漏。"""

def extract_xlsx_text(path: str) -> dict[str, list[dict]]:
    """讀取 .xlsx 檔案，回傳 {工作表名稱: [列資料字典, ...]}。先讀出第一列
    當作欄位標題（若存在），每一列轉成 {欄位名: 儲存格值} 的字典。不要假設
    固定的欄位語意（如「這一定是問題欄」「那一定是答案欄」）——客服回覆話術.xlsx
    的 4 個工作表結構不一定相同，本函式只負責忠實擷取原始資料，欄位語意判斷
    交給 TASK-03 的 LLM 轉換階段處理（用 prompt 讓 LLM 自己判斷這是不是
    Q&A 格式，不要在擷取層用程式碼猜測欄位語意，避免誤判）。"""
```

**pdf/pptx 支援視情況決定**：若本次執行範圍內的三份優先檔案都是 docx/xlsx（目前盤點
結果確認如此），可以先不裝 `pdfplumber`/`python-pptx`、不寫對應擷取函式，留給 Stage 1
後續擴大範圍時再做（`PLAN.md` 本來就講「先驗證三份優先檔案可行，再擴大範圍」）。若你
在執行過程中發現有必要現在就處理 pdf/pptx，請在交付說明中明確標註原因，不要沒有
說明地默默擴大範圍。

**輸出格式**：擷取結果先寫成本地 JSON 中繼檔（例如 `scripts/ingestion_output/*.json`），
不要在同一步驟直接生成 Q&A——擷取與生成分開，方便人工檢查擷取品質。`OriginalData/` 已
`.gitignore`，這些中繼產物也**不要進版控**（是否要加進 `.gitignore` 由你判斷，若專案
`.gitignore` 已有涵蓋 `scripts/ingestion_output/` 這類路徑的萬用規則則不用改，沒有的話
請補上）。

### TASK-02：簡繁轉換

新增 `src/ingestion/convert_chinese.py`：

```python
def to_traditional(text: str) -> str:
    """用 opencc 把簡體中文轉成繁體中文。建議設定檔用 's2twp'
    （簡體→台灣正體，含慣用詞轉換，例如「軟件」→「軟體」，比單純
    's2t'（僅字形轉換）更適合台灣醫美診所的語境）。"""
```

**本次三份優先檔案是否含簡體字內容**：`PLAN.md` 盤點指出「至少 10 個檔名含簡體字的
儀器手冊」屬於後續擴大範圍時才會遇到的檔案，不在本次三份優先檔案清單內——但仍要**實作
好這個轉換函式並寫測試**，因為 TASK-03 的驗證層依賴它存在（先把管道搭好，即使本次
三份檔案剛好不需要觸發轉換路徑）。測試至少涵蓋：simplified→traditional 轉換正確性
（找幾個常見簡繁差異字如「软件/軟體」「显示/顯示」驗證）、已經是繁體的文字經過轉換
應該保持不變（冪等/無害）。

### TASK-03：LLM 轉 Q&A + 輸出驗證 + 寫入

新增 `src/ingestion/generate_faq.py`，串接 Phase 02 的 `src/pageindex/llm_client.py`：

```python
def build_faq_prompt(source_text: str, source_filename: str) -> str:
    """組裝 prompt，要求 LLM 把來源文字改寫成「病患可能會問的問題 + 答案」
    格式的 JSON 陣列，每個元素 {"question": ..., "answer": ...}。

    強制規則（寫入 prompt 本文，並在輸出端再次驗證，完全比照
    prompt_template.py 既有 CONSTRAINT 模式）：
    - 全篇繁體中文
    - 絕對禁止輸出任何原始價格數字（本次來源文件確認含大量 $ 金額，
      LLM 改寫時必須主動過濾，不確定的費用資訊一律改成「請致電診所確認」）
    - 不得輸出政治/主權/意識形態立場表述（沿用 Phase 02 新增的第 7 條規則
      精神，這裡是新的生成路徑，需要重新聲明，不能假設共用 prompt_template.py
      的規則清單就自動繼承）
    - 不得生成醫師專屬醫囑內容（比照 physician_notes 留白原則精神——FAQ 沒有
      對應欄位，改為：涉及具體臨床決策判斷的內容應該保守改寫或省略，不臆測）
    """

def parse_and_validate_faq(raw_output: str) -> list[dict]:
    """解析 LLM 輸出為 [{"question":..., "answer":...}, ...]，並執行驗證：
    - 全篇繁體中文（可重用 prompt_template.py 的 _SIMPLIFIED_CHAR_SAMPLE
      機制，如果那個常數目前是模組內部變數不方便 import，評估要不要在
      prompt_template.py 把它改成可匯出，或在這裡獨立維護一份同等清單——
      你判斷哪個做法對專案結構更合理，但兩份清單絕對不能長期分歧漂移）
    - 無價格洩漏（可重用 prompt_template.py 的 _PRICE_PATTERN 邏輯，理由同上）
    - 無政治立場表述（可重用 _POLITICAL_STANCE_PHRASES，理由同上）
    - question/answer 皆非空白
    任何一項驗證失敗的 Q&A 項目應該被剔除、不寫入資料庫，不是整批全部作廢
    （因為一份來源文件可能生成多筆 Q&A，其中幾筆有問題不代表全部都有問題）。
    驗證失敗的項目連同失敗原因記錄下來供人工複查（例如印出或寫進一個
    rejected_faqs 中繼檔），不要靜默丟棄。
    """
```

**串接方式**：`local_llm_call`（`src/pageindex/llm_client.py`）簽章符合
`Callable[[str], str]`，`build_faq_prompt()` 組出 prompt 字串、傳給 `local_llm_call()`、
拿到原始輸出後傳給 `parse_and_validate_faq()`。**不要修改 `llm_client.py` 本身**——
它是 Phase 02 已完成並驗證過的既有模組，這裡只是新增一個呼叫端。

**完整流程**（新增 `scripts/run_stage1_ingestion.py` 作為本次三份優先檔案的執行入口）：

```
extract_docx_text() / extract_xlsx_text()
  → （若偵測到簡體字內容）to_traditional()
  → build_faq_prompt() → local_llm_call() → parse_and_validate_faq()
  → 組成 faq_writer.upsert_faqs() 要求的 dict 格式
    （clinic_id='3503190424'、category='special'——三份優先檔案都是診所
    專屬業務資料、source_type='clinic_upload'——這是文件擷取管線的產物，
    不是人工手寫也不是無來源的 LLM 生成，topic_key 可以留 None 或依你
    判斷填入合理值，例如依來源檔名分類，但不要求精確對應到某個
    page_index_trees.doc_id）
  → faq_writer.upsert_faqs(conn, faqs, source_type='clinic_upload')
    寫入隔離測試複本（不要寫入正式 clinic.db，比照 TASK-008/Phase 02/
    Phase 04 建立的隔離慣例，用 shutil.copy2() 複製再操作）
```

## CONSTRAINT（必須遵守，違反視為交付無效）

1. **絕對禁止在任何輸出、註解、commit 訊息中出現簡體中文**。全部繁體中文。
2. **絕對禁止價格洩漏**——這次是本任務最核心的風險，來源文件本身含大量原始價格
   （已實測確認 `$1500`/`$4500`/`$6000`/`$8000`/`$200`/`$2000` 等），
   `parse_and_validate_faq()` 的價格檢測**必須**用真實含價格的來源段落測試過
   （不能只用不含價格的乾淨測試字串），確認真的會被攔截。
3. **絕對不能讓本任務的測試/驗證過程寫壞正式 `clinic.db`**——所有寫入操作都在
   `shutil.copy2()` 複本上進行，Claude 驗收時會檢查正式 `clinic.db` 遷移前後
   SHA-256 是否一致。
4. FTS5 虛擬表（`faq_cache_fts`）**必須明確指定 `tokenize='trigram'`**，schema 改完
   後務必逐一用 `SELECT sql FROM sqlite_master WHERE sql LIKE '%fts5%'` 確認，並跑真實
   中文關鍵字 `MATCH` 查詢驗證，不能只信任「schema 語法正確」。
5. `faq_cache` 的寫入**只能**透過 `src/pageindex/faq_writer.py` 的 `upsert_faqs()`，
   不得在擷取/生成腳本裡另外實作 INSERT/UPDATE 邏輯。
6. **不要修改** `src/pageindex/llm_client.py`、`src/pageindex/prompt_template.py`、
   `src/pageindex/db_writer.py`、`src/pageindex/seed_trees.py`、`src/query/`、
   `src/clinic/` 既有程式碼——本任務只新增 `src/ingestion/` 與
   `src/pageindex/faq_writer.py`，Phase 01/02/04 已完成的部分不動。
7. **不要處理 Stage 2（圖片 OCR）與 Stage 3（影片/複雜 PDF）**，也不要擅自擴大範圍去
   處理三份優先檔案以外的其他檔案——`PLAN.md` 明確要求「先驗證三份優先檔案可行，再
   擴大範圍」，這是任務邊界，不是建議。
8. `OriginalData/` 原始檔案與擷取後的中繼產物（JSON）都不應該進版控（`OriginalData/`
   本身已 `.gitignore`；中繼產物需要你確認 `.gitignore` 是否已涵蓋，沒有的話補上）。
9. Phase 01/02/04 既有的 104 個 pytest 測試套件不應該因為本次改動而失敗（新增
   `faq_cache` 相關測試除外，那些是預期新增的）。交付前請重新執行 `pytest tests/`
   確認全數仍然通過。

## 驗收標準（交付時請附上以下驗證結果）

1. `src/db/clinic_schema.sql` 修改後的 `faq_cache`/`faq_cache_fts` 完整內容，以及三個
   FTS5 觸發器（AI/AU/AD）的完整內容。
2. `SELECT sql FROM sqlite_master WHERE sql LIKE '%fts5%'` 的完整輸出，證明
   `faq_cache_fts` 確實是 `tokenize='trigram'`，並附上一次真實中文關鍵字 `MATCH`
   查詢的實際結果（不能是空結果，要真的命中）。
3. `extract_docx_text()`/`extract_xlsx_text()` 對三份優先檔案的實際擷取結果摘要
   （字數/段落數、xlsx 各工作表擷取到的列數），證明擷取沒有遺漏（尤其
   `緻妍自費門診手術內容.docx` 的 5 張表格內容是否有被擷取到）。
4. `parse_and_validate_faq()` 對**真實刻意構造含價格的輸入**（例如直接塞入
   `"$4500"` 這類來源文件真實出現過的格式到模擬 LLM 輸出中）進行測試，證明會被
   正確攔截、剔除該筆但不影響同批其他合格的 Q&A。
5. 用三份優先檔案實際跑過一次端到端流程（擷取 → LLM 生成 → 驗證 → 寫入隔離測試
   複本）產出的 Q&A 內容（完整 JSON 或格式化輸出皆可），並附上人工判讀：內容是否
   合理、是否有價格洩漏漏網、是否有簡體字殘留。
6. `pytest tests/` 的完整輸出，確認 104 個既有測試全數仍然通過，並列出新增了哪些
   測試案例。
7. 遷移/測試前後正式 `clinic.db` 的 SHA-256 比對，證明未受影響。
8. 交付時附上簡短說明：`src/ingestion/` 各檔案的職責劃分、`opencc` 設定檔選用
   （`s2twp` 或其他，附理由）、三份優先檔案的擷取與生成結果各自的資料量摘要、
   驗證失敗（價格/簡體字/立場/空白）的實際觸發情況（若有，附具體案例）。

## 不在本任務範圍內（請勿順手處理）

- Stage 2（圖片 OCR，47 張圖片的可行性評估）、Stage 3（影片/複雜 PDF）
- 三份優先檔案以外的其他文件（`儀器/` 目錄下的簡體字操作手冊、`衛教文章/`、
  `廠商PPT/`、`每月活動單/`、`一般醫學/` 底下的所有內容）
- `pdf`/`pptx` 格式的擷取工具（除非執行中發現本次範圍內確實需要，並在交付說明中
  明確標註原因）
- Phase 04 TASK-02（router.py/custom_notes.py 的 clinic_id 預設值移除）、TASK-03
  （依賴 Phase 05）——那是另一個獨立任務，不要在本任務順手處理
- 夜間批次生成排程（Phase 04 願景草案，屬未來 Phase 範圍）
- `page_index_trees` 相關的任何程式碼或 schema（本任務只碰 `faq_cache`）

這是本專案一貫的做法，請避免越界，讓 Phase 03 Stage 1 的第一批任務乾淨收尾。
