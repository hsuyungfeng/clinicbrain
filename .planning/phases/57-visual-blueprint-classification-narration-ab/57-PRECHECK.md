# Phase 57 實測預檢報告 (57-PRECHECK.md)

**執行者**：agy（Plan Checker & Executor）  
**預檢時間**：2026-11-27 13:16（初始）、2026-11-27 13:18（複核）  
**目標計畫**：`.planning/phases/57-visual-blueprint-classification-narration-ab/`（57-01 至 57-04）  
**預檢結論**：**GO**（B-PRE-1、B-PRE-2 阻斷項已於計畫修訂中完全解除，環境可直接進入執行）

---

### 一、數據與寫死位置獨立驗證（clinic.db 唯讀）

本代理以 SQLite URI 唯讀模式（`file:/home/hsuyungfeng/DevSoft/clinicbrain/clinic.db?mode=ro`）實際執行查詢，各項實測指標如下：

| 檢驗項目 | 計畫／CONTEXT 預期值 | 實測值 | 吻合狀態 | 說明與取證細節 |
| :--- | :---: | :---: | :---: | :--- |
| **視覺資產總數** | 399 | **399** | **PASS** | `SELECT COUNT(*) FROM visual_assets` |
| **推理樹總數** | 92 | **92** | **PASS** | 實體資料表為 `page_index_trees`（非 `reasoning_trees`） |
| **tree_id 精確對應** | 72 | **72** | **PASS** | `metadata` 含 `tree_id` 欄位且存在於 `page_index_trees` |
| **doc_id 一致性** | 72/72 (100%) | **72/72** | **PASS** | 72 筆之 `metadata.doc_id` 與對應樹之 `doc_id` 完全一致 |
| **缺動畫推理樹** | 47 | **47** | **PASS** | 92 棵樹中有 45 棵具對應資產（部分樹多筆），未覆蓋樹為 47 棵 |
| **健保批次總數** | 314 | **314** | **PASS** | `SELECT COUNT(*) FROM visual_assets WHERE topic_key LIKE 'nhi-%'` |
| **健保批次第一幕藍圖** | 全部 pathology_mechanism | **314/314** | **PASS** | 314 筆的第一幕藍圖 100% 為 `pathology_mechanism` |
| **非健保來源分布** | 72 tree, 8 distill, 4 icd, 1 manual | **85 筆** | **PASS** | 72 tree + 8 batch_distill + 4 icd10 + 1 none/manual = 85 筆（總計 399） |
| **全體第一幕藍圖分布** | pathology_mechanism 320 筆 | **320 筆** | **PASS** | 314 (nhi) + 1 (tree) + 5 (其他) = 320 筆；其餘 79 筆分布於 11 種藍圖 |
| **審核通過率** | 398 通過、1 拒絕 | **398 / 1** | **PASS** | approved: 398, rejected: 1（通過率 99.7%） |

#### 生成器寫死位置驗證：
- **`scripts/generate_nhi200_visual_batch.py`**：
  - **第 291 行**：`"blueprint": "pathology_mechanism"`，寫死於第一幕 Prompt 結構內。
  - **第 473 行**：深層參數校正之 hardcoded 判斷。
- **`scripts/generate_nhi400_visual_batch.py`**：
  - **第 268 行**：`"blueprint": "pathology_mechanism"`。
  - **第 133 行**：fallback 預設藍圖清單。
  - **第 204 行**：`bp = "pathology_mechanism" if idx == 0 else ...`。
  - **第 214 行**：次專科參數注入判斷。

---

### 二、環境與相依性預檢

#### 1. `VALID_SCENE1_BLUEPRINTS` 來源檢查
- **實測狀況**：
  - `VALID_SCENE1_BLUEPRINTS` 真實定義於 **`src/visual/autodraft_ir.py:17-30`**，為包含 12 種藍圖的 tuple。
- **複核狀態**：57-02-PLAN.md 已更新引用路徑為 `src/visual/autodraft_ir.py`，不再自 `blueprints.py` 錯誤匯入。

#### 2. 單元測試於 `clinicbrain/.venv` 執行能力
- **實測指令**：
  ```bash
  clinicbrain/.venv/bin/pytest clinicbrain/tests/test_visual_golden_49.py clinicbrain/tests/test_visual_autodraft.py -k "test_infer_scene1_blueprint_all_topics"
  ```
- **實測結果**：8 passed in 1.40s，測試環境就緒。

#### 3. 本地 TTS（語音旁白合成）可用性檢查
- **實測狀況**：
  - Python 虛擬環境與系統均無本地 TTS 引擎（`edge-tts`, `piper`, `espeak` 皆無）。
  - 前端既有架構（`demo/visual/full.html`）係採用 Web Speech API。
- **複核狀態**：57-03-PLAN.md 已正式定調為「純字數時長演算法 + 瀏覽器 Web Speech API 規格」，明定不產出任何 .mp3/.wav 實體音檔，徹底解除後端環境無音訊庫之障礙。

#### 4. `clinic.db` 唯讀連線模式檢查
- 採用標準 URI 語法：`file:{db_path}?mode=ro` 搭配 `PRAGMA query_only = ON`。

---

### 三、複核紀錄 (Re-check History)

#### 2026-11-27 13:18 複核（結論：GO）
針對初始預檢列出的兩項阻斷項目逐一複核：
1. **[B-PRE-1] 常數模組引用問題**：已更正為 `src/visual/autodraft_ir.py`。**已解除 (PASS)**。
2. **[B-PRE-2] 本地 TTS 音訊依賴**：57-03 已修改架構為 Web Speech API 規格與純字數時長推算，不需實體合成音檔。**已解除 (PASS)**。

**預檢結論轉為：GO**。所有任務均具備可測性與明確驗收路徑。
