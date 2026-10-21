---
name: clinic-visual-batch
description: 指導本地大模型（Qwen3.8-27B-FP8 / 3.8 Flash）批次生成 PageIndex 臨床推理樹之 3 幕向量動畫解說卡，並引導 Hermes Agent 進行自動化監控、測試、驗證與自癒重試之標準作業規範。
---

# Taiwan Clinic Medical Visual Animation Batch Generation & Hermes Monitor Skill

本 Skill 定義 **ClinicBrain** 專案中，如何驅動**本地大語言模型（Local LLM: Qwen3.8-27B-FP8 / 3.8 Flash，128K 上下文）**從已核准的 PageIndex 臨床決策推理樹批次生成符合醫學規範之 3 幕向量解說動畫卡，並由 **Hermes Agent** 執行全程自動化監控、測試回歸與品質把關。

---

## 1. 角色拓撲與職責分工 (Agent Topology)

| 角色 | 實體 / 代理人 | 職責 |
| :--- | :--- | :--- |
| **Generator (生成核心)** | **Local LLM (Qwen3.8-27B-FP8 / 3.8 Flash)** | 讀取已核准推理樹文本，推斷最符合該療程之專科解剖機轉，組裝結構化 3 幕 Typed IR JSON，恪守醫療法規與字元限制。 |
| **Engine (繪圖核心)** | **確定性向量代碼引擎 (`visual_engine.js`)** | 純數學向量繪圖，根據 IR 參數渲染 60fps 動態向量動畫，杜絕 LLM 隨機編寫代碼造成之語法崩潰與圖形變形。 |
| **Monitor (監控與測試)** | **Hermes Agent (`hermes`)** | 守護批次進程、執行 `validate_ir` 門檻檢驗、發動錯誤自癒回饋（Self-Healing Retry）、運行 Playwright 無頭渲染測試與多幀 Vision 審計。 |
| **Auditor (審查與簽核)** | **門診專科醫師 / 院所主管** | 於管理後台 `http://127.0.0.1:8000/admin/index.html` 檢視「🎬 待簽核動畫」，拖曳時間軸複核解剖真實性並點擊核准。 |
| **Promoter (自動昇華)** | **自動昇華引擎 (`auto_promotion`)** | 診所醫師簽核後，自動昇華副本至一般醫學庫（`clinic_id = NULL`），其他診所與匿名病患立即可查，免二次審核。 |

---

## 2. 本地 LLM 生成指南：3 幕專科架構與參數規格 (Local LLM Generation Guide)

### 2.1 尋找待生成推理樹 (Query Missing Trees)
執行以下查詢確認正式庫中已核准但尚未生成動畫的推理樹清單：
```bash
python3 scripts/autodraft_visual_from_trees.py --dry-run
```

### 2.2 臨床藍圖推斷矩陣 (11 大機轉藍圖)
Local LLM 在處理推理樹文本時，**必須優先匹配專屬外科手術**，不得退回一般儀器；Scene 1 必須從以下 11 種機轉藍圖擇一：

| 類別 | 藍圖名稱 (`blueprint`) | 適用療程關鍵字 | 核心參數 (`params`) 規範 |
| :--- | :--- | :--- | :--- |
| **專科骨骼手術** | `surgical_action` | `截骨`, `正顎`, `下巴截骨`, `下顎骨`, `削骨`, `骨膜下剝離` | `bone_label`, `nerve_label`, `nerve_status`, `incision_label`, `fixation_label`, `bone_shift_mm` (0..15), `protect_nerve` (true), `step_labels` (3步) |
| **開放外科拉皮** | `deep_plane_facelift` | `SMAS`, `深層拉皮`, `筋膜拉皮`, `中下臉拉皮`, `facelift` | `layer_labels` (3層), `smas_label`, `anchor_label`, `ligament_label`, `suture_fill`, `step_labels` (3步) |
| **開放外科頸部** | `corset_platysmaplasty` | `天鵝頸`, `闊頸肌`, `雙下巴抽脂`, `馬甲縫合`, `cervicoplasty` | `layer_labels` (3層), `muscle_label`, `fat_label`, `suture_label`, `suture_fill`, `step_labels` (3步) |
| **微創囊腫處置** | `cyst_excision` | `粉瘤`, `表皮樣囊腫`, `皮下囊腫` | `cyst_label`, `sac_label`, `core_label`, `layer_labels` (2層), `sac_fill`, `step_labels` (3步) |
| **微創甲床處置** | `nail_matrix` | `甲溝炎`, `嵌甲`, `凍甲`, `甲基質` | `nail_label`, `fold_label`, `spicule_label`, `matrix_label`, `matrix_fill`, `step_labels` (3步) |
| **微創刮除處置** | `subdermal_curettage` | `頂漿腺`, `狐臭`, `螺旋刀`, `脂肪瘤` | `target_label`, `shaver_label`, `layer_labels` (2層), `tool_fill`, `step_labels` (3步) |
| **自體組織純化** | `process_diagram` | `自體脂肪`, `脂肪移植`, `純化離心` | `source`, `particles` (4..12), `container_layers` (2..4層), `step_labels` (3步) |
| **聚焦音電能量** | `skin_energy` | `音波`, `HIFU`, `電波`, `Thermage`, `拉提` (非開刀) | `mode` (`focused`/`volumetric`), `probe_label`, `layer_labels` (3層), `focal_points` (3..7), `energy_fill`, `step_labels` (3步) |
| **雷射光電擊碎** | `laser_action` | `皮秒`, `飛梭`, `雷射`, `除斑`, `痘疤` | `mode` (`shatter`/`fractional`), `beam_label`, `target_label`, `layer_labels` (2層), `beam_fill`, `step_labels` (3步) |
| **神經肌肉放鬆** | `neuromuscular` | `肉毒`, `動態紋`, `抬頭紋`, `咀嚼肌` | `nerve_label`, `muscle_label`, `surface_label`, `blocker_fill`, `step_labels` (3步) |
| **真皮深層支撐** | `dermal_support` | `玻尿酸`, `晶亮瓷`, `親水凝膠`, `填充` | `filler_label`, `layer_labels` (2層), `droplets` (4..8), `filler_fill`, `step_labels` (3步) |

### 2.3 Scene 2：專科解剖病理對照 (`contrast`)
Scene 2 呈現「左側病理風險（傳統處置，`warning`）」vs「右側微創優勢（診所專科，`optimal`）」，Local LLM 應優先自以下專科對照組合中選取匹配：
1. **體雕抽脂**：`tissue_trauma_torn_vessel`（粗鈍抽吸撕裂血管出血）vs `ultrasonic_emulsification`（超音波乳化保護神經血管）。
2. **眼袋雙眼皮**：`scar_contracture_ectropion`（傳統外切疤痕攣縮下瞼下翻）vs `transconjunctival_fat_reposition`（經結膜內切無外疤平順轉位）。
3. **結構隆鼻**：`silicone_extrusion_erythema`（矽膠假體重力壓迫鼻尖發紅穿出短鼻）vs `cartilage_triangular_strut`（自體軟骨力學三角支架穩固零穿出）。
4. **假體隆乳**：`capsular_contracture_ball`（纖維包膜攣縮變硬球形）vs `dual_plane_natural_teardrop`（雙平面筋膜覆蓋自然水滴垂墜）。
5. **微整針劑**：`nodule_clumping`（單點過量結節硬塊表情僵硬）vs `micro_droplet_diffusion`（多層微滴散佈均勻與組織平滑交融）。

### 2.4 Scene 3：活體生理修復歷程 (`timeline`)
Scene 3 呈現動態三階段生理修復進程，具備頂部動態階段看板、專科生理文字即時切換與專科圖元演繹：
1. **骨骼癒合**：`connectors: "bone_healing"`，里程碑：`["骨痂形成", "骨質緻密", "咬合穩固"]`。
2. **退瘀色譜**：`connectors: "bruise_metabolism"`，里程碑：`["血腫吸收", "色素代謝", "膚色復原"]`。
3. **疤痕隱痕**：`connectors: "scar_maturation"`，里程碑：`["切口潮紅", "加壓褪紅", "隱痕平整"]`。
4. **感覺神經**：`connectors: "nerve_regeneration"`，里程碑：`["暫時麻木", "神經發芽", "感覺恢復"]`。
5. **組織緊緻**：`connectors: "skin_retraction"`，里程碑：`["水腫消退", "基質收縮", "平整回彈"]`。
- **組織單元效果**：可選用 `unit_effect: "glow_restored"`（組織活力全面復原金色光環）。
- **免責條款強制**：Scene 3 的 `caption` 結尾**必須包含**：「恢復程度因人而異，需由醫師當面評估。」或「實際因人而異需由醫師當面評估。」

### 2.5 嚴格法規與格式鐵則 (Hard Constraints)
1. **零阿拉伯數字鐵則**：全文本（`title`、`caption`、`labels`、`params` 所有字串）**嚴禁出現任何半形或全形阿拉伯數字（0-9、０-９）**！一律使用中文數字（如「二公分」、「九十度」、「五毫米」）。
2. **零價格洩漏**：嚴禁提及任何收費金額、促銷或費用字眼。
3. **零違規保證療效**：嚴禁使用「保證有效」、「保證根除」、「百分之百」、「零風險」、「完全不復發」等違反台灣醫療法之禁用詞彙。
4. **字元長度硬上限**：
   - 卡片頂部 `title`：1～30 字（建議 $\le 16$ 字）。
   - 場景 `title`：1～16 字。
   - 場景 `caption`：20～120 字。
   - `labels` 陣列：0～4 項，每項文字 1～12 字。
   - `params` 中各標籤（`bone_label`, `smas_label`, `core_label` 等）：$\le 8$ 字。
   - `params.step_labels` 各項目：$\le 10$ 字。
   - `contrast.left.footnote` / `contrast.right.footnote`：$\le 16$ 字。
   - `contrast.left.note` / `contrast.right.note`：$\le 14$ 字。
   - `timeline.milestones` 各項目：$\le 8$ 字。

---

## 3. Hermes Agent 自動化流水線手冊 (Hermes Runbook)

當交由 Hermes 代理人執行批次生成與監控時，Hermes 遵循以下五步流水線：

### Step 1: Pre-Flight 環境與服務預檢
```bash
# 1. 檢查本地 LLM 推論核心運作 (Qwen3.8-27B-FP8 @ localhost:8080)
curl -s http://127.0.0.1:8080/v1/models | grep -q "Qwen" && echo "✅ Local LLM Gateway Online" || echo "❌ LLM Offline"

# 2. 檢查 API 服務狀態
systemctl --user is-active clinicbrain-api.service && echo "✅ API Server Active" || echo "❌ API Server Inactive"

# 3. 檢查藍圖與引擎安全契約測試
/home/hsu/.local/bin/uv run pytest tests/test_visual_blueprints.py tests/test_visual_engine_static.py
```

### Step 2: 驅動 Local LLM 批次生成
```bash
# 對正式庫執行自動化批次生成（自動調用本地 Qwen3.8-27B）
/home/hsu/.local/bin/python3 scripts/autodraft_visual_from_trees.py --allow-prod-db
```

### Step 3: 自癒修復重試機制 (Self-Healing Loop)
若任一推理樹在生成時觸發 `validate_ir` 報錯，Hermes 需捕捉具體錯誤碼，並組裝診斷反饋給模型：
* **`forbidden_phrase`**：檢查是否有「保證」、「永久」、「零風險」或漏寫場景 3 結尾詞「需由醫師當面評估」，要求模型修正該段說明。
* **`schema_error`**：檢查是否有字串長度溢出（如 `footnote > 16` 字或 `milestones > 8` 字），要求模型縮減字數。
* **`unknown_blueprint`**：檢查 Scene 1 藍圖是否拼錯，提示模型只能從 11 大合法外科/醫美藍圖中選取。
* **`text_unsafe`**：檢查是否誤入阿拉伯數字或 HTML 標籤。

### Step 4: 瀏覽器無頭回歸測試與抽幀審計
生成完畢後，啟動 Playwright 執行確定性 seek 測試與邊界安全區測試：
```bash
/home/hsu/.local/bin/uv run pytest tests/test_visual_engine_browser.py
```
若需錄製 MP4 動畫並抽幀審計：
```bash
/home/hsu/.local/bin/python3 demo/visual/render_video.py --bundle demo/visual/out/rhinoplasty-strut.json --fps 12 --hold 2.5 --width 800 --out demo/visual/out/rhinoplasty-strut.mp4
```

### Step 5: 產出審計回報並通知醫師簽核
Hermes 輸出標準結構化成果日誌，通知專科醫師至 `http://127.0.0.1:8000/admin/index.html` 的「🎬 待簽核動畫」分頁進行最後簽核。醫師一旦點擊核准，資產將自動昇華至全院一般醫學庫。
