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

### TASK-02：移除函式預設值中的硬編碼診所

- 5 個函式的 `clinic_id: str = "zhiyan-clinic"` 預設值，評估是否要移除預設值
  改成必填參數（強迫呼叫端明確指定，避免未來多診所上線後不小心漏傳導致
  查錯診所資料——這是比較安全的方向，但要評估現有呼叫端/測試套件的相容性
  影響）

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

## 待確認

- 5 個函式的 `clinic_id: str = "zhiyan-clinic"` 預設值是否要移除，需要評估
  對既有測試/呼叫端的相容性影響（`doc_id` 前綴問題已於 2026-09-22 確認解法，
  見上方「doc_id 設計決策」與 TASK-00，不再是待確認項目）
