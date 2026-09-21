# TASK-007 實作計畫：診所資料庫整合（clinic_custom_notes）

> 給執行者（Antigravity）：本文件是完整實作規格。完成後請勿自行 commit — 交回給使用者，
> 由 Claude（此計畫的作者）驗證後再決定是否提交。請先讀過 `AGENTS.md`（專案根目錄）與
> `.planning/HANDOFF.json`，理解專案的既有規範與 CONSTRAINT 後再開始。

## 背景與現況

TASK-007 原始只有一行標題「Integrate clinic database with RAG query」，從未展開成具體
規格。這份計畫是調查後補上的規格。

`src/db/clinic_schema.sql` 定義了 `clinic_custom_notes` 表：

```sql
CREATE TABLE clinic_custom_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id TEXT NOT NULL,
    section TEXT NOT NULL,           -- pre_op, procedure, post_op_short, maintenance
    note TEXT NOT NULL,              -- Physician's custom note
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (clinic_id) REFERENCES clinic_info(clinic_id)
);
```

**實測現況**（2026-09-21）：這張表目前 0 筆資料、查詢層（`src/query/router.py`）完全沒
有查過它、整個 codebase 也沒有任何 INSERT 進這張表的程式碼路徑。

### 重要架構釐清：這張表跟 `page_index_trees.*_physician_notes` 不是同一件事

`page_index_trees` 每個段落（`pre_op`/`procedure`/`post_op_short`/`maintenance`）都各自
有一個對應的 `*_physician_notes` 欄位（例如 `pre_op_physician_notes`）。這是**綁在單一
`doc_id`（單一療程）上的專屬醫囑**，目前全部是 `NULL`，設計上由醫師針對「這一個特定療程」
填寫（見 `AGENTS.md` 2.2 節：「LLM 不得自行生成內容，留空待醫師人工審核填入」）。

`clinic_custom_notes` 則是**綁在 `clinic_id + section` 上、不綁特定療程**的診所層級通用
備註——例如「本診所所有術前流程一律要求空腹 8 小時」這種橫跨多個療程、屬於診所整體政策
的說明，不屬於任何單一 `doc_id`。

**這兩者不衝突、不應該合併成同一欄位**，本任務只處理 `clinic_custom_notes`，不要去動
`page_index_trees.*_physician_notes` 的既有邏輯與資料。

## 目標

1. 補上 `clinic_custom_notes` 的查詢路徑：查詢某療程時，若該療程屬於某診所（目前
   系統唯一的診所是 `zhiyan-clinic`），應同時撈出該診所在對應 `section` 的通用備註，
   跟 PageIndex 樹的該段落內容一起回傳。
2. 補上寫入路徑：目前完全沒有任何方式能把資料寫進這張表，需要提供一個簡單、可重複
   執行的方式（腳本或函式皆可，見下方子任務 B）。
3. 撰寫至少 1-2 筆範例資料（比照 `src/pageindex/seed_trees.py` 手寫範本的精神），
   讓這條路徑有實際資料可驗證，不是空表。

## 具體任務

### 子任務 A：查詢層整合

在 `src/query/router.py` 新增查詢函式（可仿照既有的 `get_clinic_hours()` /
`get_clinic_info()` 寫法，函式簽章風格保持一致）：

```python
def get_clinic_custom_notes(conn: sqlite3.Connection, clinic_id: str = "zhiyan-clinic") -> dict:
    """回傳 {section: note} 的字典，例如 {"pre_op": "本診所術前一律要求空腹8小時", ...}"""
```

在 `handle_query()` 裡，當 route 為 `special` 且有 PageIndex 樹命中時，撈出該診所的
`clinic_custom_notes`，合併進回傳結果——**具體怎麼合併請自行設計**（例如在
`QueryResponse` dataclass 新增一個 `clinic_custom_notes: dict` 欄位單獨回傳，或是把對應
`section` 的備註附加到每個 `page_index_hits` 項目的欄位裡皆可），但務必：

- **不要**混進 `general` 路由的回傳結果（`clinic_custom_notes` 是診所專屬資訊，跟
  `clinic_info`/`clinic_hours` 一樣，只該出現在 `special` 路由，理由與
  `router.py` 模組頂部現有的說明一致：避免診所專屬資料滲入一般醫學問答）。
- **不要**跟 `page_index_trees.*_physician_notes` 的既有欄位混為一談或互相覆蓋——
  兩者在回傳結果中應該是可分辨的獨立資訊，讓呼叫端知道「這是療程專屬醫囑」還是
  「這是診所通用備註」。

### 子任務 B：寫入路徑

新增一個簡單的腳本或函式（放在 `src/db/` 或新建 `src/clinic/` 皆可，自行判斷合理位置，
並在交付說明中解釋），提供類似這樣的能力：

```python
def upsert_clinic_note(conn, clinic_id: str, section: str, note: str) -> None:
    """新增或更新（同 clinic_id + section 視為同一筆，用 UPDATE 而非每次新增一筆）
    診所的段落通用備註。"""
```

**設計要求**：
- `section` 必須是 `pre_op`/`procedure`/`post_op_short`/`maintenance` 四者之一，
  超出範圍應該拒絕寫入並清楚報錯（不要靜默失敗或寫入無效值）。
- 同一個 `clinic_id + section` 只保留最新一筆（用 UPDATE，不要每次呼叫都新增一筆
  造成重複資料——這點呼應本專案在 TASK-003/SCHEMA-INCREMENTAL 階段已經建立的「增量
  更新優於整批新增」原則，雖然 `clinic_custom_notes` 表本身沒有
  `content_version` 欄位，不需要引入那麼複雜的版本追蹤，但至少不能無限新增重複列）。
- `updated_at` 在更新時要正確帶入 `CURRENT_TIMESTAMP`（比照
  `src/pageindex/db_writer.py` 的既有做法：不用 trigger 自動維護，由呼叫端明確帶入）。

### 子任務 C：範例資料

比照 `src/pageindex/seed_trees.py` 的精神，寫 1-2 筆合理的診所通用備註範例（呼叫子任務
B 的寫入函式），內容需符合下方 CONSTRAINT。範例應該是**真的會出現在醫美診所情境的通用
政策說明**，不是隨便湊字數，例如：術前空腹規定、療程當天禁止的行為（比照現有
`page_index_trees` 範本裡已經出現過的「懷孕或裝有心律調節器者不建議施作」這類通用性
禁忌，但這裡要寫的是**跨療程的診所政策**，不是特定單一療程的細節——這個區分很重要，
若拿不準某句話該放在 `clinic_custom_notes` 還是某療程的 `pre_op` 欄位，判斷標準是：
「這句話適用於本診所所有療程嗎？還是只適用於某一個特定療程？」前者放
`clinic_custom_notes`，後者維持原本放在 `page_index_trees` 對應療程列的做法，不要
搬動既有資料）。

## CONSTRAINT（必須遵守，違反視為交付無效）

這些規則來自專案根目錄 `AGENTS.md`，是全專案通用的強制規定：

1. **絕對禁止在任何輸出、註解、commit 訊息中出現簡體中文**。全部使用繁體中文。
2. **絕對禁止任何形式的價格資訊**出現在範例備註或程式碼輸出中。
3. `page_index_trees` 與其 `*_physician_notes` 欄位**與本任務無關**，不要觸碰它的
   既有資料或寫入邏輯（那是 `src/pageindex/db_writer.py` 的職責，見 AGENTS.md 2.2 節）。
4. 本任務**不需要**碰 FTS5 相關 schema——`clinic_custom_notes` 目前沒有對應的 FTS5
   虛擬表，也不需要新增一個（這張表資料量小、查詢一律是 `clinic_id + section` 精確
   查找，不需要全文檢索）。若你判斷真的有必要新增 FTS5 表，先重讀 AGENTS.md 2.3 節，
   任何新的 FTS5 虛擬表都要明確指定 `tokenize='trigram'` 並實測驗證，不能只憑
   schema 語法正確就假設可行——但預設情況下這個任務不該用到 FTS5。
5. 內容不確定時寧可保守、不要編造——與 `src/pageindex/prompt_template.py` 的既有原則
   一致。範例備註要是合理、真實可信的診所政策說明，不是隨便寫幾句充數。

## 驗收標準（交付時請附上以下驗證結果）

1. 執行寫入函式/腳本後，`SELECT * FROM clinic_custom_notes` 應該看到範例資料正確
   寫入（至少 1-2 筆，`section` 值合法、`clinic_id` 對應到 `zhiyan-clinic`）。
2. 對同一個 `clinic_id + section` 重複呼叫寫入函式兩次（用不同的 `note` 內容），驗證
   最終該 `clinic_id + section` 只有一筆資料（新內容覆蓋舊內容），不是變成兩筆——
   這是驗證子任務 B「同一 clinic_id+section 只保留最新一筆」要求有沒有真的做到。
3. 用 `src/query/router.py` 的 `handle_query()` 對至少 2 個 `special` 路由查詢（例如
   跟療程相關的查詢）驗證回傳結果有包含 `clinic_custom_notes` 的內容；再用至少 1 個
   `general` 路由查詢，驗證回傳結果**不含**任何 `clinic_custom_notes` 內容（這是驗證
   子任務 A「不要混進 general 路由」的要求）。
4. 確認 `python3 scripts/seed_database.py` 整條流程仍可從頭跑過、不拋出例外（這是
   現有的回歸測試方式）。
5. 對修改/新增過的 Python 檔案做基本的 import 健全性檢查，比照本專案既有模組使用的
   `try: from .X import Y except ImportError: from X import Y` 相對/絕對匯入相容模式
   （此專案腳本是直接用 `python3 path/to/script.py` 執行，沒有 `__init__.py`）。
6. 重新執行 TASK-005 既有的路由測試案例，確認沒有 regression（可參考
   `.planning/HANDOFF.json` 裡 TASK-005 的 notes 欄位列出的測試查詢清單，或直接對
   `extract_search_terms()`/`classify()` 跑幾組先前驗證過的查詢字串比對結果）。
7. 交付時附上簡短說明文字：查詢/寫入函式放在哪個檔案、如何跟 `handle_query()` 現有
   回傳結構整合、範例資料的內容與理由。

## 不在本任務範圍內（請勿順手處理）

- TASK-008（評估測試套件）的工作內容。
- `page_index_trees` 與 `*_physician_notes` 相關的任何邏輯或既有資料異動。
- OTC 本地化層（`src/db/otc_mappings.json` 等，已於 TASK-006 完成）。
- 本地 LLM 推理層（Phase 02 草案範圍）——這是規則式的資料查詢/寫入，不需要引入 LLM。
- 為 `clinic_custom_notes` 新增 FTS5 全文檢索（除非驗收標準明確要求且經過謹慎驗證，
  預設不需要）。

這是本專案一貫的做法（見 `AGENTS.md` 第 5 節「任務範圍要守住邊界」），請避免越界。
