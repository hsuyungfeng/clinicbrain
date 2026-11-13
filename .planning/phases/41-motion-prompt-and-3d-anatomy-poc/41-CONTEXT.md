# Phase 41: 動態規格標準化與 3D 臨床解剖探索 (Motion-Prompt Integration & BodyVista 3D Anatomy PoC)

## 1. 階段定位與目標
本階段旨在解決診所衛教卡片（`clinic-visual-batch`）動態描述精度不足，並針對醫美/整形外科專科（緻妍外科診所，`3503190424`）探索次世代 3D 臨床解剖可視化與 PageIndex 連動技術路徑。

本階段核心任務包含三步驟：
1. **第一步（立即實施，高投報）：`motion-prompt` 動態規格與緩動預設抽取整合**
   - 深入檢視 `showheyohtaki/motion-prompt`，精選適用於醫療動畫之動態（Motion）、鏡頭（Camera）、UI 過渡與純 Canvas 2D/CSS 緩動曲線（easing curves）。
   - 建立規格模組 `.agents/skills/clinic-visual-batch/resources/motion_vocab.json`，並更新 `.agents/skills/clinic-visual-batch/SKILL.md`，制定本地 LLM 提示規範。
   - 確保本地大模型（Qwen3.8-27B-FP8 / 3.8 Flash）生成「PageIndex 3 幕衛教卡片」時具備精確動效參數，大幅降低隨機動態錯誤。
2. **第二步（沙盒概念驗證 PoC）：`FreedomIntelligence/BodyVista` 專科解剖評估**
   - 於本機隔離沙盒環境 clone `FreedomIntelligence/BodyVista`，實測其 3D 模型檔案體積（GLTF/GLB）、WebGL 渲染延遲與模組結構。
   - 抽查 1~2 個緻妍診所核心療程（例如：顏面拉皮／音波的臉部 SMAS 層與神經走向，或是自體脂肪隆乳／假體植入之胸大肌／乳腺腔隙），評估其解剖模型精細度是否達到整形外科臨床衛教水準。
   - 檢核繁體中文與台灣醫學術語對齊要求，以及 100% 離線區域網路自託管可行性。
3. **第三步（架構整合規劃）：3D 解剖檢視器前端組件與 PageIndex 關聯設計**
   - 若 PoC 評估通過，規劃將 3D 解剖檢視器封裝為獨立前端組件（Consultation 3D Viewer），與病患諮詢前台（`patient_consult`）整合。
   - 制定推理樹 `doc_id` 與 3D 解剖實體 ID（`anatomy_id`）之映射標準，支援自動連動旋轉、層次剝離與病灶高亮。
   - 確保受控於嚴格醫療法規防禦線：全繁體中文、零價格洩漏（`deep_mask_prices`）與禁止保證療效。

## 2. 核心約束與醫療法規標準
- **純本地離線保證**：所有動畫規格與未來 3D 模型資產必須 100% 於本地或診所區域網路自託管，嚴禁外連未授權第三方雲端服務或遙測。
- **繁體中文與台灣專科名詞**：解剖結構與病理動效命名嚴格對齊台灣醫學會名詞標準，禁止未校準的大陸用語。
- **嚴格零價格洩漏**：所有動態標籤與解剖註記嚴禁包含任何價格、費用或促銷金額。
- **無保證療效與免責聲明**：視覺動效與解剖演繹均需明確標示個人體質差異與醫師親自評估之警語。
