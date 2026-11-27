# Phase 57: 動畫藍圖分類、黃金標準與旁白 A/B 測試 執行總結

**執行日期**：2026-11-27  
**執行狀態**：`BLOCKED`（阻斷原因：`BLOCKED-AWAITING-LABELS` 待醫師完成黃金集標註）  
**執行角色**：agy (Executor)  
**協調者**：Claude (`wB:p1`)

---

## 1. 階段目標與執行概要

Phase 57 旨在為緻妍診所之衛教動畫系統建立客觀分類與評估體系：
1. **57-01 (Wave 1: 對帳與現況基線)**：盤點 399 筆動畫資產與 92 棵臨床推理樹之對應關係，建立 50 筆分層抽樣之黃金標準集模板與基線。
2. **57-02 (Wave 2: 分類器與批次改接)**：實作 Scene 1 藍圖分類器，將健保批次生成腳本之寫死藍圖改為旗標控制（`fixed` vs `classifier`），並預備黃金集準確率評估。
3. **57-03 (Wave 3: 旁白評估與 A/B 設計)**：待 57-02 解除阻斷後推進。
4. **57-04 (Wave 4: 整合驗收)**：待後續推進。

---

## 2. 完成項目與驗收紀錄

### Plan 57-01（對應對帳、黃金標準集模板、現況基線）- `DONE`
- **對帳報告 (`57-01-MAPPING.md`)**：
  - 正式 `clinic.db`（唯讀模式連線）實測確認：
    - `visual_assets` 總筆數：**399 筆**（健保批次 314 筆，第一幕皆為 `pathology_mechanism`）。
    - 臨床推理樹 `clinical_reasoning_trees`：**92 棵**。
    - 透過 `metadata.tree_id` 成功精確對應：**72 棵**（且與 `doc_id` 100% 一致）。
    - 尚缺動畫之推理樹：**47 棵**（已造冊列出補全優先級）。
- **黃金標準集模板 (`golden/golden_set_template.csv`)**：
  - 分層抽樣 50 棵樹（25 棵有動畫資產、25 棵無動畫資產），涵蓋一般、體雕、微整、眼整、鼻整、隆乳等全部主要臨床類別。
- **基線指標 (`golden/baseline_metrics.json`)**：
  - 現況第一幕單一藍圖依賴率高達 **100%** (`pathology_mechanism`)。
  - 狀態標註為 `awaiting_physician_labels`。

### Plan 57-02（分類器模組與批次改接）- `BLOCKED-AWAITING-LABELS`
- **分類器實作 (`src/visual/blueprint_classifier.py`)**：
  - 整合 `VALID_SCENE1_BLUEPRINTS`（來自 `src.visual.autodraft_ir.py`）與 `other`。
  - 支援 D1 正規化比對（忽略空白與全半形標點符號差異）。
  - 單元測試 `tests/test_blueprint_classifier.py` **7 passed**。
- **批次腳本改接 (`generate_nhi200_visual_batch.py`, `generate_nhi400_visual_batch.py`)**：
  - 兩支腳本均新增 `--blueprint-mode {fixed,classifier}` 參數，預設保留 `fixed`。
  - 解除所有寫死之 `pathology_mechanism`（涵蓋 nhi200 L291/L473 與 nhi400 L133/L204/L214/L268）。
  - 當分類器輸出 `needs_review: true` 時，批次發布自動跳過入庫。
  - 快照與改接行為整合測試 `tests/test_nhi_batch_classifier_mode.py` **5 passed**。
- **準確率評估 (T3)**：
  - 依據 **D-03** 與硬性限制 (b)，在醫師完成標註前不得推算準確率，暫停並產出 `57-02-EVAL.md`。

---

## 3. 測試與驗證匯總

- **單元與改接整合測試**：
  - 執行指令：`clinicbrain/.venv/bin/pytest tests/test_blueprint_classifier.py tests/test_nhi_batch_classifier_mode.py`
  - 執行結果：**12 passed in 1.61s**（退出碼 0）。
- **核心 Visual 規範回歸測試**：
  - 執行指令：`clinicbrain/.venv/bin/pytest tests/test_blueprint_classifier.py tests/test_nhi_batch_classifier_mode.py tests/test_visual_ir.py tests/test_visual_blueprints.py`
  - 執行結果：**50 passed in 1.80s**（退出碼 0）。

---

## 4. 交付檔案清單

```
clinicbrain/
├── src/visual/
│   └── blueprint_classifier.py               # Scene 1 動畫藍圖 LLM 分類器
├── scripts/
│   ├── build_blueprint_golden_baseline.py    # 黃金集抽樣與基線建置腳本
│   ├── generate_nhi200_visual_batch.py       # 1-200 批次改接腳本
│   └── generate_nhi400_visual_batch.py       # 201-400 批次改接腳本
├── tests/
│   ├── test_blueprint_classifier.py          # 分類器單元測試
│   └── test_nhi_batch_classifier_mode.py     # 批次改接快照與整合測試
└── .planning/phases/57-visual-blueprint-classification-narration-ab/
    ├── 57-01-MAPPING.md                      # 399 筆資產完整對帳表
    ├── 57-01-SUMMARY.md                      # 57-01 執行總結 (DONE)
    ├── 57-02-EVAL.md                         # 57-02 評估報告 (Awaiting Labels)
    ├── 57-02-SUMMARY.md                      # 57-02 執行總結 (BLOCKED)
    ├── 57-SUMMARY.md                         # Phase 57 階段執行總結 (本文件)
    └── golden/
        ├── golden_set_template.csv           # 50 筆分層抽樣黃金集模板 (待醫師標註)
        └── baseline_metrics.json             # 現況基線指標 JSON
```

---

## 5. 阻斷與後續交接事項

1. **阻斷代碼**：`BLOCKED-AWAITING-LABELS`
2. **所需動作**：請專業臨床醫師檢視並填寫 `clinicbrain/.planning/phases/57-visual-blueprint-classification-narration-ab/golden/golden_set_template.csv` 中的 `physician_blueprint` 與 `evidence_span`。
3. **解除阻斷後路徑**：
   - 執行真實黃金集準確率評估，若 $\ge 85\%$ 則核定通過。
   - 推進 57-03（旁白 Web Speech + 字數時長離線評估與 A/B 測試文件）與 57-04（整體驗收）。
