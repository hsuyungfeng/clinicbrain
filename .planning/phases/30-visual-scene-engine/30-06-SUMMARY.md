# Phase 30 Plan 06: AGENTS.md 2.27 與目錄補充執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `30-06-PLAN.md` 規格，完成專案最高規範文件 [`AGENTS.md`](file:///home/hsu/Desktop/clinicbrain/AGENTS.md) 的 2.27 節撰寫與第 4 節目錄結構補充，忠實記錄 Phase 30（30-01 至 30-05）已實作並經過自動化測試鎖定之所有架構、規格、限制與安全準則：

1. **新增 2.27 視覺場景引擎章節（Task 1, P30-DOC）**：
   - **定位與動機**：將醫療概念定義（骨架 JSON 與文字敘述）與視覺幾何渲染（純 JavaScript 繪圖引擎）解耦，避免任意 LLM 生成 SVG 或程式碼帶來之安全風險，同一份資產規格同時驅動線上衛教諮詢解說卡動畫、獨立通用播放器檢視與無聲 MP4 影片匯出。
   - **Blueprint 參數規格單一來源與向後相容**：
     - 單一權威來源 `src/visual/blueprints.py` 定義三大 blueprint（`process_diagram`、`contrast`、`timeline`）之參數結構與預設值。
     - 固定語意調色盤代號 `PALETTE_TOKENS`（10 種語意色碼代號），資料層不存 CSS 顏色代碼。
     - 遞迴合併語意 `merge_defaults`（物件遞迴合併、陣列整批取代、None 視為全預設值），以 `tests/fixtures/visual_merge_vectors.json` 10 組向量雙向鎖定。
     - `validate_ir` 選填支援 `params` 與 `duration_sec`，未帶參數時 100% 向後相容，違規時回傳固定英文錯誤碼。
     - `generator.py` 之 `load_skeleton` 驗證選填參數，`generate_ir` 原樣帶入骨架參數，LLM 僅填寫說明文字，完全無法竄改畫面幾何或結構。
   - **JavaScript 視覺引擎純函式架構**：
     - IIFE 外部檔案 `src/web/static/visual_engine.js`，導出全域物件 `ClinicVisual`。
     - 元件皆為進度 $u \in [0, 1]$ 之無狀態純函式，不保留跨影格狀態，拖曳 seek、重播與逐格錄影具備完全確定性。
     - 血管生長嚴格使用 SVG `pathLength="100"` 搭配 `stroke-dasharray="100"` 與 `stroke-dashoffset` 換算，絕不呼叫版面相依之 `getTotalLength()`。
     - 座標邊界與字幕安全區：所有繪圖元素落在 $[5, 795] \times [5, 505]$ 內，所有文字元素底部 $y \le 410$。
   - **視覺 Bundle 唯讀匯出工具**：
     - `scripts/export_visual_bundle.py` 以 SQLite URI `mode=ro` 嚴格唯讀連線，拒絕任何寫入。
     - 預設僅匯出審核狀態為 `approved` 之資產；`--allow-pending` 嚴禁於正式資料庫 `clinic.db` 執行（結束碼 2 阻斷）。
     - 匯出前強制經由 `validate_ir` 檢驗醫療合規，並透過 `merge_defaults` 補齊所有場景之預設參數與時長。
   - **通用解說播放器與無聲 MP4 影片匯出**：
     - `demo/visual/player.html` 與 `player.js` 純外部檔案架構（零內嵌腳本），嚴格檢驗 `?bundle=` 路徑（`^[A-Za-z0-9][A-Za-z0-9._/-]*\.json$`，防範路徑穿越與注入），外連 `doctor-toolbox.com` 預約諮詢卡。
     - `demo/visual/render_video.py --bundle PATH` 透過臨時本機 HTTP 伺服器與無頭 Chromium 逐格截圖，以 ffmpeg 合成標準 H.264/yuv420p 無聲 MP4 影片。
   - **正式衛教諮詢解說卡雙軌整合與平順降級**：
     - `consult.html` 同源引入 `visual_engine.js` 與 `consult.js`，嚴格遵守 CSP `script-src 'self'`。
     - `consult.js` 僅在 `ClinicVisual` 存在且所有場景皆具備 `params` 時啟用動畫；否則平順退回 Phase 29 既有之 480×120 靜態圖解。
     - 動畫由 `requestAnimationFrame` 時間戳驅動，病患手動點擊翻頁，無強制自動輪播；支援 `@media (prefers-reduced-motion: reduce)` 直接呈現 $u=1$ 最終畫面。
   - **第二主題證明（零 JS 改動）**：
     - 新增第二主題 `data/visual/skeletons/hyaluronic-acid-filler.json`（玻尿酸填充原理），證明 `src/web/static/*.js`、`demo/visual/*.js`、`scripts/` 與 `src/` 達成 **100% 零改動**。
     - 撰寫標準手冊 `docs/visual-blueprints.md`。
   - **前端安全規則與靜態防禦**：
     - 嚴格外部腳本，禁止任何內嵌 `<script>`。
     - 原始碼與註解嚴格禁止 `innerHTML`、`insertAdjacentHTML`、`document.write`、`outerHTML`、`eval`、`localStorage`、`sessionStorage`、`document.cookie`、`setInterval`、`setTimeout`、`Date.now`、`Math.random`、`new Date`、`performance.now`、`fetch(`、`XMLHttpRequest`、`import(`、`<script` 等子字串。
   - **已知限制與待驗證事項**：
     - 新 Blueprint 需人工/Claude 設計，系統不支援由 LLM 自行發明 SVG 結構。
     - MP4 影片為無聲圖解。
     - 醫學敘述臨床審核最終仰賴執業醫師人工審核簽核。
     - 正式環境啟用須由使用者明確授權並執行遷移與重新核准，不得自動生效。
     - 衛教轉換成效**待驗證**。
   - **測試清單**：逐項列出 Phase 30 新增與延伸之 8 套測試。

2. **第 4 節目錄結構補充**：
   - 僅於目錄清單中新增 Phase 30 引入之檔案與測試模組條目，**既有條目與行數零刪改**。

3. **零刪改與專案外保護**：
   - `git diff AGENTS.md | grep -c '^-[^-]'` 確實驗證為 **0 行被刪**（71 行純新增）。
   - 未修改 `/home/hsu/AGENTS.md`、`~/.skillshare` 或任何專案外檔案。

---

## 2. 測試與驗收結果

- **驗收指令執行結果**：
  - `git diff AGENTS.md | grep -c '^-[^-]' | grep -qx 0` 驗證通過（被刪行為 0）。
  - `uv run pytest -q -p no:cacheprovider tests/test_visual_blueprints.py tests/test_visual_engine_static.py tests/test_visual_bundle.py`
    -> **34 passed in 0.70s**。
- **正式資料庫保護**：
  - `sha256sum clinic.db` 維持為 `e28dc0089b01d59a03456bcced7974254c7986697d12dc0fb50da1e4a17ba6e1`，未遭任何更動或寫入。

---

## 3. 改動檔案清單

- `AGENTS.md`：新增 2.27 節「視覺場景引擎（Phase 30 新增）」與第 4 節目錄結構新條目（71 行純新增，0 行刪除）。
- `.planning/phases/30-visual-scene-engine/30-06-SUMMARY.md`：本執行摘要。
