# Phase 12 Plan 04: 免責宣告欄位與 sync/import 驗證 總結 (GC-03, GC-02)

## 執行概述

- **執行日期**：2026-10-05
- **目標需求**：GC-03（查詢回應之免責宣告欄位）、GC-02（雙向同步匯入對 general FAQ 之劑量處方與就醫警訊檢查）
- **狀態**：完成 (PASSED)
- **測試通過情況**：全量 842 passed, 0 failed, 1 warning (22.21s)
- **正式資料庫完整性**：`clinic.db` SHA-256 維持 `ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e` 未受任何寫入污染

---

## 關鍵架構決策與實作

1. **免責聲明欄位純加法擴充 (`disclaimer`)**：
   - `QueryResponse` 與 `QueryResponseModel` 新增 `disclaimer: Optional[str] = None` 欄位（置於最後，保證既有欄位與序列化相容）。
   - 填入規則：當回應之 `data_level == 'general'` 時，自動填入 `src/general/disclaimer.py` 之 `DISCLAIMER_TEXT`；`data_level == 'clinic'` 或 `None` 時為 `None`（JSON 為 `null`）。
   - 涵蓋快取短路（分層短路與相容短路）以及非短路 PageIndex 檢索回應。
   - 文字唯一來源保證：`router.py`、`models/query.py`、`routes/query.py` 絕無第二份免責宣告硬編碼拷貝。
   - 公開別名：`router.STOPWORD_SPLIT_PATTERN = _STOPWORD_SPLIT_PATTERN`。

2. **雙向同步匯入對 general FAQ 前置合規驗證 (`/sync/import`)**：
   - 於 `import_sync_data` 完成基本清洗後、任何資料庫寫入（trees, faqs, notes, hours）之前，執行前置驗證迴圈。
   - 採 Fail-Closed 策略：只有正規化後明確等於 `"special"` 者豁免驗證；其餘一切值（包含 `"general"`、帶空白變體、大小寫變體、`null`、非字串）一律走嚴格 general 驗證。
   - 驗證器調用 `validate_single_faq(..., check_dosage=True, require_doctor_warning=True)`：
     - 若包含用藥處方或劑量建議，拋出 HTTP 400（detail 含「用藥劑量」）。
     - 若缺少就醫警訊提示收尾句，拋出 HTTP 400（detail 含「何時該就醫」）。
   - 隱私承諾：400 錯誤 detail 僅包含規則編號或固定合規文案，絕不回顯未過濾之答案原文。
   - 原子性保證：因於寫入前拋出例外，整批匯入原子性中斷，同批其他合法項目與備註一概不入庫。
   - special 豁免政策：依照 2026-10-05 使用者決策，special 類別視為院所內部特定診療與療程說明，維持信任豁免新層。

---

## 程式碼變更清單

1. **`src/query/router.py`**
   - 匯入 `DISCLAIMER_TEXT`。
   - 公開 `STOPWORD_SPLIT_PATTERN = _STOPWORD_SPLIT_PATTERN`。
   - `QueryResponse` 新增 `disclaimer: Optional[str] = None`。
   - `handle_query` 三處回傳點填入 `disclaimer`。

2. **`src/api/models/query.py`**
   - `QueryResponseModel` 新增 `disclaimer: Optional[str] = Field(None, ...)`。

3. **`src/api/routes/query.py`**
   - `_execute_query` 在 `response_dict` 增加 `"disclaimer": raw_response.disclaimer`。

4. **`src/api/routes/sync.py`**
   - 匯入 `validate_single_faq`。
   - 更新模組 docstring 記錄合規政策。
   - `import_sync_data` 寫入前執行 general FAQ 前置檢核迴圈。

5. **測試檔案**
   - `tests/test_query_disclaimer_field.py`：6 個單元與端對端測試。
   - `tests/test_sync_general_validation.py`：5 個雙向同步合規攔截測試。

---

## 驗收結果

- RED 測試成功驗證（未實作前 exit 1）。
- Phase 11 相關測試（包含 router 與 clinic-first 檢索 131 個測試）零修改通過。
- 既有 `tests/test_api_sync.py` 零修改全數通過。
- 全量回歸測試：842 passed, 0 failed, 1 warning。
