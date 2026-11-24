# Phase 56: 最佳組合拳 — Typed IR / 3D × Ornith-1.5-35B × raea 混合影片管線研究

**Researched:** 2026-11-24
**Status:** Verified via local PoC (`clinicbrain/scratch/raea_poc/`)

## 1. 核心架構決策（三層分工）

經實際於本機 Linux（NVIDIA GeForce GTX 1060 6GB + Vulkan 1.4.312）與本機 `Ornith-1.5-35B`（`http://127.0.0.1:8080`）實測後，確認「自由生成 TSX」畫質與時序不穩，而「**確定性解剖核心 × Local LLM 結構化文案 × `raea` 固定模板高速渲染與品管**」為最佳組合：

| 層級 | 負責元件 | 職責與產出 |
|---|---|---|
| **解剖與病理核心層** | `visual_engine.js` + `video_queue.py` / BodyVista 3D GLB | 維持現有 398 筆 2.5D Typed IR 確定性母片與網頁互動播放；Phase 41 3D 則使用預先 `dequantize` 過之標準 GLB 模型 |
| **內容決策層** | `Ornith-1.5-35B` (`http://127.0.0.1:8080/v1/chat/completions`) | 讀取 `clinic.db` 之 `visual_assets`（`ir_json` + `edu_json`），產出**結構化 JSON**（短影音標題摘要、口白旁白腳本、衛教重點與合規標籤），不直接生成 TSX 程式碼 |
| **合成與品管層** | `raea`（`v0.1.9`）固定 TSX 模板 + `raea check` | 讀取結構化 JSON 與母片/3D GLB，於 GPU 合成 9:16 社群短片或 16:9 3D 衛教片，並以 `raea check` 自動驗收安全區、音量響度（`-14 LUFS`）、暗部色塊（`--quality master`）與對比度 |

## 2. 實測關鍵發現與避坑清單（已在 PoC 驗證）

1. **`Ornith-1.5-35B` 推理模式控制**：
   - `llama-server` 預設啟用長思考（`reasoning_content`），易導致 `max_tokens` 耗盡或超過 180s 超時。
   - 呼叫時必須帶入 `"chat_template_kwargs": {"enable_thinking": false}`，並限制輸出為嚴格 JSON Schema；若本機 LLM 離線，須安全降級回 `clinic.db` 既有 `title` / `caption` / `takeaway`。
2. **`raea` 9:16 社群短影音安全區與渲染效能**：
   - 實測 10 秒 1080×1920（240 幀）含音訊合成耗時 **`10.03 秒`**（`31.7 ms/frame`），明顯快於 Playwright 逐格截圖。
   - `raea check` 預設檢查 9:16 頂部 `220px`、底部 `420px`、右側 `140px` 社群按鈕安全區；固定模板採用對稱邊距（`left: 145, right: 145`）與獨立中央影片視窗（`top: 415, height: 880`），可同時達成視覺置中與 `raea check` 0 errors。
   - `<Mix lufs={-14} ceiling={-1}>` 可自動標準化音量至 `-14.1 LUFS`（通過響度檢查）。
3. **Phase 41 BodyVista 3D GLB 相容性與材質**：
   - `clinicbrain/scratch/bodyvista/dental/models/` 原始 `.glb` 採用 WebGL 專用 `EXT_meshopt_compression` 與 `KHR_mesh_quantization`，Bevy `bevy_gltf` 載入器不支援，必須先以 `@gltf-transform/cli` 執行 `copy` + `dequantize` 轉為無擴充標準 GLB。
   - 解剖組織自然嵌套會觸發 `raea` 穿模檢查（`error clips`），`<Model>` 必須加上 `allowOverlap`。
   - 骨骼透明化使用 `<StandardMaterial base_color={Srgba.hex("#e2e8f0").with_alpha(0.32)} alpha_mode="Blend" double_sided />`，神經血管束使用暖紅微發光材質；渲染須加 `--quality master` 以消除暗部 `blotching`，且 720p 攝影機 `radius` 需再拉遠約 10–15% 避免模型上下緣觸碰 80px 安全區卡片。
4. **中文與法規合規**：
   - 本機已具備 `Noto Sans CJK TC`，`raea` 渲染繁體中文無缺字/豆腐塊。
   - 所有輸出文案必須維持繁體中文、零價格、零百分比療效數據、零保證療效字樣，並保留醫療免責聲明。
