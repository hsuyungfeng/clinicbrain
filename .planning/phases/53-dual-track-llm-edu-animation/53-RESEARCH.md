# Phase 53 Research: 雙軌混合衛教系統與 Local LLM 400 題結構化升級

**Date**: 2026-11-18
**Status**: Complete

## 1. 現有系統盤點（已實測確認）

1. **Local LLM 服務**：
   - `llama-server` 運行於 `0.0.0.0:8080`，模型 `/models/Ornith-1.5-35B-Q5_K_M.gguf`（`-c 262144`）。
   - [src/visual/autodraft.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/visual/autodraft.py) 已實作 `local_llm_call()` 包裝（`_default_visual_llm()`），可直接複用 OpenAI 相容端點。

2. **動畫藍圖與渲染器（Track A）**：
   - [src/visual/blueprints.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/visual/blueprints.py) 目前註冊 14 種藍圖，NHI 資產標準 3 幕結構為：`pathology_mechanism`（8s）→ `contrast`（8s）→ `timeline`（8s）。
   - `contrast` 已內建 `contrast_layout`（`auto`, `side_by_side`, `outcome_fork`, `tradeoff_matrix`, `layered_scan`），適合呈現「憩室病 vs 憩室炎」或「檢查／處置對照」。
   - `timeline` 專注生理復原進度；為使第 3 幕能表達「衛教重點行動 + 急診紅旗警訊 + 一句話記牢」，需新增專用藍圖 `care_redflag`。
   - [src/web/static/visual_engine.js](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/web/static/visual_engine.js) 透過 `blueprints` 物件、`sanitizeParams()` 與 `draw...()` 函式渲染 SVG；且 Phase 52 已將 `visual_engine.js` SHA-256 納入 [src/visual/video_queue.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/visual/video_queue.py) 快取鍵，引擎升級後會自動觸發增量重渲。

3. **合規與數字規則邊界（關鍵發現）**：
   - 動畫 IR（[src/visual/ir.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/visual/ir.py) / `autodraft.py`）禁止阿拉伯數字（需轉國字），而完整衛教文稿（如 `60歲以上`、`每天 2000–3000cc`、`每週 150 分鐘`）需要精確生理數據。
   - [src/api/routes/query.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/api/routes/query.py) 的 `deep_mask_prices()` 僅遮蔽貨幣／價格樣式，不會誤傷 `60歲` 或 `150分鐘`。
   - 因此將完整 7 段衛教資料存於獨立欄位 `visual_assets.edu_json`（容許非價格生理數據），動畫 `ir_json` 仍嚴守既有 `ir.py` 與 Phase 52 解剖鎖定規則（保留既有 `organ_system` 與 `anatomy_target`）。

4. **資料庫與 API 路由（Track B）**：
   - `visual_assets` 目前共 14 欄（含 `ir_json`、`review_status` 等），可透過冪等 `ALTER TABLE visual_assets ADD COLUMN edu_json TEXT` 擴充（並同步至 schema 定義），不破壞既有 398 筆紀錄。
   - [src/api/routes/visual.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/api/routes/visual.py) 已集中處理 `/api/v1/visual/*` 路由，適合新增 `GET /api/v1/visual/edu/{topic_key}` 及獨立頁面路由 `GET /edu/{topic_key}`。
   - 前端主要入口為 [src/web/static/index.html](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/web/static/index.html)（[app.js](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/web/static/app.js)）與 [src/web/static/consult.html](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/web/static/consult.html)（[consult.js](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/web/static/consult.js)）。
