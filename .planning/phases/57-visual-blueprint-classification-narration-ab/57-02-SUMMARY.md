# Phase 57 Plan 02: 第一幕動畫藍圖分類器與健保批次改接 執行總結

**執行日期**：2026-11-27  
**執行狀態**：`BLOCKED-AWAITING-LABELS`（T1、T2 完成，T3 依硬性限制暫停等待醫師標註）  
**執行角色**：agy (Executor)

---

## 1. 任務執行與驗收對帳 (Tasks & Acceptance)

### Task T1: 分類器模組 (`src/visual/blueprint_classifier.py`)
- **實作內容**：
  - 引用 `src.visual.autodraft_ir.VALID_SCENE1_BLUEPRINTS`，加上 `other` 構成合法 Scene 1 藍圖列舉集合。
  - 實作 `classify_scene1_blueprint(source_text, llm_call_fn, confidence_threshold=0.6, title="")`。
  - 實作結構化 JSON 解析與容錯提取（支援 Markdown 區塊與 `<think>` 去除）。
  - 實作 D1 比對容錯 `normalize_text_for_comparison`，去除空白與統一全半形標點符號進行子字串驗證。
  - 當列舉值非法、證據非子字串、信心度 $<0.6$ 或標註為 `other` 時，一律自動設定 `needs_review: true`。
- **驗收準則驗證**：
  - 單元測試以假 `llm_call_fn` 完整覆蓋：合法分類、Enum 外值、證據不在原文、低信心、`other` 選項、全半形標點容錯、Markdown 格式包裝。
  - 驗證指令：`clinicbrain/.venv/bin/pytest tests/test_blueprint_classifier.py`
  - 驗證結果：**7 passed in 1.39s**（退出碼 0）。

---

### Task T2: 健保批次改接與旗標控制 (`generate_nhi200_visual_batch.py`, `generate_nhi400_visual_batch.py`)
- **實作內容**：
  - 在兩支腳本中新增 `--blueprint-mode {fixed,classifier}` 參數，預設保留 `fixed`。
  - `generate_nhi200_visual_batch.py`：
    - L263-267：Prompt 模板前將寫死之 `pathology_mechanism` 改為 `s1_bp` 動態決定。
    - L299-301：第一幕 blueprint 改為 `{s1_bp}`，title 改為 `{s1_title}`。
    - L472-500：自癒邏輯相容非 `pathology_mechanism` 藍圖。
    - L581-591：在 `generate_single_nhi_ir` 加入分類器調用與 `needs_review` 標記。
    - L747-750：批次發布前檢查 `ir.get("needs_review")`，若為 True 則跳過自動發布入庫。
  - `generate_nhi400_visual_batch.py`：
    - L90、L133、L210-217：`post_process_self_heal` 支援 `blueprint_mode` 與非 fixed 藍圖 fallback。
    - L258-261：非固定三幕時，自動調用 `validate_params(bp, params)` 與 `default_params(bp)` 修正參數。
    - L279-284、L304：`mock_generate_ir` 動態指派 `s1_bp` 與其合法 default params。
    - L380-393：`generate_single_item_with_self_healing` 串接分類器，偵測需審核項目。
    - L501-507：`run_batch` 加入 `blueprint_mode` 傳遞與入庫守門。
- **寫死位置判讀與驗證**：
  - `nhi200` L291 / L473：在 classifier 模式下正確依分類器輸出賦值。
  - `nhi400` L133 / L204 / L214 / L268：在 classifier 模式下均不強制寫死 `pathology_mechanism`。
- **快照與整合測試**：
  - 實作 `tests/test_nhi_batch_classifier_mode.py` 驗證：
    - `fixed` 模式下第一幕 100% 維持 `pathology_mechanism`。
    - `classifier` 模式下正確改用分類器輸出。
    - `needs_review` 正確被標記且阻止入庫。
  - 驗證指令：`clinicbrain/.venv/bin/pytest tests/test_blueprint_classifier.py tests/test_nhi_batch_classifier_mode.py`
  - 驗證結果：**12 passed in 1.61s**（退出碼 0）。

---

### Task T3: 黃金集準確率評估（需醫師標註）
- **核查結果**：
  - 檢視 `golden/golden_set_template.csv`，確認 50 筆分層抽樣項目之 `physician_blueprint` 與 `evidence_span` 目前全為空，專業醫師尚未進行標註。
- **阻斷處置**：
  - 依據核定決策 **D-03** 與 Phase 57 執行硬性限制 (b)：
    > *「57-02 T3 需醫師標註，醫師標註前必須暫停並回報 BLOCKED-AWAITING-LABELS，不得推算準確率。」*
  - 產出 `57-02-EVAL.md`，指標標記為 `awaiting_physician_labels`。
  - 本任務依規範進入暫停狀態，回報 `BLOCKED-AWAITING-LABELS`。

---

## 2. 產出檔案清單

| 檔案路徑 | 類型 | 說明 |
| :--- | :--- | :--- |
| `src/visual/blueprint_classifier.py` | 原始碼 | Scene 1 動畫藍圖 LLM 分類器（含 D1 正規化比對與 Enum 防禦） |
| `scripts/generate_nhi200_visual_batch.py` | 腳本修改 | 健保 1-200 批次生成改接（支援 `--blueprint-mode`） |
| `scripts/generate_nhi400_visual_batch.py` | 腳本修改 | 健保 201-400 批次生成改接（支援 `--blueprint-mode`） |
| `tests/test_blueprint_classifier.py` | 單元測試 | 分類器 7 項單元測試（全數 PASS） |
| `tests/test_nhi_batch_classifier_mode.py` | 整合測試 | 批次腳本 fixed/classifier 模式快照與行為測試（5 項全數 PASS） |
| `.planning/phases/57-visual-blueprint-classification-narration-ab/57-02-EVAL.md` | 評估報告 | 標註待處理狀態與準確率評估標準 |
| `.planning/phases/57-visual-blueprint-classification-narration-ab/57-02-SUMMARY.md` | 執行總結 | 本文件 |

---

## 3. 合規與安全自檢

- [x] **未寫入正式 clinic.db**：全程使用唯讀模式，無任何資料庫異動。
- [x] **未擅自推算偽造準確率**：嚴格遵守硬性限制 (b)，停在 `BLOCKED-AWAITING-LABELS`。
- [x] **無 Git Commit / Push**：保持本地乾淨工作區。
