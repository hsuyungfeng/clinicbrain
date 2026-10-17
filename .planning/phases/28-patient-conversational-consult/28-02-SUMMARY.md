# Phase 28 Plan 02：純函式組稿模組與句界截斷修復執行總結

## 1. 執行目標
- 建立純函式組稿與截斷防護模組 `src/general/answer_compose.py`（無 I/O、不呼叫 LLM、不連資料庫），提供回答結構保證與醫療合規驗證。
- 改造 `src/pageindex/rag_ask.py`：移除原本會造成半句（如「若出現胸…」）截斷的 `_clip` 函式，改為調用 `clip_at_sentence`。
- 引入 `CONTEXT_TOTAL_CHARS = 2400` 預算控制，在 context 組裝端動態平衡 FAQ 與推理樹預算，單項下限 120 字，超出預算時依序剔除多餘 FAQ，絕不切出半句或省略號。
- 確保長答案（如 700 字）中包含的就醫警訊句完整保留於 context 內。

## 2. 實作變更清單
1. `src/general/answer_compose.py`（全新檔案，Task 1）：
   - 提供 8 個核心純函式：`clip_at_sentence`、`split_sentences`、`is_complete_ending`、`classify_intent`、`parse_model_output`、`assemble_answer`、`validate_composed`、`build_compose_prompt`。
   - `clip_at_sentence`：按句界切割，優先在預算內保留 `has_doctor_warning` 警訊句，重組時依原文順序輸出，永不輸出 `…` 或半句。
   - `assemble_answer`：確保價值段 2～4 句、結尾恰一個「？」結尾的單一追問、附加無網址無數字的 `CTA_TEXT`。
   - `DEFAULT_FOLLOWUPS`：為六類意圖（what, recovery, risk, suitable, when_to_see_doctor, other）提供預設合規追問。
   - 模組完全無 `sqlite3`、`urllib`、`requests` 等外部 I/O 依賴。
2. `tests/test_answer_compose.py`（全新檔案，Task 1 測試）：
   - 包含 14 個單元測試，涵蓋長文本警訊句保留、半句截斷判定、多追問擷取單一、追問含數字（天數）合規防誤攔、CTA 無網址無金額檢驗。
3. `src/pageindex/rag_ask.py`（Task 2 改造）：
   - 徹底移除 `def _clip` 函式。
   - 匯入 `src.general.answer_compose.clip_at_sentence`。
   - 定義 `CONTEXT_TOTAL_CHARS = 2400`、`MIN_ITEM_CHARS = 120` 與預設單項預算常數。
   - 重構 `retrieve_evidence`：實作 `_render_evidence` 動態預算調整與二分搜尋；超出總預算時依序減少候選 FAQ 筆數，保證總 context 長度在預算內且所有內容皆為完整句。
4. `tests/test_rag_ask_enhancement.py`（Task 2 測試擴充）：
   - 新增 `test_retrieve_evidence_preserves_warning_in_long_faq`：驗證 700 字答案結尾的就醫警訊句完整進入 context，且結尾絕無 `…` 或 `...`。
   - 新增 `test_retrieve_evidence_budget_cap_and_no_ellipsis`：驗證 8 筆長 FAQ 加 2 棵完整推理樹時，context 長度受限於預算範圍內且無任何省略號。

## 3. 測試驗證結果
- `Task 1 Acceptance Criteria`：
  - 8 個函式定義齊全。
  - 引用 `has_doctor_warning`。
  - 禁用的 I/O 模組（sqlite3, urllib, requests）計數為 0。
- `Task 2 Acceptance Criteria`：
  - `grep -c "def _clip" src/pageindex/rag_ask.py` 為 0。
  - `grep -n "clip_at_sentence" src/pageindex/rag_ask.py` 命中 7 處。
  - `grep -n "CONTEXT_TOTAL_CHARS" src/pageindex/rag_ask.py` 命中 5 處。
- `單元與整合測試`：
  - `uv run pytest tests/test_answer_compose.py tests/test_rag_ask_enhancement.py tests/test_admin_ask.py -x -q`：28 passed
  - `uv run pytest tests/test_patient_consult_latency.py tests/test_llm_client.py tests/test_rag_ask_enhancement.py tests/test_admin_ask.py tests/test_answer_compose.py -x -q`：44 passed
- `正式庫防護`：
  - 正式庫 `clinic.db` SHA-256：`0b9548af8601c32dd1b884b54e34b3bd6fbc82609b08372c3e9d5212b8626084`（前後完全一致，未發生任何寫入）。
