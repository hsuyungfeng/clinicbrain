# Phase 30 Plan 04: 正式衛教諮詢解說卡引擎動畫整合執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `30-04-PLAN.md` 規格，將病人端衛教諮詢頁（`/admin/consult.html`）的解說卡與 Phase 30 的視覺場景引擎（`visual_engine.js`）完成整合：當資產包含 `params` 且引擎可用時，以純函式動畫渲染（微粒流動、血管生長、對照脈動）；在無 `params` 或引擎未載入時，完全平順相容退回既有靜態圖，不影響諮詢功能。

1. **公開輸出帶出 params 與 duration_sec（Task 1, P30-PROD）**：
   - 實作 [`src/visual/match.py`](file:///home/hsu/Desktop/clinicbrain/src/visual/match.py) 之 `_shape_public_visual`：
     - 對外輸出安全新增 `params`（dict 或 None）與 `duration_sec`（int 或 None）兩鍵。
     - 既有 Phase 29 資產（無 params）維持輸出 `params=None` 與 `duration_sec=None`，達成 100% 向後相容。
     - 禁出欄位守門：嚴格禁止 `id`、`ir_json`、`source_type`、`review_status`、`metadata`、`keywords` 等敏感欄位外洩。
     - 竄改防禦：資料庫內遭惡意注入之非法 params 會在 `visible_assets` 階段因 `validate_ir` 失敗而自動排除，`find_visual` 回傳 None。
   - 更新 [`tests/test_visual_match.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_visual_match.py) 與 [`tests/test_visual_serving.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_visual_serving.py)。
   - **Commit**: `638a241` `feat(visual): 公開輸出帶出 params 與 duration_sec (Task 1)`

2. **consult.js 引擎整合與雙軌降級（Task 2, P30-PROD）**：
   - 更新 [`src/web/static/consult.html`](file:///home/hsu/Desktop/clinicbrain/src/web/static/consult.html)：
     - 依序同源引入 `<script src="/admin/visual_engine.js"></script>` 與 `<script src="/admin/consult.js"></script>`。
     - 維持零內嵌腳本，嚴格遵循 CSP `script-src 'self'`。
   - 更新 [`src/web/static/consult.js`](file:///home/hsu/Desktop/clinicbrain/src/web/static/consult.js)：
     - `renderVisual` 新增引擎判斷條件：僅當 `window.ClinicVisual` 存在且所有場景皆帶有效 `params` 時啟用。
     - 動畫驅動：進入場景時以 `window.requestAnimationFrame` 之回呼時間戳（Timestamp）將進度 $u$ 由 0 推進至 1，不使用任何禁止之計時或隨機 API。
     - 導航控制：場景間維持由「上一步／下一步」手動切換（不自動輪播），切換後重新自起點播放當前場景動畫。
     - 無障礙降級：`prefers-reduced-motion: reduce` 環境下直接渲染 $u=1$ 最終狀態。
     - 例外防禦與退回：引擎未載入、拋出例外或無 params 時，安全退回既有 480×120 靜態 SVG，並保證清理引擎 SVG 與未完成之 rAF 動畫。
   - 擴充靜態掃描測試 [`tests/test_consult_visual_ui.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_consult_visual_ui.py) 與 [`tests/test_patient_consult_ui.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_patient_consult_ui.py)。
   - 建立 [`tests/test_consult_engine_browser.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_consult_engine_browser.py) 進行真實 Playwright 瀏覽器測試。
   - **Commit**: `d5e228e` `feat(visual): consult.js 整合視覺引擎動畫與降級處理 (Task 2)`

---

## 2. 測試與驗收結果

- **測試執行結果**：
  - Task 1 驗證指令：30 項測試全數通過（`30 passed in 2.22s`）。
  - Task 2 驗證指令：24 項測試全數通過（`24 passed in 2.65s`）。
  - Phase 30 完整回歸驗證：85 項測試全數通過，1 項 skip（`85 passed, 1 skipped in 4.68s`）。
- **Playwright 瀏覽器測試狀態**：
  - 成功以臨時本機 HTTP 伺服器啟動並完成帶 params 引擎渲染、上一步/下一步切換、最後一步 completed 事件、無 params 靜態圖退回、缺引擎檔阻斷退回、以及 reduced motion 測試，全數在真實無頭 Chromium 執行通過。
- **正式庫保護**：
  - `clinic.db` SHA-256 維持為 `e28dc0089b01d59a03456bcced7974254c7986697d12dc0fb50da1e4a17ba6e1`，未遭任何更動。

---

## 3. 改動檔案清單

- `src/visual/match.py`：公開輸出帶出 `params` 與 `duration_sec`。
- `tests/test_visual_match.py`：新增公開輸出欄位與竄改防禦測試。
- `tests/test_visual_serving.py`：延伸諮詢回應帶出 params 欄位測試。
- `src/web/static/consult.html`：引入 `visual_engine.js` 外部腳本。
- `src/web/static/consult.js`：實作 `ClinicVisual` 動畫渲染與平順降級。
- `tests/test_consult_visual_ui.py`：更新外部腳本清單與順序檢核。
- `tests/test_patient_consult_ui.py`：更新原始碼掃描與端點回應測試。
- `tests/test_consult_engine_browser.py`：新增病人頁引擎瀏覽器整合測試。
