# Phase 49 CONTEXT — 398 筆臨床動畫深度升級與字幕／成片驗收

## 1. 背景與已交付基礎（Wave 0）
已於 `src/web/static/visual_engine.js`、`src/visual/blueprints.py`、`Plan.md` 與 `tests/test_phase49_visual_upgrade.py` 完成：
1. **49-A（解剖位置相對性）**：Scene 1 開頭（`u < 0.14`）呈現宏觀人體輪廓座標錨點與組織深淺層次，`u >= 0.14` 後切換回純局部切面，不留常駐小地圖。
2. **49-B（場景二四範式分流）**：`drawContrast` 支援 `outcome_fork`、`tradeoff_matrix`、`layered_scan`、`side_by_side` 四種臨床對比範式。
3. **49-C（場景三細膩好處動畫）**：`drawTimeline` 加入依 `connectors` 分流之微觀正向變化動畫與非量化功能舒適度平緩趨勢帶。
4. **49-D（分段字幕與動態 labels）**：`drawSceneNarrativeOverlay` 於底部字幕安全區（`y: 414..500`, `data-subtitle="1"`）渲染分段字幕與 `tone` 標籤膠囊。

## 2. `hermes-test` 實測發現的待辦缺口
* `splitCaptionSegments()` 目前僅依 `[。！？；]+` 切段，但實庫 398 筆 IR 的 `caption` 多半句內使用「，」、僅結尾有一個「。」，導致真實資產在三幕都顯示 `1/1`（整段一次倒出，且長句超過兩行會被截斷）。
* `visual_engine.js` 升級後，既有 `data/videos/` 下 Phase 43 舊版快取 MP4 尚未以 `--force` 重新渲染驗證。
* 使用者指定透過 `herdr` 委派 `hermes-test`（pane `wA:p3`）擔任測試驗收人員。
