> **【標註來源說明（操作者）】** 本報告以醫師確認後的盲測標註計算：
> 四筆曾被自動流程改寫的藍圖已還原為醫師原始判斷；B15、B16 的證據由醫師重新填寫；BBL 與 Rejuran 的證據經醫師確認為本人判斷。
> 本報告數字取代先前被標記為無效的版本。

# 57-02 T6 盲測集第一幕藍圖分類獨立評估報告

> **【重要評估聲明】**
> 1. 本次評估為在**獨立盲測樣本（30 筆）**上的首次無介入測試，盲測表單本身完全未含 AI 欄位與 AI 建議。
> 2. 評估門檻固定為 `85.0%`，**本門檻保持凍結，僅作為客觀參考指標，不作為上線放行依據**。
> 3. 盲測表單的 `title` 欄位以 `doc_id` 傳入，部分縮寫與特徵對查表命中與 LLM 理解存在客觀限制。

## 一、核心指標總覽

| 指標項目 | 數值 | 分子 / 分母 | 評估說明 |
| :--- | :---: | :---: | :--- |
| **A. LLM-only 原始準確率** | **83.3%** | 25 / 30 | 單純依賴本機 LLM 提示詞判定之原始全量準確率 |
| **B. 完整系統原始準確率** | **83.3%** | 25 / 30 | 結合 TOPIC 查表（Registry）與 LLM 之全量預測準確率 |
| **C. 完整系統自動接受準確率** | **93.3%** | 14 / 15 | **通過複合放行閘門（自動接受）子集之精準度** |
| 完整系統自動接受率 | 50.0% | 15 / 30 | 通過放行閘門進入夜間自動發布佇列之涵蓋比例 |
| 查表命中覆蓋率與準確率 | 10.0% (命中) / 100.0% (準確) | 3 / 3 | 命中白名單查表註冊表之比率與正確度 |
| 無效證據片段 (Invalid Evidence) | 6 筆 (20.0%) | 6 / 30 | LLM 提取之證據非原文子字串之攔截次數 |
| `other` 比例 (醫師 / LLM / 系統) | 3.3% / 10.0% / 10.0% | - | 各階段判定無合適藍圖之保守比例 |
| **85% 凍結門檻判定** | **❌ 未達標** | - | 門檻 `85.0%`（凍結不作放行依據） |

## 二、各藍圖類別精確率與召回率（完整系統）

| 藍圖代碼 (`blueprint`) | 樣本數 (Support) | TP | FP | FN | 精確率 (Precision) | 召回率 (Recall) | F1-Score |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `process_diagram` | 6 | 4 | 1 | 2 | 80.0% | 66.7% | 0.727 |
| `skin_energy` | 3 | 2 | 1 | 1 | 66.7% | 66.7% | 0.667 |
| `laser_action` | 3 | 2 | 0 | 1 | 100.0% | 66.7% | 0.800 |
| `neuromuscular` | 0 | 0 | 0 | 0 | N/A | N/A | N/A |
| `dermal_support` | 0 | 0 | 1 | 0 | 0.0% | N/A | N/A |
| `cyst_excision` | 0 | 0 | 0 | 0 | N/A | N/A | N/A |
| `nail_matrix` | 0 | 0 | 0 | 0 | N/A | N/A | N/A |
| `subdermal_curettage` | 0 | 0 | 0 | 0 | N/A | N/A | N/A |
| `deep_plane_facelift` | 1 | 1 | 0 | 0 | 100.0% | 100.0% | 1.000 |
| `corset_platysmaplasty` | 1 | 1 | 0 | 0 | 100.0% | 100.0% | 1.000 |
| `surgical_action` | 2 | 2 | 0 | 0 | 100.0% | 100.0% | 1.000 |
| `pathology_mechanism` | 13 | 12 | 0 | 1 | 100.0% | 92.3% | 0.960 |
| `other` | 1 | 1 | 2 | 0 | 33.3% | 100.0% | 0.500 |

## 三、完整系統混淆矩陣 (Confusion Matrix)

| 真實 \ 預測 | `process_` | `skin_ene` | `laser_ac` | `dermal_s` | `deep_pla` | `corset_p` | `surgical` | `patholog` | `other` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `process_diag` | 4 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| `skin_energy` | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| `laser_action` | 0 | 1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| `dermal_suppo` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `deep_plane_f` | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| `corset_platy` | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| `surgical_act` | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| `pathology_me` | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 12 | 0 |
| `other` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |

## 四、30 筆盲測樣本逐列對照明細

| tree_id | doc_id | 醫師標註 (標準答案) | LLM 預測 | 完整系統預測 | 來源 (Source) | 放行 (Accepted) | 結果 |
| :---: | :--- | :--- | :--- | :--- | :---: | :---: | :---: |
| `B01` | `3503264627-asce-rose-exosome-regeneration` | `process_diagram` | `process_diagram` | `process_diagram` | `llm` | ❌ 否 | ✅ |
| `B02` | `3503264627-bbl-broadband-light` | `laser_action` | `skin_energy` | `skin_energy` | `llm` | ❌ 否 | ❌ |
| `B03` | `3503264627-blepharoplasty-eye-contouring` | `surgical_action` | `surgical_action` | `surgical_action` | `llm` | ✅ 是 | ✅ |
| `B04` | `3503264627-bulbous-nose-rhinoplasty` | `surgical_action` | `surgical_action` | `surgical_action` | `llm` | ❌ 否 | ✅ |
| `B05` | `3503264627-full-deep-plane-facelift` | `deep_plane_facelift` | `deep_plane_facelift` | `deep_plane_facelift` | `llm` | ✅ 是 | ✅ |
| `B06` | `3503264627-nd-yag-laser-toning` | `laser_action` | `laser_action` | `laser_action` | `llm` | ✅ 是 | ✅ |
| `B07` | `3503264627-overfilled-face-syndrome-correction` | `other` | `other` | `other` | `llm` | ❌ 否 | ✅ |
| `B08` | `3503264627-picosecond-laser-rejuvenation` | `laser_action` | `laser_action` | `laser_action` | `registry` | ✅ 是 | ✅ |
| `B09` | `3503264627-rejuran-pdrn-skin-healer` | `process_diagram` | `dermal_support` | `dermal_support` | `llm` | ✅ 是 | ❌ |
| `B10` | `3503264627-swan-neck-cervicoplasty` | `corset_platysmaplasty` | `corset_platysmaplasty` | `corset_platysmaplasty` | `registry` | ✅ 是 | ✅ |
| `B11` | `3503264627-ultherapy-focused-ultrasound` | `skin_energy` | `skin_energy` | `skin_energy` | `registry` | ✅ 是 | ✅ |
| `B12` | `general-hao-hyperbaric-oxygen` | `process_diagram` | `process_diagram` | `process_diagram` | `llm` | ❌ 否 | ✅ |
| `B13` | `general-hao-zimmer-inductive` | `skin_energy` | `skin_energy` | `skin_energy` | `llm` | ❌ 否 | ✅ |
| `B14` | `hao-hyperbaric-oxygen` | `process_diagram` | `process_diagram` | `process_diagram` | `llm` | ❌ 否 | ✅ |
| `B15` | `hao-prolotherapy-prp` | `process_diagram` | `other` | `other` | `llm` | ❌ 否 | ❌ |
| `B16` | `hao-zimmer-inductive` | `skin_energy` | `other` | `other` | `llm` | ❌ 否 | ❌ |
| `B17` | `icd-k279-peptic-ulcer` | `pathology_mechanism` | `pathology_mechanism` | `pathology_mechanism` | `llm` | ❌ 否 | ✅ |
| `B18` | `icd-k589-ibs` | `pathology_mechanism` | `process_diagram` | `process_diagram` | `llm` | ❌ 否 | ❌ |
| `B19` | `icd-k649-hemorrhoids` | `pathology_mechanism` | `pathology_mechanism` | `pathology_mechanism` | `llm` | ✅ 是 | ✅ |
| `B20` | `icd-l0390-cellulitis` | `pathology_mechanism` | `pathology_mechanism` | `pathology_mechanism` | `llm` | ✅ 是 | ✅ |
| `B21` | `icd-l209-atopic-dermatitis` | `pathology_mechanism` | `pathology_mechanism` | `pathology_mechanism` | `llm` | ✅ 是 | ✅ |
| `B22` | `icd-l509-urticaria` | `pathology_mechanism` | `pathology_mechanism` | `pathology_mechanism` | `llm` | ✅ 是 | ✅ |
| `B23` | `icd-l700-acne` | `pathology_mechanism` | `pathology_mechanism` | `pathology_mechanism` | `llm` | ✅ 是 | ✅ |
| `B24` | `icd-m179-knee-osteoarthritis` | `pathology_mechanism` | `pathology_mechanism` | `pathology_mechanism` | `llm` | ❌ 否 | ✅ |
| `B25` | `icd-m5450-low-back-pain` | `pathology_mechanism` | `pathology_mechanism` | `pathology_mechanism` | `llm` | ✅ 是 | ✅ |
| `B26` | `icd-m7500-frozen-shoulder` | `pathology_mechanism` | `pathology_mechanism` | `pathology_mechanism` | `llm` | ✅ 是 | ✅ |
| `B27` | `icd-m810-osteoporosis` | `pathology_mechanism` | `pathology_mechanism` | `pathology_mechanism` | `llm` | ❌ 否 | ✅ |
| `B28` | `icd-n3000-uti` | `pathology_mechanism` | `pathology_mechanism` | `pathology_mechanism` | `llm` | ✅ 是 | ✅ |
| `B29` | `icd-s93409-sprain-strain` | `pathology_mechanism` | `pathology_mechanism` | `pathology_mechanism` | `llm` | ❌ 否 | ✅ |
| `B30` | `site-b0987ae19c-1` | `process_diagram` | `process_diagram` | `process_diagram` | `llm` | ❌ 否 | ✅ |

## 五、盲測結果與黃金集差異分析說明

1. **樣本獨立性**：
   - 本次盲測 30 筆全數為未曾參與提示詞調整與規則制定的全新案例，能真實反映未知新進主題在未介入下的泛化能力。
2. **標題欄位限制 (Title Field Limitation)**：
   - 盲測表單的標題欄位直接填入 `doc_id`（例如 `icd-m179-knee-osteoarthritis`），缺乏完整正體中文標題。
   - 查表註冊表（Registry）設計仰賴常見中文主題詞（例如「膝關節炎」），導致查表覆蓋率受限於 slug 英文命名。
3. **放行閘門守護效果**：
   - 透過 `is_auto_acceptable` 放行閘門與語意錨定檢驗，系統成功將不確定或高風險之預測攔截（未接受），有效保護了自動發布佇列的安全。

