# Phase 04：多診所支援

## 背景

目前系統只有 1 家診所（緻妍外科診所），`clinic_id` 用人工命名的 slug
`"zhiyan-clinic"`，且這個值以**預設參數**的形式寫死在 5 個不同函式裡：

```
src/query/router.py:160  get_clinic_hours(..., clinic_id: str = "zhiyan-clinic")
src/query/router.py:179  get_clinic_info(..., clinic_id: str = "zhiyan-clinic")
src/query/router.py:192  get_clinic_custom_notes(..., clinic_id: str = "zhiyan-clinic")
src/query/router.py:239  handle_query(..., clinic_id: str = "zhiyan-clinic")
src/clinic/custom_notes.py:87   get_clinic_custom_notes(..., clinic_id: str = "zhiyan-clinic")
src/clinic/custom_notes.py:102  seed_sample_notes(..., clinic_id: str = "zhiyan-clinic")
```

底層資料表中 `clinic_info`/`clinic_hours`/`clinic_custom_notes` 三張表已經是用
`clinic_id` 欄位設計，架構本身**支援**多診所（單一資料庫、邏輯隔離）。但
`page_index_trees` **完全沒有 `clinic_id` 欄位**——診所身份只靠 `doc_id` 字串
前綴（如 `zhiyan-clinic-hifu-lifting`）辨識，且 `prompt_template.py` 用硬編碼
字串比對（`_FEW_SHOT_DOC_IDS`、`.replace("zhiyan-clinic-", "")`）解析它。這比
原先設想的「doc_id 前綴要不要換成代碼」更根本：現在的做法本身就是技術債
（2026-09-22 這次 session 盤點程式碼後確認，見下方「doc_id 設計決策」）。

目前：
1. `clinic_id` 值的命名方式未定案（人工 slug vs 官方代碼）
2. 查詢入口完全不知道當前查詢屬於哪家診所（永遠吃預設值）
3. `page_index_trees` 沒有真正的 `clinic_id` 欄位可用來做 SQL 層級的診所篩選

## 使用者決策（2026-09-22）

1. **多診所隔離方式**：單一資料庫、`clinic_id` 邏輯隔離（維持現有架構方向，
   不改成每診所一個獨立 SQLite 檔案）
2. **診所識別方式**：每家診所有自己的入口（子網域 / URL 路徑 / API endpoint），
   由部署層決定 `clinic_id`，不依賴使用者登入身份判斷——這件事本身屬於
   Phase 05（doctor-toolbox.com API 整合、對外服務介面）的範圍，本 Phase
   先把資料層與程式碼的 `clinic_id` 設計打好基礎
3. **`clinic_id` 格式**：改用**台灣健保特約醫事機構代碼**（10 碼數字，衛福部/
   健保署核發的官方唯一碼），取代人工命名 slug。緻妍外科診所的代碼是
   `3503190424`。理由：官方唯一碼天然無重複風險，且未來對接健保申報系統或
   `doctor-toolbox.com` API（Phase 05）時，這是業界通用的識別鍵，不需要再另外
   維護一套對照表
4. **`doc_id` 設計（2026-09-22 確認）**：`page_index_trees` 新增真正的
   `clinic_id TEXT REFERENCES clinic_info(clinic_id)` 欄位，`doc_id` 改為
   **純療程 slug、不含診所前綴**（如 `zhiyan-clinic-hifu-lifting` →
   `hifu-lifting`）。理由：診所身份跟療程識別是兩件不同的事，硬塞進同一個
   字串靠 `.replace()` 解析是技術債，不是設計；有了真正的欄位後，「這家
   診所的所有樹」直接 `WHERE clinic_id = ?` 查詢即可，不需要 `LIKE
   'prefix-%'`；且 `doc_id` 不會因為未來又要換一次 `clinic_id` 命名規則
   （例如 Phase 05 真的對接健保系統後發現代碼格式要調整）而被迫整批重寫。

## 具體任務（待展開為 Antigravity 可執行的詳細規格）

### TASK-00：`page_index_trees` 補 `clinic_id` 欄位 + `doc_id` 去前綴化

- `src/db/clinic_schema.sql`：`page_index_trees` 新增
  `clinic_id TEXT REFERENCES clinic_info(clinic_id)` 欄位
- 遷移既有 6 筆資料：把 `doc_id` 從 `zhiyan-clinic-{procedure}` 改成
  `{procedure}`（去掉前綴），同時把新的 `clinic_id` 欄位填入對應值
  （遷移前用 `3503190424`，見 TASK-01）
- `src/pageindex/seed_trees.py`：`CLINIC_ID` 常數的用途從「組 doc_id 前綴」
  改成「填入獨立的 clinic_id 欄位」，`f"{CLINIC_ID}-{procedure}"` 這類字串
  組合要移除，doc_id 直接用療程 slug
- `src/pageindex/prompt_template.py`：移除
  `_FEW_SHOT_DOC_IDS`（改存純療程 slug）與
  `tree["doc_id"].replace("zhiyan-clinic-", "")` 這行解析邏輯（doc_id 已經
  是純療程名，不需要再解析）
- `src/pageindex/db_writer.py`（`upsert_trees`）、`src/query/search.py`、
  `src/query/router.py` 若有任何依賴 `doc_id` 字串前綴判斷診所的邏輯，一併
  檢查並改用 `clinic_id` 欄位
- 這是本 phase 的地基任務，TASK-01（clinic_id 值遷移為健保代碼）建立在
  這個真正的欄位之上，不是疊加在字串解析上

### TASK-01：`clinic_id` 值遷移為健保代碼

- 把資料庫裡現有 `clinic_id = 'zhiyan-clinic'` 的所有資料（`clinic_info`、
  `clinic_hours`、`clinic_custom_notes`，以及 TASK-00 新增的
  `page_index_trees.clinic_id`）遷移成 `clinic_id = '3503190424'`
- **修正（2026-09-22 展開 TASK-PLAN.md 時發現）**：原本這裡寫「更新
  `scripts/seed_database.py` 的 `clinic_info` 種子資料，目前寫死
  `'zhiyan-clinic'` 那筆 INSERT」，經實際檢查程式碼後確認**不準確**——
  `scripts/seed_database.py` 裡根本沒有任何寫入 `clinic_info` 的 INSERT
  （只有 `SELECT COUNT(*) FROM clinic_info` 做統計）。正式 `clinic.db` 裡
  唯一的那 1 筆 `clinic_info` 資料是先前某次 session 手動寫入的，版控裡
  沒有可重建它的腳本。真正要做的是**新增**一個補齊種子腳本的子任務，
  完整規格見 `TASK-PLAN.md` TASK-01 第 2 項
- 執行前務必先在測試複本驗證（比照 TASK-00 的隔離慣例）

完整可執行規格（含程式碼層級細節、CONSTRAINT、驗收標準）已展開至
`.planning/phases/04-multi-clinic-support/TASK-PLAN.md`（涵蓋 TASK-00 與
TASK-01；TASK-02/TASK-03 維持草案狀態，見下方對應章節）。

### TASK-02：移除函式預設值中的硬編碼診所（2026-09-22 決策已定案）

**現況風險（比原先描述更嚴重）**：這 5 個函式的預設值 `"zhiyan-clinic"` 在
TASK-01（`clinic_id` 值遷移為健保代碼）完成後，**已經是指向資料庫裡不存在的
過期值**——任何忘記傳入 `clinic_id` 的呼叫端現在會靜默查到空結果（查不到
`'zhiyan-clinic'` 的 `clinic_info`/`clinic_hours`/`clinic_custom_notes`），
不是查錯診所的資料，是查到「查無此診所」的空狀態。這比「查錯診所資料」更
難察覺（不會有明顯錯誤資料混入，只會看起來像「診所資訊剛好是空的」）。

**使用者決策（2026-09-22）**：
1. `get_clinic_hours()`、`get_clinic_info()`、`get_clinic_custom_notes()`
   （`src/query/router.py` 3 處）與 `src/clinic/custom_notes.py` 的
   `get_clinic_custom_notes()`、`seed_sample_notes()`——**這 4 個函式移除
   預設值，`clinic_id` 改為必填參數**，呼叫端沒傳就直接 `TypeError`（Python
   內建行為，不需要額外寫檢查），比靜默查到空結果安全。
2. `handle_query()`（`src/query/router.py`）**單獨例外**：改成
   `clinic_id: str | None = None`（保留預設值，但預設值從錯誤的
   `"zhiyan-clinic"` 改成語意明確的 `None`）。理由：`handle_query()` 是
   唯一對外的統一查詢入口，`general` 路由的查詢（如泛用醫學問答）本質上
   不需要 `clinic_id`（現有設計本來就刻意不查 `clinic_info`/`clinic_hours`/
   `clinic_custom_notes`），若也強制必填，會逼所有 general 查詢的呼叫端
   （包括未來可能的匿名入口）傳一個用不到的值。`handle_query()` 內部呼叫
   `get_clinic_info()`/`get_clinic_hours()`/`get_clinic_custom_notes()`
   （這些已改為必填）的地方——也就是 `special` 路由且需要診所資訊時——如果
   `clinic_id is None`，應該拋出明確的 `ValueError`（訊息說明「special
   路由需要 clinic_id」），不能靜默略過或傳 `None` 給下層必填參數（那會在
   下層變成 `TypeError`，錯誤訊息對呼叫端不夠明確）。

**驗收時發現的額外關聯問題（順道請一併修正，屬於同一批改動的自然延伸，
不算越界）**：`handle_query()` 內部透過 `_search_terms_merged()` 呼叫
`search_page_index_trees()` 時，**完全沒有傳入 `clinic_id`**——代表即使
`handle_query()` 收到了正確的 `clinic_id`，療程搜尋這一段仍然會回傳所有
診所的 `page_index_trees` 資料，沒有用到 Phase 04 TASK-00 已經加上的
`clinic_id` 過濾能力。這是 TASK-00 完成後就存在、但直到現在才被注意到的
落差，請在改 `handle_query()` 時一併把 `clinic_id` 傳給
`search_page_index_trees()`（`_search_terms_merged()` 這個共用 helper
可能需要新增一個可選的額外參數或改用 `functools.partial`/lambda 包裝
`search_fn`，你判斷哪種寫法對現有程式碼風格更自然）。`search_drugs`/
`search_service_items` 這兩個沒有 `clinic_id` 概念（全國性 NHI 資料，非
診所專屬），不需要改。

### TASK-03（依賴 Phase 05）：查詢入口的 `clinic_id` 解析

- 目前完全沒有實作，屬於部署層/API 層的工作，待 Phase 05（doctor-toolbox.com
  整合、對外服務介面設計）啟動時一併規劃，不在本 Phase 提前假設技術方案

## CONSTRAINT

- 沿用 `AGENTS.md` 全部既有規則
- `clinic_id` 遷移（TASK-00 的欄位新增+doc_id 改寫、TASK-01 的代碼值遷移）
  皆屬於資料異動，執行前務必比照 TASK-008/Phase 02 建立的隔離慣例，先在
  測試複本上驗證整條流程（含 100+ 既有 pytest 測試全數通過）才能對正式
  `clinic.db` 執行
- TASK-00 完成後，`doc_id` 命名規則（純療程 slug、不含診所前綴）需要在
  `AGENTS.md` 2.2 節明確記錄，避免未來新增診所時又長出新的命名不一致問題
- TASK-00 是 TASK-01 的前置依賴，不可顛倒順序（先有欄位，再遷移欄位裡的值）

## ⚠️ TASK-02 目前有未 commit 的部分改動（2026-09-22 發現，執行前務必先看）

`src/query/router.py`、`src/clinic/custom_notes.py` 目前 working tree 裡已經有未
commit 的改動——`get_clinic_hours()`/`get_clinic_info()`/`get_clinic_custom_notes()`
（`router.py` 3 處）與 `src/clinic/custom_notes.py` 的 2 個函式已經把 `clinic_id`
改成必填（符合下方決策 1），但 **`handle_query()` 也被改成完全必填、沒有保留
`clinic_id: str | None = None`**——這跟下方決策 2 不符，導致
`tests/test_router.py::test_handle_query_general_strict_isolation` 3 個測試案例
目前是壞的（`TypeError: handle_query() missing 1 required positional argument`）。
`tests/test_multi_clinic.py` 也已經被改過，import 了
`get_clinic_hours, get_clinic_info, get_clinic_custom_notes, handle_query`
與 `seed_sample_notes`，但目前檔案內容看起來還沒有用到這些新 import（可能是
準備要新增測試案例但還沒寫完）。**執行 TASK-02 時請先看這批既有改動、接續完成
它，不要當作全新任務重新開始**——尤其 `handle_query()` 的簽章要改回符合下方
決策 2 的 `clinic_id: str | None = None`，並修正 general 路由隔離測試。

## TASK-02 執行時需要同步處理的既有呼叫端（2026-09-22 盤點確認）

移除預設值後，以下呼叫端會因為沒傳 `clinic_id` 而直接壞掉，需要一併修正：

- `src/clinic/custom_notes.py` 的 `main()`（CLI 入口，`if __name__ ==
  "__main__"` 區塊）：`seed_sample_notes(conn)`、`get_clinic_custom_notes(conn)`
  兩處呼叫都沒傳 `clinic_id`。建議在檔案內定義一個
  `CLINIC_ID = "3503190424"` 常數（比照 `seed_trees.py`/`seed_clinic_info.py`
  的既有模式），`main()` 明確傳入
- `scripts/seed_database.py`：`seed_sample_notes(conn)` 呼叫也沒傳
  `clinic_id`，同樣需要補上（該檔案已經有 `seed_clinic_info` 的
  `CLINIC_ID = "3503190424"` 可以參考或直接重用）
- `tests/test_router.py` 的 `test_handle_query_general_strict_isolation`：
  `handle_query(conn, query)` 沒傳 `clinic_id`——這是刻意的（驗證 general
  路由即使沒有診所上下文也不該洩漏診所資訊），因為 `handle_query()` 這次
  決策保留 `clinic_id: str | None = None`，這個測試呼叫不需要修改，維持
  現狀即可
- `tests/test_custom_notes.py`、`tests/test_multi_clinic.py` 裡若有其他
  呼叫這 4 個改為必填參數的函式卻沒傳 `clinic_id` 的地方，執行前先
  `grep -n` 過一輪確認，逐一補上

## 待確認

- （無——5 個函式預設值的處理方式已於 2026-09-22 定案，見上方 TASK-02。
  `doc_id` 前綴問題已於同日確認解法並執行完成，見 TASK-00/TASK-01。）
