# Phase 57-02 Task T5: 藍圖查表註冊表與複合放行閘門 執行總結

**執行日期**：2026-11-27  
**執行狀態**：`DONE`  
**執行角色**：agy (Executor)  
**協調者**：Claude (`wB:p1`)  
**依據計畫**：`57-02-T5-PLAN.md`、`57-02-DECISIONS.md`（A1/B2/C1）與 `golden/PHYSICIAN-LABELING-GUIDE.md`

---

## 1. 任務執行與驗收條件逐項核對 (Acceptance Checklist)

| 驗收條件 | 狀態 | 檢驗結果與證據 |
| :--- | :---: | :--- |
| **1. 單元與回歸測試全數通過** | **PASS** | `pytest tests/test_blueprint_registry.py tests/test_blueprint_classifier.py tests/test_nhi_batch_classifier_mode.py tests/test_nhi_fixed_snapshot.py`<br>**24 passed in 1.78s**（退出碼 0）。 |
| **2. 查表規則庫 SHA-256 雜湊凍結** | **PASS** | `src/visual/blueprint_registry.py` 之 SHA-256 雜湊值已凍結於測試中，實測與常數完全吻合：<br>`f5e1b322572e47b55bb821c2f2b21c9172f95c6a41606631041ab69fa6576d89`。 |
| **3. xlsx 唯讀約束** | **PASS** | `golden/physician_labeling_sheet.xlsx` 執行前後 SHA-256 完全一致（`82883bf440bd9895ce85cdc801471fb7d5f58aeb84186766275984fdc521c84e`），未遭修改。 |
| **4. 資料庫零寫入** | **PASS** | 全程未對 `clinic.db` 進行任何連線或寫入操作。 |
| **5. Git 乾淨約束** | **PASS** | 未執行任何 `git commit` 或 `git push`。 |
| **6. 泛化能力誠實聲明** | **PASS** | **[重大聲明]**：本次完成查表規則與放行閘門實作後，現有 50 筆黃金標準集已正式轉為設計與除錯用途，**嚴禁再作為分類器「泛化能力（Generalization Ability）」之無偏評估依據**。日後若需驗收泛化能力，必須依賴全新未曝光之盲測樣本。 |

---

## 2. 核心實作架構

### A. 確定性查表 (`TOPIC_BLUEPRINT_REGISTRY`)
嚴格落實 `57-02-DECISIONS.md` 之 A1、B2、C1 決策，建立具備專科優先權重之有序查表規則：
- **專屬微創處置 (A1 決定)**：
  - 粉瘤／表皮樣囊腫 $\rightarrow$ `cyst_excision`
  - 嵌甲／甲溝炎 $\rightarrow$ `nail_matrix`
  - 狐臭／頂漿腺／螺旋刀／脂肪瘤 $\rightarrow$ `subdermal_curettage`
  - 深層拉皮／SMAS 筋膜拉皮 $\rightarrow$ `deep_plane_facelift`
  - 雙下巴闊頸肌馬甲式 $\rightarrow$ `corset_platysmaplasty`
  - 正顎／削骨／下巴截骨 $\rightarrow$ `surgical_action`
- **能量、光學與微整 (C1 決定)**：
  - 微針電波／鳳凰電波／音波拉提 $\rightarrow$ `skin_energy`
  - 皮秒／飛梭／海神雷射除毛／光纖 $\rightarrow$ `laser_action`
  - 肉毒桿菌 $\rightarrow$ `neuromuscular`
  - 玻尿酸／洢蓮絲／填充劑 $\rightarrow$ `dermal_support`
  - 海菲秀／水渦漩／水光針 $\rightarrow$ `process_diagram`
- **常見重大與輕症疾病 (B2 決定)**：
  - 感冒／上呼吸道感染／咽炎／過敏性鼻炎／胃炎／支氣管炎／高血壓／糖尿病／痛風等 29 項常見疾病 $\rightarrow$ `pathology_mechanism`

### B. 特徵詞錨定檢驗 (`verify_evidence_keywords`)
- 定義 12 個藍圖之核心臨床特徵詞清單（如雷射需含「光束/脈衝/奈米」，能量需含「電波/音波/熱能/探頭」）。
- 即使模型輸出 `status == "ok"`，若抽取之證據片段未命中該藍圖特徵詞，一律判定無效，阻斷自動放行。

### C. 複合放行閘門 (`is_auto_acceptable`)
- 僅在「命中白名單查表」或「LLM 輸出 `ok` 且通過特徵詞錨定」時才允許放行。
- 依決策明確排除實測無效之 0.85 信心門檻。

### D. 過渡期零風險守門 (`filter_for_batch_publishing`)
- 實作過渡期硬性隔離：在 `--blueprint-mode classifier` 下，所有產出 IR 一律強制附加 `needs_review: true` 並阻斷自動入庫發布，維持實體入庫 0% 瑕疵風險。

---

## 3. 交付檔案清單

1. `src/visual/blueprint_registry.py`：查表註冊表、特徵詞錨定與放行閘門模組。
2. `tests/test_blueprint_registry.py`：完整 7 項單元測試（包含規則覆蓋、特徵錨定、放行閘門與 SHA-256 凍結比對）。
3. `.planning/phases/57-visual-blueprint-classification-narration-ab/57-02-T5-SUMMARY.md`：本結案總結文件。

---

## 4. 下一步交接 (57-02-T6)

- 57-02 T5 技術實作已全部就緒並完成凍結。
- 請協調者 Claude 推進 **57-02-T6**：產出修訂後的整體收斂總結報告，並維持批次預設 `--blueprint-mode fixed`。
