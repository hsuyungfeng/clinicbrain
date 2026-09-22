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

底層資料表（`clinic_info`/`clinic_hours`/`clinic_custom_notes`/
`page_index_trees.doc_id` 前綴）都已經是用 `clinic_id` 欄位設計，架構本身
**支援**多診所（單一資料庫、邏輯隔離），只是目前：
1. `clinic_id` 值的命名方式未定案（人工 slug vs 官方代碼）
2. 查詢入口完全不知道當前查詢屬於哪家診所（永遠吃預設值）

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

## 具體任務（待展開為 Antigravity 可執行的詳細規格）

### TASK-01：`clinic_id` 遷移

- 把資料庫裡現有 `clinic_id = 'zhiyan-clinic'` 的所有資料（`clinic_info`、
  `clinic_hours`、`clinic_custom_notes`）遷移成 `clinic_id = '3503190424'`
- `page_index_trees.doc_id` 目前命名是 `zhiyan-clinic-{procedure}`（如
  `zhiyan-clinic-hifu-lifting`），需要決定是否也要改成 `3503190424-{procedure}`
  ——**這會動到 6 筆既有 PageIndex 樹的 doc_id**，屬於資料遷移而非新增，執行
  前務必先在測試複本驗證，且要確認 `src/pageindex/seed_trees.py` 的
  `CLINIC_ID` 常數、`src/pageindex/prompt_template.py` 的
  `_FEW_SHOT_DOC_IDS`/`doc_id.replace("zhiyan-clinic-", "")` 這類硬編碼字串
  比對邏輯要同步更新，否則會悄悄失效
- 更新 `scripts/seed_database.py`（`clinic_info` 的種子資料，目前寫死
  `'zhiyan-clinic'` 那筆 INSERT）

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
- `clinic_id` 遷移屬於資料異動，執行前務必比照 TASK-008/Phase 02 建立的隔離
  慣例，先在測試複本上驗證整條流程（含 100+ 既有 pytest 測試全數通過）才能
  對正式 `clinic.db` 執行
- 遷移後的 `doc_id` 命名規則需要在 `AGENTS.md` 或本文件中明確記錄，避免未來
  新增診所時又長出新的命名不一致問題

## 待確認

- `page_index_trees.doc_id` 是否要跟著改成健保代碼前綴，或保留現有命名、
  只在 `clinic_id` 欄位本身換成代碼（doc_id 只是識別字串，不一定要跟
  clinic_id 完全一致）——這個影響範圍較大，建議下次 session 優先確認
- 5 個函式的預設值是否要移除，需要評估對既有測試/呼叫端的相容性影響
