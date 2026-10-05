# Phase 12 Plan 01 Summary: 醫療安全檢核層實作 (GC-02, GC-03)

## 執行成果摘要

- **目標需求**：GC-02（用藥劑量與處方建議攔截）、GC-03（就醫警訊檢核層）
- **狀態**：完成
- **測試基線與最終結果**：
  - 實施前基線：669 passed（或既有套件）
  - 最終全量測試：**812 passed, 0 failed, 1 warning**（新增 143 個測試項目）
  - 正式庫雜湊確認：`sha256sum -c prod.sha256` 驗證成功（SHA-256 恆為 `ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e`）

---

## 交付項目與關鍵修改

1. **`src/ingestion/medical_safety.py` (新增)**：
   - `check_dosage_prescription(answer: str) -> Optional[str]`：
     - DX-1（具體數字/範圍 + 嚴格劑量單位，如 mg, 毫克, iu）
     - DX-2（給藥動詞 + 份量單位，如 服用兩顆、吃一錠）
     - DX-3（具名藥物 + 份量或頻率，如 每天三次、每8小時）
     - DX-4（具名藥物 + 給藥動詞組合，具備否定/現況/遵醫囑豁免）
     - DX-5（泛稱服藥/吃藥語句，具備豁免）
     - DX-6（拉丁頻率簡寫，如 bid, tid, q8h, prn）
     - NFKC 標準化與小寫轉換，全形字元（如「５００ｍｇ」）無所遁形。
   - `has_doctor_warning(answer: str) -> bool`：
     - 檢查是否同句兼備「具體條件」（危險症狀或數值門檻）與「就醫動作」，且排除否定動作。

2. **`src/ingestion/generate_faq.py`**：
   - `validate_single_faq` 與 `parse_and_validate_faq` 新增條件式關鍵字參數：
     - `check_dosage: bool = False`（第五層，僅對 answer 檢查）
     - `require_doctor_warning: bool = False`（第六層，僅對 answer 檢查）
   - 預設均為 False，既有四層與一般擷取保持 100% 向後相容。
   - **W2 run_stage1_ingestion 處置說明**：`scripts/run_stage1_ingestion.py` 是處理診所自有衛教文件（`clinic_upload`），屬於信任來源，依審查決策維持預設關閉，不增加多餘限制。

3. **`src/batch/faq_generator.py`**：
   - `REJECT_CODES` 加入 `"dosage_prescription"` 與 `"missing_doctor_warning"`。
   - `classify_reject_reason` 優先於 malformed 攔截這兩類代碼，防止因「缺少」被誤判。
   - `build_seed_faq_prompt`：恆加入禁止具體用藥劑量處方；`require_doctor_warning=True` 時加入以就醫警訊收尾之指示。
   - `generate_topic_faqs` 接線：LLM 生成路徑一律啟用 `check_dosage=True`；general 主題啟用 `require_doctor_warning=True`。

4. **`tests/test_medical_safety.py` (新增)**：
   - 47 則劑量處方正例攔截、50 則安全衛教負例放行。
   - 15 則警訊正例識別、17 則空泛負例拒絕。
   - 雙層整合與 answer-only 安全隔離測試。
   - 正式庫 40 筆診所 FAQ 回掃：0 誤拒。
   - classify 映射、prompt 規則生成與 topic wiring 端到端驗證。

---

## 威脅與合規驗證

- **T-12-01 (劑量攔截防繞過)**：先 NFKC 再比對，DX-1~DX-3 無豁免，全形與拉丁縮寫皆命中。
- **T-12-02 (隱私洩漏防護)**：拒絕原因只包含規則代碼（如 `(規則: DX-4)`），repr(result) 絕不洩漏未核准內容。
- **T-12-03 (空泛警訊防繞過)**：要求同句必須有具體條件（症狀或數值），空泛如「不適請就醫」皆被拒絕。
