# Phase 45: 3D 臨床解剖 WebGL 檢視組件實裝 (3D Clinical Anatomy WebGL Viewer Component)

> **所屬里程碑**：v1.5 / v1.6  
> **關聯規格**：`docs/anatomy-3d-architecture.md` (Phase 41 Plan 03 產出)  
> **核心目標**：為 clinicbrain 打造輕量、受控、具備 2D 向量降級防線的原生 Web Component `<clinic-anatomy-viewer>`，與 PageIndex 臨床推理樹深度聯動，實現 3D 解剖視角導引與醫療法規嚴格把關。

---

## 1. 背景與動機

在 Phase 41 中，系統完成 3D 臨床解剖探索與架構規格定稿（`docs/anatomy-3d-architecture.md`）。在 Phase 44，系統完成了次世代 2D 向量動畫引擎升級（`visual_engine.js`），在 Phase 43 完成了 398 部動畫的自動化影片佇列。

為滿足診所醫師在門診審核與病患諮詢時更立體、深度的解剖結構溝通需求（如音波拉提的 SMAS 淺筋膜層、植牙拔牙的神經血管束、雙眼皮提上瞼肌等），Phase 45 將正式落實 3D 臨床解剖檢視組件 `<clinic-anatomy-viewer>`，並與 PageIndex 臨床推理樹之步驟進行事件驅動的雙向聯動。

---

## 2. 核心架構與法規防線

1. **組件邊界與渲染生命週期**：
   - 原生 Web Component 封裝：`customElements.define('clinic-anatomy-viewer', ...)`，杜絕全域 CSS/JS 污染。
   - 渲染技術棧：Three.js 核心子集 + WebGL 2.0，支援 GLTF/GLB 載入。
   - 資產體積控制：專科解剖資產包 $\le 3\text{MB}$，核心腳本延遲載入（Lazy Loading）。
   - 上下文自癒與降級：監聽 `webglcontextlost` / `webglcontextrestored`；若 WebGL 完全不可用，無縫降級回退至 `visual_engine.js` 2D 向量動畫。

2. **PageIndex 關聯契約 (`anatomy_metadata`)**：
   - 定義結構化映射：`doc_id` ➔ `anatomy_target`、初始相機角度、步驟動作（`highlight_layer`、`warning_zone` 等）。
   - 事件匯流排：監聽 `anatomy:focus-step`，驅動平滑運鏡（Camera Fly-To）與目標網格脈衝高亮。

3. **四層醫療法規防禦**：
   - **嚴格零價格外洩**：所有 Tooltip 與步驟文字強制經過 `deep_mask_prices()` 遞迴清洗。
   - **法定免責聲明**：固定標註「3D 解剖模型僅供衛教輔助參考，解剖結構存在個人體質差異，實際手術計畫以門診醫師親自評估為準。」
   - **台灣繁體專科術語**：繁體中文、杜絕未校準之簡體醫學名詞。
   - **100% 離線本地自託管 (Fail-Closed Offline Security)**：所有 3D 資源均由本地服務託管，嚴禁任何外連遙測。

4. **Herdr 獨立測試驗收機制**：
   - 調度待命中的獨立 Agent Hermes (`wA:p3`) 作為外部驗證 Tester，執行自動化測試與跨進程獨立審計。
