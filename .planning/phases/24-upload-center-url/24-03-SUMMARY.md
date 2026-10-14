# Plan 24-03 總結：文件上傳中心來源切換、名稱欄位與網址送出

## 執行成果

- **完成日期**：2026-10-14
- **成果狀態**：全部測試通過（27/27 web_ui 測試全數通過，node 行為測試 16/16 通過且零 skip，全套相關測試 124/124 passed），零 HTML injection 違規，完全遵循正體中文與安全規範。
- **Commit**：`feat(web): 實作文件上傳中心來源切換、名稱欄位與網址送出 (Plan 24-03)` (`603a394`)

## 產出與變更清單

### 1. 新增之 HTML 控制項 (`src/web/static/index.html`)

- `uploadSource`（radio：`value="file"` 檔案上傳預設勾選、`value="url"` 網站解析）
- `uploadName`（text input，maxlength 80，作為主題與來源顯示名稱）
- `uploadNameHint`（提示段落元素，由 JS 透過 textContent 設定）
- `urlSourceField`（網址輸入容器，預設 hidden）
- `uploadUrl`（url input，帶有安全預設提示字串）
- `fileSourceArea`（拖曳與檔案選擇整體容器，網址模式時自動隱藏）

### 2. 純輔助函式清單 (`src/web/static/app.js`)

宣告於頂層，載入時不存取任何 DOM，經由 Node.js sandbox 執行行為測試：
1. `uploadNameFieldState(queueLength, fileStem)`：
   - 單檔（queueLength === 1）：`{ readOnly: false, prefill: fileStem, hint: "" }`
   - 多檔（queueLength > 1）：`{ readOnly: true, prefill: null, hint: "多檔將自動以檔名命名" }`
   - 空佇列（queueLength === 0）：`{ readOnly: false, prefill: null, hint: "" }`
2. `uploadNameForSubmit(queueLength, nameValue)`：
   - 僅在單檔且 trim 後非空時回傳名稱字串；多檔或空白一律回傳 `null`（保證批量上傳絕不附加自訂名稱）。
3. `pickUniqueStemEntries(existingStems, incomingStems)`：
   - 抽離自 `addUploadFiles` 的同檔名（去副檔名）排重邏輯。
   - 規則：已存在者跳過，新加入中同 stem 者僅保留第一個，保持原輸入順序。
4. `missingFieldsLabels(keys)`：
   - 固定中文對照：`address`→地址、`phone`→電話、`business_hours`→營業時間、`doctors`→醫師；未知鍵自動丟棄，防止 XSS 或未定義字串外洩。
5. `uploadDetailText(data, fallback)`：
   - 安全解析伺服器錯誤 detail：僅當為字串時回傳，否則回退至固定安全訊息。

### 3. pickUniqueStemEntries 抽出前後行為比對

- **抽出前**：`addUploadFiles` 遍歷 incoming entries 時，以 `uploadState.queue.some(q => q.status !== "skip" && fileStem(q.path) === fileStem(item.path))` 比對，後到者標記為 skip。
- **抽出後**：以純函式 `pickUniqueStemEntries` 支援純邏輯運算；原 `addUploadFiles` 行為完全等價且零退化。
- **比對結果**：行為一致，已由行為測試 `test_same_stem_batch_keeps_first_only` 與 `test_batch_sequence_via_pure_helpers` 完整驗證。

### 4. 互動連動與安全防禦

- **來源切換**：`uploadSource=url` 時隱藏檔案拖曳區、顯示網址輸入框、`uploadName` 設為必填；`uploadSource=file` 時反之。
- **目標連動**：`uploadTarget=tree` 時禁用網址 radio，並將標籤文字動態改為「網站解析（僅支援 FAQ 草稿）」；若原為網址模式則自動切回檔案模式。
- **DOM 安全性**：切片全區間無 `innerHTML`、`insertAdjacentHTML`、`document.write`、`outerHTML` 或 `eval(`，所有動態字串與伺服器回應一律經 `textContent` 或 `.value` 寫入。

## 驗證指標

- `python3 -m pytest tests/test_web_ui_phase24.py tests/test_web_ui_v2.py tests/test_web_ui_v3.py tests/test_web_ui.py -q`：27 passed in 1.40s。
- `python3 -m pytest tests/ -q -k "web_ui or admin or upload"`：124 passed in 5.30s。
- `node --check src/web/static/app.js`：通過。
- 正式庫 `clinic.db`：SHA-256 維持 `0089ca28795fd0f0f2a41e9fa6b16f840ae794bfaf4e5597576410e9f0cf23db`，零變更零污染。
