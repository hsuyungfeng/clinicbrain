# TASK-006 實作計畫：OTC 藥品本地化層

> 給執行者（Antigravity）：本文件是完整實作規格。完成後请勿自行 commit — 交回給使用者，
> 由 Claude（此計畫的作者）驗證後再決定是否提交。請先讀過 `AGENTS.md`（專案根目錄）與
> `.planning/HANDOFF.json`，理解專案的既有規範與 CONSTRAINT 後再開始。

## 背景與現況

目前 `scripts/seed_database.py` 的 `update_otc_names()`（第 183-227 行）用一個寫死在
函式內的 Python dict（14 個成分）做 `UPDATE ... WHERE ingredient LIKE '%X%'`：

```python
otc_mapping = {
    'ACETAMINOPHEN': '俗稱普拿疼的乙醯胺酚',
    'IBUPROFEN': '常見的布洛芬',
    # ... 共 14 筆
}
```

**實測數據**（2026-09-21，`clinic.db` 現況）：
- 藥品總數：7,573 筆
- 目前已覆蓋 `otc_name_chinese`：456 筆（約 6%）
- 已知同義詞缺口：ACETAMINOPHEN 成分在資料庫中也常以 `PARACETAMOL` 記錄（同一化學物質的
  美規/英規命名差異），目前的 mapping 只匹配 `'ACETAMINOPHEN'` 字串，會漏掉純寫
  `PARACETAMOL` 的品項。這是需要修正的真實 bug，不是理論風險。

## 目標

1. 擴充 OTC 成分覆蓋範圍，同時修正已知的同義詞匹配缺口。
2. 把對照表從寫死在 Python 函式內的 dict，移到更適合診所人員自行維護、且與專案既有
   資料架構風格一致的儲存方式。
3. 讓查詢層（`src/query/router.py` 的 `handle_query()`）實際用上 `otc_name_chinese`
   ——目前這個欄位存在資料庫裡、`search_drugs()` 也會回傳它，但沒有任何地方在**組織
   使用者可讀回覆**時特別把它凸顯出來（目前只是原始 SQL 欄位之一）。

## 具體任務

### 子任務 A：修正並擴充對照表資料

1. 讀取 `OriginalData/藥品項查詢項目檔260101.csv` 的 `成分` 欄位，統計最高頻的
   活性成分字串（用 pandas 或 csv 模組做簡單的 value_counts，不需要精密 NLP）。
   目標找出至少涵蓋以下已知常見 OTC 類別的成分，並修正/擴充對照：
   - 解熱鎮痛：ACETAMINOPHEN **與其同義詞 PARACETAMOL**（务必两个字串都匹配到同一個
     中文說明，不要重複定義成兩筆不同對照）、IBUPROFEN、ASPIRIN、MEFENAMIC ACID
   - 抗組織胺：DIPHENHYDRAMINE、LORATADINE、CETIRIZINE、FEXOFENADINE、
     CHLORPHENIRAMINE
   - 腸胃藥：OMEPRAZOLE、ESOMEPRAZOLE（資料中已知存在，見 `src/db/clinic_schema.sql`
     驗證範例）、RANITIDINE、FAMOTIDINE、簡單制酸劑（如 ALUMINUM HYDROXIDE、
     MAGNESIUM HYDROXIDE 若資料中有找到）
   - 慢性病常見藥（現有 mapping 已涵蓋 METFORMIN/AMLODIPINE/LOSARTAN/
     ATORVASTATIN/SIMVASTATIN，維持不變即可，除非統計發現有明顯缺漏的高頻成分）
   - 其他統計發現的高頻成分，只要能找到對應且準確的台灣通俗說法就一併加入；若無法
     確定通俗說法**不要亂猜**，寧可留空、標記為待審核，也不要生成不確定的內容
     （這點與 `src/pageindex/prompt_template.py` 的驗證原則一致——見下方合規要求）。

2. 目標覆蓋率：不要求 100%，但應该讓覆蓋率從目前 ~6% 有明顯提升（沒有絕對數字要求，
   實際達成多少依統計結果而定，但應在計畫產出的說明中回報「擴充前後覆蓋率變化」）。

### 子任務 B：對照表儲存方式重構

現況是寫死在 `scripts/seed_database.py` 函式內的 dict。改成以下其中一種方式（**請
自行判斷並在交付說明中寫清楚選了哪個、為什麼**，兩種都是可接受的設計，不強制指定）：

- **選項 1**：獨立 JSON 設定檔，例如 `src/db/otc_mappings.json`，格式：
  ```json
  {
    "mappings": [
      {"ingredient_pattern": "ACETAMINOPHEN", "aliases": ["PARACETAMOL"], "otc_name_chinese": "俗稱普拿疼的乙醯胺酚"},
      ...
    ]
  }
  ```
  `update_otc_names()` 改成讀取這個檔案，而不是內嵌 dict。

- **選項 2**：獨立 DB 表 `otc_mappings`（於 `src/db/clinic_schema.sql` 新增
  `CREATE TABLE IF NOT EXISTS otc_mappings (...)`），欄位至少包含
  `ingredient_pattern TEXT`、`otc_name_chinese TEXT`、`created_at`/`updated_at`。
  `update_otc_names()` 改成先 `SELECT` 這個表，再逐筆 `UPDATE drugs`。

**不管選哪個**，都要滿足：
- 同義詞（如 ACETAMINOPHEN/PARACETAMOL）必須能共用同一筆中文說明，不要求呼叫端
  自己處理同義詞邏輯——由資料結構或查詢邏輯負責。
- `update_otc_names(conn)` 函式簽章維持不變（`scripts/seed_database.py` 呼叫它的地方
  不應該需要跟著改），內部實作可以自由調整。
- 不要破壞 `scripts/seed_database.py` 現有的執行流程。已確認 `main()` 第 291 行
  仍會呼叫 `otc_count = update_otc_names(conn)`，這個呼叫點必須繼續正常運作。

### 子任務 C：查詢層整合

在 `src/query/router.py` 或 `src/query/search.py`（自行判斷放哪裡更合理，並在交付
說明中解釋）新增一個小函式，把 `search_drugs()` 回傳的結果，在有 `otc_name_chinese`
非空值的情況下，於使用者可讀的欄位（可以是新增一個 `display_name` 欄位，或直接在
既有欄位上處理，自行判斷）優先呈現本地化俗名而非原始英文/學名。

**不要**大幅改動 `handle_query()` 既有的路由/分流邏輯，只需要在藥品結果的呈現層
加這一層本地化優先顯示。

## CONSTRAINT（必須遵守，違反視為交付無效）

這些規則來自專案根目錄 `AGENTS.md`，是全專案通用的強制規定：

1. **絕對禁止在任何輸出、註解、commit 訊息中出現簡體中文**。全部使用繁體中文。
2. **絕對禁止任何形式的價格資訊**出現在對照表或程式碼輸出中（本任務不太可能觸碰到
   價格資料，但仍需注意——若統計 CSV 過程中順手印出任何含金額的除錯訊息，記得移除）。
3. 若新增/修改任何 FTS5 相關內容——本任務範圍內**不應該**需要動到 FTS5 schema，
   但若你判斷有必要（例如想讓 `otc_name_chinese` 更好搜尋），修改前務必重讀
   `AGENTS.md` 第 2.3 節，任何新/改的 FTS5 虛擬表都必須明確指定
   `tokenize='trigram'`，並用真實中文關鍵字跑一次 `MATCH` 查詢驗證，不能只憑
   schema 語法正確就假設可行。
4. `page_index_trees` 表**與本任務無關**，不要觸碰它的寫入邏輯（那是
   `src/pageindex/db_writer.py` 的職責，見 AGENTS.md 2.2 節）。
5. 對照表中「不確定的通俗說法」寧可留空、不要編造——這比照
   `src/pageindex/prompt_template.py` 裡「寧可用較保守、通用的描述，也不要編造具體
   數據」的既有原則。

## 驗收標準（交付時請附上以下驗證結果）

1. 執行對照表更新流程後（不論是重跑 `seed_database.py` 還是新的獨立腳本），回報
   實際覆蓋率數字：`SELECT COUNT(*), COUNT(otc_name_chinese) FROM drugs`，並與
   本文件開頭記錄的基準（7,573 / 456）對比。
2. 至少對 5 個真實成分關鍵字做手動查詢驗證（例如透過 `src/query/search.py` 的
   `search_drugs()` 或直接 SQL），證明本地化名稱有正確套用，包含明確驗證
   ACETAMINOPHEN **與** PARACETAMOL 兩種寫法都能對應到同一筆中文說明（這是本次
   要修正的已知缺口，務必驗證通過）。
3. 確認 `python3 scripts/seed_database.py` 整條流程仍可從頭跑過、不拋出例外
   （這是現有的回歸測試方式，専案目前沒有正式測試框架）。
4. 用 `python3 -c "..."` 或類似方式，對修改過的 Python 檔案做基本的 import 健全性
   檢查（確認沒有語法錯誤、import 路徑正確）——比照本專案既有模組
   （`src/pageindex/seed_trees.py` 等）使用的 `try: from .X import Y except
   ImportError: from X import Y` 相對/絕對匯入相容模式，因為這個專案的腳本是直接用
   `python3 path/to/script.py` 執行，沒有用 package 安裝方式（無 `__init__.py`）。
5. 交付時附上簡短說明文字：選了哪個儲存方案（JSON 或 DB 表）、為什麼、統計出的
   高頻成分清單、最終涵蓋的成分數量、覆蓋率變化、任何被跳過或標記待審核的成分
   及原因。

## 不在本任務範圍內（請勿順手處理）

- TASK-007（診所資料庫整合）與 TASK-008（評估測試套件）的工作內容。
- `page_index_trees` 相關的任何邏輯。
- FTS5 schema 大幅重構（除非驗收標準明確要求且經過謹慎驗證）。
- 本地 LLM 推理層（Phase 02 草案範圍）——OTC 對照表是規則式的字串比對，不需要
  也不應該引入 LLM 生成內容。

這是本專案一貫的做法（見 `AGENTS.md` 第 5 節「任務範圍要守住邊界」），過去已有
因為順手做了超出範圍的事而需要額外清理的前例，請避免重蹈覆轍。
