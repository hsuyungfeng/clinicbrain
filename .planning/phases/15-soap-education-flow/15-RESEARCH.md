# Phase 15 Research: 臨床 SOAP 衛教提煉與審核流技術分析

## 一、現有模組架構分析

### 1.1 SOAP 儲存與特徵結構
* 資料表：`soap_records` 包含 `clinic_id`, `external_id`, `subjective`, `objective`, `assessment`, `plan`, `conditions` (JSON), `symptoms` (JSON), `insights` (JSON)
* `insights["home_care"]` 與 `insights["symptoms"]`：已在 Phase 14 由 `extract_general_medical_insights()` 提取並去識別化。
* 衛教提煉重點在於：以 `conditions`（診斷病症）為分群 key，彙整多筆病歷中重複出現的 `plan` / `home_care` 衛教重點。

### 1.2 FAQ 快取與審核架構
* 資料表：`faq_cache` 具備 `review_status`（`pending`, `approved`, `rejected`）與 `source_type`（`manual`, `llm_generated`, `clinic_upload`）。
* 需擴充 `source_type` 列舉支援：`'soap_distilled'`（SOAP 提煉草稿）。
* 審核工具：`scripts/review_faq.py` 已支援 `list --topic`、`show`、`approve`、`reject`、`reset`、`mark-regen`。
* 驗證防禦鏈：
  - `validation_report()` 已整合價格檢驗、保證療效禁詞、政治立場、簡體字、DX 劑量攔截器與就醫警訊檢驗。

## 二、技術設計挑戰與解決方案

### 2.1 臨床文字聚合與去個資二次清洗
* 挑戰：雖然入庫時已做 PII 遮蔽，但直接將單一病患的 Plan 拼貼成問答可能帶有特定病患語境（如「王先生下次帶報告」）。
* 解法：
  1. 規則模板式聚合（Deterministic Template Aggregator）：針對常見疾病，將萃取出的 `home_care` 項目進行字串正規化與詞頻聚合（例如「多喝水休息」出現 3 次以上則採納）。
  2. 通用提煉格式：組裝成標準結構問答：
     - 問題：`【照護指南】罹患{condition}時居家應如何照護？`
     - 答案：條列式居家照護重點 + 必備就醫警訊提示 + 免責聲明。
  3. 嚴格過濾特定日期、時間、人名、代名詞語句。

### 2.2 審核工具 `review_faq` 溯源呈現
* 醫師在審核時，需要知道這筆衛教建議是從哪些 SOAP 紀錄（筆數、涵蓋病例）聚合出來的。
* 在 `faq_cache` 的 `metadata` (JSON) 欄位中記錄來源溯源資訊：
  `{"source": "soap_distilled", "condition": "急性咽喉炎", "soap_count": 5, "source_record_ids": ["EXT-01", "EXT-02"]}`。
* `review_faq show` 輸出增加「臨床病歷溯源」區塊，顯示採樣病例數與去識別化主訴關鍵字。
