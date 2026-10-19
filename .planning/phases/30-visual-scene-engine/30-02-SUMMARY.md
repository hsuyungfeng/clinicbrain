# Phase 30 Plan 02: 視覺場景引擎實作與瀏覽器契約確定性測試執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `30-02-PLAN.md` 規格，完成純前端無相依之外部 JavaScript 視覺場景引擎 `src/web/static/visual_engine.js`，將 `process_diagram`、`contrast`、`timeline` 三個 blueprint 實作為由參數驅動、以進度 `u ∈ [0, 1]` 為輸入的純函式元件，並以靜態掃描與 Playwright 瀏覽器測試落實契約一致性、完全確定性與安全邊界：

1. **引擎骨架、調色盤、契約介面與靜態掃描（Task 1, P30-ENGINE）**：
   - 建立外部檔案 [`src/web/static/visual_engine.js`](file:///home/hsu/Desktop/clinicbrain/src/web/static/visual_engine.js)（IIFE，無外部庫依賴，相容於 `/admin` CSP `script-src 'self'`）。
   - 導出全域物件 `ClinicVisual`，提供公開介面：
     - `blueprints`：註冊表，包含各模板之 `params` 欄位清單、`defaults` 與 `draw` 函式。
     - `PALETTE`：凍結之調色盤常數，鍵集合完全對齊 Python `PALETTE_TOKENS`（共 10 色）。
     - `resolveParams(blueprint, params)`：遞迴物件合併、陣列整批取代、未知/無效輸入回傳深拷貝預設值，並以數值界限夾限正規化。
     - `sceneDuration(scene)`：依 `duration_sec` 或模板預設（process 8s、contrast 9s、timeline 7s）計算時長。
     - `mount(svgEl, scenes)`：綁定 SVG 容器，設定 `viewBox="0 0 800 510"`，回傳包含 `totalDuration`、`renderAt(t)`、`sceneIndexAt(t)`、`destroy()` 之控制器。
   - 建立 [`tests/test_visual_engine_static.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_visual_engine_static.py)：嚴格掃描禁止字串，確保原始碼與註解皆無 `innerHTML`、`insertAdjacentHTML`、`document.write`、`outerHTML`、`eval`（任何大小寫與複合詞）、`localStorage`、`sessionStorage`、`document.cookie`、`setInterval`、`setTimeout`、`Date.now`、`Math.random`、`new Date`、`performance.now`、`fetch(`、`XMLHttpRequest`、`import(`、`<script`，且無任何非 SVG 規範之外部 URL。
   - **Commit**: `25f30e4` `feat(visual): 實作 visual_engine.js 骨架與靜態安全掃描測試 (Task 1)`

2. **三個 blueprint 元件實作（Task 2, P30-ENGINE）**：
   - `process_diagram`：
     - 繪製組織來源區塊與抽取針管（針管往返由進度 $u$ 透過正弦波純數學計算）。
     - 根據 `particles` 數量計算微粒沿拋物線流向右側離心管。
     - 離心管內根據 `container_layers` 之 weight 比例分層；$u \ge 0.75$ 時為 `keep: true` 之層疊加呼吸強調光框。
     - 三步驟標籤（`step_labels`）隨 $u$ 推進漸顯，標籤文字頂點嚴格位於字幕安全區（$y \le 410$）。
   - `contrast`：
     - 左側對照面板：支援 `mode="mass"`（單一大塊並於 $u \ge 0.38$ 發生中心缺血暗化脈動）與 `mode="scattered"`（確定性雜湊分佈）。
     - 右側推薦面板：支援 `mode="layered"`（`rows` $\times$ `per_row` 微粒伴隨微血管接觸光圈依序彈出）與 `mode="mass"`。
     - 中線分隔、注射套管微幅推進與雙側標籤展示。
   - `timeline`：
     - 組織基質與單元配置（`units` 2..5 個），支援 `unit_effect` 為 `mature`（淡轉深）、`fade`（深轉淡）、`steady`（恆定）。
     - 血管生長：**純函式實作，嚴格使用 `pathLength="100"` 搭配 `stroke-dasharray="100"` 與 `stroke-dashoffset` 換算，絕不呼叫版面相依之 `getTotalLength()`**。
     - 底部進度軸與三個里程碑（`milestones`）節點變色漸顯。
   - **Commit**: `8044caf` `feat(visual): 完成三個 blueprint 純函式與參數化元件 (Task 2)`

3. **Playwright 瀏覽器測試（Task 3, P30-ENGINE）**：
   - 於 [`tests/conftest.py`](file:///home/hsu/Desktop/clinicbrain/tests/conftest.py) 追加 `playwright_browser` 與 `playwright_page` 輔助 fixture（不可用時自動 skip）。
   - 建立 [`tests/test_visual_engine_browser.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_visual_engine_browser.py) 進行真實無頭 Chromium 測試：
     - **載入與零違規**：驗證載入過程 console 零 error，網路監聽驗證無任何非 `file://` 請求。
     - **契約一致性**：頁面中 `blueprints` 模板清單、params 欄位名、`PALETTE` 鍵集合與 Python 規格雙向一致。
     - **向量一致性**：以 [`tests/fixtures/visual_merge_vectors.json`](file:///home/hsu/Desktop/clinicbrain/tests/fixtures/visual_merge_vectors.json) 逐組驗證 `ClinicVisual.resolveParams`，10 組向量完全匹配。
     - **完全確定性**：針對三個模板，對 $u \in \{0, 0.25, 0.5, 0.75, 1.0\}$ 順序 seek、逆序 seek 與亂序 seek，同一時間點之 `outerHTML` 字元級 100% 相同。
     - **邊界與字幕安全區**：**不使用 `getBBox()`**，以 `getBoundingClientRect()` 換算 viewBox 座標，排除 `defs`、`clipPath`、`data-bg="1"` 背景與隱藏元素後，所有元件落在 $[5, 795] \times [5, 505]$ 內（容差 1 單位），所有 `text` 元素之底部 $y \le 411$。
     - **安全降級**：未知模板、缺少參數、超界數值、未知調色盤代號皆不拋例外且安全渲染。
   - **Commit**: `f972673` `test(visual): 新增視覺引擎瀏覽器契約、確定性、邊界與降級測試 (Task 3)`

---

## 2. Playwright 測試執行狀態聲明

- **實際執行確認（非 skip）**：
  Playwright 與本機無頭 Chromium 成功啟動並**完全執行**。
  `tests/test_visual_engine_browser.py` 的 6 項測試全數實際於瀏覽器內執行完畢，無任何一項被 skip。

---

## 3. 改動檔案清單

- `src/web/static/visual_engine.js`：新增視覺場景引擎主程式。
- `tests/test_visual_engine_static.py`：新增靜態安全與介面掃描測試。
- `tests/test_visual_engine_browser.py`：新增 Playwright 瀏覽器測試套件。
- `tests/conftest.py`：追加 Playwright 瀏覽器輔助 fixture（既有 fixture 行為完全不變）。
- `.planning/phases/30-visual-scene-engine/30-02-SUMMARY.md`：本執行摘要。

---

## 4. 驗收指令執行結果

1. **Task 1 靜態掃描測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_visual_engine_static.py`
   -> **4 passed in 0.43s**。

2. **Task 2 靜態檢核**：
   `uv run pytest -q -p no:cacheprovider tests/test_visual_engine_static.py`
   -> **4 passed in 0.46s**。

3. **Task 3 整合與瀏覽器測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_visual_engine_browser.py tests/test_visual_engine_static.py tests/test_visual_blueprints.py`
   -> **24 passed in 1.37s**（6 個瀏覽器測試、4 個靜態掃描測試、14 個規格測試全數通過，0 skipped）。

---

## 5. 偏離與特別說明

- **零偏離計畫**：所有實作與測試嚴格依照 `30-02-PLAN.md` 規劃完成。
- **既有前端與合規防護零改動**：未修改 `consult.js`、`consult.html`、既有 UI 測試；未修改 `src/ingestion`、`src/general`、`validate_visual_text`。
- **Git 與正式庫安全**：未執行任何 `git reset`、`git checkout`、`git stash`、`git clean` 或 `git restore`；未修改或寫入正式 `clinic.db`；未執行 `git push`。
