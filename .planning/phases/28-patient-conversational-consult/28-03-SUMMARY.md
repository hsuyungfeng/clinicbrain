# Phase 28 Plan 03：組稿接入病人路由與確定性降級執行總結

## 1. 執行目標
- 將 Phase 28 Plan 02 的組稿純函式串成病人端「已核准資料組稿」流程（P28-TPL），實現「先提供價值、後獲取資訊」的對話式體驗。
- 落實 AGENTS 2.8 雙門檻（>=0.9 / >=0.7）、風險特徵對稱、歧義邊界（>=0.1）與最小長度的「高信心直答」：符合標準時直接回覆已核准（含預生成後核准）FAQ 原文，不呼叫 LLM（0 次呼叫）。
- 建立確定性降級機制：當 LLM 忙碌、夜間批次執行中、離線、截斷或輸出檢驗失敗時，安全降級為已核准資料萃取之確定性回答，不回傳 busy，不外露未核准內容。
- 支援 2.24 未審一般說明附帶單一追問與預約邀請 CTA，但草稿資料庫儲存內容保持純淨，不含追問或 CTA。

## 2. 實作變更清單
1. `src/general/patient_compose.py`（全新建立）：
   - `compose_from_approved(conn, query, found, llm_call)`：評估直答（重用 `faq_shortcut` 雙門檻與風險對稱）、組裝 evidence blocks、非阻塞鎖探測、LLM 組稿與輸出四層檢驗、確定性降級與 `sanitize_faq_text` 價格屏蔽。
   - `decorate_general_answer(answer, query)`：為 2.24 未審說明附加單一追問與 CTA，不足 2 句時安全退回原 answer。
   - `_get_db_path(conn)`：純 SELECT table-valued function 查詢主庫路徑，符合隱私守門規則。
2. `src/general/patient_consult.py`（更新）：
   - 接入 `compose_from_approved` 於 `answered` 分支，成功時回傳結構化對話回答，失敗時退回既有 `found.message`。
   - `llm_general` 兩個分支（同題待審草稿重用、2.24 新生成草稿）回傳 message 經 `decorate_general_answer` 處理，附加追問與 CTA，資料庫儲存內容保持不變。
   - 新增 `compose_llm_call` 選用參數，未提供時預設沿用 `llm_call`。
   - 調整函式宣告順序，避免 `default_patient_llm` 前向參照問題。
3. `tests/test_patient_compose.py`（全新建立）：
   - 包含 12 項行為單元測試：直答判定、風險不對稱不直答、歧義不直答、過短不直答、LLM 組稿與草稿隔離、各類異常降級、鎖佔用降級、合規失敗降級、截斷輸出降級、確定性警訊句萃取、裝飾函式、預生成核准直答與待審隔離。
4. `tests/test_patient_consult.py`（更新）：
   - 新增已核准資料組稿回傳 answered、同題草稿重用分離檢驗、任意路徑 LLM 呼叫次數最多一次測試。
5. `tests/test_patient_consult_ui.py`（依使用者裁示方案 A 更新 line 110）：
   - 將舊的精確全等斷言 `assert data["message"] == mock_body` 更新為：
     (1) `mock_body in data["message"]`
     (2) `data["message"].endswith(CTA_TEXT)`
     (3) `data["message"].count("？") == 1`
   - 理由：Phase 27 舊測試斷言編碼的是 Phase 28 之前的舊格式，28-03 刻意改為「價值回答＋單一追問＋CTA」，故更新斷言以相容新結構。

## 3. 測試驗證結果
- **28-03 Plan Verify 指令**：
  ```bash
  uv run pytest tests/test_patient_consult.py tests/test_patient_compose.py tests/test_patient_consult_latency.py tests/test_general_consult.py tests/test_patient_consult_ui.py -x -q
  ```
  **`43 passed, 1 warning in 1.62s`** 全數通過。
- **隱私守門測試**：
  ```bash
  uv run pytest -q -p no:cacheprovider tests/test_general_privacy.py
  ```
  **`6 passed, 1 warning in 1.29s`** 全數通過。
- **正式庫防護**：
  正式庫 `clinic.db` SHA-256：`0b9548af8601c32dd1b884b54e34b3bd6fbc82609b08372c3e9d5212b8626084`，維持不變。
