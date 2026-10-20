# Phase 31 Plan 04: 審核頁 🎬 待簽核動畫分頁與 Playwright 測試執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `31-04-PLAN.md` 規格，於 Web 管理介面（`/admin/`）新增「🎬 待簽核動畫」分頁，整合 `visual_engine.js` 視覺場景引擎，提供醫師即時合成預覽、時間軸拖曳 seek、場景切換、說明文字修訂、已核准推理樹草稿生成、以及一鍵核准／駁回功能：

1. **Task 1: index.html、style.css 與 app.js「🎬 待簽核動畫」分頁實作（P31-UI）**：
   - [`src/web/static/index.html`](file:///home/hsu/Desktop/clinicbrain/src/web/static/index.html)：
     * 主選單新增 `<button class="nav-tab ... " data-tab="tab-visuals">🎬 待簽核動畫</button>`，使審核頁導覽列具備 7 個分頁。
     * 總覽儀表板新增 `id="statVisualsPendingTotal"` 待簽核動畫統計卡片。
     * 新增 `<section id="tab-visuals" class="tab-content hidden">`：包含診所／範圍／狀態篩選列、由已核准推理樹生成動畫草稿工具列（`#visualsTreeSelect` 與 `#btnAutodraftVisual`）與動畫卡片容器 `#visualsContainer`。
     * 於 `/admin/app.js` 前以 `<script src="/admin/visual_engine.js"></script>` 外部引入視覺引擎（零內嵌腳本）。
   - [`src/web/static/style.css`](file:///home/hsu/Desktop/clinicbrain/src/web/static/style.css)：
     * 定義 `.visual-review-card`、`.visual-review-player`、`.visual-review-svg`、`.visual-review-controls`、`.visual-review-scrubber`、`.visual-scene-list`、`.visual-scene-item` 與 `.visual-edit-box` 樣式。
   - [`src/web/static/app.js`](file:///home/hsu/Desktop/clinicbrain/src/web/static/app.js)：
     * 將 `"visualsFilterClinic"` 納入 `CLINIC_FILTER_IDS` 並於 `setGlobalClinic` 保持全站同步。
     * 實作 `initVisualsSection()`、`loadApprovedTreesForVisualSelect()` 與 `loadVisuals()`。
     * 實作 `createVisualReviewCard(asset)`：
       - 頂部呈現資產 ID、topic_key、診所專屬／一般醫學範圍標籤、AI生成／手寫來源標籤、審核狀態標籤與合規驗證通過／未通過標籤。
       - 透過 `window.ClinicVisual.mount(svgEl, asset.scenes)` 建立 SVG 畫布（viewBox 0 0 800 510），支援播放／暫停切換、0..1000 range 滑桿拖曳 seek（安全邊界扣除 0.001 避免落入次一場景起點）與場景 1/2/3 切換按鈕。
       - 支援卡片內展開編輯說明文字（`PATCH /api/v1/admin/visuals/{id}`），儲存後自動重置為待簽核並即時更新；支援一鍵核准發布與駁回。
       - **嚴格遵守前端安全規範**：全區段零 `innerHTML`、`insertAdjacentHTML`、`outerHTML`、`document.write`、`eval`、`setInterval`，文字一律以 `textContent` 填入。

2. **Task 2: tests/test_visual_review_ui.py 靜態安全與 Playwright 真實瀏覽器測試（P31-UI）**：
   - 靜態安全驗證：檢查 index.html 零內嵌腳本、外部腳本依序載入、7 個頁籤齊全、app.js Phase 31 區段零被禁語法、style.css 樣式類別齊全。
   - Playwright 真實瀏覽器 E2E：啟動臨時埠 uvicorn 服務掛載隔離資料庫，點擊「🎬 待簽核動畫」分頁驗證 SVG 畫布正常渲染且子節點數 > 5、場景按鈕與滑桿拖曳無 console 錯誤、內聯修訂標題儲存後狀態維持 pending、點擊核准發布後狀態變更為已發布，最後於 `consult.html` 提問確認該動畫優先顯示並合成播放。

---

## 2. 測試與驗收結果

- **31-04 Task 1 & Task 2 測試套件**：
  `uv run pytest -q -p no:cacheprovider tests/test_visual_review_ui.py`
  -> **4 passed in 6.48s**。
- **31-04 計畫指定完整驗證**：
  `uv run pytest -q -p no:cacheprovider tests/test_visual_review_ui.py tests/test_consult_engine_browser.py tests/test_visual_engine_browser.py tests/test_visual_engine_static.py`
  -> **22 passed in 13.47s**。
- **正式資料庫保護**：
  `sha256sum clinic.db`: `2f66cd1b42fd927bca22a847b537c4cc43fb80c6a139aafb67669caaf25daf66`（完全未變更、未遷移）。

---

## 3. 改動檔案清單

- `src/web/static/index.html`：新增「🎬 待簽核動畫」主選單按鈕、儀表板統計卡片、分頁容器與外部腳本引用。
- `src/web/static/style.css`：新增動畫審核卡片與播放器專用樣式。
- `src/web/static/app.js`：新增動畫列表載入、卡片建立、ClinicVisual 引擎掛載播放控制、內聯修訂與審核簽核邏輯。
- `tests/test_visual_review_ui.py`：新增靜態安全檢驗與 Playwright E2E 真實瀏覽器測試套件。
- `.planning/phases/31-visual-autodraft-and-approval/31-04-SUMMARY.md`：本執行摘要。

---

## 4. 遵守規則聲明

1. 完成 31-04 並建立 `31-04-SUMMARY.md`，接續執行 31-05。
2. 嚴格遵守規定，未執行任何 `git reset`, `git checkout`, `git stash`, `git clean`, `git restore`。
3. 嚴禁修改或遷移正式庫 `clinic.db`，所有測試皆使用 `isolated_db_path` 隔離複本，不呼叫真實 LLM。
4. 依指示**未自行執行 git commit**，保留工作區改動等待 hermes 測試與 argon 審查。
