# FreedomIntelligence/BodyVista 3D 解剖平台沙盒 PoC 與專科精細度稽核報告

> **審核日期**：2026-11-11  
> **評估專案**：FreedomIntelligence/BodyVista（香港中文大學深圳 CUHK-SZ NLP 研究團隊開源項目）  
> **應用場景**：緻妍外科診所（`3503190424`）門診 3D 視覺化諮詢與 PageIndex 臨床推理樹實體對齊  
> **審核代理**：Agy (Executor) & Hermes (Tester)

---

## 1. 專案架構與量化資源分析

經於本機隔離沙盒環境（`scratch/bodyvista/`）檢測，BodyVista 平台核心特徵如下：

* **核心資料來源**：`Bio2Mesh Atlas`（基於 Z-Anatomy 原始世界座標系與 BodyParts3D 網格貼合演算法）。
* **全域解剖部位數**：`catalog.json` 涵蓋 **2,900 個部位 (parts)** 與 **12 個人體系統**。
* **網格面數 (Triangles)**：原始網格 `source_triangles = 10,766,761`（約 1,076 萬面），顯示優化網格 `display_triangles = 3,007,156`（約 300 萬面）。
* **檔案體積盤點**：
  * 完整倉庫體積：**783 MB**。
  * 全身 3D 模型檔 (`assets/full_body.glb`)：**75.4 MB**。
  * 各系統單獨資料包：心血管 (`cardiovascular.js`, 31.9MB)、肌肉 (`muscular.js`, 23.2MB)、神經 (`nervous.js`, 21.6MB)、骨骼 (`skeletal.js`, 13.9MB)。
* **前端渲染開銷評估**：
  * 單次載入需傳輸超過 **150MB+** 之靜態資源。
  * 瀏覽器 WebGL 上下文解壓縮後，顯存/記憶體佔用約 **600MB～1.2GB**。
  * 在診所端平板（如 iPad 衛教螢幕）或低配診間螢幕上，存在高機率之記憶體崩潰（`WebGL Context Lost`）與長達 10~20 秒的載入白屏。

---

## 2. 緻妍診所核心專科解剖精細度抽查 (Specialty Precision Audit)

針對緻妍外科診所常見的核心手術與醫美療程進行逐項網格與目錄檢索比對：

### 2.1 抽查主題一：顏面拉皮／音波拉提 (Facelift / HIFU / Facial Anatomy)
* **SMAS 筋膜層 (Superficial Muscular Aponeurotic System)**：
  * **檢索結果**：**0 筆命中 (0 hits)**。
  * **臨床缺口**：BodyVista 包含頸闊肌（`platysma`）與咬肌筋膜（`masseteric fascia`），但**完全缺失**現代整形外科面部除皺拉提最關鍵的 SMAS 獨立網格層。
* **顏面神經分支 (Facial Nerve Branches, CN VII)**：
  * **檢索結果**：僅有左右側「顏面神經主幹」(`facial nerve (vii)`) 與「運動核」(`motor nucleus`)。
  * **臨床缺口**：外科拉皮與音波避開神經所需之五大分支（顳支、顴支、頰支、下頜緣支、頸支）並未獨立分離成可互動網格，無法高亮特定危險區域。
* **面部脂肪室 (Facial Fat Compartments)**：
  * **檢索結果**：全資料庫脂肪組織僅有髕骨下脂肪墊（`infrapatellar fat pad`），面部脂肪為 **0 筆**。
  * **臨床缺口**：缺乏深層頰脂墊（Buccal Fat Pad）、眼輪匝肌下脂肪（SOOF）、顴骨脂肪墊（Malar Fat Pad），無法呈現自體脂肪補臉或音波溶脂之層次。
* **判定**：**宏觀醫學教學級**，尚未達到醫美整形外科臨床拉皮與微整之精準層次。

### 2.2 抽查主題二：自體脂肪／假體隆乳 (Breast Augmentation)
* **胸大肌 (Pectoralis Major)**：
  * **檢索結果**：8 筆命中（包含左/右側胸大肌腹部、鎖骨部、胸小肌等）。
  * **臨床適用性**：胸大肌結構相對完整，可支持展示肌肉走向。
* **乳腺組織與雙平面腔隙 (Mammary Gland & Dual Plane)**：
  * **檢索結果**：`breast`、`mammary` 檢索均為 **0 筆**。
  * **臨床缺口**：僅有女性皮膚表層外觀輪廓，缺乏內部乳腺腺體、乳管與胸大肌筋膜下的分離間隙（Subpectoral Pocket），無法直觀解說假體置放之「半筋半肉（Dual Plane）」臨床術式。
* **判定**：缺乏腺體內部解剖細節，需人工補模或專科擴充。

---

## 3. 台灣醫療法規與語言在地化審核

1. **繁簡語言與專科術語對齊**：
   * BodyVista `catalog.json` 內部全數採用**簡體中文**（如「左侧胸大肌腹部」、「左侧眼轮匝肌眶部」）。
   * 需建立自動化管線，透過 `opencc` (`s2twp`) 轉為台灣正體中文，並比對台灣中華民國解剖學會之標準醫學名詞（如禁止出現大陸專有俗稱）。
2. **完全離線自託管合規性**：
   * 專案內靜態資產可完全本地託管於診所區域網路，具備 100% 離線運行能力。
   * 需清除原始網頁代碼中可能內嵌之外部 CDN 字體（Google Fonts）與第三方統計代碼，以貫徹 ClinicBrain 的 Fail-Closed 隱私保護。
3. **價格與宣傳防線**：
   * 未來若與 PageIndex 連動，3D 模型彈出的所有解說文字必須強制經過 `deep_mask_prices()` 遞迴清洗，嚴禁標註任何手術收費金額。

---

## 4. 結論與建議架構路徑 (Conclusion & Strategic Advice)

### 4.1 總體評估結論
* **優勢**：骨骼、大肌肉群與內臟結構宏觀完整，三維座標體系精準，適合做基層大科衛教（骨科、消化內科、胸腔內科）。
* **劣勢**：檔案體積過於龐大（GLB 75MB + JS 150MB+），且醫美微創與整形外科專科層次（SMAS、面神經末梢分支、面部脂肪室、乳腺腔隙）存在顯著缺口。

### 4.2 建議整合策略（分階段引進）
1. **短期（不宜整包引入）**：
   切勿將 780MB 原始倉庫直接作為靜態資產塞入 ClinicBrain 主專案，避免造成倉庫肥大與載入效能瓶頸。
2. **中期（專科子網格裁剪 Sub-Mesh Pruning + Draco 壓縮）**：
   針對緻妍外科特定重點（如面部、胸部），將 300 萬面的模型裁剪為局部的獨立專科 3D 資產包（目標單包 $< 3\text{MB}$），並以 Draco / Meshopt 進行 80% 體積壓縮。
3. **長期（專科客製補模）**：
   與專業醫學 3D 設計師或專科醫師合作，在既有頭頸部骨骼肌肉基底上，補上手術必備的 SMAS 筋膜與自體脂肪注入層次，再與 PageIndex 臨床推理樹深度連動。
