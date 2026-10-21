# Phase 33 CONTEXT：專科解剖對照與修復歷程語意繪圖全面升級 (Contrast & Timeline Semantic Engine 2.0)

## 來源與背景（使用者指示 2026-10-21）
- **核心訴求**：「場景 2 與場景 3 完全可以、且非常適合依照這個模式全面升級！將這套規格作為 Phase 33（專科解剖對照與修復歷程語意繪圖全面升級）來推進執行，Claude 執行實作 ➔ Hermes 測試 ➔ Agy 最終檢查與修復。」
- **問題現狀**：
  - Phase 32 成功解決了場景 1 的專科解剖動態（`surgical_action` 等 10 大藍圖），徹底杜絕抽象圓點。
  - 目前場景 2（`contrast`）與場景 3（`timeline`）雖已加入切口與冰敷雪花初版，但對於眼整形（內外開）、隆鼻（矽膠頂出 vs 軟骨三角架）、隆乳（包膜攣縮 vs 雙平面）、體雕（暴力抽吸血管撕裂 vs 超音波乳化）、骨骼修復（骨痂橋接）、瘀青退化色譜、疤痕隱痕重塑等專科情境，仍缺乏深度的語意圖元。
  - 本階段目標是讓場景 2 與場景 3 具備專科級具象動態表現，達到 100%「依文字意義轉寫 Code 表現」。

---

## 核心設計決策與藍圖規格

### 1. 場景 2 (`contrast` 對照組) 專科解剖模式擴充
在 `src/visual/blueprints.py` 中擴充 `contrast` 模式列舉：

#### (1) `left.mode`（傳統處置／病理風險對照）：
* `mass`: 原有大團塊過量放置（脂肪/微整硬塊）。
* `scattered`: 散在分佈。
* `wide_incision`: 傳統廣大切口翻瓣與面/頦神經受壓拉扯發紅。
* `thermal_spread`: 儀器熱能過度擴散與周圍組織燙傷紅腫。
* `tissue_trauma_torn_vessel` (抽脂體雕): 粗鈍管盲吸撕裂深淺血管與神經、大面積出血發紫、皮下嚴重凹凸不平。
* `scar_contracture_ectropion` (眼部手術): 外切口疤痕纖維攣縮牽引下瞼外翻、睫毛下垂、凹陷黑眼圈。
* `silicone_extrusion_erythema` (鼻整形): L型矽膠重力壓迫鼻尖發紅變薄、穿出風險、莢膜攣縮短鼻朝天。
* `capsular_contracture_ball` (假體隆乳): 筋膜下厚纖維莢膜緊縮包覆、假體僵硬如石、球狀移位變形。
* `nodule_clumping` (微整針劑): 大分子單點堆積結節、肉芽腫硬塊、表情牽動受阻。

#### (2) `right.mode`（微創優勢／診所精準處置）：
* `layered`: 原有多層次立體分佈。
* `minimal_incision`: 3D 導板貼合、在安全邊距內隱密切開、避開神經路徑。
* `targeted_energy`: 標靶收斂、能量精準聚焦於目標深度層次。
* `ultrasonic_emulsification` (抽脂體雕): 超音波探針專一性共振乳化脂肪、保留完整結締組織網與血管神經、平整貼合。
* `transconjunctival_fat_reposition` (眼部手術): 經結膜內切口零外疤、眶隔脂肪精準平鋪轉位至淚溝凹陷、平順無痕。
* `cartilage_triangular_strut` (鼻整形): 自體鼻中隔與耳軟骨搭建立體海鷗線三角支架、力學穩固支撐、零假體穿出風險。
* `dual_plane_natural_teardrop` (假體隆乳): 雙平面胸大肌部分放鬆置入、上緣平順漸層銜接、下緣如自然水滴垂墜柔軟。
* `micro_droplet_diffusion` (微整針劑): 鈍針多層微滴散佈、與自身組織平滑交融、表情靈活自然。

---

### 2. 場景 3 (`timeline` 歷程組) 生理修復動態擴充
在 `src/visual/blueprints.py` 中擴充 `timeline` 連接器與單元效果列舉：

#### (1) `connectors`（修復動態連接結構）：
* `vessels`: 血管網絡生成（脂肪存活）。
* `none`: 一般時程指示。
* `wound_healing`: 急性期彈性加壓帶包覆與冰敷雪花 ❄️、水腫吸收消退水紋。
* `collagen_remodeling`: 膠原纖維網交織緊縮、平整立體緊緻線條。
* `bone_healing` (骨骼重塑歷程): 截骨斷端隨 $u$ 演進，生出微細骨網骨痂橋接（Callus Formation）➔ 骨小樑交織緻密化 ➔ 咬合線骨質完全融合穩固。
* `bruise_metabolism` (退瘀色譜歷程): 皮下暗紫血腫 ➔ 巨噬細胞吞噬代謝轉為墨綠褐斑 ➔ 橙黃散開 ➔ 原生膚色完全復原紅潤。
* `scar_maturation` (疤痕隱痕歷程): 術後初期潮紅微凸切口線 ➔ 矽膠膜加壓漸進褪紅 ➔ 排列混亂膠原蛋白重整為緻密平行極細白線。
* `nerve_regeneration` (感覺神經重生): 暫時性麻木鈍感 ➔ 感覺神經末梢沿神經鞘管發芽長出金黃高光軸突 ➔ 重新覆蓋表皮感覺受器完全恢復敏感度。
* `skin_retraction` (組織緊緻回縮): 術後皮下間隙水腫 ➔ 纖維母細胞合成新基質收縮拉緊筋膜 ➔ 皮膚平整回彈貼合骨骼曲線。

#### (2) `unit_effect`：
* `mature`: 成熟穩定漸層。
* `fade`: 淡化消退。
* `steady`: 恆定平衡。
* `glow_restored`: 修復完成金色微光。

---

### 3. Autodraft 語意推斷升級 (`src/visual/autodraft.py`)
- **場景 2 推斷函式 `infer_scene2_contrast(tree)`**：
  - 根據推理樹第 2 段（併發症與技術）文本意圖，自動判斷並輸出對稱的 `(left.mode, right.mode)` 與客製標籤。
- **場景 3 推斷函式 `infer_scene3_timeline(tree)`**：
  - 根據推理樹第 3/4 段（術後照護與恢復）文本意圖，自動判斷並輸出最吻合之 `connectors` 與 `milestones`。
- **整形器 100% 容錯防呆**：
  - 嚴格校驗新列舉值，超過字數截斷，非法字串優雅降級回預設值，絕不拋出未捕獲例外。

---

### 4. 前端繪圖引擎升級 (`src/web/static/visual_engine.js`)
- 在 `drawContrast` 中擴充上述 5 組對照組繪製子邏輯（利用 SVG path, rect, circle, polygon, text 組合）。
- 在 `drawTimeline` 中擴充上述 5 組生理修復動態子邏輯。
- **醫療前端安全鐵則**：
  - 嚴格禁止 `eval`（包含任何大小寫及子字串）。
  - 嚴格禁止 `new Function`。
  - 嚴格禁止 `innerHTML` / `outerHTML` / `document.write`。
  - 嚴格禁止非 SVG 規範的外部網路請求。

---

## 多 Agent 協作管線 (Herdr Multi-Agent Pipeline)

1. **Planner & Reviewer (agy, w6:p1)**：
   - 制定 Phase 33 全套計畫（`33-01-PLAN.md`, `33-02-PLAN.md`）。
   - 審查各 Agent 交付產物、執行最後安全檢查與驗收。
2. **Executor (claude, w6:p6)**：
   - 實作後端架構 `blueprints.py`、`autodraft.py` 與前端繪圖引擎 `visual_engine.js`。
   - 編寫各模組單元測試與契約測試。
3. **Tester (hermes, w6:p2)**：
   - 執行無頭 Playwright 回歸測試套件。
   - 逐格渲染 MP4 動畫並進行多幀 Vision 視覺確認。
   - 監控正式庫 SHA-256 零污染。
