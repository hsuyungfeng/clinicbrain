# Phase 28：病人端對話式諮詢與預生成 QA - Research

**Researched:** 2026-10-16
**Domain:** 內部程式碼調查（FastAPI + 本機 llama-server + SQLite 審核閘門）
**Confidence:** MEDIUM（根因為由日誌與程式碼推論，未呼叫真實 LLM 驗證；已標註）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- 實測比較（果凍矽膠隆乳）：本機 LLM 一般醫學（75 秒、1572 token）內容豐富但有事實錯誤；Gemini 含價格違規；診所文件＋雲端 LLM 語氣最佳但外送雲端不可用；clinicbrain RAG 合規但重複句多、且被截斷（「若出現胸」）。
- 架構三層：(1) 預生成 QA（夜間批次，pending→醫師核准→公開，命中即回）；(2) 即時組稿：已核准診所專屬資料＋已核准一般醫學資料，由本機 LLM 依固定結構生成；(3) 未命中時的未審一般說明沿用 AGENTS 2.24 例外（標示未審，不進公開快取）。
- 回答結構：價值回答 2～4 句 → 單一追問 → 預約／留資邀請。每次只問一個問題，不要求姓名／電話。
- 960 秒生成耗時視為異常，先查根因（reasoning／max_tokens／重試），再決定是否需要背景生成＋輪詢。
- 使用 FAITHFUL_SAMPLING（AGENTS 2.19）與長度上限；紅旗短路與免責聲明維持。
- 收集越多診所專屬資料與病人問答主題（去識別化、標準化，不存原文），越多預生成相似 QA。
- 限制：不得直接寫正式庫；不得啟用 systemd；不得重啟 llama-server；價格屏蔽；繁體中文；文件繁體中文；測試不得呼叫真實 LLM（除明確標記的實機驗證，且用副本庫）。

### Claude's Discretion
非同步機制細節（in-memory job vs 其他）、截斷偵測方式、相似 QA 生成演算法、測試切分。

### Deferred Ideas (OUT OF SCOPE)
- 留資表單與 doctor-toolbox.com 整合（階段二）
- 反向代理速率限制實際套用
- 完整測試套件 18 失敗／3 錯誤排查（另案）
</user_constraints>

<phase_requirements>
## Phase Requirements

REQUIREMENTS.md 中尚無 Phase 28 專屬 ID（grep 無 PAT-/CONSULT- 條目）。建議規劃時自訂如下 ID 並補入 REQUIREMENTS.md：

| ID（建議） | Description | Research Support |
|----|-------------|------------------|
| P28-LAT | 查明並修復約 960 秒生成耗時 | 第一節根因與修復 |
| P28-TRUNC | 答案不得截斷、就醫警訊不得遺失 | 第二節 |
| P28-TPL | 價值回答＋單一追問＋預約邀請結構 | 第三節 |
| P28-PRE | 夜間批次預生成相似 QA（pending） | 第四節 |
| P28-ASYNC | 視需要背景生成＋輪詢，不記錄問句 | 第五節 |
</phase_requirements>

## Summary

耗時根因（高度可能，需以副本庫實機單次驗證）：`/consult` 走 `generate_general_draft`，提示為「JSON 陣列 + 8/9 條規則」，模型（Qwen 系列，`reasoning_format=deepseek`、生成前綴 `<think>\n`）**無視提示內的 `/no_think` 與請求中的 `reasoning_effort:"low"`，持續思考**。`logs/slots.json` 顯示該請求 `max_tokens=12288`，已 decode 10033 token、仍在 reasoning（`n_remain 2255`）。`logs/probe_nothink.json` 證明：附帶 `/no_think` 的極簡提示，伺服器仍產生 201 token 的 `reasoning_content`，且實測 decode 速率為 **21.4 tok/s**（非 AGENTS 所述 ~90 tok/s，後者為 MTP 設定下之量測；目前 llama.cpp build 實際約 21）。1572 token/75s 與 21 tok/s 完全吻合。故 12288 token 上限 ≈ 575 秒；`content` 為空時 `LLMEmptyOutputError` 觸發 `_call_no_think_first` 的**再重試一次** ≈ 第二個 575 秒，合計約 960～1150 秒，與觀察到的 960 秒吻合。`[INFERRED]` 非直接量測。

截斷根因：不在 LLM 端，而在 `rag_ask.retrieve_evidence` 的 `_clip(text, 500)`（`t[:n] + "…"`）。診所 FAQ 答案依 Phase 12 規則「就醫警訊在結尾」，超過 500 字即被機械切在警訊句中間（「若出現胸…」），模型再依被截斷的 context 作答／複述。次要風險：`local_llm_call` 不檢查 `finish_reason=="length"`，content 非空但被 max_tokens 截斷時會當成功回傳。

**Primary recommendation：** (1) 在 `local_llm_call` 增加 `finish_reason` 偵測與可選 `chat_template_kwargs:{"enable_thinking":false}`／`reasoning_effort:"none"` 覆寫，病人端即時組稿用「純文字輸出（非 JSON）、關閉思考、max_tokens≈700、FAITHFUL_SAMPLING」，取消空白重試；(2) 以句界截斷取代字數硬切並保證警訊句整句保留；(3) 組稿提示 + 後處理器結構化輸出；(4) 夜間批次新增「病人問答預生成」階段（pending）；(5) 修復後單題預期 30～60 秒，仍建議採 in-memory job + 輪詢，因為 HTTP 長連線（反向代理 60 秒預設逾時）風險仍在。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 紅旗短路／免責聲明 | API/Backend（`src/general/`） | — | 既有，不呼叫模型 |
| 已核准資料檢索 | Database（`visible_faq_sql`/`visible_tree_sql`） | API | 審核閘門唯一來源 |
| 組稿提示與後處理（結構、截斷、追問、CTA） | API/Backend（新模組 `src/general/answer_compose.py`） | — | 純函式、可不依賴 LLM 測試 |
| 本機 LLM 呼叫參數（思考、取樣、finish_reason） | API/Backend（`llm_client.py`） | — | 單一出口 |
| 長任務（job＋輪詢） | API/Backend（記憶體 job registry） | Browser（consult.html 輪詢） | 比照 `batch_answer_job.py` |
| 預生成 QA | Batch（`src/batch/`） | Database（faq_cache pending） | 離峰、醫師審核 |
| 預約 CTA | API（固定 `BOOKING_URL`）＋Browser 顯示 | — | 不收集個資 |

## Standard Stack

沿用現有，無新增外部套件（`[VERIFIED: codebase]`）：Python 3.12（uv）、FastAPI、sqlite3 標準庫、pytest、`urllib.request`（llm_client）。**不需要安裝任何新套件，Package Legitimacy Audit：不適用（無新增外部套件）。**

| 既有元件 | 用途 |
|---------|------|
| `src/pageindex/llm_client.py:local_llm_call` | 單一 LLM 出口，`sampling` 可覆寫 payload |
| `src/api/routes/admin.py:FAITHFUL_SAMPLING` | `{"temperature":0.1,"dry_multiplier":0.0,"repeat_penalty":1.0}`（建議搬到 `llm_client.py` 共用，避免病人端 import admin） |
| `src/pageindex/faq_writer.py:upsert_faqs` | faq_cache 唯一寫入路徑（pending） |
| `src/pageindex/faq_review.py:visible_faq_sql / sanitize_faq_text` | 可見性與去識別化＋價格屏蔽 |
| `src/ingestion/generate_faq.py:validate_single_faq` | 六層驗證（價格／簡體／政治／禁詞／劑量／警訊） |
| `src/ingestion/medical_safety.py:has_doctor_warning` | 警訊檢驗（同一句須同時有具體條件＋就醫動作） |

## 一、耗時根因（P28-LAT）

證據鏈：
1. `src/general/patient_consult.py:110-122`：`GENERAL_LLM_TIMEOUT_SECONDS=900`、`max_tokens=12288`；`general_fallback._call_no_think_first` 對 `LLMEmptyOutputError` **重試一次**（整個重送）。`[VERIFIED: codebase]`
2. `llm_client.local_llm_call` 預設 payload：`reasoning_effort:"low"`、`max_tokens` 被 `sampling` 覆寫為 12288；**未帶** `chat_template_kwargs`、`reasoning_format` 等。`[VERIFIED: codebase]`
3. `logs/slots.json`：`generation_prompt:"<|im_start|>assistant\n<think>\n"`、`reasoning_format:"deepseek"`、`max_tokens:12288`、`n_decoded:10033`、`is_processing:false` 快照時 `n_remain 2255`；另 `n_prompt_tokens:10526`（該快照為某次含長 context 的請求，非必然為 consult，但說明長提示 prefill 亦佔時間）。`[VERIFIED: logs/slots.json]`
4. `logs/probe_nothink.json`：`/no_think` 被模型當成普通文字；`reasoning_content` 仍輸出；`predicted_per_second: 21.43`。`[VERIFIED: logs]`
5. `logs/_probe_gen.out`：同題在 480 秒逾時（舊版程式，重試邏輯尚為 `_call_with_no_think_retry`）。`[VERIFIED: logs]`
6. llama.cpp server 官方文件：`reasoning_effort:"none"` 可關閉思考；`chat_template_kwargs:{"enable_thinking":false}` 可傳給 Jinja 模板；`--reasoning-budget` 為伺服器啟動旗標（不可改，禁止重啟 llama-server）。`[CITED: github.com/ggml-org/llama.cpp tools/server/README.md]`
7. `ThreadPool`：`post_general_consult` 為 sync def，每個請求佔用 FastAPI threadpool 一條執行緒達數分鐘。`[VERIFIED: codebase]`

規劃建議（修復）：
- `local_llm_call` 新增：回應 `finish_reason == "length"` 時拋 `LLMTruncatedError(RuntimeError)`（含 usage），**不當成功**；為既有呼叫端保持相容（目前所有呼叫端把 RuntimeError 視為失敗，需檢查 `batch_answer_job`/`admin` 對例外類別的處理，必要時讓新例外繼承 `LLMEmptyOutputError` 以沿用既有分支）。
- 病人端新增 `PATIENT_SAMPLING = {**FAITHFUL_SAMPLING, "max_tokens": 700~900, "reasoning_effort": "none", "chat_template_kwargs": {"enable_thinking": False}}`。兩個關閉思考手段是否對此 Qwen3.8 build 生效 **必須以副本庫＋單次實機探測驗證**（標示為明確的實機驗證任務，不放進自動測試）；驗證判準：回應 `reasoning_content` 為空或 < 100 token，總耗時 < 60 秒。`[ASSUMED]` 兩參數對此模板有效（官方文件說明請求欄位存在，但特定 GGUF 的 chat template 是否讀取 `enable_thinking` 未驗證）。
- 若關閉思考無效的備案：以 `reasoning_budget`-類請求欄位不可用 → 退而求其次降低 `max_tokens` 至 ≈1500 並接受空白即失敗（**不重試**）；重試只對連線類錯誤，不對 `LLMEmptyOutputError`／`LLMTruncatedError`。
- 取消 `_call_no_think_first` 的空白重試（對病人端），改為失敗即回固定文字（`NO_DATA_TEXT`）；管理端草稿路徑可保留。
- 提示改為**純文字輸出**（不要求 JSON 陣列）可省去 JSON 包裝 token 與解析失敗；組稿結構由後處理器補齊。
- 時間預算：prefill 約 940 tok/s（AGENTS），context 控制在 ≤ 2000 token；decode 21 tok/s × 400 token ≈ 20 秒。目標 P95 < 60 秒。

## 二、截斷 bug（P28-TRUNC）

| 位置 | 機制 | 影響 |
|------|------|------|
| `rag_ask.py:30` `_clip(t, 500)` `t[:n]+"…"` | 對診所 FAQ 答案硬切 500 字；就醫警訊在尾端 | **「若出現胸」的主因** |
| `rag_ask.py:51` 推理樹各段 300、摘要 200 | 同上 | 衛教後段遺失 |
| `llm_client.py:106-124` | 不看 `finish_reason` | content 非空但被 max_tokens 截斷時當成功（6144 預設） |
| `general_fallback.parse_and_validate_faq` | answer 上限 300 字（提示規則 6）與 `MIN_ANSWER_CHARS` | 模型被迫壓縮，警訊句易被省略→驗證失敗 |
| `batch_answer_job`/`validate_single_faq(require_doctor_warning=True)` | 缺警訊則整筆拒絕（不截斷） | 病人端回固定文字 |

修復規劃：
1. 新增純函式 `clip_at_sentence(text, limit)`：在 `limit` 以內回溯最後一個句界（`。！？；\n`）；**永不輸出半句**，並且**若原文含警訊句（`has_doctor_warning` 命中的句子），先保留該句再填其他句子**（警訊優先預算）。
2. `retrieve_evidence` 的 `SNIPPET_CHARS` 改為依總預算（例：context 總量 ≤ 2400 字）動態分配，使用 `clip_at_sentence`。
3. 輸出端截斷偵測（兩層，不依賴 LLM）：(a) `finish_reason=="length"` → 失敗；(b) 後處理檢查結尾字元須為句末標點（`。！？」）`），否則視為截斷、不回傳；(c) 警訊在最後一句，被切則 `has_doctor_warning` 失敗，二者互補。
4. 回歸測試：以 >500 字且警訊在末尾的 FAQ 驗證 `retrieve_evidence` 輸出仍含完整警訊句。

## 三、結構化模板與驗證器互動（P28-TPL）

建議插入點：新模組 `src/general/answer_compose.py`（純函式，無 I/O）＋病人端 `patient_consult` 的「已核准資料→即時組稿」新分支（紅旗→預生成快取命中→已核准資料組稿→2.24 未審例外→固定文字）。

輸出模板（後處理器**重新組裝**，不信任模型自行排版）：
`[價值回答 2～4 句（含警訊句）]` + `[單一追問，一句、以「？」結尾]` + `[CTA 固定字串：如需評估，可透過預約連結…]`。模型只產出 JSON 之外的兩個欄位標記（例如「答：」「追問：」兩行純文字）；後處理器負責：句數限制、只保留第一個追問、CTA 由程式附加（CTA 為固定常數，避免模型生成價格或承諾）。

與驗證器的互動（`[VERIFIED: codebase]`）：
- `validate_single_faq`：價格（`_PRICE_PATTERN`）、簡體、政治、保證療效、劑量、警訊皆對 `answer` 檢查。**追問句與 CTA 要在驗證「之後」附加，或單獨驗證**：追問若含數字（如「3 天」）會被劑量／價格規則誤攔，且追問不得出現用藥名。建議：驗證對象＝價值回答部分；追問另跑價格＋禁詞＋簡體；CTA 為常數。
- `has_doctor_warning` 要求「同一句」同時有具體條件與就醫動作，且分句後逐句判斷；追問（疑問句）不會誤判為警訊，但**警訊必須在追問之前**（追問結尾不是警訊句屬預期），模板順序＝價值（含警訊）→追問→CTA。
- 價格屏蔽：`sanitize_faq_text`/`deep_mask_prices` 在回傳前再套一次（既有 `post_general_consult` 已做 `deep_mask_prices(result.message)`）。
- 「只問一個問題」：後處理器計 `？` 數，> 1 則保留第一個其餘刪除；0 則附預設追問（常數表，依意圖分類，不用 LLM）。
- 句數限制：價值段以 `。！？` 切分，> 4 句則截為前 4 句**但警訊句必留**（取警訊句＋前 3 句）。
- 預約 CTA 保持 `BOOKING_URL = https://doctor-toolbox.com/`；回應 JSON 已有 `booking_url`，前端顯示按鈕；訊息文字內只放不含網址的短句，避免 `deep_mask_prices` 誤處理。
- 即時組稿資料來源：已核准診所專屬（`handle_query(..., cache_shortcut=False)` 含 `clinic_id`）與已核准一般 FAQ/樹（`consult_general`）。病人端為匿名、無 `clinic_id`：需決定預設診所（見 Open Questions 1）。

## 四、夜間批次預生成（P28-PRE）

可重用點：
- `src/batch/runner.py:run_batch`：階段式結構（SOAP→FAQ→樹→第 7 階段 autofill），新增「階段 8：病人問答預生成」，受 `max_pending`、`time_budget_seconds`、`LocalLLMUnavailableError` 優雅中止、`RunLogger`（不記原文）規範。
- `faq_generator.generate_topic_faqs / write_topic_faqs / existing_questions(exclude_regen_marked=True)`：去重與寫入（`upsert_faqs(source_type='llm_generated')` → 恆 pending）。
- `topic_sources.load_seed_file`：人寫題目＋四層檢驗；`data/batch/faq_seeds.json`。
- `cache_stats` 的 `miss_keyword`（`ROUTE_KEYWORD_VOCAB` 白名單關鍵字、近 14 天門檻）：作為「熱門主題」來源。**僅有白名單關鍵字，無完整問句**。

演算法（建議，不存原文）：
1. 主題選取：`miss_keyword` 近 14 天 top-N 關鍵字（診所路由詞）＋ `always` 種子；已核准診所 FAQ／樹的 `topic_key` 作為「資料依據」。
2. 題目產生（**由程式模板而非 LLM 擬題**，避免捏造）：對每個主題 × 固定意圖模板（「什麼是…」「術後恢復期多久」「風險與注意事項」「適合哪些人」「何時需要就醫」）展開；模板為人審過的常數表，載入時過四層檢驗。
3. 答案生成：以該主題**已核准**診所 FAQ／樹作 reference（沿用 `reference_from_tree`，該函式已套用 `visible_tree_sql`；FAQ 參考需用 `visible_faq_sql`），走第三節模板與 FAITHFUL_SAMPLING，結果以 `upsert_faqs(... 'llm_generated')` 寫入 → pending；`metadata.origin='patient_prefill'`、`generated_from='approved_clinic_data'`。
4. 病人端查詢未命中時產生的去識別化題目（Phase 26 的 `general_fallback` pending 草稿）已在 faq_cache；批次可對「同一 `topic_key` 的 pending 草稿群」做相似題擴充：僅以 `topic_key` 與人寫模板展開，不用病人原文。
5. 診所專屬資料收集：不新增資料表；沿用 `data/batch/faq_seeds.json` 擴充＋已核准 FAQ。若要「越多資料越多預生成」，以 `topic_key` 為鍵，批次統計每個主題已核准項目數，優先選資料充足者。
6. 限制：`--max-pending`（預設 200）保護審核量；GPU 21 tok/s 下每題 ≈ 30 秒，5 主題 × 5 模板 ≈ 13 分鐘，在 `time_budget_seconds=3600` 內。

注意：病人端快取命中需 `source_type NOT IN gated OR approved`，pending 預生成對 `/consult` 完全不可見直到醫師核准（`visible_faq_sql`）。`/consult` 目前呼叫 `consult_general`（`category='general' AND clinic_id IS NULL`），**診所專屬預生成（`special`）目前不在 `/consult` 路徑**（AGENTS 2.24 待辦已載明）；規劃須決定是否在 `/consult` 增加診所範圍檢索（見 Open Questions 1）。

## 五、是否需要非同步（P28-ASYNC）

結論：修復後（< 60 秒）同步 POST 勉強可行，但**建議仍實作 job＋輪詢**，理由：反向代理預設逾時 60 秒、瀏覽器分頁切換、`sync def` 長佔 threadpool、`_PATIENT_LLM_LOCK` 忙碌時使用者體驗。若規劃要控制範圍，可設定為「兩階段」：Wave 1 修復耗時＋截斷＋模板（仍同步）；Wave 2 加 job/polling。

既有模式：`batch_answer_job.py`（單一作業、背景 thread、`snapshot()` 記憶體複本、輪詢端點不接 DB、每題各自連線）與 `/review/batch-generate/status`（3 秒輪詢）。

病人端 job 設計限制（隱私，AGENTS 2.9）：
- `POST /api/v1/general/consult` 回 `{job_id, status:"pending"}`（`job_id` 為 `secrets.token_urlsafe(16)`，不可預測）；`GET /api/v1/general/consult/{job_id}` 輪詢。**路徑在 `/api/v1/general` 前綴下，存取日誌過濾器已涵蓋 path**（`ExcludeGeneralPathFilter`）；job_id 不是問句，但仍在過濾範圍內。
- job 記憶體保存：問句**不保留**（只在 worker 參數內使用，完成後清除）；結果保留 TTL ≤ 5 分鐘後刪除（讀取一次即可刪除）；上限總 job 數（例 20）防記憶體灌入；僅一個併發 worker（沿用 `_PATIENT_LLM_LOCK` 非阻塞語意：忙碌時 `busy`，可考慮短佇列 ≤ 3）。
- 不得寫入 `cache_stats` 或任何日誌；例外訊息不外露。
- 錯誤測試：job 到期後回 404；未知 id 回 404（固定文字，不洩漏存在性差異以外資訊）。
- 前端 `consult.html`：現為 `fetch` → 一次 `.then`；改為提交後以單一 `setTimeout` 鏈輪詢（2～3 秒，上限 ~3 分鐘），全部以 `textContent` 渲染（既有 `tests/test_patient_consult_ui.py` 靜態掃描）。已存在 `status-busy`、`loadingMessage` 可沿用。
- 與管理端互斥：`_PATIENT_LLM_LOCK` 與 `admin._GENERATION_LOCK` 為**不同的鎖**——病人端與管理端／背景補齊可同時打 llama-server（`-np 1` 一個 slot，排隊→逾時誤判離線）。規劃應讓病人端 worker 也取得 `_GENERATION_LOCK`（或將兩鎖合併為 `llm_client` 層共用鎖）與夜間批次 `db_lock`。`[VERIFIED: codebase]` 目前 `patient_consult.py` 沒有引用 `_GENERATION_LOCK`。

## Architecture Patterns

### 流程圖
```
病人問句 → POST /api/v1/general/consult
  ├─ 紅旗? ──是→ 固定就醫指示（不呼叫模型）
  ├─ 預生成/已核准 FAQ 命中? ──是→ 套模板（價值→追問→CTA）直接回
  ├─ 已核准診所/一般資料可組稿? ──是→ [job] compose_prompt → LLM(純文字,關思考,FAITHFUL,max_tokens~800)
  │                                   → 後處理: 去思考/截斷偵測/句數/單一追問/CTA → 驗證 → 回（不入公開快取）
  └─ 無資料 → 2.24 例外：LLM 一般說明(標示未審)＋pending 草稿；失敗→固定文字
夜間批次: miss_keyword/種子 + 已核准資料 → 模板擬題 → LLM → 驗證 → faq_cache(pending) → 醫師核准 → 命中即回
```

### 建議結構
```
src/general/answer_compose.py   # 純函式：clip_at_sentence、assemble、單一追問、CTA、截斷偵測
src/general/consult_jobs.py     # in-memory job registry（無問句保留、TTL）
src/pageindex/llm_client.py     # finish_reason、PATIENT_SAMPLING、LLMTruncatedError
src/batch/patient_prefill.py    # 階段 8 預生成
```

### Anti-Patterns
- 以字數硬切 evidence（現況 bug）。
- 對 content 空白／超時重試（耗時翻倍）。
- 在 HTTP 請求執行緒內持有數分鐘 LLM 呼叫而無共用鎖。
- 在驗證前附加追問／CTA（誤觸劑量／價格規則）或在驗證後信任模型排版。
- 讓病人端 job 儲存問句或把問句放入 URL／日誌。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| 可見性過濾 | 自寫 `review_status` SQL | `visible_faq_sql` / `visible_tree_sql` |
| FAQ 寫入 | 直接 INSERT | `faq_writer.upsert_faqs` |
| 價格／個資屏蔽 | 自寫 regex | `sanitize_faq_text` / `deep_mask_prices` |
| 警訊判定 | 自寫關鍵字 | `has_doctor_warning` |
| 紅旗 | 自寫詞表 | `detect_red_flag` |
| 背景作業框架 | 新執行緒池／外部佇列 | 比照 `batch_answer_job.py` 模式 |
| 跨行程互斥 | 新鎖檔 | `src/batch/db_lock.py` |

## Common Pitfalls

1. **思考參數無效**：`/no_think` 文字無效（已實證）。須以實機探測確認 `reasoning_effort:"none"`／`chat_template_kwargs` 生效，否則耗時問題只是被限縮而未消失。預防：探測腳本只用副本庫與單次呼叫，結果寫入 phase 文件。
2. **速率假設錯誤**：AGENTS 稱 ~90 tok/s，實測 21 tok/s。所有逾時／配額估算以 21 tok/s 計。建議同步更正 AGENTS.md 的描述（`[ASSUMED]` 依 MTP 是否啟用而異，需使用者確認）。
3. **重試放大延遲**：空白重試使 575s→1150s。
4. **兩把鎖不互通**：`_PATIENT_LLM_LOCK` vs `_GENERATION_LOCK`。
5. **FTS trigram 對短詞無效**：預生成擬題／檢索詞 <3 字走 LIKE（既有 `search_*` 已處理，勿繞過）。
6. **測試 fixture 污染**：`isolated_conn` 複製正式庫，測試須用專屬 `topic_key`（AGENTS 2.1）。
7. **簡轉繁靜默**：`local_llm_call` 對輸出 `to_traditional`，簡體檢驗對 LLM 輸出不觸發。
8. **追問含數字被劑量規則攔**：見第三節。
9. **job 記憶體洩漏／隱私**：TTL、上限、不存問句。
10. **`status` 契約**：`consult.html` 與 `test_patient_consult_ui.py` 依賴既有 `status` 值（red_flag/answered/llm_general/no_match/busy）；新增 `pending`/`composed` 需同步前端與 CSS。

## Code Examples

句界截斷（建議實作骨架）：
```python
import re
_SENT_END = re.compile(r"(?<=[。！？；\n])")

def clip_at_sentence(text: str, limit: int) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    out = ""
    for s in _SENT_END.split(t):
        if len(out) + len(s) > limit:
            break
        out += s
    return out  # 永不輸出半句；全為長句時回空字串由呼叫端處理
```
後處理組裝（骨架）：
```python
def assemble(value: str, followup: str | None, intent: str) -> str:
    sents = [s for s in _SENT_END.split(value) if s.strip()]
    warn = [s for s in sents if has_doctor_warning(s)]
    body = [s for s in sents if s not in warn][: 4 - len(warn)] + warn[:1]
    q = (followup or DEFAULT_FOLLOWUP[intent]).split("？")[0] + "？"
    return "".join(body) + q + CTA_TEXT
```
llm_client finish_reason 檢查：
```python
fr = choices[0].get("finish_reason")
if fr == "length":
    raise LLMTruncatedError(f"輸出達 max_tokens 上限被截斷（usage={resp_json.get('usage')}）")
```

## State of the Art

| 現況 | 建議 | 影響 |
|------|------|------|
| JSON 陣列輸出＋思考 | 純文字＋關思考＋後處理組裝 | 大幅降 token 與耗時 |
| 字數硬切 context | 句界＋警訊優先 | 修截斷 |
| 同步長請求 | job＋輪詢 | 抗逾時 |

## Runtime State Inventory

不適用（非改名／遷移）。注意：若新增 `faq_cache.metadata.origin='patient_prefill'` 無需 schema 遷移（沿用 `metadata` 欄位，且 `faq_writer` 缺 `metadata` 欄位時 Fail-Closed）。正式庫不得寫入；所有驗證用副本庫。

## Environment Availability

| Dependency | Required By | Available | Notes |
|------------|------------|-----------|-------|
| llama-server (127.0.0.1:8080) | 僅明確標記之實機探測 | 未探測（任務禁止呼叫 LLM） | 實機驗證任務需使用者許可，用 `logs/probe_copy.db` 型副本 |
| uv / pytest | 測試 | ✓（既有 stack） | 本次 Bash 工具因 rtk hook 部分指令失敗，故未實跑測試 |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest（既有，`tests/conftest.py` 含 `isolated_conn`、autouse `_default_allow_no_auth`） |
| Quick run | `uv run pytest tests/test_patient_consult.py tests/test_general_fallback.py tests/test_llm_client.py -x -q` |
| Full suite | `uv run pytest -q`（已知 18 失敗／3 錯誤屬另案，不納入閘門；以新增檔案＋相關回歸為準） |

### Phase Requirements → Test Map（皆不呼叫真實 LLM，以假 `llm_call`／monkeypatch `urllib`）
| Req | Behavior | Type | File |
|-----|----------|------|------|
| P28-LAT | `local_llm_call` payload 含關思考參數；`finish_reason=length` 拋 `LLMTruncatedError`；空白不重試（假 urlopen 計次=1） | unit | `tests/test_llm_client.py`（擴充）、`tests/test_patient_consult.py` |
| P28-LAT | 病人端 LLM 呼叫次數 ≤ 1、`max_tokens`/sampling 符合常數（捕捉 payload） | unit | `tests/test_patient_consult_latency.py` ❌ Wave 0 |
| P28-TRUNC | `clip_at_sentence` 不產半句；警訊句在 >500 字 FAQ 末尾仍被完整保留（`retrieve_evidence`） | unit | `tests/test_answer_compose.py`、`tests/test_rag_ask_enhancement.py`（擴充） ❌ Wave 0 |
| P28-TRUNC | 結尾非句末標點→拒絕回傳 | unit | 同上 |
| P28-TPL | 組裝：價值 ≤4 句、恰一個「？」、CTA 常數存在、警訊句在追問前；多追問只留一個；價格／劑量攔截；追問含數字不誤攔 | unit | `tests/test_answer_compose.py` |
| P28-TPL | 紅旗不呼叫模型；已核准資料組稿用假 LLM；pending 內容不進 context | integration | `tests/test_patient_consult.py`（擴充） |
| P28-PRE | 階段 8：假 `llm_call` 產生 pending；對 `/general/query`、`/consult`、sync export 不可見；核准後可見；`max_pending` 與時間預算；`LocalLLMUnavailableError` 優雅中止；`RunLogger` 無原文 | integration | `tests/test_patient_prefill_batch.py` ❌ Wave 0（比照 `test_nightly_general_batch.py`） |
| P28-ASYNC | job 建立／輪詢／TTL 過期 404／不保留問句（序列化 job 狀態不含問句字串）／忙碌 busy／存取日誌過濾涵蓋；輪詢端點不連 DB | integration | `tests/test_consult_jobs.py` ❌ Wave 0 |
| P28-UI | consult.html 靜態掃描：輪詢使用 `textContent`、無 innerHTML／eval | static | `tests/test_patient_consult_ui.py`（擴充） |

實機驗證（明確標記、需人工許可、僅副本庫）：單次探測 `enable_thinking:false`／`reasoning_effort:"none"` 的 `reasoning_content` 長度與耗時；結果記入本 phase 的 VERIFICATION。不納入 CI。

### Sampling Rate
- 每次提交：上述 Quick run；每 wave：新增檔案＋`test_general_*`、`test_api_general.py`、`test_nightly_general_batch.py`、`test_phase20_hardening.py` 回歸；phase gate：正式 `clinic.db` SHA-256 不變（既有守門慣例）。

### Wave 0 Gaps
- [ ] `tests/test_answer_compose.py`、`tests/test_patient_consult_latency.py`、`tests/test_patient_prefill_batch.py`、`tests/test_consult_jobs.py`
- [ ] 測試 autouse：病人端 LLM 預設換成會拋錯的假函式（比照 Phase 20 慣例）

## Security Domain

| ASVS | 適用 | 控制 |
|------|------|------|
| V5 輸入驗證 | 是 | `GeneralQueryRequest` 長度 1–300、`AnonymousRoute` 固定 422；job_id 格式驗證 |
| V4 存取控制 | 是 | 匿名端點僅讀已核准資料；job_id 不可預測；管理端仍 `verify_admin_key` |
| V6 密碼學 | 輕度 | `secrets.token_urlsafe` 產 job_id（勿用 random） |
| V7 日誌 | 是 | 不記問句；`/api/v1/general` 存取日誌過濾；批次 `RunLogger` 白名單 |
| V8 資料保護 | 是 | 不存個資；去識別化後才入草稿 |

威脅：Prompt 注入（輸出端驗證為唯一防線，沿用 2.18 設計）；灌 job 耗盡記憶體（上限＋TTL）；經 LLM 誘導外洩未審內容（context 僅含已核准資料）；DoS 佔用 GPU（單一 worker＋busy；反向代理 limit_req 屬 deferred）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 960 秒 ≈ 兩次（12288 token 於 21 tok/s ≈ 575s）重試之和；未直接量測 | 第一節 | 根因需修正；仍以實機探測確認 |
| A2 | `reasoning_effort:"none"`／`chat_template_kwargs.enable_thinking=false` 對此 Qwen3.8 GGUF 模板有效 | 第一節 | 耗時無法降低，需備案（小 max_tokens、不重試、背景 job） |
| A3 | 目前實際速率 21 tok/s（取自 probe 單次量測），AGENTS 的 ~90 tok/s 屬不同設定 | Pitfalls | 配額估算偏差 |
| A4 | 反向代理逾時預設 60 秒（通用常識，專案未設定 nginx） | 第五節 | 影響是否強制 job 化 |
| A5 | 病人端預設查詢範圍（是否綁預設診所）未決 | 第三、四節 | 影響資料來源與隱私 |

## Open Questions

1. **病人端匿名端點是否要檢索診所專屬 FAQ（`special`）？** AGENTS 2.9/2.24 與 CONTEXT 的「已核准診所專屬資料組稿」有張力：匿名端點目前不接受 `clinic_id`。建議在 discuss/規劃時請使用者決定：單診所部署固定 `clinic_id`（伺服器設定，非用戶端輸入）或維持僅一般資料。
2. **AGENTS 2.24 例外（未審一般說明）與第 (2) 層組稿的標示**：組稿（基於已核准資料）是否需「尚未經醫師審核」標籤？建議否（資料已核准），但 LLM 組稿本身是新文字，需使用者確認標示文案。
3. **實機探測許可**：是否允許用副本庫對 llama-server 做單次探測（不重啟、不改設定）。
4. **單一 slot 下病人端與管理端優先序**：病人端是否優先於背景補齊？目前建議共用鎖、病人端忙碌時回 busy。

## Project Constraints (from CLAUDE.md / AGENTS.md)
- 所有輸出、註解、commit 訊息繁體中文；價格屏蔽；不得寫正式庫、不啟用 systemd、不重啟 llama-server。
- `faq_cache` 唯一寫入路徑 `upsert_faqs`；FTS5 trigram；`visible_faq_sql` 唯一可見性來源；`REVIEW_GATED_SOURCES` 集中定義。
- 測試不得呼叫真實 LLM；`isolated_conn` 測試需專屬 `topic_key`；測試後不得遺留模型鎖。
- 不收集姓名／電話／身分證；不記錄問句原文；`/api/v1/general` 存取日誌過濾。
- 使用者全域：以 uv 管理（`uv run pytest`）；文件以繁體中文為主。
- 實作後須依 AGENTS 執行 graphify 重建指令；commit 結尾附 Co-Authored-By。

## Sources

### Primary（HIGH）
- 程式碼：`src/general/patient_consult.py`、`consult.py`、`src/pageindex/general_fallback.py`、`llm_client.py`、`rag_ask.py`、`batch_answer_job.py`、`src/api/routes/general.py`、`admin.py`、`src/batch/faq_generator.py`、`runner.py`、`src/ingestion/generate_faq.py`、`medical_safety.py`
- 日誌：`logs/slots.json`、`logs/probe_nothink.json`、`logs/_probe_gen.out`、`logs/general_draft_result.json`
- llama.cpp server README（https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md，取自 raw 版本，已閱讀前 100000 字元）：`reasoning_effort`、`chat_template_kwargs`、`--reasoning-budget`
### Secondary / Tertiary
- 無。未呼叫 LLM、未讀 journalctl、未碰正式庫。

## Metadata
**Confidence:** 截斷根因 HIGH（程式碼直接證據）；耗時根因 MEDIUM（日誌＋推論）；關思考參數有效性 LOW（待實機）；批次與 job 設計 HIGH（沿用既有模式）。
**Research date:** 2026-10-16　**Valid until:** 14 天（本機 llama.cpp build 變動快）
