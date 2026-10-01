# Phase 08-04 總結報告：GENERAL-03 隱私驗收、AGENTS.md 規範與全量回歸

## 執行概述

本計畫為 Phase 08（一般醫療諮詢）之 Wave 4 關帳任務，完成了 GENERAL-03 端對端隱私驗收測試（包含資料庫 dump/原始位元組掃描、全系統 logger 掃描、AST 靜態語法樹分析）、`AGENTS.md` 規範文件化（新增 2.9 節與目錄結構更新），並完成全量回歸與正式資料庫零污染比對。

---

## 交付成果清單

### 1. 核心驗收與規範更新
- **隱私驗收測試套件 (`tests/test_general_privacy.py`)**：共 6 個完整測試函式全數通過：
  1. `test_db_has_no_question_text_after_requests`：發送三種路徑問句（answered、no_match、red_flag）與自訂 Header 哨兵後，掃描資料庫 iterdump 與檔案原始位元組，查無任何問句原文或 Header 哨兵值；資料庫 sha256 與所有資料表列數在請求前後完全不變。
  2. `test_no_log_contains_question_or_headers`：使用 caplog 在 DEBUG 等級監控所有 logger（含 root、uvicorn.*、fastapi、httpx、httpcore），日誌文字查無問句原文、FAQ 內容或 Header 哨兵。
  3. `test_response_never_echoes_question`：驗證所有回覆模型皆不包含 `query` 欄位，且 JSON 字串不回顯問句。
  4. `test_422_responses_do_not_echo_or_log_input`：六種畸形輸入（超長、純空白、list、dict、非法 JSON、text/plain）皆回傳固定文字 422，不回顯哨兵且不記入日誌。
  5. `test_get_is_rejected_and_access_filter_covers_it`：GET 請求被 405 拒絕且 uvicorn 存取日誌過濾器成功攔截該紀錄。
  6. `test_src_general_has_no_logging_or_persistence`：AST 靜態語法樹分析，確認 `src/general/*.py` 與 `src/api/routes/general.py` 無 `import logging`、無 `print`、無寫入型 SQL。
- **專案規範文件 (`AGENTS.md`)**：
  - 新增第 2.9 節《一般醫療諮詢入口（Phase 08 新增）》：詳細記載獨立匿名端點規範、13 條紅旗規則單一權威來源、免責聲明來源、傳輸層與存取日誌過濾、422 錯誤防禦、認證決策與速率限制建議、已知限制與測試慣例。
  - 第 4 節目錄結構補入 `src/general/`、`src/api/routes/general.py`、`src/api/access_log_filter.py`。

---

## ROADMAP 成功標準對照表

| 標準 | 說明 | 對應驗收測試 | 狀態 |
|---|---|---|---|
| **1. 紅旗症狀偵測與就醫提示** | 涵蓋胸痛、呼吸困難、意識改變、大量出血、過敏休克、中風、中毒、填充劑血管阻塞（與注射同句升 emergency）、劇痛、高燒等；命中立即短路，不執行檢索，不呼叫 LLM | `test_general_red_flags.py`<br>`test_general_consult.py:test_red_flag_shortcut_does_not_call_search`<br>`test_api_general.py:test_red_flag_triggers_emergency_and_no_search` | ✅ 通過 |
| **2. 免責聲明強制附帶** | 所有回覆（含回答、無資料、紅旗警示）皆附法定免責宣告，說明非醫囑、無法取代親自診察 | `test_general_disclaimer.py`<br>`test_general_consult.py`<br>`test_api_general.py:test_disclaimer_present_in_all_states` | ✅ 通過 |
| **3. 診所資料隔離** | 僅檢索一般醫療知識（`category='general'`），嚴格隔離診所私有資訊與特約藥品/給付項目 | `test_general_consult.py:test_clinic_isolation_strict`<br>`test_api_general.py:test_clinic_isolation_and_parameter_ignored` | ✅ 通過 |
| **4. 匿名與無狀態承諾** | 不記錄問句、不存病患提問歷史、不外洩至日誌；422 錯誤不回顯問句 | `test_general_access_log_filter.py`<br>`test_api_general.py:test_validation_error_does_not_echo_input`<br>`test_general_privacy.py`（全數 6 個測試） | ✅ 通過 |

---

## 關帳驗證數據

1. **正式庫零污染檢驗**：
   - 測試前 `sha256sum clinic.db`：`c51cc4d039379fe00f70d7864b29a952928233fa6caa6e72954900f4c28c65ad`
   - 全量測試後 `sha256sum clinic.db`：`c51cc4d039379fe00f70d7864b29a952928233fa6caa6e72954900f4c28c65ad`
   - 比對結果：**完全一致（位元組零變更）**。
2. **全量測試結果**：
   - `python3 -m pytest -q`：**485 passed**, 1 warning in 11.55s（既有 288 基線 + Phase 08 新增 197 個測試，0 失敗）。
3. **工作區狀態**：
   - 無執行任何 `git commit`。
   - `git diff --stat src/api/app.py` 恰為 `2 insertions(+)`。
