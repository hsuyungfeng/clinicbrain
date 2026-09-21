# TASK-008 實作計畫：評估測試套件（Phase 01 最終任務）

> 給執行者（Antigravity）：本文件是完整實作規格。完成後請勿自行 commit — 交回給使用者，
> 由 Claude（此計畫的作者）驗證後再決定是否提交。請先讀過 `AGENTS.md`（專案根目錄）與
> `.planning/HANDOFF.json`，理解專案的既有規範與 CONSTRAINT 後再開始。這是 Phase 01
> 八個任務中的最後一個，完成後整個 Phase 01 就結束了，請確保品質。

## 背景

這個專案從 TASK-001 到 TASK-007，**至今沒有任何正式的測試檔案**。所有驗證都是用
`python3 -c "..."` 手動打指令重跑，每次驗證都要重打一次相同的查詢字串。這份計畫要把
散落在過去幾次 session 手動驗證過的案例，收斂成一份可以用 `pytest` 一鍵執行的正式測試
套件，作為 Phase 01 的收尾。

環境已確認有 `pytest`（8.3.5）可用，請使用它，不要用標準庫 `unittest`（除非你有明確理由
判斷 `unittest` 更合適，並在交付說明中解釋）。

## 目標

1. 建立 `tests/` 目錄與測試檔案，涵蓋下方列出的六大類測試範疇。
2. 測試必須是**可重複執行、不依賴外部狀態、不污染正式 `clinic.db`**的。
3. 至少 50 個測試案例（原始 Phase 01 規劃就是這個數字），但重點是涵蓋率與品質，不是
   湊數字——寧可 45 個扎實的案例，也不要 60 個空洞的案例。

## 資料庫隔離規則（務必遵守，這是本任務最容易犯錯的地方）

**絕對不要讓測試直接連線到專案根目錄的 `clinic.db`**（`/home/hsu/Desktop/clinicbrain/
clinic.db`）並對它做寫入測試（例如 `clinic_custom_notes` 的 UPSERT 測試、任何 INSERT/
UPDATE 操作）。這個檔案是開發時手動維護的資料庫，先前幾次 session 的驗證都需要小心
避免污染它，重建也很簡單（1.8 秒），但測試套件應該用更乾淨的方式處理：

- 建議做法：用 pytest fixture，在測試 session 開始時，把正式 `clinic.db` 複製一份到暫存
  路徑（例如 `pytest` 內建的 `tmp_path` fixture，或 `tempfile` 模組），所有測試都對這份
  複本操作，測試結束自動清除。**唯讀查詢測試**（FTS/LIKE 搜尋、路由分類）可以直接連
  複本查詢；**會寫入的測試**（`clinic_custom_notes` UPSERT）務必確保寫入的是複本，不是
  正式檔案，且不同測試之間的寫入不能互相汙染（例如每個寫入測試前重新複製一份乾淨的
  複本，或用交易 rollback 的方式隔離）。
- 若複本方式太複雜，也可以用 `:memory:` SQLite 資料庫 + 直接套用 `src/db/clinic_schema.sql`
  重建 schema，但要注意：部分測試案例（如 OTC 本地化、PageIndex 樹搜尋）需要有實際
  seed 過的資料才有意義，若走 in-memory 空 schema，需要另外決定要不要在 fixture 裡跑
  一次完整的 seed 流程（`scripts/seed_database.py` 的邏輯）灌資料進去——這樣會比複製
  現成的 `clinic.db` 慢，請自行評估效能與正確性的取捨，並在交付說明中解釋選了哪個做法。
- **驗收時 Claude 會親自檢查測試執行前後 `clinic.db` 的內容/hash 是否有變化**，若發現
  測試套件實際上寫壞了正式資料庫，視為交付不合格，須重做。

## 具體測試範疇（六大類，缺一不可）

### 類別 1：`extract_search_terms()` 固定回歸案例

以下 6 組查詢字串與其**已知正確輸出**，已經跨 TASK-005、TASK-006、TASK-007 三次 session
手動重跑驗證過，結果逐字一致，請直接鎖定為測試的預期值（不要重新設計新案例取代它們，
這些案例的價值就在於「已經被驗證過三次」）：

```python
KNOWN_GOOD_EXTRACT_TERMS = {
    "診所幾點開門？": ["診所幾點開門", "開門", "幾點"],
    "音波拉提會痛嗎？": ["音波拉提", "拉提", "音波"],
    "乙醯胺酚是什麼藥？": ["乙醯胺酚"],
    "感冒吃什麼好？": ["感冒吃"],
    "雷射拆線": ["雷射拆線", "雷射", "拆線"],
    "請問玻尿酸填充可以維持多久？": ["玻尿酸填充", "玻尿酸", "填充", "維持"],
}
```

對 `src/query/router.py` 的 `extract_search_terms()` 函式，逐一驗證輸出與上表完全相符
（順序也要一致，因為排序邏輯本身就是被測試的行為之一）。

### 類別 2：價格遮罩（`mask_prices()`）

測試至少涵蓋以下格式都能被正確替換成 `[請致電診所確認]`：
- `"1500元"`（中文「元」）
- `"3000塊"`（中文「塊」）
- `"NT$500"` / `"NT$ 500"`（含空格與不含空格皆測）
- `"$800"`
- 同一段文字混合多種格式（例如「原價1500元，特價NT$800」應該兩處都被替換）
- 沒有價格的一般文字應該原樣不變
- 空字串與 `None` 輸入不應該拋出例外（`mask_prices("")` 與 `mask_prices(None)` 皆要測）

### 類別 3：special/general 路由隔離

至少 3 組 `special` 查詢 + 3 組 `general` 查詢，驗證：
- `special` 查詢命中診所營運關鍵字時，`clinic_info`/`clinic_hours` 應該被正確帶出
- `special` 查詢命中療程或診所政策關鍵字時，`clinic_custom_notes` 應該被正確帶出
- **所有 `general` 查詢的回傳結果，`clinic_info` 必須是 `None`、`clinic_hours` 必須是
  空 list、`clinic_custom_notes` 必須是空 dict** ——這是最關鍵的合規測試，任何一次
  滲漏都要讓測試失敗。

可以直接使用 TASK-007 交付驗證時用過的案例作為起點（`音波拉提會痛嗎？`、
`玻尿酸可以維持多久？`、`請問診所有什麼術前注意事項？` 為 special；`高血壓可以吃什麼
水果？`、`感冒要多喝水嗎？`、`頭痛想吐該看哪一科？` 為 general），但可以視需要擴充。

### 類別 4：OTC 同義詞機制

**重要**：請使用以下兩組**已確認在目前資料集中真的有效**的同義詞案例，不要用
ACETAMINOPHEN/PARACETAMOL 這組——TASK-006 驗證時發現這批資料裡沒有任何品項是「只寫
PARACETAMOL 不寫 ACETAMINOPHEN」的，用這組來證明 alias 機制不具說服力（該案例即使沒有
alias 機制、用舊邏輯也一樣會命中）：

- `ASPIRIN` 與其別名 `ACETYLSALICYLIC ACID`：驗證查詢 `ACETYLSALICYLIC ACID` 時，能
  搜到至少 1 筆原本用純 `ASPIRIN` 字串查不到、但用別名補到的品項，且該品項的
  `otc_name_chinese` 與直接查 `ASPIRIN` 得到的結果一致。
- `MAGNESIUM HYDROXIDE` 與其別名 `MAGNESIUM OXIDE`：同上邏輯，驗證別名機制確實補到
  額外品項（先前驗證過這組補到 12 筆）。

另外測試：`src/db/otc_mappings.json` 裡定義的每一筆 `pattern`，至少確認其對應的
`otc_name_chinese` 不含價格資訊、不含簡體字（可以寫一個迴圈測試，逐筆掃過 68 筆對照表，
不需要為每一筆單獨寫一個測試案例）。

### 類別 5：`clinic_custom_notes` UPSERT 行為

- 對同一 `clinic_id` + `section` 連續呼叫 `upsert_clinic_note()` 兩次、內容不同，驗證
  最終資料庫裡該 `clinic_id + section` 只有 1 筆，且內容是第二次寫入的值（不是變成
  2 筆）。
- 驗證非法 `section`（不在 `pre_op`/`procedure`/`post_op_short`/`maintenance` 範圍內）
  會拋出 `ValueError`。
- 驗證空白/純空格 `note` 會拋出 `ValueError`（`upsert_clinic_note()` 目前有做這個檢查，
  見 `src/clinic/custom_notes.py`）。

（這幾項全部要在**隔離的測試資料庫複本**上執行，見上方「資料庫隔離規則」，不能對正式
`clinic.db` 做寫入測試。）

### 類別 6：FTS5 trigram / LIKE 分流正確性

- 驗證 3 字以上的查詢字串會走 FTS5 `MATCH` 路徑、2 字以下會走 LIKE fallback——可以用
  `src/query/search.py` 的 `_use_fts()` 函式直接測試邊界值（2 字 vs 3 字 vs 空字串）。
- 對三個資料表（`drugs`、`service_items`、`page_index_trees`）各挑至少 1 個真實查詢
  案例，驗證能正確搜到預期資料（例如查 `"雷射拆線"` 應該在 `service_items` 搜到對應
  項目，查 `"音波拉提"` 應該在 `page_index_trees` 搜到 `zhiyan-clinic-hifu-lifting`）。

## 選擇性項目（若時間允許，非強制）

`src/pageindex/prompt_template.py` 的 `parse_and_validate()` 先前（TASK-004）已經手動
測試過 7 種情境（合法輸出、價格洩漏、簡體字、缺欄位、保證療效用語、code fence 容錯、
非法JSON），但從未寫成正式測試檔案。如果時間允許，將這 7 種情境也納入本次測試套件；
若評估後覺得會讓這次交付範圍過大，可以略過，並在交付說明中註明「未涵蓋，建議後續
補上」，不強制要求。

## CONSTRAINT（必須遵守，違反視為交付無效）

1. **絕對禁止在任何輸出、註解、commit 訊息中出現簡體中文**。全部使用繁體中文（測試
   案例的 docstring/註解也要繁體中文；查詢字串本身當然也是繁體中文，這點應該不會有
   疑慮）。
2. **絕對不能讓測試套件寫壞正式 `clinic.db`**——見上方「資料庫隔離規則」，這是本任務
   最重要的一條 CONSTRAINT，Claude 驗收時會直接檢查這件事。
3. 不要修改 `src/query/`、`src/clinic/`、`src/pageindex/`、`src/db/` 下任何既有的
   程式邏輯——本任務純粹是新增測試，不是修 bug。如果測試過程中意外發現某個既有函式
   有 bug，**不要自行修改**，在交付說明中清楚回報發現了什麼問題、在哪個檔案哪一行，
   交給使用者決定後續處理方式。
4. `page_index_trees.*_physician_notes` 相關資料與邏輯與本任務無關，不要觸碰。

## 驗收標準（交付時請附上以下驗證結果）

1. 測試套件可以用 `pytest tests/` 從專案根目錄一鍵執行，回報通過/失敗的案例數。
2. 執行測試前後，比對正式 `clinic.db` 的檔案 hash（例如 `md5sum clinic.db` 或
   `sha256sum clinic.db`）完全一致，證明測試沒有動到正式資料庫。
3. 全部類別 1-6 的測試都應該是通過的（若有預期會失敗的案例——例如刻意測試某個已知
   限制——請明確標註為「已知限制測試」，不要讓它以失敗狀態混在測試結果裡）。
4. 交付時附上簡短說明文字：測試檔案結構（幾個檔案、怎麼組織）、資料庫隔離採用了
   哪種做法（複本或 in-memory）、實際測試案例總數、選擇性項目（TASK-004 驗證器測試）
   有沒有做、若過程中發現任何既有程式碼的疑似 bug 也一併回報。

## 不在本任務範圍內（請勿順手處理）

- 修正任何既有程式碼的邏輯（即使測試過程中發現問題，只回報不修改）。
- Phase 02 以後的任何工作（本地 LLM、OCR、doctor-toolbox.com 整合等，見
  `.planning/VISION-EXPANSION.md`）。
- 效能測試、壓力測試——本任務是功能正確性驗證，不是效能基準測試。

這是本專案一貫的做法（見 `AGENTS.md` 第 5 節「任務範圍要守住邊界」），這是 Phase 01
最後一個任務，請確保範圍守住，讓 Phase 01 乾淨收尾。
