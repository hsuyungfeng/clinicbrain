# Phase 17 Research: 定時一般醫學知識補充與批次擴充

## 1. 既有架構與模組複用分析

### 1.1 種子定義架構 (`src/batch/topic_sources.py`)
- **格式規範**：`SeedTopic` 支援 `category='general'`，此時 `clinic_id=None`、`keywords=()`、`always=True`。
- **問題標籤（`QUESTION_TAGS`）**：固定四維標籤集合 `{"what", "symptoms", "when_to_see_doctor", "home_care"}`。
- **檔案路徑**：`data/batch/faq_seeds.json`。
- **現狀**：目前僅有 4 個 general 主題（`common-cold-home-care`, `influenza-basics`, `acute-gastroenteritis`, `allergic-rhinitis`），共 17 個問題。

### 1.2 批次生成與防禦管線 (`src/batch/faq_generator.py`)
- **生成邏輯**：`generate_topic_faqs` 僅針對種子中定義的人寫問題，杜絕模型臆造問題。
- **合規檢查**：四層防護（價格屏蔽、正體中文、立場中立、保證療效過濾）＋`dosage_prescription`（處方用藥劑量防護）＋`missing_doctor_warning`（就醫警訊必備）。
- **Fail-Closed 審核**：寫入時透過 `upsert_faqs(source_type='llm_generated')`，預設標記為 `review_status='pending'`。

### 1.3 批次調度整合 (`src/batch/runner.py`)
- 目前批次步驟：
  - 步驟 0a: 前置 SOAP 增量同步（選用）
  - 步驟 0b: SOAP 衛教提煉（`distill_soap_records`）
  - 步驟 1: 規劃（選取主題）
  - 步驟 2: FAQ 預生成
  - 步驟 3: PageIndex 樹重建
- Phase 17 擴充點：
  - 支援 `--general-only` / `--skip-general` 控制旗標。
  - 當設定為 `--general-only` 時，略過 SOAP 提煉與 special 樹重建，僅專注執行 general 疾病的增量生成。
  - 斷點續跑：已有合格答案（或未標記 `needs_regeneration`）的問答題自動略過，不重複消耗 LLM 算力。

---

## 2. 擴充主題規劃（台灣常見大宗基層醫學衛教）

規劃新增 6~8 個基層高頻疾病主題：
1. **高血壓居家照護 (`hypertension-basics`)**
   - 什麼是高血壓？常見症狀有哪些？什麼時候需要緊急就醫？在家量測血壓與居家照護重點？
2. **第二型糖尿病衛教 (`diabetes-type2-care`)**
   - 什麼是糖尿病？常見症狀有哪些？低血糖與高血糖何時就醫？飲食生活與日常照護重點？
3. **急性與慢性蕁麻疹 (`urticaria-care`)**
   - 什麼是蕁麻疹？常見症狀與誘發因子？出現呼吸困難等何時緊急就醫？止癢與日常照護重點？
4. **氣喘日常照護 (`asthma-home-care`)**
   - 什麼是氣喘？發作時有哪些常見症狀？什麼情況屬於急性發作需立即就醫？平時如何避免誘發？
5. **胃食道逆流衛教 (`gerd-management`)**
   - 什麼是胃食道逆流？常見症狀有哪些？何時需要進一步就醫檢查？日常生活與飲食調整方式？
6. **痛風急性發作與飲食 (`gout-basics`)**
   - 什麼是痛風？急性關節炎常見症狀？關節紅腫熱痛何時就醫？日常飲食與高普林食物注意事項？
7. **帶狀疱疹照護 (`herpes-zoster-care`)**
   - 什麼是帶狀疱疹（皮蛇）？初期常見症狀有哪些？何時應儘速就醫抗病毒治療？皮膚水泡傷口如何照護？
8. **偏頭痛誘發與照護 (`migraine-basics`)**
   - 什麼是偏頭痛？常見前兆與伴隨症狀？出現突發劇烈頭痛何時應掛急診？日常如何記錄與預防誘發？

---

## 3. 審核工具擴充 (`scripts/review_faq.py`)
- `pending-summary` 新增 `--category` 篩選支援（如 `--category general` 或 `--category special`），並可分類統計 SOAP 提煉草稿 vs LLM 生成一般衛教草稿。
- 支援醫師在晨間明確區分診所專屬草稿與通用衛教草稿進行審核。
