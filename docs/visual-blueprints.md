# 視覺解說卡 Blueprint 規格與新增指南

本文檔記錄 **clinicbrain** 視覺場景引擎（Phase 30）之 Blueprint 參數規格、新增流程與安全檢查清單。所有內容均為已實作並通過自動化測試驗證之事實。

---

## 1. 既有 Blueprint 參數規格表

所有 blueprint 規格單一來源定義於 [`src/visual/blueprints.py`](file:///home/hsu/Desktop/clinicbrain/src/visual/blueprints.py)，並與前端引擎 [`src/web/static/visual_engine.js`](file:///home/hsu/Desktop/clinicbrain/src/web/static/visual_engine.js) 雙向契約鎖定。

### 1.1 調色盤代號 (`PALETTE_TOKENS`)
僅允許使用以下 10 種語意代號，嚴禁任意 hex、rgb 或 CSS 色名：
- `fat`: 脂肪組織金黃色 (`#f59e0b`)
- `oil`: 油滴深橙色 (`#ea580c`)
- `blood`: 血管與血液深紅色 (`#dc2626`)
- `skin`: 皮膚組織粉褐色 (`#fbcfe8`)
- `neutral`: 中性灰色 (`#94a3b8`)
- `accent`: 強調藍色 (`#38bdf8`)
- `warn`: 警示紅橘色 (`#f87171`)
- `ok`: 推薦綠色 (`#34d399`)
- `gel`: 玻尿酸凝膠淺青藍色 (`#67e8f9`)
- `pale`: 淺層組織淡白色 (`#e2e8f0`)

---

### 1.2 三大核心 Blueprint 規格

#### Blueprint: `process_diagram`（流程圖解，預設時長 8 秒）
- **用途**：呈現微創抽取、純化分離與保留組織之物理流向。
- **參數結構 (`params`)**：
  - `source` (object):
    - `label` (text, 1~8 字): 組織來源名稱（預設：「皮下脂肪」）。
    - `fill` (palette): 來源區填色代號（預設：`skin`）。
  - `particles` (int, 4~12): 動畫微粒數量（預設：`5`）。
  - `container_layers` (list, 2~4 層):
    - `label` (text, 1~6 字): 層別名稱。
    - `fill` (palette): 層別填色代號。
    - `weight` (int, 1~5): 容器高度比重權重。
    - `keep` (bool): 最終是否為目標保留層（`keep: true` 之層在 $u \ge 0.75$ 時會有強調光圈）。
  - `step_labels` (list, 恰 3 條, 每條 1~10 字): 底部三階段步驟標籤（預設：`["微創抽取", "離心分層", "保留純化脂肪"]`）。

#### Blueprint: `contrast`（對照面板，預設時長 9 秒）
- **用途**：左右並列對比「不建議之集中施作方式」與「推薦之精細分層施作方式」。
- **參數結構 (`params`)**：
  - `left` (object, 左側警示對照側):
    - `title` (text, 1~8 字): 標題（預設：「單處過量」）。
    - `note` (text, 1~14 字): 副標（預設：「較易出現硬塊」）。
    - `mode` (enum: `"mass"` | `"scattered"`): 呈現形態（單一團塊或分散雜湊）。
    - `core_effect` (enum: `"dim"` | `"none"`): `dim` 於團塊中心畫暗化核心並顯示 `core_label`（脂肪移植：缺血）；`none` 不畫（適用玻尿酸等無此現象的主題）。預設 `"dim"`。
    - `core_label` (text, 1~8 字): 暗化核心上的標籤（預設：「中心缺血」；`core_effect="none"` 時不顯示）。
    - `footnote` (text, 1~16 字): 左面板底註（預設：「單處集中：不易獲取充足養分」）。
    - `unit_fill` (palette): 團塊與微粒顏色代號（預設 `"fat"`）。
  - `right` (object, 右側推薦目標側):
    - `title` (text, 1~8 字): 標題（預設：「分層少量」）。
    - `note` (text, 1~14 字): 副標（預設：「接觸周圍組織」）。
    - `mode` (enum: `"layered"` | `"mass"`): 呈現形態（分層微粒伴隨血管接觸圈或均勻團塊）。
    - `rows` (int, 1~4): 分層層數（預設：`3`）。
    - `per_row` (int, 3~8): 每層微粒數量（預設：`5`）。
    - `footnote` (text, 1~16 字): 右面板底註（預設：「多層分散：接觸周圍健康組織」）。
    - `unit_fill` (palette): 微粒顏色代號（預設 `"fat"`）。

#### Blueprint: `timeline`（時間軸進程，預設時長 7 秒）
- **用途**：呈現術後組織血管長入、融入、代謝或穩定之長時程演變。
- **參數結構 (`params`)**：
  - `milestones` (list, 恰 3 條, 每條 1~8 字): 三個時間節點標籤（預設：`["術後初期", "微血管長入", "狀態穩定"]`）。
  - `unit_effect` (enum: `"mature"` | `"fade"` | `"steady"`):
    - `mature`: 組織微粒由淺轉深，表現成熟長成。
    - `fade`: 組織微粒隨時間變淡，表現自然被身體吸收代謝。
    - `steady`: 組織微粒維持恆定。
  - `connectors` (enum: `"vessels"` | `"none"`):
    - `vessels`: 動態生長微血管（以 `pathLength="100"` 之 pure dashoffset 計算）。
    - `none`: 無血管連接（適用非自體組織如玻尿酸凝膠）。
  - `units` (int, 2~5): 核心組織單元數量（預設：`3`）。
  - `unit_fill` (palette): 組織單元顏色代號（預設 `"fat"`；玻尿酸用 `"gel"`）。
- **注意**：主題專屬的文字、說法與顏色一律必須是參數，不得寫死在引擎內（2026-10-20 玻尿酸驗證時曾因寫死「中心缺血」而出現醫學上錯誤的說法）。

---

## 2. 新增 Blueprint 的完整五步驟

當未來需要全新之醫學視覺隱喻（例如：超音波拉提熱凝結點、電波加熱分佈）時，必須嚴格依照以下順序實作，不可顛倒：

### 步驟一：在 Python 端註冊參數規格
修改 [`src/visual/blueprints.py`](file:///home/hsu/Desktop/clinicbrain/src/visual/blueprints.py)：
1. 於 `BLUEPRINTS` 字典註冊新 blueprint 鍵名，明確宣告其 `params` 欄位與嚴格型別約束（僅支援 `enum`、有界 `int`、有界 `text`、`palette` token、有界 `list`、`object`、`bool`）。
2. 在 `defaults` 填寫完整的合法預設值字典。
3. 確保 `merge_defaults` 邏輯能正確遞迴合併。

### 步驟二：在 JavaScript 引擎實作純函式渲染元件
修改 [`src/web/static/visual_engine.js`](file:///home/hsu/Desktop/clinicbrain/src/web/static/visual_engine.js)：
1. 實作純函式繪圖元件 `draw(ctx, params, u)`：
   ```javascript
   function draw(ctx, params, u) {
     ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
     // 根據進度 u ∈ [0, 1] 透過純數學公式計算幾何座標
   }
   ```
2. 在 `blueprints` 物件註冊該模板之 `params` 陣列、`defaults` 與 `draw: draw(ctx, params, u)`。
3. 實作 `resolveParams` 正規化與邊界防禦邏輯，在未知或超界輸入時回傳安全夾限值。

### 步驟三：補齊契約、確定性與邊界測試
1. 在 [`tests/test_visual_blueprints.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_visual_blueprints.py) 新增 Python 參數驗證、邊界夾限與合規測試。
2. 在 [`tests/test_visual_engine_browser.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_visual_engine_browser.py) 驗證：
   - **雙向一致性**：Python `BLUEPRINTS` 與 JS `ClinicVisual.blueprints` 鍵集合與欄位清單一致。
   - **純函式確定性**：在 $u \in \{0, 0.25, 0.5, 0.75, 1.0\}$ 下多次順序或亂序渲染，生成的 SVG outerHTML 必須 100% 字元級一致。
   - **座標邊界**：以 `getBoundingClientRect()` 驗證所有元素皆落在 `[5, 795] x [5, 505]` 內，文字底端 $y \le 410$。
   - **安全降級**：缺參數或參數型別錯誤時不得拋出例外。

### 步驟四：撰寫骨架並驗證主題資料
1. 於 `data/visual/skeletons/<topic-slug>.json` 建立骨架，指定 `blueprint` 與對應 `params`。
2. 撰寫 4～6 條衛教概念要點（`reference`），絕不包含任何價格、數字、百分比或承諾禁詞。
3. 透過 `generate_ir` 搭配 LLM 生成說明文字並通過 `validate_ir`。

### 步驟五：瀏覽器全場景檢視與 MP4 匯出確認
1. 透過 `scripts/export_visual_bundle.py` 匯出 bundle。
2. 透過 `demo/visual/player.html?bundle=...` 在瀏覽器中檢視各時間點渲染細節。
3. 透過 `demo/visual/render_video.py --bundle ...` 匯出 MP4 影片，抽格檢查畫質與時長。

---

## 3. 實作檢查清單 (Checklist)

- [ ] **完全確定性**：元件只相依於進度 $u$ 與 `params`。隨機視覺感必須使用以索引為種子的確定性雜湊函式（`deterministicHash`），嚴禁呼叫 `Math.random`。
- [ ] **時間純粹性**：不得使用 `Date.now`、`new Date`、`performance.now`、`setTimeout`、`setInterval`。
- [ ] **靜態無違規**：原始碼與註解**嚴格不得**包含任何被禁字串：`innerHTML`、`insertAdjacentHTML`、`document.write`、`outerHTML`、`eval`（任何大小寫與複合詞，包括 evaluation 等）、`localStorage`、`sessionStorage`、`document.cookie`、`fetch`、`XMLHttpRequest`。
- [ ] **視窗邊界防護**：外框限定 `viewBox="0 0 800 510"`，元件座標須保留安全邊界，背景設定 `data-bg="1"`。
- [ ] **字幕安全區**：所有文字元件底部 $y$ 座標必須 $\le 410$，預留底部 $100\text{px}$ 予播放器控制列與衛教字幕。
- [ ] **SVG 效能**：動態線條/血管必須使用 `pathLength="100"` 搭配 `stroke-dasharray="100"` 與 `stroke-dashoffset`，**嚴禁呼叫會觸發重排重繪之 `getTotalLength()`**。

---

## 4. 反面做法 (Anti-patterns)

- **嚴禁讓 LLM 自行撰寫 SVG 或 JavaScript**：模型只能為固定場景填寫審核過的純文字說明；動態畫面一律由預先審核的程式碼元件驅動。
- **嚴禁接受任意顏色字串或 HTML**：不得接受 `#ffffff` 或 `<span style="...">`，所有色彩一律經由 `PALETTE_TOKENS` 白名單映射。
- **嚴禁跨呼叫保留內部狀態**：元件內部不得設置閉包累計計數器或全域變數，否則在使用者拖曳時間軸倒退或重播時會產生撕裂。
- **嚴禁內嵌腳本**：`/admin` 頁面受嚴格 CSP `script-src 'self'` 管制，所有邏輯必須放於獨立外部 `.js` 檔案中。

---

## 5. 已知限制與架構承諾

1. **不承諾自動生成新畫面**：本系統為資料驅動之模板引擎，非生成式畫布。任何新的幾何結構或醫療隱喻必須由工程師或 Claude 人工設計並通過自動化測試驗證後才能上線。
2. **醫療審核不可豁免**：由骨架與 LLM 生成之說明文字一律為 `pending` 狀態，必須由執業專科醫師審核通過（`approved`）後方可對病患公開服務。
