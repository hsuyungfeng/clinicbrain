# Phase 15 Context: 臨床 SOAP 衛教提煉與審核流

## 一、階段目標
在維持公開自然語言端點（`/api/v1/query`、`/api/v1/general/query`）嚴格隔離與零病患隱私洩漏的前提下，建立臨床衛教提煉管線與醫師審核工作流：
1. **臨床提煉 (Extraction & Distillation)**：從已入庫且去識別化的 `soap_records` 中，分析 Assessment 與 Plan 段落，萃取高頻疾病之照護指引與居家衛教（home care），提煉為標準問答對草稿。
2. **草稿儲存 (Staging & Pending)**：提煉之草稿以 `source_type='soap_distilled'` 寫入 `faq_cache`，強制設定 `review_status='pending'`，未經醫師審核前對所有自然語言查詢絕對不可見。
3. **醫師審核工作流 (Physician Review CLI)**：擴充 `scripts/review_faq.py` 與 `faq_review.py`，支援檢視提煉來源（關聯之去識別化 SOAP 紀錄統計與主題）、比對既有診所/通用 FAQ、逐筆簽核核准 (`approve`) 或駁回 (`reject`)。
4. **多層合規防護 (Compliance Guards)**：提煉過程強制執行價格數字遞迴清洗（`[請致電診所確認]`）、保證療效禁詞攔截、DX 劑量/處方攔截器驗證，以及繁體正體中文過濾。

## 二、邊界與安全鐵則（遵循 AGENTS.md）
1. **公開端點絕對隔離**：公開端點嚴格禁止直接檢索或讀取 `soap_records`。只有在 `faq_cache` 中且 `review_status='approved'` 的 FAQ 才能被查詢層引用。
2. **零病患個資洩漏**：提煉來源必須使用已完成身分證、電話、姓名遮蔽與 HMAC-SHA256 偽名化的紀錄；提煉出的衛教問答文字嚴禁包含任何患者代碼或個資殘留。
3. **單一權威寫入路徑**：
   - `faq_cache` 寫入一律經由 `faq_writer.upsert_faqs()`。
   - 審核狀態變更一律經由 `faq_review.set_review_status()`。
4. **正式庫絕對保護**：測試全程使用複本（`tmp_path` 隔離），正式庫 `clinic.db` SHA-256 恆定受保。
