# Phase 44: 次世代生動向量視覺引擎全面升級 (Next-Gen Dynamic Vector Visual Engine)

## 1. 階段目標與核心價值
本階段旨在將已發布之 **398 筆 24 秒醫學向量動畫卡片** 從死板扁平的「工程流程圖」質感，升級為具備生命律動、立體深淺光影與物理慣性質感的「次世代醫學解說動畫」。

**核心優勢（架構解耦紅利）**：
- **零資料庫改動**：正式資料庫 `clinic.db` 中的 398 筆 `ir_json` 完全不需變更或重新生成。
- **純代碼純函式升級**：所有視覺與動態增強集中於 `src/web/static/visual_engine.js`，瀏覽器或播放器一刷新，398 部動畫立即可見立體生動效果。
- **為後續 Phase 43 鋪路**：Phase 44 完工後，Phase 43 產出之 MP4 影片將直接具備高階生動光影，無須重複渲染。

## 2. 核心技術規格與模組劃分
1. **Wave 1 (44-01-PLAN.md)：`ClinicMotion` 物理動態數學庫實裝**
   - 封裝非線性緩動（`easeOutCubic`, `easeInOutQuad`）、果凍回彈（`springGentle`，過衝 $1.05 \to 1.0$）與蓄力爆發（`anticipate`）。
   - 封裝確定性器官呼吸微動（`createBreathingPulse`，$\pm 1.2\%$ 尺度微搏動）。
   - 封裝擴散同心圓光環（`createRippleWave`）。
   - 封裝布朗有機粒子擾動演算法（`createBrownianDrift`）。
2. **Wave 2 (44-02-PLAN.md)：11 大專科藍圖 2.5D 光影與微環境升級**
   - 升級 `drawPathologyMechanism`、`drawProcessDiagram`、`drawSurgicalAction`、`drawDeepPlaneFacelift`、`drawSkinEnergy` 等繪圖函式。
   - 導入雙層半透明徑向漸層（Subsurface Scattering 微透光質感）。
   - 筋膜與器械切口邊緣高光流動（Shimmer Sweep）與體積投影（Ambient Occlusion）。
3. **Wave 3 (44-03-PLAN.md)：對照顫動、修復粒子與確定性全套驗收**
   - Scene 2 傳統側警示紅光不安震顫 vs 微創側翡翠綠流光防護屏障。
   - Scene 3 時間軸節點打勾時爆發金色修復微粒子（Sparkle Dust）。
   - Playwright 60fps seek 正反向確定性測試、全套回歸與全景審核矩陣驗收。
