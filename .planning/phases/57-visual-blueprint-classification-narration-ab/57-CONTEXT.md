# Phase 57: 動畫藍圖分類、黃金標準與旁白 A/B 測試

**Status:** Planned（待 agy PLANCHECK／PRECHECK）
**Scope:** `src/visual/`、`scripts/generate_nhi200_visual_batch.py`、`scripts/generate_nhi400_visual_batch.py`、`src/web/`（僅 A/B 曝光）、`tests/`；不改 `clinic.db` 的正式內容（除明確的 dry-run 與經核准的回填）。

## 已實測的現況（2026-11-27，clinic.db 唯讀）
- 動畫資產 399 筆；推理樹 92 棵。
- 資產來源對應（以 `metadata.tree_id` 與 `topic_key` 核對）：
  - 健保批次 `nhi-*`：314 筆，**無**推理樹來源。
  - 推理樹 `tree_id` 可精確對應：72 筆（其中 `doc_id` 一致 72/72）。
  - `batch_distill`：8 筆；`icd10_primary_care_catalog`：4 筆；`manual`：1 筆。
  - 推理樹沒有對應動畫：47 棵（以 tree_id 計）。
- 第一幕蓝图：`pathology_mechanism` 320/399。其中健保批次 **314/314**、推理樹來源僅 1/72。
- **根因**：`scripts/generate_nhi200_visual_batch.py` 的 prompt 模板在第 291 行寫死 `"blueprint": "pathology_mechanism"`；藍圖由 archetype 決定器官與模式，但不決定第一幕藍圖。並非關鍵詞規則漏判。
- 審核：398 通過、1 拒絕。通過率 99.7%，無法證明審核有把關。

## 鎖定決策（操作者 2026-11-27 指示）
- D-01 先做對應對帳與黃金標準，才改分類器；基線數字是後續驗收的唯一依據。
- D-02 分類改為 LLM 從固定清單選藍圖，清單含「其他」；每個選擇必須附原文證據片段，證據不在推理樹原文內即視為無效。
- D-03 黃金標準由醫師標註，至少 50 棵推理樹；標註前不得宣稱分類準確率。
- D-04 旁白與理解題先做 A/B 測試設計與離線評估；正式曝光 A/B 需操作者核准後才開始。
- D-05 渲染層遷移（Remotion 等）只做評估報告，本階段不實作。
- D-06 不 commit、不 push；不對真實病患或診所發送任何內容。

## 外部證據（有限，供設計參考）
- 動畫對健康資訊的短期知識與行為有改善，低健康素養者以口語化動畫較佳；長期效果證據仍不足（[Frontiers 2025 回顧](https://www.frontiersin.org/journals/digital-health/articles/10.3389/fdgth.2025.1717044/full)、[PubMed 25586711](https://pubmed.ncbi.nlm.nih.gov/25586711/)）。
- 結構化輸出只保證格式，不保證類別正確，需語義稽核（[TDS](https://towardsdatascience.com/your-json-is-valid-but-your-data-is-wrong-five-failure-modes-llm-structured-outputs-wont-catch/)）。

## 計畫對應
| Plan | 內容 | Wave | 依賴 |
|---|---|---|---|
| 57-01 | 對應對帳、黃金標準集模板、現況基線 | 1 | 無 |
| 57-02 | LLM 分類含「其他」、證據片段、健保批次改接、準確率量測 | 2 | 57-01 |
| 57-03 | TTS 旁白與理解題、A/B 離線評估與曝光設計 | 3 | 57-02 |
| 57-04 | 渲染層遷移評估報告（不實作） | 4 | 57-03 |
