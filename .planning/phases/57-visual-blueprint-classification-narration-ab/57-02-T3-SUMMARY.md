# Phase 57-02 Task T3: 黃金標準集準確率評估 執行總結

**執行日期**：2026-11-27  
**執行狀態**：`DONE`（評估完成，準確率未達預設 85% 門檻，依約維持 `fixed` 模式）  
**執行角色**：agy (Executor)  
**協調者**：Claude (`wB:p1`)  
**依據計畫**：`57-02-T3-PLAN.md`

---

## 1. 任務執行與驗收條件逐項核對 (Acceptance Checklist)

| 驗收條件 | 驗收狀態 | 實際檢驗結果與證據 |
| :--- | :---: | :--- |
| **1. 單元測試通過** (`pytest tests/test_eval_blueprint_classifier.py`) | **PASS** | 8 項測試全數 PASS（退出碼 0，耗時 4.05s），涵蓋全對、全錯、非 ok 狀態排除、分母為零 N/A、未標註 (code 1)、欄位缺失 (code 2)、sha256 唯讀防禦。 |
| **2. 腳本獨立執行並產出 EVAL** | **PASS** | 執行 `python scripts/eval_blueprint_classifier.py --out golden/57-02-EVAL.md` 退出碼 0，成功產出完整 Markdown 報表。 |
| **3. 數字重算與真實性** | **PASS** | 所有分子、分母、百分比、召回率與混淆矩陣皆由 Python 純函式動態自 xlsx 兩表計算產生，無人工手寫造假。 |
| **4. xlsx 唯讀約束（sha256 一致性）** | **PASS** | 評估前與評估後 `physician_labeling_sheet.xlsx` 之 SHA-256 哈希值完全一致（測試 `test_xlsx_immutability` 自動檢驗通過）。 |
| **5. 資料庫零寫入** | **PASS** | 全程未連線寫入 `clinic.db`。 |
| **6. Git 乾淨約束** | **PASS** | 未執行任何 `git commit` 或 `git push`。 |

---

## 2. 評估指標核心結果摘要

以 `physician_labeling_sheet.xlsx` 之「標註」工作表（50 筆經專業醫師標註且通過 `--require-complete`）為權威 Ground Truth，比對「AI建議（僅供參考）」之分類器預測：

| 評估維度 | 分子 / 分母 | 實測值 | 預設基準 (85%) | 說明 |
| :--- | :---: | :---: | :---: | :--- |
| **A. 原始準確率 (Raw Accuracy)** | 26 / 50 | **52.0%** | ❌ 未達標 | 全量 50 筆直接比對（含 `needs_review` 與 `invalid_evidence`）。 |
| **B. 自動接受準確率 (Auto-Accept Accuracy)** | 22 / 38 | **57.9%** | ❌ 未達標 | 僅採計 `ai_status == 'ok'` 可直接入庫的 38 筆樣本。 |
| **自動接受率 (Auto-Accept Rate)** | 38 / 50 | **76.0%** | 監控指標 | 38 筆通過信心門檻與證據子字串檢驗，12 筆進入人工審核。 |
| **Other 選項比例** | 4 (醫師) vs 0 (AI) | 8.0% vs 0.0% | 監控指標 | 醫師在 4 筆基層常見疾病（感冒、咽喉炎、過敏性鼻炎、胃炎）選擇 `other`，模型皆預測為 `pathology_mechanism`。 |
| **證據無效 (`invalid_evidence`)** | 10 / 50 | **20.0%** | 需人工複核 | 共 10 筆項目的模型抽取證據非原文連續子字串，自動被守門攔截。 |
| **需人工審核 (`needs_review`)** | 2 / 50 | **4.0%** | 需人工複核 | 包含低信心度或複雜病況（如第二型糖尿病、疤痕皮下切割）。 |
| **錨定效應一致率** | 26 / 50 | **52.0%** | 描述性統計 | 醫師與 AI 建議一致 26 筆 (52%)，不一致 24 筆 (48%)。 |

---

## 3. 關鍵發現與誤差分析

1. **粗粒度 vs 細粒度藍圖理解差異**：
   - 醫師在多項處置（未感染粉瘤、甲溝炎、頂漿腺狐臭、脂肪瘤抽吸、等離子贅疣）傾向選擇廣義的 `surgical_action`（共 15 筆，召回率 20.0%）。
   - 分類器則依照臨床特徵細分為專屬藍圖（如 `subdermal_curettage`、`nail_matrix`、`skin_energy`）。
2. **通訊與流程藍圖 (`process_diagram`) 認知**：
   - 醫師標註 7 筆 `process_diagram`（電波、飛梭、音波、光纖拉提、腹直肌修復、海菲秀等），分類器大多預測為對應之器械/能量藍圖（`skin_energy` 3 筆、`laser_action` 2 筆、`surgical_action` 1 筆、`curettage` 1 筆），導致該類別召回率為 0.0%。
3. **決策閘門落實**：
   - 由於原始準確率（52.0%）與自動接受準確率（57.9%）均未達預設之 85% 門檻，且該門檻尚未經操作者確認：
   - **嚴格維持現狀：健保批次生成腳本（nhi200/nhi400）不自動切換為 `--blueprint-mode classifier`，持續保留預設之 `--blueprint-mode fixed`**。

---

## 4. 交付檔案清單

| 檔案路徑 | 類型 | 說明 |
| :--- | :--- | :--- |
| `scripts/eval_blueprint_classifier.py` | 腳本 | 純函式核心評估與 Markdown 產出 CLI 工具 |
| `tests/test_eval_blueprint_classifier.py` | 測試 | 涵蓋全對、全錯、狀態排除、N/A 分母、exit code 0/1/2 與 sha256 唯讀測試 |
| `.planning/phases/57-visual-blueprint-classification-narration-ab/golden/57-02-EVAL.md` | 評估報告 | 完整 50 筆評估報告（含召回率表與 13x13 混淆矩陣） |
| `.planning/phases/57-visual-blueprint-classification-narration-ab/57-02-T3-SUMMARY.md` | 執行總結 | 本文件 |

---

## 5. 後續建議與交接

1. **57-02 計畫結案**：T1（分類器實作）、T2（批次改接）、T3（黃金集準確率評估）已全數完成。
2. **推進 Wave 3 (57-03)**：依原定里程碑推進「旁白 Web Speech API + 字數時長估算之離線評估與 A/B 方案設計」，無需等待分類器達到 85% 即可平行展開前端旁白評估。
