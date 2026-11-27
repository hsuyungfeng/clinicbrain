# Phase 57 計畫審查報告 (57-PLANCHECK.md)

**審查者**：agy（Plan Checker & Executor）  
**審查時間**：2026-11-27 13:17（初始審查 FAIL）、2026-11-27 13:18（修訂複核 PASS）  
**審查目標**：
- `.planning/phases/57-visual-blueprint-classification-narration-ab/57-CONTEXT.md`
- `.planning/phases/57-visual-blueprint-classification-narration-ab/57-01-PLAN.md`
- `.planning/phases/57-visual-blueprint-classification-narration-ab/57-02-PLAN.md`
- `.planning/phases/57-visual-blueprint-classification-narration-ab/57-03-PLAN.md`
- `.planning/phases/57-visual-blueprint-classification-narration-ab/57-04-PLAN.md`

**審查結論**：**PASS**（阻斷項 B1–B3 已全數修訂到位；討論項 D1、D4 已回寫驗收標準；具備可執行性）

---

### 一、複核要點與改動核實

| 項目 | 審查意見（上一版 FAIL） | Claude 修訂回寫結果 | 複核狀態 |
| :--- | :--- | :--- | :---: |
| **B1** | `VALID_SCENE1_BLUEPRINTS` 實體在 `autodraft_ir.py`，`blueprints.py` 無此常數 | 57-02 Objective 明確更正引用來源為 `src/visual/autodraft_ir.py` | **PASS** |
| **B2** | 57-02 T2 遺漏 `generate_nhi400_visual_batch.py` 的檢查與驗收標準 | T2 驗收標準補齊 `nhi200`（291/473 行）與 `nhi400`（133/204/214/268 行）之 grep 檢查與 mock 快照測試 | **PASS** |
| **B3** | 本地環境無 TTS 引擎，57-03 T1 無法輸出音檔 | 57-03 T1 改採「前端 Web Speech API + 字數時長推算」，明定不產出音檔並以 `find` 檢驗 | **PASS** |
| **D1** | `evidence_span` 嚴格子字串易因標點/空白誤判 | 57-02 T2 納入「忽略空白與全半形標點」之正規化子字串比對驗證標準 | **PASS** |
| **D4** | 理解題選項過長易超出短 caption 篇幅 | 57-03 T2 增訂題幹 ≤40 字、每個選項 ≤20 字之硬性字數上限約束 | **PASS** |

---

### 二、實測基準數據核實 (Ground Truth Baseline)

經唯讀查詢 `clinic.db`（`PRAGMA query_only = ON`）核對，計畫提及之基線數字全數獲得證實：
1. **視覺資產總數**：399 筆（approved 398、rejected 1，通過率 99.7%）。
2. **推理樹總數**：92 棵（資料表為 `page_index_trees`）。
3. **tree_id 精確對應**：72 筆（對應樹之 `doc_id` 100% 一致）。
4. **缺動畫推理樹**：47 棵（92 棵中僅 45 棵具對應資產，47 棵完全未覆蓋）。
5. **健保批次**：`topic_key LIKE 'nhi-%'` 共 314 筆，第一幕藍圖 **100% (314/314)** 均為 `pathology_mechanism`。
6. **寫死根因**：
   - `scripts/generate_nhi200_visual_batch.py` 第 291 行寫死 `"blueprint": "pathology_mechanism"`。
   - `scripts/generate_nhi400_visual_batch.py` 第 268 行與第 133 行同為寫死。

---

### 三、波次與依賴核定 (Waves & Dependencies)

- **Wave 1 (57-01)**: 唯讀對帳與黃金標準模板產出。無任何外部依賴，全唯讀安全，環境完全支援。
- **Wave 2 (57-02)**: LLM 分類器與健保批次改接。依賴 57-01；已落實 `--blueprint-mode fixed` 預設回退機制與兩支腳本雙重驗收。
- **Wave 3 (57-03)**: 前端 Web Speech 旁白字幕規格、字數時長演算法、理解題與 A/B 設計文件。依賴 57-02；已移除後端音訊依賴。
- **Wave 4 (57-04)**: Remotion 渲染層評估報告。純文件產出，依賴 57-03。

---

### 四、審查結論

**審查結論：PASS**  
本階段計畫 57-01 至 57-04 邏輯完備、驗收條件嚴謹且完全具備實測可驗證性，已可正式進入執行階段。

---

### 五、複核紀錄 (Historical Review Records)

#### 2026-11-27 13:17 初版審查紀錄（結論：FAIL）
- 列出阻斷項：
  - B1: `VALID_SCENE1_BLUEPRINTS` 引用路徑指向 `blueprints.py` 導致 ImportError。
  - B2: `generate_nhi400_visual_batch.py` 未納入 T2 驗收。
  - B3: 本地後端無 TTS 庫無法產出實體音檔。
- 列出討論項：
  - D1: 證據子字串比對需標點空白正規化容錯。
  - D2: 50 棵樹建議分層抽樣覆蓋無動畫樹。
  - D3: 醫師標註瓶頸與 fixed 模式解耦。
  - D4: 理解題選項長度規範。
- 處置：交由 Coordinator Claude 完成修訂回寫。
