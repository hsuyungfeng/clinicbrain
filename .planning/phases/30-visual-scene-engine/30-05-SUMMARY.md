# Phase 30 Plan 05: 第二主題（玻尿酸填充）零 JS 改動驗證與 Blueprint 新增指南執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `30-05-PLAN.md` 規格，驗證 Phase 30 所建立的視覺場景引擎具備完全之資料驅動特性：引入第二個主題（玻尿酸填充原理）時，僅新增骨架 JSON 與測試，對 `src/web/static/*.js`、`demo/visual/*.js`、`scripts/` 與 `src/` 達成 **100% 零改動**。同時撰寫標準化文件 [`docs/visual-blueprints.md`](file:///home/hsu/Desktop/clinicbrain/docs/visual-blueprints.md)，明確定義未來新增 blueprint 的五大標準步驟與檢查清單。

1. **玻尿酸填充骨架與零 JS 改動驗證（Task 1, P30-PROOF）**：
   - 建立第二主題骨架 [`data/visual/skeletons/hyaluronic-acid-filler.json`](file:///home/hsu/Desktop/clinicbrain/data/visual/skeletons/hyaluronic-acid-filler.json)：
     - `topic_key`: `hyaluronic-acid-filler`，標題「玻尿酸填充原理」。
     - 關鍵字包含「玻尿酸」「玻尿酸填充」「填充」「微整形填充」。
     - 完全由既有三大模板規格參數驅動：
       * 場景 1 (`process_diagram`)：`source` {label: "凝膠", fill: "gel"}，`particles`: 8，三層容器 `container_layers`（淺層 pale / 中層 gel keep:true / 深層 skin，weight 2/3/2），三階段步驟標籤 `step_labels`。
       * 場景 2 (`contrast`)：左側 `left` {title: "單點過量", note: "較不自然", mode: "mass"}，右側 `right` {title: "分點少量", note: "更貼近自然", mode: "layered", rows: 2, per_row: 5}。
       * 場景 3 (`timeline`)：三階段節點標籤 `milestones`（術後初期／逐漸融入／維持期），`unit_effect`: "fade"（表現逐漸吸收代謝），`connectors`: "none"，`units`: 4。
     - 參考概念要點（`reference`）：共 5 條概念指引，嚴格不含任何價格、數字、百分比符號或承諾禁詞。
   - 建立自動化驗證測試 [`tests/test_visual_second_topic.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_visual_second_topic.py)：
     - 驗證骨架通過 `load_skeleton` 解析與禁詞校驗。
     - 驗證 `generate_ir` 搭配假模型輸出合格說明文字後，生成的 IR 完整保留骨架 parameters、blueprint 與 labels，並通過 `validate_ir` 醫療法規檢核。
     - 驗證在隔離測試資料庫完成入庫與核准後，可成功透過 `export_visual_bundle.py` 匯出合格之 bundle JSON。
     - 以無頭 Chromium（Playwright）載入 `visual_engine.js` 實機渲染三場景於 $u \in \{0, 0.5, 1.0\}$，所有元素均位於 viewBox $[0, 800] \times [0, 510]$ 容差安全區內。
     - 斷言瀏覽器中 `ClinicVisual.blueprints` 鍵集合維持為 `["contrast", "process_diagram", "timeline"]` 三種，證明無任何特化擴充。
   - **Commit**: `d993f81` `feat(visual): 新增第二主題玻尿酸填充骨架與零 JS 改動測試 (Task 1)`

2. **新增 Blueprint 指南（Task 2, P30-PROOF）**：
   - 撰寫繁體中文手冊 [`docs/visual-blueprints.md`](file:///home/hsu/Desktop/clinicbrain/docs/visual-blueprints.md)：
     - **參數規格表**：逐項詳載目前三大 blueprint 之結構、型別約束、預設值，以及 10 種語意調色盤代號（`PALETTE_TOKENS`）。
     - **新增 Blueprint 五步驟**：定義從 Python 端註冊參數規格、JavaScript 引擎實作純函式 `draw(ctx, params, u)`、補齊契約與確定性測試、撰寫骨架到瀏覽器全場景檢視與 MP4 匯出的標準化研發流程。
     - **實作檢查清單**：明訂完全確定性、時間純粹性、靜態無違規（禁用子字串清單）、視窗邊界防護與字幕安全區（$y \le 410$）。
     - **反面做法**：記錄嚴禁讓 LLM 自行寫 SVG/JS、嚴禁接受任意顏色字串、嚴禁跨呼叫保留內部狀態、嚴禁內嵌腳本等安全紅線。
     - **已知限制**：明確指出本系統不承諾由 AI 自動生成新幾何畫面，新 blueprint 仍需人工/Claude 設計，且所有醫療敘述仍需執業醫師簽核。
   - **Commit**: `8c997dc` `docs(visual): 新增視覺解說卡 Blueprint 規格與新增指南 (Task 2)`

---

## 2. 測試與驗收結果

- **測試執行結果**：
  - Task 1 驗證指令：`uv run pytest -q -p no:cacheprovider tests/test_visual_second_topic.py tests/test_visual_generator.py tests/test_visual_blueprints.py` 全數 28 項測試通過（`28 passed in 1.04s`）。
  - Task 2 驗證指令：`test -s docs/visual-blueprints.md && grep -c "draw(ctx, params, u)" docs/visual-blueprints.md` 檢核通過（計數 3）。
- **零程式碼改動驗收**：
  - 執行 `git diff --stat d2b4344..HEAD`：
    僅新增 `data/visual/skeletons/hyaluronic-acid-filler.json`、`docs/visual-blueprints.md`、`tests/test_visual_second_topic.py` 三檔。
    `src/web/static/*.js`、`demo/visual/*.js`、`scripts/`、`src/` 達成 **0 改動**。
- **正式資料庫保護**：
  - `clinic.db` SHA-256 維持為 `e28dc0089b01d59a03456bcced7974254c7986697d12dc0fb50da1e4a17ba6e1`，未遭任何存取或更動，且正式庫中絕未入庫第二主題。

---

## 3. 改動檔案清單

- `data/visual/skeletons/hyaluronic-acid-filler.json`：第二主題玻尿酸填充原理骨架。
- `tests/test_visual_second_topic.py`：第二主題零 JS 改動與邊界驗證測試套件。
- `docs/visual-blueprints.md`：Blueprint 規格與新增實作指南。
