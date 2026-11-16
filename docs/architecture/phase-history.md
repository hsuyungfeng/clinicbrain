# clinicbrain 歷史 Phase 架構與規格歸檔（Phase 08–46）

> 本文件由 `AGENTS.md` 第二章歷史段落（§2.9 起）歸檔而來，保留完整實作脈絡與設計決策。

### 2.9 一般醫療諮詢入口（Phase 08 新增）
為提供民眾安全、匿名且合規之一般醫療衛教諮詢管道，自 Phase 08 起建立專屬一般諮詢架構：
- **獨立匿名端點 (`POST /api/v1/general/query`)**：
  - 匿名無綁定：不要求 `X-API-Key`，不接受亦不需 `clinic_id`；若客戶端夾帶 `clinic_id` 或 `X-Clinic-ID` 標頭一律靜默忽略。
  - 伺服器固定診所例外（Phase 28 / P28-CLINIC）：`/api/v1/general/consult` 與 `/consult/jobs` 依伺服器設定 `patient_clinic_id` 可檢索該診所已核准之 special 內容（請求夾帶仍一律忽略），詳見 2.25 節。
  - 資料庫隔離（GENERAL-04）：僅檢索 `category='general' AND clinic_id IS NULL` 之 `faq_cache` 與 `page_index_trees`；嚴格隔離診所私有資訊，絕不查詢藥品、健保服務給付項目與診所營運資料表；完全不呼叫外部 LLM 模型。
  - 目前資料現況：正式資料庫內 general 類資料目前為 0 筆，所有非紅旗問句皆會誠實回傳 `no_match`（不捏造醫療內容）；general 衛教內容須另經醫師審核後始得入庫。
- **急重症紅旗偵測 (`src/general/red_flags.py`)**：
  - 單一權威詞表：定義 13 條規則（E01~E08, U01~U05），分為 `emergency`（立即撥打 119/急診）與 `urgent`（當日儘速就醫）兩級。
  - 優先短路：問句命中紅旗時立即回傳固定就醫指示，完全不進行分詞、不存取資料庫。
  - 保守醫療策略：否定語境（如「沒有胸痛」）刻意仍觸發；填充劑血管阻塞徵兆（E08）須與注射語境同句才觸發，並附加「聯絡施作診所」提示。
  - 邊界決策：依使用者決策，精神心理類不在本表範圍；新增或修改詞表須經使用者審閱並補漏報導向正例與誤觸發負例測試。
- **免責聲明與就醫提示 (`src/general/disclaimer.py`)**：
  - 本模組為固定文字唯一權威來源。所有對外回覆（包含回答、無資料、紅旗警示）一律強制附帶法定醫療免責宣告，明確告知無法取代醫師面對面親自診察。
- **傳輸層與日誌隱私承諾（GENERAL-03）**：
  - 零日誌與無狀態：不寫入任何資料庫資料表、不記錄 `cache_stats`、回應模型刻意不回顯 `query` 欄位。
  - 僅提供 POST 方法：問句置於請求主體，不進入 URL；同路徑之 GET 請求回傳 405 Method Not Allowed。
  - 存取日誌過濾 (`src/api/access_log_filter.py`)：`ExcludeGeneralPathFilter` 自動攔截並整行丟棄 `uvicorn.access` 中所有 `/api/v1/general` 開頭之路徑紀錄（含 IP 與 query string）；反向代理（如 Nginx）若另有存取日誌，須自行對此路徑關閉記錄。
- **輸入驗證與錯誤防禦**：
  - 自訂路由 `AnonymousRoute(APIRoute)` 攔截所有 `RequestValidationError`，一律回傳固定繁體中文 `{"detail": "請求格式不正確"}`（HTTP 422），防範 FastAPI 預設錯誤在 `detail[].input` 回顯使用者敏感問句。
  - 單次請求成本受限於問句長度（1-300 字元）與數量上限（`limit <= 10`）。
- **認證決策與速率限制建議**：
  - 本端點作為大眾匿名入口，刻意不加管理員金鑰。潛在濫用風險為唯讀計算負載。
  - 建議於反向代理層使用 `limit_req` 實施速率限制；若未來於應用層實作，僅得使用純記憶體計數，嚴禁持久化病患 IP 或問句。
- **已知限制與後續項目（不在本 Phase 處理）**：
  1. 既有 `GET /api/v1/query?q=` 仍會在存取日誌中留下問句，且 `POST /api/v1/query` 走 `handle_query` 流程，不屬本端點之匿名承諾範圍，一般民眾入口請一律使用 `/api/v1/general/query`。
  2. `consult_general` 沿用既有 `extract_search_terms`，長問句若未含停用詞可能切出過長片段影響 FTS 命中率；後續可考慮評估 2~3 字滑動窗口詞彙。
- **測試慣例**：
  - general 樹無專用寫入路徑（`upsert_trees` 需機構代碼），測試在暫存複本以 raw INSERT 建立 `clinic_id IS NULL` 的 general 樹；general FAQ 則透過權威寫入函式 `faq_writer.upsert_faqs` 寫入。

### 2.10 夜間批次生成與審核閘門（Phase 09 新增）
為達成離峰預先生成常見問答、減輕醫師日常重複解答負擔，並自動更新過期臨床推理樹，自 Phase 09 起導入夜間批次與審核閘門架構：
- **醫師審核閘門語意 (`faq_cache.review_status`)**：
  - 狀態列舉：`pending`（待審核）、`approved`（已核准）、`rejected`（已駁回）。
  - 可見性規則：`manual`（手寫）與 `clinic_upload`（CLI／同步匯入之院所權威來源）恆常對外可見；由本地模型生成之 `llm_generated` 資料預設寫入為 `pending`，在未獲醫師核准前對外完全隱蔽。
  - 單一權威讀取與寫入路徑：
    - `src/pageindex/faq_review.py:visible_faq_sql` 為所有 FAQ 查詢可見性過濾條件的唯一來源；新增任何 FAQ 讀取邏輯一律須經 `search_faq_cache` 或引用此條件。
    - `src/pageindex/faq_review.py:set_review_status` 為修改審核狀態之唯一寫入路徑；核准前強制重跑四層醫療合規檢核；可見性改變時自動遞增 `content_version`。
  - 消費端全面套用：自然語言查詢（含快取短路 `handle_query`）與同步匯出（`POST /api/v1/sync/export`）皆已無條件套用審核閘門，確保未核准項目零洩漏。
- **資料庫遷移與 Fail-Closed 防禦**：
  - 正式庫遷移指令：先手動備份 `cp clinic.db clinic.db.bak-$(date +%Y%m%d)`，後執行 `python3 scripts/migrate_faq_review_status.py --confirm-prod-backup`。
  - 未遷移庫防禦：未完成遷移之舊庫在寫入 `llm_generated` 時一律拋錯拒絕（Fail-Closed）；檢索端則退化為完全排除 `llm_generated` 內容。
  - **遷移 DDL 單一來源（Phase 10）**：`scripts/migrate_faq_review_status.py` 的 `ALTER TABLE ... ADD COLUMN` 不再手寫，由 `src/db/clinic_schema.sql` 的 `faq_cache` CREATE TABLE 區塊依欄位名稱擷取（`extract_column_definition`）。約束：`review_status`、`reviewed_at` 的欄位定義必須單行、定義文字內不得含 `--`；解析失敗在連線前即拋 `RuntimeError`（fail-closed）。修改這兩欄定義只需改 schema。
- **批次執行器與資源防禦 (`src/batch/runner.py`)**：
  - 執行入口：`python3 scripts/run_nightly_batch.py`。
  - 多重資源保護：`--max-faq-topics`（預設 5）、`--max-trees`（預設 3）、`--max-pending`（預設 200，保護醫師審核負擔）、`--time-budget-seconds`（預設 3600.0，超時優雅中斷）、`--llm-timeout`（單次推論逾時 120 秒）。
  - 單筆失敗隔離：單一主題或單一推理樹處理失敗不影響同批其他項目。
  - 本地 LLM 離線降級：健康檢查或中途遇到 `LocalLLMUnavailableError` 時優雅中止，保留已完成項目並記錄日誌，以結束碼 0 退出，不造成排程失敗。
- **臨床推理樹重建與【重建會覆蓋手寫內容】重要警示**：
  - 唯一標記入口：`src/pageindex/db_writer.py:set_needs_regeneration`，提供 CLI 工具 `scripts/mark_tree_regen.py`。
  - 繞過閘門取捨與後果：臨床推理樹重建**不走審核閘門**；被標記重建的手寫樹（`manual` 或 `clinic_upload`）其四段臨床內容與摘要將直接被 LLM 覆蓋，`source_type` 變更為 `llm_generated`。
  - 補償防護機制：
    1. 醫師權威註記保護：四段之 `*_physician_notes` 覆寫既有值，寫入後一致性校驗，若被清空自動執行前像還原。
    2. 自動前像快照：重建前將既有內容以 JSON 格式儲存於 `logs/nightly_batch/tree_snapshots/`。
    3. 審核警告事件：覆蓋手寫內容時於日誌發出醒目的 `tree_overwrote_handwritten` 警告並累計至摘要。
- **主題種子清單 (`data/batch/faq_seeds.json`)**：
  - 結合熱門未命中關鍵字（過去 14 天累計未命中次數達門檻）與 `always` 候選分流。
  - 所有問題由人撰寫，載入時強制四層醫療合規檢查；全部題目皆已存在的主題自動跳過且不佔名額（不餓死其他主題）。
- **非阻塞檔案鎖與日誌隱私保證**：
  - 鎖檔位置：固定位於目標資料庫同目錄（`<db_path>.nightly.lock`），跨不同 log 目錄皆具互斥性，不重疊執行。
  - 預設 log-dir 解析為專案絕對路徑 `logs/nightly_batch`。
  - 日誌隱私範圍：`RunLogger` 嚴禁記錄 `query/question/answer/prompt/raw` 等鍵名；批次期間透過 `content_loggers_silenced()` 靜音內部 logger，保證程式產生日誌無問句與模型原文；第三方 logger 不在保證內。
- **結束碼定義**：0 = 完成或優雅跳過（含 dry-run、LLM 不可用、持鎖略過、預算用盡）；1 = 未預期例外；2 = 參數/前置檢查拒絕。
- **排程服務與啟用規範**：
  - 提供 `clinicbrain-nightly.service`（oneshot）與 `clinicbrain-nightly.timer`（凌晨 02:30，含 Persistent 補跑）範本。
  - 專案依規範絕不代為啟用或啟動任何 systemd 服務，由使用者自行規劃啟用。
- **已知限制（架構決策接受）**：
  1. `/api/v1/sync/import` 以 `clinic_upload` 寫入，若與既有 pending/rejected 的 `llm_generated` 列同鍵，會覆寫並變更為 approved（外部匯入視為院所權威來源）。
  2. `local_llm_call` 逾時會轉為 `LocalLLMUnavailableError`，單次逾時即讓批次提前優雅結束（結束碼 0），留待下一晚繼續。
  3. 樹重建繞過審核閘門（如上述，以快照與註記還原為補償防線）。
  4. 未命中關鍵字僅記錄標準化白名單字詞，無法獲知病患真實具體問法。
  5. 批次的 `existing_questions` 去重（`src/batch/faq_generator.py`）不分審核狀態與資料來源，被駁回（`rejected`）的題目仍視為已存在，因此永遠不會被重新生成；如需重生須由人工另行處理（例如改寫題目文字或人工刪除該列；Phase 12 起可由 review_faq mark-regen 明確觸發重生成，見 2.12）。
- **真實本地模型批次驗證（Phase 13 DEBT-04 完成）**：
  - 於完全隔離之資料庫複本上，以真實本機推論引擎（`llama-server` + Qwen3.8-27B-UD-Q4_K_XL）完成端到端全流程實跑驗證（測試：`tests/test_real_llm_batch.py`）。
  - 實測單題 FAQ 生成耗時約 32 秒，通過五層醫療合規檢核並寫入 `review_status='pending'`，對外檢索維持零洩漏；臨床推理樹重建耗時約 140 秒，自動建立前像快照並完整保護既有醫師權威註記；`RunLogger` 經白名單審核確認日誌完全無病患個資或模型內容洩漏。
  - 正式 `clinic.db` 全程以唯讀保護並比對 SHA-256 雜湊值（`ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e`），驗收確認正式庫零寫入零污染。
  - `llm_client.local_llm_call` 現參數：`max_tokens=6144`、`reasoning_effort="low"`、預設逾時 420 秒；回傳前對模型輸出套用 `to_traditional`（簡轉繁）。**取捨**：模型偶發的簡體輸出會被悄悄轉成繁體，下游四層驗證的「簡體字」檢查對 LLM 輸出不再觸發也不留痕；其餘四層驗證仍獨立把關。
  - 日誌新增 `faq_regen_unchanged_ids`／`faq_regen_failed_ids`（列 id，非敏感資訊，不含題目或答案）。

### 2.12 一般疾病內容生成與審核（Phase 12 新增）
為使系統能以合規且安全的方式提供常見疾病（如感冒、流感、急性腸胃炎、過敏性鼻炎）之衛教問答，自 Phase 12 起導入一般疾病內容生成、多層合規防禦與審核增強機制：
- **擴充疾病種子清單 (GC-01)**：
  - 種子清單支援擴充主題與可選之 `question_tags` 標籤，分類包含 what、symptoms、when_to_see_doctor、home_care（程式：`src/batch/topic_sources.py:QUESTION_TAGS`；測試：`tests/test_disease_seeds.py::test_question_tags_constant`）。
  - 簽核四項常見疾病（感冒、流感、急性腸胃炎、過敏性鼻炎）共 17 題繁體中文問答種子入庫，所有項目皆通過格式與分類檢驗（程式：`src/batch/topic_sources.py:load_seed_file`；測試：`tests/test_disease_seeds.py::test_seed_file_structure_and_disease_coverage`）。
  - 夜間批次預設採用簽核之種子清單，端到端驗收確認 4 主題與 17 題正確載入（程式：`src/batch/runner.py:BatchConfig`；測試：`tests/test_phase12_acceptance.py::test_01_preflight_seed_topics`）。
- **用藥劑量與處方建議攔截層 (GC-02)**：
  - 實作劑量與處方安全規則（DX-1~DX-6），攔截阿拉伯數字劑量、中文數字劑量、處方用藥建議，並保留「請遵照醫囑」「請勿自行增減」之免責豁免（程式：`src/ingestion/medical_safety.py:check_dosage_prescription`；測試：`tests/test_medical_safety.py::test_validate_single_faq_default_disabled`）。
  - **2026-10-06 複審補強（`5714714`）**：① DX-2 涵蓋「只有數量、句中無藥名」的劑量句（「每次吃2顆」「小孩一次吃半顆」「吃3片就夠了」，「吃N片」排除吐司、水果等食物）；② DX-4/DX-5 的否定豁免改為**否定詞必須緊鄰給藥動詞**（`請勿自行服用…` 豁免，`請勿擔心可吃止痛藥` 不豁免）；③ 詞庫補糖漿、栓劑、噴劑、針劑、口服液、止瀉劑、退燒貼／針與 acetaminophen、tylenol 等英文學名。**詞庫為封閉式，未列名的藥與劑型仍可能漏攔，最終仰賴醫師審核。**
  - 實測精確度（封閉語料，不代表泛化能力；複審另以 50 句獨立正例實測曾漏 20 句，補強後以獨立新語料測試）：劑量正例 47/47 攔截、負例 50/50 放行；正式庫既有 40 筆診所 FAQ 回掃 0 誤拒（包含診所 FAQ id 6 之「給予抗生素」描述性敘述）（程式：`src/ingestion/medical_safety.py:check_dosage_prescription`；測試：`tests/test_medical_safety.py::test_backscan_clinic_upload_faqs`）。
  - 批次生成管線全面啟用劑量攔截，違規項目分類為 `dosage_prescription` 拒絕代碼（程式：`src/batch/faq_generator.py:generate_topic_faqs`；測試：`tests/test_medical_safety.py::test_classify_dosage_prescription_code`）。
- **就醫警訊強制檢驗與免責聲明欄位 (GC-03)**：
  - General 類別問答之 answer 強制要求具體症狀或數值條件之就醫警訊收尾句，實測正例 15/15 通過、負例 17/17 攔截；單純「若症狀加重請回診」單獨出現視為不合規。**複審補強**：勸人別就醫的反向句（「胸痛時不要去醫院」「無需前往醫院」）不算警訊；條列式「請儘速就醫：1. 高燒超過3天 2. 呼吸困難」會併入前一行判斷（LLM 回答「何時就醫」最常見的格式）。外科微創警訊（Phase 20 加固）：危險症狀擴充為紅腫、化膿、流膿、發炎、滲血、組織壞死等。否定語境以同一分句內「否定詞＋≤4 個非標點字元」判定（`_NEG_PRE`），如「不紅腫」「沒有明顯紅腫化膿」「未見化膿」一律不得充當具體警訊；代價是「沒有好轉的紅腫化膿」這類句子會被保守拒絕（Fail-Closed 取向，可接受）。
已知寬鬆：「出現高燒時應就醫」（單獨一個危險症狀即算具體條件）視為合格（程式：`src/ingestion/medical_safety.py:has_doctor_warning`；測試：`tests/test_medical_safety.py::test_classify_missing_doctor_warning_code`）。
  - **2026-10-19 經使用者核准新增警訊症狀詞**：危險症狀（`_SYMPTOM`）詞庫新增「持續性疼痛」與「異常腫脹」兩詞（僅限此二詞，其餘規則與 `_NEG_PRE` 維持不變）。
  - 批次生成針對 general 主題注入第 9 條 Prompt 就醫警訊收尾規則，違規者以 `missing_doctor_warning` 剔除（程式：`src/batch/faq_generator.py:build_seed_faq_prompt`；測試：`tests/test_medical_safety.py::test_prompt_build_seed_faq_prompt_rules`）。
  - 雙向資料同步匯入（`/api/v1/sync/import`）對 general FAQ 實施前置合規檢核，劑量違規或缺警訊者以 HTTP 400 整批原子性阻斷；special 類別維持豁免（程式：`src/api/routes/sync.py:import_sync_data`；測試：`tests/test_sync_general_validation.py::test_sync_import_general_faq_dosage_blocked_and_atomic`）。
  - 自然語言查詢回應結構純加法擴充 `disclaimer: Optional[str] = None` 欄位；當 `data_level == 'general'` 時自動附帶法定醫療免責宣告文字，診所層級為 null（程式：`src/query/router.py:handle_query`；測試：`tests/test_query_disclaimer_field.py::test_query_response_disclaimer_general_shortcut`）。
  - 匿名諮詢端點與自然語言查詢端點在 general 題目命中時皆附帶免責聲明（程式：`src/api/routes/query.py:_execute_query`；測試：`tests/test_query_disclaimer_field.py::test_api_query_endpoint_disclaimer`）。
- **醫師審核工具增強與衝突比對 (GC-04)**：
  - 提供共用覆蓋率純函式，沿用與快取短路同一套標準化與覆蓋率計算（程式：`src/query/faq_shortcut.py:faq_coverage`；測試：`tests/test_faq_conflicts.py::test_faq_coverage_measurements`）。
  - 審核 general 問答時自動檢索相近診所 FAQ，門檻引用 `CLINIC_RELATED_FLOOR = 0.4`，嚴格隔離未核准之 LLM 生成診所問答，支援 mode=ro 唯讀連線（程式：`src/pageindex/faq_conflicts.py:find_similar_clinic_faqs`；測試：`tests/test_faq_conflicts.py::test_find_similar_clinic_faqs_retrieval`）。
  - 審核工具 `review_faq.py list` 支援 `--topic` 主題篩選與來源/驗證結果顯示；`show` 顯示生成來源、驗證結果與相近診所問答；`approve` 強制檢驗 general 警訊（程式：`scripts/review_faq.py:main`；測試：`tests/test_review_faq_cli.py::test_cli_show_general_similar_clinic_faqs`）。
- **被駁回題目手動標記重生成 (DEBT-03)**：
  - 唯一標記函式 `mark_for_regeneration` 僅允許標記 `rejected` 狀態之 `llm_generated` 項目（程式：`src/pageindex/faq_review.py:mark_for_regeneration`；測試：`tests/test_faq_regen.py::test_mark_for_regeneration_restrictions`）。
  - 批次生成 `existing_questions` 支援 `exclude_regen_marked=True`，優先處理被標記之主題（程式：`src/batch/faq_generator.py:existing_questions`；測試：`tests/test_faq_regen.py::test_existing_questions_exclude_regen_marked`）。
  - CLI `mark-regen` 子命令提供醫師標記入口，未帶 `--allow-prod-db` 於連線前以 code 2 阻斷正式庫操作；新增 `--seed`（預設 `data/batch/faq_seeds.json`），**題目不在人寫種子清單內者回報 `not_in_seed` 並拒絕標記**（夜間批次只重生成種子內題目，種子外的旗標會永遠殘留）；種子檔載入失敗時僅警告並略過此檢查。`list` 新增「重生」欄顯示「待重生」（程式：`scripts/review_faq.py:main`；測試：`tests/test_review_faq_cli.py::test_cli_mark_regen_subcommand`）。
  - 端到端重生成生命週期：標記重生成後新答案以 `pending` 入庫且版號遞增；若模型回傳相同答案則清除重生成旗標並維持 `rejected`，避免無限生成（程式：`src/batch/runner.py:run_batch`；測試：`tests/test_phase12_acceptance.py::test_04_regeneration_lifecycle_debt03`）。
- **端到端驗收保證**：
  - 17 題正式種子批次生成後預設 pending 隱蔽；醫師 CLI 核准後自然語言與一般諮詢皆正確命中；正式庫 SHA-256 全程未變（程式：`tests/test_phase12_acceptance.py`；測試：`tests/test_phase12_acceptance.py::test_02_e2e_generation_approval_and_consultation`）。
  - 同步匯出閘門：未核准前不外洩 17 筆 general FAQ，核准後包含於匯出資料（程式：`src/api/routes/sync.py:export_sync_data`；測試：`tests/test_phase12_acceptance.py::test_05_sync_export_gate`）。
- **已知限制（架構決策接受）**：
  1. **詞彙守衛非主題守衛**：覆蓋率相近比對（`find_similar_clinic_faqs`）為詞彙重疊守衛；17 題一般疾病種子對院所既有 40 筆醫美外科 FAQ 最高詞彙覆蓋率皆 $\le 0.30$（$< 0.4$），衝突清單為空不代表臨床無指示衝突，審核工具 show 一律附帶醒目警語提示醫師自行比對。
  2. **免責聲明範圍**：僅自然語言查詢 `/api/v1/query`（在 `data_level == 'general'` 時）與匿名諮詢端點 `/api/v1/general/query` 附帶免責聲明；雙向同步匯出（`/api/v1/sync/export`）與審核工具（`review_faq.py`）維持純淨資料結構，不額外附加免責字串。
  3. **重生成採一次標記一次嘗試**：為防範模型死循環，被標記之題目在批次中僅嘗試生成一次；若產出實質新內容則更新入庫回到 `pending`，若產出內容未變則清除重生成旗標並維持 `rejected`（計入 `faq_regen_unchanged`），不重複消耗推論配額。
  4. **劑量／處方層為條件式檢驗**：用藥安全檢核透過 `check_dosage` 與 `require_doctor_warning` 參數啟用，文件擷取（`run_stage1_ingestion.py`）與院所特殊上傳項目預設不強制套用；DX-4/DX-5 對「遵照醫囑」「請勿自行」具有豁免；「給予抗生素」描述性敘述不予攔截；「若醫師開立藥物，請依指示服用」則採保守攔截策略。
  5. **就醫警訊之結構要求**：警訊收尾必須同時具備「具體症狀或數值條件」與「就醫動作」；單獨「若症狀加重請回診」因缺乏具體辨識指引，視為不合規。
  6. **審核狀態變更之警訊檢核預設關閉**：`faq_review.set_review_status` 底層預設 `enforce_general_warning=False`，僅醫師審核 CLI（`review_faq approve`）明確傳入 `enforce_general_warning=True` 進行強制把關。

### 2.13 臨床語音與 SOAP 紀錄擷取（Phase 14 新增）
為接收外部雲端推播（如 `https://doctor-toolbox.com/`）或院內語音聽寫逐字稿，並將臨床資料分析擷取應用於醫療輔助與檢索，自 Phase 14 起導入 SOAP 紀錄接收、去識別化與專屬醫師檢索架構：
- **結構化與純文字雙重相容 (`src/soap/section_parser.py`)**：
  - 支援傳入已結構化之 S/O/A/P 欄位，或從 `raw_text` / `transcript` 純文字中依臨床常見中英標記（S/主訴/病史、O/客觀檢查/理學檢查、A/評估/診斷、P/處置/計畫/醫囑）自動正則切分；無明顯標記時安全退化歸入主訴（`subjective`）。
  - **一般醫學特徵擷取 (`extract_general_medical_insights`)**：從臨床文本中自動辨識常見病症、症狀與衛教照護指示，歸納為一般醫學特徵並回傳摘要與標籤。
- **病患個資去識別化與二次防禦 (`src/soap/deid.py`)**：
  - 身分證字號遮蔽（支援台灣身分證驗證與掩碼）、行動電話（09xx-xxx-xxx）、市話、病患姓名標籤遮蔽為 `[已遮蔽]`。
  - 價格數字全面套用 `deep_mask_prices()` 遮蔽為 `[請致電診所確認]`，杜絕未核定金額寫入。
  - `patient_token` 衍生：未提供 token 且有外部病患識別時，以 HMAC-SHA256 結合環境變數 `CLINICBRAIN_DEID_KEY`（退回 `CLINICBRAIN_ADMIN_API_KEY`）與診所代碼生成偽名化 token；**程式碼內不得有預設金鑰**（身分證搜尋空間小，公開 salt 可被字典攻擊還原），未設定金鑰時帶 `patient_id` 的推播回 503（Fail-Closed）。
  - 遮蔽正則不得使用 `\b`（Unicode 下中文字視為 `\w`，「身分證A123456789」會漏遮蔽），改用 `(?<![A-Za-z0-9])`／`(?<!\d)` 前後斷言。
  - 外部傳入的 `patient_token`／`external_id` 須為安全字元集且不得形似身分證或電話，`tags` 一併去識別化。
  - **已知限制**：自由文本中沒有「姓名／病患：」等標籤的人名無法可靠偵測，不會被遮蔽；推播來源應在上游去識別化，本層僅為二次防線。
- **單一權威寫入函式 (`src/soap/soap_writer.py:upsert_soap_records`)**：
  - 以 `(clinic_id, external_id)` 為唯一約束進行冪等 UPSERT；內容未變則安全跳過，更新時自動更新 `updated_at`。
- **醫師專屬 FTS 檢索與嚴格權限隔離 (`src/api/routes/soap.py`)**：
  - `POST /api/v1/soap/records`、`POST /api/v1/soap/search`、`GET /api/v1/soap/records/{external_id}` 掛載 `verify_admin_key` 認證。
  - 強制綁定 `clinic_id`，落實嚴格診所隔離；公開自然語言查詢端點（`/api/v1/query` 與 `/api/v1/general/query`）完全無法存取 `soap_records`。
- **資料庫遷移單一來源 (`scripts/migrate_soap_schema.py`)**：
  - 從 `src/db/clinic_schema.sql` 動態解析 `soap_records` 表、`soap_records_fts` trigram 虛擬表與 3 個同步觸發器 DDL，支援 `--confirm-prod-backup` 與 `--dry-run`。

### 2.14 臨床 SOAP 衛教提煉與審核流（Phase 15 新增）
為將去識別化之 SOAP 臨床紀錄轉化為合規安全之衛教問答，並提供醫師權威簽核流程，自 Phase 15 起導入臨床衛教提煉與草稿審核架構：
- **衛教草稿提煉 (`src/soap/distiller.py:distill_soap_records`)**：
  - 依疾病（`condition`）分組聚合相同診所 SOAP 紀錄之居家照護重點，只採納出現次數達門檻（`min_occurrences`，預設 2）之照護敘述。
  - 生成標準化問答對（問題為 `【照護指引】罹患{condition}應注意哪些居家照護事項？`），強制附加「何時該就醫」警訊與醫療免責宣告。
  - 提煉產物通過 `deep_mask_prices()` 價格清洗、禁詞攔截與 DX 劑量/處方建議檢驗，違規項目安全跳過。
  - `metadata` 保存溯源資訊（`record_count` 參考病歷筆數、標的疾病、診所代碼），不得含病患個資。
- **草稿暫存與權威寫入 (`src/pageindex/faq_writer.py`)**：
  - 擴充 `source_type='soap_distilled'`，寫入 `faq_cache` 時強制設定 `review_status='pending'`。
  - **寫入路徑絕不自動 ALTER**：`upsert_faqs` 不會替資料庫新增 `metadata` 欄位（任何來源皆然，含 `/api/v1/sync/import`），避免未經確認變更正式庫。寫入 `soap_distilled` 時若缺 `metadata` 欄位（或缺審核欄位），一律拋 `RuntimeError`（Fail-Closed）。
  - **遷移單一來源**：`faq_cache.metadata` 欄位定義在 `src/db/clinic_schema.sql`，由 `scripts/migrate_faq_metadata.py` 擷取並冪等套用（沿用 `migrate_faq_review_status.py` 的 `extract_column_definition`，欄位定義須單行、不含 `--`）。正式庫遷移須先手動備份：
    ```bash
    cp clinic.db clinic.db.bak-$(date +%Y%m%d)
    python3 scripts/migrate_faq_metadata.py --confirm-prod-backup
    ```
    未帶 `--confirm-prod-backup` 於連線前以結束碼 2 拒絕；`--dry-run` 僅預覽 DDL。測試複本由 `tests/conftest.py` 顯式套用此遷移。
  - **重跑冪等**：內容（問題/答案/類別/主題）未變時，只刷新 `metadata`，不遞增 `content_version`、不重設審核狀態（已核准草稿不會被重跑打回 `pending`）；內容實質變更才遞增版號並回到 `pending`。
  - 在未獲醫師審核核准前，`visible_faq_sql` 確保待審（`pending`）與已駁回（`rejected`）草稿對公開查詢端點（`/api/v1/query` 與 `/api/v1/general/query`）、快取短路與同步匯出絕對隱蔽不可見（Fail-Closed 隔離）。條件為 `source_type IS NULL OR source_type NOT IN ('llm_generated','soap_distilled') OR review_status='approved'`；**必須保留 `IS NULL` 分支**——SQL 的 `NOT IN` 遇 NULL 結果為 unknown，會讓 `source_type` 為 NULL 的既有列誤被隱藏。
- **醫師審核工具擴充 (`scripts/review_faq.py` 與 `src/pageindex/faq_review.py`)**：
  - `list` 命令支援 `--source soap_distilled` 篩選專用提煉草稿。
  - `show` 命令自動解析 `metadata` 並顯示 `[臨床病歷溯源]` 區塊（參考病歷數與標的疾病）。
  - `approve` / `reject` 命令支援核准與駁回，核准時自動重跑醫療合規檢核，核准後始開放對外短路命中。`set_review_status` 對非 `llm_generated`／`soap_distilled` 之列回報跳過碼 `not_reviewable`（原 `not_llm_generated`）；`mark_for_regeneration` 仍僅限 `llm_generated`（`soap_distilled` 無重生成流程）。
- **批次執行 CLI 腳本 (`scripts/distill_soap_faqs.py`)**：
  - 提供 `--clinic-id`、`--min-occurrences`、`--dry-run` 與 `--confirm-prod-backup`。
  - 對正式庫操作若未帶 `--dry-run` 且未帶 `--confirm-prod-backup` 於連線前回退結束碼 2。
  - `--dry-run` 以唯讀連線（SQLite `mode=ro` URI）開啟資料庫，零資料庫變更，且不要求資料庫已遷移 `metadata` 欄位。
  - 實際寫入時若資料庫尚未遷移（缺 `metadata` 或審核欄位），印出中止訊息並以結束碼 2 退出，不會自動補欄位。
- **測試慣例**：`tests/test_faq_review_soap.py` 含「寫入路徑不自動 ALTER」與「重跑不重設已核准」回歸測試；`tests/test_faq_review_gate.py::test_visible_faq_sql` 把關 `IS NULL` 分支。

### 2.15 定時自動化同步與批次提煉排程（Phase 16 新增）
將 Phase 14（SOAP 擷取）與 Phase 15（衛教提煉）接進夜間批次，形成「前置同步 → 提煉草稿 → 晨間醫師審核」閉環：
- **批次階段順序（`src/batch/runner.py:run_batch`）**：0a 前置增量同步（選用）→ 0b SOAP 提煉（`distill_soap_records`）→ FAQ 預生成 → 推理樹重建。`--skip-soap` 與 `--soap-only` 互斥（argparse mutually exclusive）；預設啟用提煉、不啟用前置同步。
- **Fail-Closed 保證**：提煉產物一律經 `faq_writer.upsert_faqs(source_type='soap_distilled')` 寫入 `review_status='pending'`；`visible_faq_sql` 使 pending／rejected 草稿對快取短路、`/api/v1/query`、`/api/v1/general/query` 與同步匯出絕對隱蔽，醫師 `approve` 前不可見。批次本身永不核准任何草稿。
- **連線模式**：`--dry-run` 以 `mode=ro` 唯讀連線開庫且不執行前置同步（不連網、不寫入）；非 dry-run 才取得 `<db>.nightly.lock` 非阻塞檔案鎖並以可寫連線執行。正式庫非 dry-run 仍須 `--allow-prod-db`。`review_faq.py pending-summary` 為唯讀（`mode=ro`），且未遷移庫（缺審核欄位）回結束碼 2。
- **前置同步（`src/sync/soap_sync_runner.py`，以 `--soap-sync-url` 啟用）**：
  - 失敗策略＝**降級繼續**：拉取或寫入失敗時 `soap_sync_status` 為 `degraded`／`failed`、`errors` 加 1，並對連線 `rollback()`，批次仍以既有本機病歷繼續提煉；不因網路問題讓整晚批次落空。日誌與錯誤訊息只記例外類別，不記 URL 與回應內容（URL 可能夾帶憑證）。
  - 遠端 URL 僅允許 `https`（或 `http://localhost|127.0.0.1|::1` 供本機測試），拒絕 `file://`、`ftp://` 與明文遠端；回應上限 10 MB；API 金鑰只從環境變數 `CLINICBRAIN_SOAP_SYNC_API_KEY` 讀取，**不接受命令列傳入**（避免出現在 `ps`／shell history），且 `BatchConfig.soap_sync_api_key` 設 `repr=False`。
  - 提煉階段中途失敗同樣 `rollback()`，避免未提交交易被後續階段一併提交。
- **去識別化與二次防護（`process_soap_records`，比照 `/api/v1/soap/records`）**：S/O/A/P 與 `raw_text` 一律經 `deidentify_text()`（內含身分證／電話／姓名標籤遮蔽與 `deep_mask_prices()`）；`tags` 逐項去識別化後以逗號串接。`external_id` 與外部 `patient_token` 必須通過 `is_safe_identifier`，否則略過該筆（計入 `skipped_unsafe`）。僅有 `patient_id`（或兩者皆無）時一律以 HMAC 衍生 token，**未設定 `CLINICBRAIN_DEID_KEY` 即略過該筆（Fail-Closed）**；嚴禁把原始病患識別碼當 token，也不得以 `PTK-{external_id}` 等可預測值備援。
- **晨間審核通報**：`python3 scripts/review_faq.py pending-summary` 彙整待審草稿（SOAP 提煉／LLM 預生成／其他，依疾病分組並顯示參考病歷筆數）。簽核指引刻意不產生批次 `approve` 指令，要求先逐筆 `show` 檢視。
- **Systemd**：正式排程單元為專案根目錄 `clinicbrain-nightly.service`／`.timer`（凌晨 02:30，見 2.10 節）。Phase 16 曾重複產生 `templates/systemd/` 另一組範本（03:00，與根目錄單元衝突），已於複審後移除，排程單元以根目錄為唯一來源；專案依規範不代為啟用任何 systemd 服務。
- **已知限制**：① 提煉為詞彙級關鍵字統計，草稿品質仰賴醫師審核；② 前置同步目前只支援單一遠端端點與 POST `{clinic_id, since_days}` 契約；③ 同一病患多筆病歷會重複計入 `record_count`（以病歷筆數而非病患數計）。
- **測試**：`tests/test_phase16_hardening.py`（Fail-Closed 略過、URL 限制、rollback、旗標互斥、草稿隱蔽、前置同步失敗不中斷）、`tests/test_nightly_soap_batch.py`、`tests/test_soap_sync_runner.py`、`tests/test_nightly_full_schedule_e2e.py`。

### 2.16 定時一般醫學知識補充與批次擴充（Phase 17 新增）
讓夜間批次能分批、可續跑地擴充「一般醫學（`category='general'`、`clinic_id IS NULL`）」衛教草稿，供醫師晨間簽核：
- **種子擴充（`data/batch/faq_seeds.json`）**：除 Phase 12 的 4 個常見疾病外，新增 8 個一般醫學主題（高血壓、第二型糖尿病、蕁麻疹、氣喘、胃食道逆流、痛風、帶狀皰疹、偏頭痛，各 4 題，共 32 題，皆帶 `question_tags`）。題目全為人工撰寫的「什麼是／常見症狀／何時就醫／居家照護」四型，不含價格數字、不含藥名與劑量、不含療效保證字樣；載入時仍強制通過 `load_seed_file` 四層檢驗。**題目刻意不問用藥**，慢性病（高血壓、糖尿病、氣喘、痛風）的用藥細節屬處方範疇，不由批次預生成。
- **Fail-Closed 保證**：批次生成之 general 草稿一律走 `faq_writer.upsert_faqs(source_type='llm_generated')`，`review_status` 恆為 `pending`；經 `visible_faq_sql` 對 `/api/v1/general/query`、`/api/v1/query` 快取短路與同步匯出完全隱蔽，直到醫師 `review_faq approve`（核准時重跑四層檢驗＋就醫警訊強制檢驗）。生成階段另強制 general 答案含具體症狀／數值條件的就醫警訊收尾句（見 2.12）。
- **批次旗標（`scripts/run_nightly_batch.py`，`src/batch/runner.py`）**：
  - `--general-only`：只做 general 主題 FAQ 預生成；不做 SOAP 前置同步與提煉，也不重建推理樹。
  - `--skip-general`：略過 general 主題（保留診所專屬主題）。
  - 互斥：`--general-only` 與 `--skip-general`（argparse 互斥群組）、`--general-only` 與 `--soap-only`（CLI 結束碼 2）、`--general-only` 與 `--skip-faq`（矛盾，結束碼 2）。`BatchConfig.__post_init__` 對程式化呼叫同樣拒絕這三種矛盾組合（`ValueError`），不靜默擇一。
- **斷點續跑精確度**：規劃階段與生成階段共用 `existing_questions(..., exclude_regen_marked=True)` 並同樣以 `strip()` 比對——已存在（含 pending／rejected）的題目跳過；僅「`rejected` 且 `needs_regeneration=1` 的 `llm_generated`」題目會重新進入待生成清單。全部題目皆已存在的主題不佔 `--max-faq-topics` 名額，因此預設每晚 5 主題、約兩晚即可補齊 12 個 general 主題。`max_pending`（預設 200）仍保護醫師審核負擔。
- **摘要與可觀測性**：`BatchSummary.general_generated_count`（新增＋重生成更新）與 `general_skipped_count`（已存在而略過）；日誌仍遵守不記錄問句／答案原文。
- **審核工具**：`review_faq.py list --category general|special` 與 `pending-summary --category ...`；pending-summary 將 LLM 草稿分為「診所專屬」與「通用衛教」兩區，仍不提供批次核准指令。`faq_review.list_faqs` 新增 `category` 篩選。
- **已知限制**：① 被駁回且未標記重生成的題目永不重新生成（見 2.10 已知限制 5）；② general 草稿的醫學正確性完全仰賴醫師審核，四層檢驗僅攔截格式／合規類風險；③ 慢性病主題的衛教不涵蓋用藥，若醫師需要用藥說明須人工撰寫（`manual` 來源）。
- **測試**：`tests/test_general_faq_seeds.py`、`tests/test_nightly_general_batch.py`（含複審新增的矛盾旗標與 pending 隱蔽測試）、`tests/test_general_expansion_e2e.py`。

### 2.17 診所資料上傳與管理 Web App（Phase 18 新增）
讓診所人員與醫師以瀏覽器完成「文件上傳 → 待審草稿 → 醫師簽核 → 對外生效」，免用 CLI：
- **審核閘門來源集中定義**：`src/pageindex/faq_review.py:REVIEW_GATED_SOURCES = ('llm_generated','soap_distilled','web_upload')` 是「未核准前對外隱蔽」來源的唯一定義，`visible_faq_sql`、`list_faqs`、`set_review_status` 與 `faq_writer`（預設 `pending`、缺審核欄位時 Fail-Closed 拒寫）皆引用它；新增受控來源只改這一處。
- **為何新增 `web_upload` 而非沿用 `clinic_upload`**：`clinic_upload`（CLI 擷取、`/api/v1/sync/import`）被定義為院所權威來源，**恆為可見**；若 Web 上傳沿用它，即使 `review_status='pending'` 也會被公開端點查到（Fail-Open）。Web 上傳因此使用獨立的 `web_upload`，由 `upsert_faqs` 直接以 `pending` 寫入（無「先 approved 再改回 pending」的競態窗口）。
- **管理 API（`src/api/routes/admin.py`，前綴 `/api/v1/admin`，全部掛 `verify_admin_key`）**：
  - `POST /upload`：僅 `.docx/.xlsx/.pdf`、上限 15MB（最多多讀 1 byte 判斷超限）；檔名取 basename 防路徑穿越；驗證檔頭（zip `PK\x03\x04`／`%PDF-`）；診所代碼須存在於 `clinic_info`（否則 404）；內文依序 `to_traditional` → `deidentify_text` → `deep_mask_prices`；單檔最多 200 段、單段答案 3000 字；每段再過 `validate_single_faq` 四層驗證，違規段落單筆剔除並回報 `rejected_paragraphs`；`preview_only=true` 不寫庫。暫存檔於 `finally` 刪除。
  - `GET /review/faqs`（`status`／`category` 以 pattern 驗證，`clinic_id`、`source_type`、分頁；回傳含 `metadata` 溯源）、`POST /review/faqs/{id}/approve|reject`（走唯一權威 `set_review_status`，核准前重跑合規驗證）、`GET /review/summary`（唯讀連線）。
- **前端（`src/web/static/`，純 HTML／Vanilla JS，掛載於 `/admin`）**：所有動態內容以 `textContent` 寫入（防儲存型 XSS）；API Key 存 `sessionStorage`（分頁關閉即失效），經 `X-API-Key` 標頭送出，不用 Cookie（故無 CSRF 面）；SOAP 檢索使用 `POST /api/v1/soap/search`（需金鑰與機構代碼，問句不進 URL）。`/admin` 回應帶 CSP（`script-src 'self'`、`frame-ancestors 'none'`）、`X-Frame-Options: DENY`、`no-store`。樣式使用 jsdelivr CDN 的 Tailwind CSS（僅樣式，無第三方腳本）；離線部署時樣式會退化但功能不受影響。
- **多檔／資料夾上傳（前端）**：上傳中心可在檔案對話框多選（Ctrl+A）、按「選擇資料夾」、或把整個資料夾拖進來（`webkitGetAsEntry` 於 drop 事件同步取得後再遞迴，`readEntries` 迴圈讀至空批）。僅收 `.docx/.xlsx/.pdf`，略過 `~$` 鎖檔與隱藏檔，單檔 >15MB 或空檔標示略過，清單上限 200 個；**同檔名（不含副檔名）只收第一個**，因後端以檔名作為主題鍵 `doc-<檔名>`，同名檔會互相覆蓋。仍沿用單檔端點，前端逐檔依序送出並各自回報成功／失敗，單檔失敗不影響其他檔；檔名一律以 `textContent` 顯示。
- **正式庫保護**：測試全程用 `isolated_db_path` 複本；Web 服務使用的資料庫由 `config.db_path` 決定，部署時才指向正式庫。
- **已知限制**：① 文件段落轉草稿的規則簡單（以空行分段、`問：／答：` 或問號結尾辨識問答），醫師須逐筆檢視；同一檔案改段落順序重傳會產生不同「指示 N」題目；② 相同診所＋主題＋題目重傳且內容有變時，既有已核准項目會回到 `pending`（需重新簽核）；③ 全域 CORS 為 `allow_origins=["*"]`（沿用既有設定），管理端點仰賴金鑰標頭而非來源限制；④ OCR 不支援，掃描版 PDF 會被拒絕。
- **測試**：`tests/test_admin_api.py`（含複審回歸：web_upload＋pending 隱蔽、檔頭／診所／段落數／保證療效剔除／過濾參數／路徑穿越）、`tests/test_web_ui.py`（含安全標頭）、`tests/test_webapp_e2e.py`（上傳→pending→公開端點隱蔽→核准→快取短路命中）。

### 2.18 Web 臨床操作體驗與 AI 協同工作流（Phase 19 新增）
解決醫師實機反饋的兩個痛點：上傳「只有問題清單」的文件缺答案、逐筆簽核太繁瑣。三個新端點皆掛 `verify_admin_key`：
- **批量簽核 `POST /api/v1/admin/review/batch`**：`{action: approve|reject, faq_ids: [int]}`（`extra=forbid`、`StrictInt`、1～100 筆，布林與字串被拒；後端 `batch_review_faqs` 先對 ID 去重）。走唯一權威 `set_review_status` 的**單一次 commit**：逐筆合規檢驗失敗者（含 `not_reviewable`，即 `manual`／`clinic_upload` 等權威來源）列入 `failed_ids`／`failed_reasons`，其餘於同一交易生效；任何非預期例外一律 `rollback`，不留半提交。回傳 `success_count`／`failed_count`／`processed_ids`／`failed_ids`。
- **內聯修訂 `PATCH /api/v1/admin/review/faqs/{id}`**（`faq_review.update_faq_content`）：僅限審核閘門來源（`REVIEW_GATED_SOURCES`）且**非 approved** 的列——已核准內容不得被靜默改寫（須先退回待審）；文字先 `deidentify_text` ＋ `deep_mask_prices`，再過四層驗證＋劑量檢驗（general 另需就醫警訊）；修訂後狀態一律回到 `pending`（被駁回的草稿修訂後重新進入待審）、`content_version` +1、`metadata.answer_source='manual_edit'`；題目與同診所同主題重複回 422，找不到 404、不可編輯 409。
- **本機 LLM 生成 `POST /api/v1/admin/review/faqs/{id}/generate-answer`**（`src/pageindex/answer_generator.py`）：
  - 僅走本機 `llama-server`（`admin._local_llm_call`，逾時 300 秒；實測 Qwen3.8-27B 單題 68～122 秒，故前端提示「約 1～3 分鐘」），內容不外流雲端；`_GENERATION_LOCK` 非阻塞鎖使同時只處理一題（忙碌回 429），鎖於 `finally` 釋放；LLM 離線回 503 並給繁中處置提示。
  - 「真正的問題」判定：題目欄為實際問句則直接使用；題目欄是上傳佔位題（`【診所文件】… - 指示 N`）且答案欄僅為**單行問句**（問題清單型文件）時，以該行為問句，生成成功後把題目欄改寫為真正問句（否則公開查詢無法比對）。佔位題但答案是多行指示內容者視為已有實質內容，未明確 `overwrite=true` 不得覆蓋（409）；答案已完整（≥30 字且非問題清單）同樣需 `overwrite`。
  - 輸出檢驗（全部通過才寫入）：移除 `<think>` 區塊與「答：」前綴 → `sanitize_faq_text`（去識別化＋價格屏蔽）→ 長度 100～600 字 → `validate_single_faq(check_dosage=True, require_doctor_warning=True)`（簡體／政治立場／保證療效／價格／劑量／具體症狀的就醫警訊）。未通過回 422 並**不寫入**。Prompt 注入（題目要求忽略規則、輸出價格）無法繞過輸出端檢驗。
  - 寫入以樂觀鎖（`WHERE answer IS ? AND review_status != 'approved'`）防並行修改；狀態維持 `pending`，`metadata.answer_source='local_llm'`，前端標示「本機 LLM 生成・待醫師確認」。
- **列表 `GET /review/faqs`** 新增 `needs_answer`（`answer_generator.is_answer_thin`）供前端標示「⚠️ 答案待補齊」，判定邏輯只在後端一處。
- **前端（`src/web/static/`）**：全選／反選／清除與「已選取 X / Y 筆」計數、底部浮動操作列（選取時滑入，批量核准／駁回，每 100 筆分批送出，失敗項目保留於清單並提示原因）、卡片 checkbox 與點擊卡片空白處切換、單題「🤖 本地 LLM 生成解答」（有答案時改為「🔄 重新生成」並二次確認 overwrite）、「✏️ 編輯」內聯編輯、Spinner／骨架屏／Toast。來源篩選補上 `web_upload`（先前遺漏，網頁上傳草稿原本無法篩出）。**所有伺服器或使用者資料一律以 `textContent` 寫入**；`tests/test_web_ui_v2.py` 以靜態掃描確認審核區塊不含 `innerHTML`／`insertAdjacentHTML`／`document.write`／`eval`（SOAP 區塊僅剩固定字串）。
- **不做批量 AI 生成**：本機模型一次只能處理一題且單題需 1～2 分鐘，批量生成會長時間佔用推論並與夜間批次爭用；醫師逐題決定是否生成。
- **已知限制**：① AI 生成內容的醫學正確性仍完全仰賴醫師逐筆確認，檢驗僅攔截格式／合規類風險；② 生成不會參考診所既有 FAQ 或推理樹，屬一般性衛教；③ 單次列表最多載入 200 筆，超過時提示處理後重新整理；④ 批量核准不會阻擋「答案待補齊」的列（醫師可能刻意核准純指示文字），僅在介面標示警示。
- **測試**：`tests/test_admin_batch_and_ai.py`（批量／編輯／生成／認證）、`tests/test_phase19_hardening.py`（權威來源不可被批量改動、鎖釋放、think 區塊、prompt 注入、XSS 純文字、欄位白名單）、`tests/test_web_ui_v2.py`、`tests/test_clinical_ux_e2e.py`（問題清單上傳 → 生成 → 全選／反選 → 批量核准 → 公開查詢短路命中，未生成者仍隱蔽）。

### 2.19 管理端「向 LLM 提問」檢驗頁籤（Phase 20 新增）
讓醫師／管理者對本機模型實際提問，觀察它如何「只根據系統資料」作答，用來評估資料覆蓋度與回答品質：
- **端點 `POST /api/v1/admin/ask`**（`verify_admin_key`，`{question<=300 字, clinic_id}`，`extra=forbid`；診所須存在否則 404）。使用 `get_read_db` 唯讀連線，**不寫入任何資料**；與 AI 生成共用 `_GENERATION_LOCK`（本機模型一次只服務一件事，忙碌回 429，離線回 503）。
- **模組 `src/pageindex/rag_ask.py`**：
  - 檢索走 `handle_query(..., cache_shortcut=False)`，因此只取得**對外可見**資料（已核准 FAQ、推理樹、診所備註、診所基本資料），與公開端點共用同一審核閘門——**未核准草稿絕不進入模型 context**（`tests/test_admin_ask.py` 以待審「答案」不得出現在 prompt 驗證）。
  - 紅旗急重症問句（`detect_red_flag`）不呼叫模型，直接回固定就醫指示；檢索不到任何資料時**不呼叫模型、不憑空作答**，回報 `no_evidence`。
  - Prompt 要求：僅依資料作答、資料不足須明說、句末標示來源編號（`[F1]`／`[T1]`／`[N1]`）、禁金額／藥名劑量／療效保證、涉及不適須給具體就醫警訊。
  - 輸出經 `sanitize_faq_text`（去識別化＋價格屏蔽）與 `validate_single_faq(check_dosage=True)`；結果以 `compliance.ok/reason` 回報。**管理端為了評估模型品質，未通過合規時仍顯示答案但明確標示警告**——對外端點永遠不會輸出此類內容。
  - 回傳 `mode`（`answered`／`no_evidence`／`red_flag`）、`used_llm`、`sources`（編號、類型、診所／通用層級、標題）。
- **前端「💬 向 LLM 提問」頁籤**（位於 SOAP 紀錄頁籤之後）：機構代碼、問題輸入（Ctrl+Enter 送出）、範例問題按鈕、結果卡片（模式徽章、合規徽章、答案、模型可見的資料來源清單）、本次瀏覽的提問紀錄（記憶體內，不落地）。全程 `textContent` 渲染，有靜態掃描測試。
- **取樣設定（重要踩雷）**：本機 llama-server 啟動時設有 `--dry-multiplier 0.8 --repeat-penalty 1.05`（重複懲罰，利於自由寫作）。實測 RAG 提問在此設定下，模型為避免「重複 context 內出現過的字」而改用近似字或掉字（如「清創」→「清、」、「包紮」→「包紝」、「[F2]」→「[3]」）。因此提問一律於**單次請求**以 `local_llm_call(..., sampling=FAITHFUL_SAMPLING)` 覆寫 `temperature=0.1, dry_multiplier=0, repeat_penalty=1.0`（逾時 420 秒），不改動伺服器設定；任何「忠實引用資料」的新功能都應比照。自由撰寫類（如 generate-answer）維持預設。
- **資料品質觀察**：此頁籤會如實呈現資料瑕疵——例如診所 FAQ 原文本身含錯字「包紝」，模型會忠實照抄；發現後應由醫師於待審／既有資料修正，而不是在回答端掩蓋。
- **隱私**：問題只經本機 llama-server，不外送；紀錄僅存在瀏覽器分頁記憶體。
- **已知限制**：① 回答品質取決於已核准資料的覆蓋度——這正是此頁籤要讓醫師看見的；② 檢索為詞彙式（FTS5 trigram），措辭差異大的問法可能找不到資料；③ 單題約 1～3 分鐘，與 AI 生成互斥執行。
- **測試**：`tests/test_admin_ask.py`（僅用可見資料、無資料／紅旗不呼叫模型、價格屏蔽與合規標示、認證與錯誤碼、唯讀、頁籤結構）。

### 2.20 批次補齊答案（先讓 LLM 補、最後一起審）（Phase 21 新增）
文件上傳後常有大量「答案待補齊」的草稿（問題清單，或文章被切成標題片段）。醫師希望先由本機 LLM 批次補齊，最後再一起審核：
- **草稿三種型態（`answer_generator.classify_draft`）**：① `question`（題目欄是問句，或佔位題下答案欄為單行問句）；② `topic`（佔位題下答案欄為單行短片段，如「- 常見疑難傷口型別」，≤40 字、非問句，視為標題／小標題）；③ `content`（已有實質內容，未明確 `overwrite` 不得覆蓋）。
- **標題片段以文件內文為依據**：同一份文件（同診所＋同 `topic_key`）的其他段落作為依據——短片段入「文件大綱」（≤15 條）、實質段落入「內文節錄」（總量 ≤1500 字）；Prompt 要求只能使用文件內資訊、資訊不足須回「資料不足」、輸出固定「問題：／答案：」兩段並自擬病患問句（≤80 字、以「？」結尾，不合格則用保底問句 `關於「<片段>」有哪些重點？`）。同文件無任何內文可依據時回 422，不憑空生成。此型態使用 `_local_llm_ask_call`（忠實引用取樣：關閉重複懲罰，見 2.19）；`metadata.generated_from='document_context'`。模型自擬的問句若與同文件既有題目重複（UNIQUE 限制），自動改用保底問句重試一次。
- **背景作業（`src/pageindex/batch_answer_job.py`）**：單題約 1～3.5 分鐘（標題片段帶文件內文，實測 200 秒），故由伺服器背景執行緒逐題處理，不綁在 HTTP 請求上。`POST /api/v1/admin/review/batch-generate`（`faq_ids` 1～100、`StrictInt`、`extra=forbid`）啟動；`GET /review/batch-generate/status` 查進度（`state`: idle／running／done／cancelled／aborted，`total/processed/ok/skipped/failed[]/ok_ids/current_id`）；`POST /review/batch-generate/cancel`（目前題目完成後停止，已完成者保留）。皆掛 `verify_admin_key`。
  - **同時只允許一個作業**（再啟動回 409）；與單題生成、向 LLM 提問共用 `_GENERATION_LOCK`（本機模型一次只服務一件事），等鎖期間仍可被取消。
  - **每題各自連線、各自 commit**：中途取消、服務重啟只會中斷「進行中那一題」，已補齊的不會遺失；作業狀態只存記憶體，重啟後歸零。
  - **失敗隔離**：單題合規未通過或非預期錯誤只記入 `failed`，不影響其他題；已完整／已核准／非待審來源記為 `skipped`（`GenerationError.skippable`）；**本機 LLM 離線則整批中止**（`aborted`），不空轉剩餘題目。
  - **合規把關完全沿用單題流程**（價格屏蔽、四層、劑量、就醫警訊）；產出一律 `pending`、`metadata.answer_source='local_llm'`，批次**絕不核准**任何項目。
- **前端**：待審頁籤工具列新增「🤖 批量補齊答案 (N)」（有勾選則只補勾選中「答案待補齊」者，否則補目前可見的全部；單次最多 100 筆，並預估所需時間後二次確認）、「顯示範圍」下拉（全部／只看答案待補齊／只看 AI 生成待確認）、進度面板（進度條、成功／失敗／略過、可取消、失敗原因）。重新整理頁面會接續顯示仍在進行的作業；作業結束後自動重載清單並切到「只看 AI 生成待確認」，方便逐筆檢視後批量核准。全選／反選只作用於**目前可見**的卡片，被篩選隱藏的卡片會自動移出選取集合，避免誤對看不到的項目批量核准。
- **已知限制**：① 作業進度不跨服務重啟；② 內文節錄上限 1500 字，超長文件只取前段；③ 標題片段生成的品質取決於同文件內文是否涵蓋該主題，涵蓋不足時模型應回「資料不足」而被捨棄；④ 仍需醫師逐筆檢視 AI 內容後才核准。
- **測試**：`tests/test_batch_answer_job.py`（型態判定含使用者實例 ID 671、標題片段以內文為依據、無依據／資料不足被拒、撞題保底、批次完成／失敗隔離／略過／LLM 離線中止／單一作業與取消／驗證與認證）、`tests/test_web_ui_v2.py`（新控制項與端點接線）。

### 2.21 背景衛教答案自動生成器與離峰排程（Phase 20 新增）
把「待審草稿答案待補齊」的補齊工作交給本機 LLM 在背景完成，醫師最後一起審核。編號說明：規劃文件原訂為 2.19，但 2.19（向 LLM 提問）與 2.20（批次補齊）已存在，故本節為 2.21。

- **待補齊判斷（唯一來源）**：`answer_generator.is_answer_thin`。Web 介面「⚠️ 答案待補齊」旗標與背景選取共用此函式——不得另立門檻。規則：空白為待補齊；佔位題（`【診所文件】…`）僅 question／topic 型態為待補齊，多段或實質內容（content）不算（生成端會以「已有實質內容」拒絕覆蓋，顯示旗標只會誤導）；非佔位題答案不足 30 字為待補齊。`batch_answer_job.get_pending_unanswered_ids` 另限定 `review_status='pending'` 且來源為審核閘門來源。
  - 歷史踩雷：Phase 20 初版以「長度 < 15」選取，導致問題清單型草稿（如「4. Endolift…？」，約 20 字）全部漏選，正是使用者最主要的案例。已改為共用判斷並以 `test_phase20_hardening::test_selection_uses_same_rule_as_ui` 回歸鎖定。
- **單一背景佇列（Serial Queue）**：`src/pageindex/batch_answer_job.py`。同時只允許一個作業（再啟動回 409）；逐題處理，**一次只推論一題**，符合單張 RTX 2080 Ti 的 VRAM 保護。每題取得 `_GENERATION_LOCK` 才推論，單題生成、向 LLM 提問與背景作業三者互斥（他者回 429）。
- **跨行程互斥（與夜間批次）**：夜間批次在獨立行程執行，原本不共享模型鎖。背景作業開始時以非阻塞 `flock` 取得 `<db>.nightly.lock`（`src/batch/db_lock.py`，與 `scripts/run_nightly_batch.py:lock_path_for` 命名相同，測試比對）；作業結束時釋放。語意：
  - 夜間批次持鎖 → 背景作業拒絕啟動（`POST /autofill/all` 與 `POST /batch-generate` 皆回 409）。
  - 背景作業持鎖 → 夜間批次依既有規則「持鎖略過」（結束碼 0）。**代價**：若 02:30 時仍有背景作業，當晚夜間批次整晚略過（含 FAQ 預生成與推理樹重建）。這是刻意的保守選擇：寧可略過，也不讓兩個行程同時打 `llama-server`（它僅 `-np 1` 一個 slot，排隊會造成 420 秒逾時誤判離線）。
  - 收尾競態：上一作業已寫入最終狀態但尚未釋放鎖時，新啟動回「上一批次補齊作業尚在收尾」，而非誤報資料庫占用。
- **失敗與降級**（`_worker` → `_run_items`，`finally` 必定釋放鎖與 `_db_lock_fd`）：
  - 本機 LLM 離線／逾時（`LocalLLMUnavailableError`）→ 整批 `aborted`，不空轉剩餘題目；**未核准、未改寫任何已完成題目**。
  - 單題合規未通過或其他非預期例外 → 只記入 `failed`，不影響其他題（隔離）。
  - 已完整／已核准／非待審來源 → `skipped`（`GenerationError.skippable`），不計為失敗。
  - 取消：目前題完成後停止；等待模型鎖時亦可取消（每 2 秒檢查）。
  - 執行緒啟動失敗 → 釋放鎖、清空狀態，不留殘鎖。
- **輪詢端點輕量化**：`GET /review/batch-generate/status` 只回傳記憶體快照（`snapshot()` 為複本），**不接受任何資料庫依賴**（測試以 `sqlite3.connect` 攔截驗證），每 3 秒輪詢不會造成資料庫負載。認證由 router 層 `verify_admin_key` 套用。
- **Fail-Closed 待審隔離**：背景產出一律 `pending`、`metadata.answer_source='local_llm'`；對 `visible_faq_sql` 不可見（測試 `test_background_output_stays_hidden_until_approved`）。背景作業**絕不核准**任何項目。
- **夜間批次第 7 階段**（`src/batch/runner.py`，`enable_autofill_answers` 預設 True）：於 FAQ／推理樹之後，以 `max_pending` 為單次上限補齊待補齊草稿。**dry-run 不執行此階段**（`llm_call` 為占位函式、連線唯讀；測試 `test_dry_run_never_calls_llm_for_autofill`）。`--soap-only` 不執行。
- **前端**：頂部「🚀 一鍵背景自動補齊所有答案」（`POST /review/autofill/all`，無待補齊時回 `noop`）、進度橫幅（每 3 秒輪詢，單一計時器）與取消；浮動列「🤖 批量生成所選答案」。全部動態文字以 `textContent` 寫入。**已知 UI 重複**：舊版批次面板與新橫幅並存，兩者由同一狀態驅動，後續應合併為一個。
- **測試慣例（重要）**：`tests/test_phase20_hardening.py` 以 autouse fixture 將 `_local_llm_call`／`_local_llm_ask_call` 換成會拋錯的假函式，**測試一律不得呼叫真實 LLM**（否則會佔用 GPU 並讓測試卡住 200 秒以上，且因模型鎖殘留連帶拖垮後續測試——此為本次實測踩到的真實問題）。
- **已知限制**：① 作業狀態只存記憶體，服務重啟後歸零（已完成的題目仍保留在資料庫）；② 夜間批次以 `max_pending` 作為單次補齊上限，語意上是借用積壓上限當配額，後續可獨立設定；③ 同一草稿若同時被手動生成與背景補齊，後到者會因答案已變而回 409 並計為略過；④ 跨行程鎖僅對同一台機器的 `flock` 有效，不跨主機。
- **本機推論逾時與思考長度優化**（2026-10-12 實機回饋補強）：
  - **逾時放寬至 480 秒**：`src/api/routes/admin.py` 將 `LLM_GENERATE_TIMEOUT_SECONDS` 與 `LLM_ASK_TIMEOUT_SECONDS` 由 300 秒進一步放寬至 480 秒（8 分鐘），避免 Qwen 27B 處理長篇大綱/多段內文時因推論時間較長而誤判離線中斷。前端預估時間同步更新為每題約 5 分鐘。
  - **Prompt 思考長度限制**：`src/pageindex/answer_generator.py`（`build_answer_prompt` 與 `build_topic_prompt`）第一條規則明確要求「思考過程請保持簡潔（不超過 100 字），直接輸出答案本文」，徹底杜絕模型在 `<think>` 中過度推演耗盡 6,144 Token 導致答案 `content` 被截斷為空的邊界問題。
  - **錯誤訊息診斷精確化**：`src/pageindex/batch_answer_job.py` 捕獲 `LocalLLMUnavailableError` 時，將底層具體異常細節記錄於 `failed` 原因中，杜絕模糊的泛用失敗提示。
- **測試**：`tests/test_autofill_backend.py`、`tests/test_autofill_pipeline_e2e.py`、`tests/test_web_ui_v3.py`、`tests/test_phase20_hardening.py`（選取規則與 UI 一致、跨行程互斥雙向、模型鎖併發、取消於等鎖中、斷線與非預期錯誤隔離、收尾競態、執行緒啟動失敗、輪詢無 DB 依賴、dry-run 守門、隱蔽性，共 25 項全部通過）。

### 2.22 臨床決策推理樹審核與提煉擴展（Phase 21 新增）
讓醫師把長篇療程文件提煉為四段式推理樹草稿（`page_index_trees`），經醫師審核後才對外。審查加固後的不變式如下（均由 `tests/test_phase21_hardening.py` 把關）：

- **Fail-Closed 可見性（唯一來源 `tree_review.visible_tree_sql`）**：`llm_generated`、`web_upload` 之樹在 `review_status='approved'` 前對外不可見。所有讀取「對外」資料的路徑都必須套用此條件：`search_page_index_trees`（→ `handle_query`、`/api/v1/query`、`rag_ask`）、**`consult.py` 一般諮詢的樹檢索**（審查時發現直接用 `search_text` 繞過，屬 Fail-Open，已修）、**同步匯出 `sync/export`**（審查時發現無過濾，pending 樹會外送雲端，已修）、**FAQ 生成的樹參考上下文 `reference_from_tree`**（已修，避免未審內容經 FAQ 間接外洩）。
- **夜間重建不得製造未審可見內容**：`db_writer.upsert_trees` 於 `source_type ∈ {llm_generated, web_upload}` 且內容實質變更時，未明確指定 `review_status` 一律回 `pending`。審查時發現原本更新路徑不動 `review_status`，已核准的手寫樹被重建後會以未審 LLM 內容維持 approved（Fail-Open，已修）。重建的「醫囑還原」路徑須一併還原重建前的 `review_status`，否則手寫樹還原後會被隱藏。
- **醫囑保護（`*_physician_notes`）**：提煉器恆寫 `None`，且**忽略模型輸出中的醫囑欄位**（測試以模型刻意偽造醫囑驗證）。提煉**僅能建立新草稿**：`doc_id` 已存在回 409（`TreeConflictError`），絕不覆寫既有醫師手寫樹——審查時發現原本會以 `None` 覆寫醫師註記、並把來源改為 `web_upload`，屬嚴重風險，已修。
- **合規規則單一來源（`tree_distiller.validate_tree_segment`）**：提煉、編輯（`PUT`）、簽核（`approve`）、標題、醫囑欄位全部共用同一份檢驗：價格遮蔽（`deep_mask_prices`）、簡體字、保證療效禁詞、政治立場。`_FORBIDDEN_PHRASES` 已補上 AGENTS 2.5 所列之「百分之百有效、保證根除、徹底根除、一定有效」（審查時發現原清單缺漏，簽核曾可放行）。
- **編輯與簽核防護**：受控來源已核准（或駁回）之樹一經實質修改，自動回 `pending` 重新簽核（與 FAQ 的 Fail-Closed 規則一致）；手寫（`manual`／`clinic_upload`）之樹不受此限（醫師為權威來源）。簽核前必須四段齊全且逐段通過檢驗，否則 422 並保持 pending。
- **併發與 GPU**：提煉路由同時持 `_GENERATION_LOCK`（行程內，與單題生成／提問／背景補齊互斥，忙碌回 409）與夜間批次檔案鎖 `db_lock`（跨行程，夜間批次持鎖回 409）。LLM 離線回 503；其他例外回 500 但**不回傳例外內容**（可能含 SQL 或模型原文），詳情僅入伺服器日誌。
- **輸入防護**：`doc_id` 限定 `^[\w\-]{1,64}$`（422 於送入模型前攔下，不消耗推論）；來源文字超過 3500 字時仍截斷提煉，回應帶 `truncated=true` 明示未涵蓋之部分。
- **遷移冪等與不自動核准（`scripts/migrate_page_index_review.py`）**：欄位定義取自 `clinic_schema.sql`（單一來源），交易性執行，重跑無變更。新增 `review_status` 時，既有手寫與診所上傳列以欄位預設 `approved` 保持零中斷；**既有 `llm_generated`／`web_upload` 列改為 `pending`**（無醫師核准紀錄，Fail-Closed）。手寫範本不受影響。
- **正式庫現況**：正式 `clinic.db` 截至本節撰寫時**尚未套用此遷移**（無 `review_status` 欄位）；讀取端在未遷移時以 `visible_tree_sql` 的退化條件仍排除受控來源。正式套用須先備份並執行 `python3 scripts/migrate_page_index_review.py --confirm-prod-backup`，且須先釐清正式庫 `clinic.db` 近期被替換的來歷（見工作交接紀錄 `.planning/HANDOFF.json`）。
- **測試慣例**：所有 Phase 21 測試以隔離複本套用遷移（`_migrate_copy`）；測試禁止遷移或寫入正式庫（守門斷言）；禁止呼叫真實 LLM。
- **已知限制**：① `upsert_trees` 的更新路徑對醫囑欄位仍是「以傳入值覆寫」，此保護目前由呼叫端（提煉的 doc_id 守門、重建的還原機制）負責，寫入層本身不驗證醫囑來源；② 提煉以 3500 字為界，超出部分不會被提煉；③ 簡體字檢驗為取樣字集（`_SIMPLIFIED_CHAR_SAMPLE`），並非完整字表；④ doc_id 存在性檢查與寫入之間仍有極短的競態窗口（同一行程內已由 `_GENERATION_LOCK` 序列化，跨行程由 `db_lock` 序列化，實務上不會發生）。
- **測試**：`tests/test_phase21_hardening.py`（21 項：Fail-Closed 通道、同步匯出、重建可見性、醫囑保護、編輯與簽核合規、提煉輸入與錯誤處理、FAQ 上下文、遷移冪等與不自動核准）、`tests/test_tree_review_backend.py`、`tests/test_web_ui_trees.py`、`tests/test_trees_e2e_pipeline.py`。

---

### 2.23 多診所管理、網站素材擷取與審核篩選（2026-10-15 新增）
- **診所清單與新增**：`GET /api/v1/admin/clinics`、`POST /api/v1/admin/clinics`（`src/api/routes/admin.py`，`ClinicCreateRequest` 以 `extra=forbid`、代碼須為 10 碼數字、官網須為 https）。新增僅 `INSERT`，代碼重複回 409，**不覆寫既有診所列**。
- **種子來源**：凡登的 `clinic_info` 資料由 `src/pageindex/seed_clinic_info.py:FANDEN_CLINIC_INFO` 與 `seed_clinic_row()`（僅新增）提供；緻妍仍以 `ZHIYAN_CLINIC_INFO` 為唯一來源。
- **Web 前端**：上傳中心、臨床 SOAP、向 LLM 提問的機構代碼為 `<select>`（同 id 沿用原讀值程式），切換時同步三處；「＋ 新增診所…」開啟共用對話框。待審衛教草稿與推理樹頁籤另有 `reviewFilterClinic`、`treesFilterClinic`（「全部診所」或單一診所），請求帶 `clinic_id`。所有動態文字以 `textContent` 寫入。
- **白名單**：`data/scraper/sources.json` 的 `www.nu-vendome.com` 路徑前綴為 `/location-detail/`、`/service/`、`/service-detail/`（後兩者經使用者於 2026-10-15 明確核准）。
- **服務詳細頁擷取**：`src/scraper/service_detail.py:extract_service_detail()` 讀取 `div.contentBuilder` 內的 `<p>` 說明段落；**服務名稱取 `<title>`**（第一個分隔符 `｜`、`|`、` - `、`-凡登` 之前的部分，「？」去除，「、」「，」換為 `·`，超過 80 字於分隔點截斷），原因是段落標題（如「術前注意事項」）不可當作服務名稱。詳細頁說明為 SSR 直接輸出，**不需要無頭瀏覽器**。
- **網址解析分支**：`src/pageindex/web_source_adapter.py:fetch_clinic_page()` 遇 `/service-detail/` 路徑改用上述解析器，機構名稱由端點自 `clinic_info` 傳入（詳細頁不含機構資訊）。`upload-url` 在 `preview_only=false` 且沒有任何可寫入草稿時回 **422**（先前曾回 OK 卻寫入 0 筆，屬隱藏失敗）。
- **身分洩漏剔除（已知行為）**：說明文字若含機構名稱、地址或電話，會整段被身分檢查剔除。目前唯一受影響者為縮鼻翼（`alar-reduction`），依使用者決定維持剔除，未修改原文。
- **服務草稿寫入狀態**：凡登服務草稿共 27 筆（來源 `web_upload`、`metadata.source_url` 含 `service-detail`），原為 `pending`，**2026-10-15 10:27–10:29 經使用者確認核准**（批次核准與單筆核准，皆由管理端發出），目前為 `approved`、對外可見。寫入前後備份為 `clinic.db.bak-20261015b`、`clinic.db.bak-20261015c`、`clinic.db.bak-20261015d`。
- **門診表解析器**：`src/scraper/timetable.py:parse_timetables()` 將「週次 × 星期」表格解析為 `(月, 週, 星期, 開診)`，**不含醫師姓名**（醫師資訊不得進入文字管線）。使用者已指示門診表**不寫入 `clinic_hours`**，改為 pageindex 用途；寫入規格仍待確認，目前未寫入任何資料庫。
- **已知限制**：① 服務名稱仍偏長（如「縮鼻翼是什麼鼻翼過寬…」），僅部分已簡化；② 17 頁無「標題＋說明」結構而略過，3 頁抓取失敗；③ 網站 SEO 標題的品質直接影響草稿題目。
- **測試**：`tests/test_service_detail.py`、`tests/test_timetable.py`、`tests/test_clinic_selector.py`（含靜態檢查）、`tests/test_url_deps_resolver.py`、`tests/test_upload_url_endpoint.py`、`tests/test_scraper_policy.py`。以上範圍 2026-10-15 為 307 passed。

### 2.24 病人「先答後導」諮詢與 LLM 一般知識例外（Phase 26 階段一，2026-10-16 核准）
- **例外（明確覆寫 2.9／2.10 之審核閘門，僅限此處）**：`/api/v1/general/consult` 在沒有已核准資料時，**可即時回覆**本機 LLM 生成的一般醫學說明，但必須同時：標示「一般醫學知識說明，並非本診所醫師意見，尚未經醫師審核」、附免責聲明與就醫警訊、通過價格／禁詞／劑量／問題不得改寫（沿用 `generate_general_draft` 的驗證）。
- 同一問題**同時**存入一般草稿佇列（`category=general`、`clinic_id` 為空、`source_type=llm_generated`、`review_status=pending`），醫師核准後才進入公開快取與一般諮詢的已核准來源。
- 路由順序固定：紅旗 → 已核准資料（`consult_general`）→ LLM 一般說明＋草稿 → 固定文字（`no_match`）。紅旗與已核准資料路徑不呼叫模型。
- 病人端 LLM 以 `_PATIENT_LLM_LOCK` 非阻塞保護（忙碌回 `busy`，不排隊），本機模型單一 slot 不被公開流量拖垮。仍建議於反向代理層加 `limit_req`。
- 預約方式固定為 `https://doctor-toolbox.com/`（HIS 廠商）；留資表單由該平台承接，**本系統不接收、不儲存表單個資**。將來合併該平台程式前，須另行決定資料流與保存期限。
- 隱私：不要求姓名、電話、身分證、照片；不記錄問句原文或對話（`/api/v1/general` 前綴受存取日誌過濾）；草稿佇列僅存去識別化後的問題文字。
- **待辦**：端點的完整實機測試（含真實 LLM 生成耗時）尚未執行；診所專屬 FAQ（`special`）路徑未納入匿名端點，仍由 `/api/v1/query` 處理。
- **Phase 28 補述**：實機探測已於 2026-10-17 完成（見 28-PROBE.md）；診所專屬 FAQ（`special`）已透過伺服器固定設定 `patient_clinic_id` 納入匿名端點安全檢索（詳見 2.25 節）。
- **同題不重複生成**：同題（去識別化後完全相同）已有一般草稿時，`pending` 直接沿用其答案，`rejected` 回固定文字，皆不呼叫模型。
- 測試：`tests/test_patient_consult.py`（紅旗不呼叫模型、生成並標示待審、LLM 失敗不寫入、忙碌不呼叫模型、同題重用）。

### 2.25 病人端對話式諮詢與 24 小時預生成（Phase 28 新增）

為讓病人端諮詢實踐「先提供價值、後獲取資訊」，解決即時生成耗時長、答案截斷與冷啟動等問題，自 Phase 28 起建立對話式組稿、24 小時預生成與非同步作業架構：

- **耗時根因修復與本地 LLM 實機探測（28-PROBE.md）**：
  - 舊版異常耗時根因：`PATIENT_GENERAL_SAMPLING` 舊設定 `max_tokens=12288` 加上空白輸出重試邏輯，在單一 slot 被佔用時最壞延遲可達約 960 秒。
  - 2026-10-17 實機探測結果（Qwen3.8-27B-UD-Q4_K_XL，副本唯讀庫）：
    - 真實解碼速率：實測生成解碼速度為 **22.17 ～ 22.54 tok/s**（平均約 **22.5 tok/s**）。舊版文檔「90 tok/s」實為 Prompt 處理速度（prompt_per_second），非輸出解碼速度。
    - 思考關閉控制：`chat_template_kwargs: {"enable_thinking": false}` 能 100% 關閉本機思考推演（`reasoning_content` 為 0 字元、0 token，耗時從 33.7 秒降至 4.6 秒）；`reasoning_effort: "none"` 對本機 llama-server 之 Qwen3.8 GGUF 完全無效（已自程式碼移除）。
  - 單次呼叫不重試：病人端組稿與未審說明強制設定 `retry_on_empty=False`，避免重複推論倍增等待時間。
  - 取樣常數現值（安全邊界）：即時組稿 `PATIENT_COMPOSE_SAMPLING["max_tokens"] = 800`（最壞延遲約 35.5 秒）；未審說明 `PATIENT_GENERAL_SAMPLING["max_tokens"] = 1500`（最壞延遲約 66.7 秒），遠低於端點 240 秒逾時上限。日後若取得更多真實組稿之 `completion_tokens` 分布數據，可再視實測分布進一步收緊（待驗證）。
  - 截斷異常偵測：當本機 LLM 回傳 `finish_reason == "length"` 時，一律視為異常截斷並拋出 `LLMTruncatedError`，防止不完整回答或遺失警訊之內容對外輸出。

- **答案截斷修復與句界安全截斷 (`src/general/answer_compose.py`)**：
  - 截斷根因：舊版 `rag_ask` 以硬性 500 字元截斷參考資料，導致置於段落末尾之就醫警訊字樣被切斷（如「若出現胸」）。
  - 句界截斷 (`clip_at_sentence`)：純函式實作，截斷時以標點符號（`。！？\n`）為邊界收尾；若文本包含就醫警訊（`_is_warning_sentence`），優先保留警訊句完整性；總參考上下文長度受 `CONTEXT_TOTAL_CHARS = 2000` 嚴格限制。

- **三段式回答結構與程式組裝 (`assemble_answer`)**：
  - 標準結構：**價值回答（2～4 句） ＋ 單一追問 ＋ 固定預約邀請句**（先提供價值、後獲取資訊）。
  - 單一追問：每次僅提出一個與當前療程最相關的追問（以繁體中文問號「？」收尾），絕不連續追問，絕不要求病患提供姓名、電話或個資。
  - 預約邀請句：由常數 `CTA_TEXT` 提供固定文字（「若想進一步評估，可使用下方的預約連結，由醫師親自了解您的狀況。」），對應預約連結 `https://doctor-toolbox.com/`。
  - 四層醫療安全驗證：價值回答段與追問分開獨立檢核（價格屏蔽、簡體字、政治爭議詞、保證療效、用藥劑量 DX-1~6），任一段不合規即觸發降級，保證對外內容 100% 符合法規。

- **查詢路由與降級序列 (`src/general/patient_consult.py`)**：
  1. 急重症紅旗偵測：命中立即同步回傳緊急就醫指示，不建立 job、不呼叫模型。
  2. 已核准資料直答：候選池（診所 special 優先，通用 general 在後）比對，符合 AGENTS 2.8 雙門檻（問句覆蓋率 $\ge 0.9$、FAQ 覆蓋率 $\ge 0.7$）、五維風險特徵對稱、歧義邊界 $\ge 0.1$、最小長度 $\ge 4$ 時，0 次模型呼叫直答（回傳 `status="answered"`）。
  3. LLM 組稿：有已核准候選資料但未達直答門檻時，組裝標註層級（診所／通用）之 prompt 呼叫本地 LLM 生成 2～4 句價值說明與追問。
  4. 確定性降級 (`_deterministic_fallback`)：LLM 離線（`LocalLLMUnavailableError`）或生成驗證失敗（`LLMValidationError`）時，自動摘錄候選池第一句＋固定追問＋CTA，安全回答（`status="answered"`），不中斷對話。
  5. 同題草稿重用：去識別化後若已有一般草稿，`pending` 沿用其答案，`rejected` 回固定文字，皆不呼叫模型。
  6. 2.24 未審醫學說明：無任何已核准資料時，由本機模型生成一般說明，標示未經醫師審核（`LLM_LABEL`），並將去識別化問句存入一般草稿佇列供醫師審核。
  7. 固定文字降級：完全無資料且無法生成時，回傳固定文字 `NO_DATA_TEXT`。

- **共用生成鎖與排程互斥 (`src/pageindex/llm_lock.py`)**：
  - 記憶體生成鎖 `GENERATION_LOCK`：跨執行緒互斥鎖，序列化保護病人端即時生成與背景補齊作業，杜絕多個併發請求同時排入本機單一 slot 造成推論延遲激增。
  - 夜間批次排程互斥：`nightly_batch_running()` 透過非阻塞探測 `<db>.nightly.lock`，若夜間批次執行中，病人端即時推論直接快速回傳 `busy`（`BUSY_TEXT`），絕不與批次爭搶 GPU。
  - 測試雙層安全防護：`tests/conftest.py` 提供函式層攔截拋出 `AssertionError`，以及 socket 連線層阻擋向 `127.0.0.1:8080` 發起真實網路連線，確保測試套件絕不依賴或呼叫本機真實 LLM。

- **非同步作業佇列與純記憶體輪詢 (`src/general/consult_jobs.py`)**：
  - 端點設計：`POST /api/v1/general/consult/jobs` 提交問句取得安全票券；`GET /api/v1/general/consult/jobs/{job_id}` 輪詢結果。
  - 安全票券：`job_id` 為 16 位元組密碼學安全 URL-safe 亂數（正則 `^[A-Za-z0-9_-]{16,64}$`）。
  - 容量與時效：單次讀取即刪除；未讀取保留時間 `RESULT_TTL_SECONDS = 300`；容量上限 `MAX_JOBS = 20`、並發上限 `MAX_RUNNING = 4`，超出上限立即回傳 `busy`，不無限排隊。
  - 隱私承諾：問句僅作為 worker 參數傳遞，registry 狀態序列化（JSON/repr）絕不包含問句原文與診所代碼。
  - 純記憶體輪詢：GET 輪詢端點純讀取記憶體 registry，零資料庫 Depends 開銷，絕不連線資料庫；存取日誌過濾器涵蓋 jobs 端點。

- **夜間批次階段 8：24 小時主體醫學資訊預生成 (`src/batch/patient_prefill.py`)**：
  - 五意圖模板：每個推理樹主題預生成五大常見問答：是什麼（`what`）、適合誰（`who`）、風險併發症（`risk`）、術後短期照護（`post`）、長期維持（`maintenance`）。
  - 新鮮度與重排：`FRESHNESS_HOURS = 24`、`REFRESH_GRACE_HOURS = 2`。
  - 識別與追蹤：以 `topic_key`（`prefill-{doc_id}-{intent}`）為唯一鍵；`metadata` 欄位記錄 `generated_at`（UTC ISO）、`tree_content_version`、`seed_title`、`input_signature`。
  - 簽章與保護規則：已獲保護列（`approved`、`rejected` 或人工編修列）僅在簽章（推理樹版本或標題）實質變更時才重新生成（重置回 `pending`）；`time_stale` 僅對 `pending` 且非人工編修之過期列生效。
  - 永不自動核准：新生成列一律透過 `faq_writer.upsert_faqs(..., source_type='llm_generated')` 寫入，狀態恆為 `pending`，夜間批次絕不自動核准任何列。
  - 時鐘注入與資源防禦：`now_fn` 提供業務 UTC 時間，`clock` 提供時間預算單調時鐘；受 `--max-faq-topics`、`--time-budget-seconds` 與 `--max-pending` 上限約束。
  - 批次摘要統計：包含 `prefill_topics_planned`、`prefill_generated`、`prefill_refreshed`、`prefill_rejected`、`prefill_protected_skipped`、`prefill_skipped_budget`、`prefill_skipped_no_title`、`prefill_backlog`；支援 CLI 旗標 `--skip-patient-prefill`。

- **伺服器固定單一診所設定例外（P28-CLINIC）**：
  - 固定單一診所設定：匿名端點（`/consult`、`/consult/jobs`）的診所範圍由伺服器環境變數 `CLINICBRAIN_PATIENT_CLINIC_ID`（對應 `config.patient_clinic_id`）決定，**無預設值**，程式碼中無任何寫死診所代碼字面值。
  - 安全解析：`resolve_patient_clinic(conn, configured)` 每次使用皆經 `clinic_info` 驗證且為 10 碼數字；無效或資料表缺失時回傳 `None`（Fail-Closed，不改查他院）。
  - 忽略請求夾帶：端點由伺服器設定決定診所，絕不讀取請求主體中的 `clinic_id` 與標頭 `X-Clinic-ID`（一律忽略）。
  - 雙重跨診所隔離：僅經 `visible_faq_sql` 與 `visible_tree_sql` 檢索該診所已核准資料，並以 Python 雙重比對 `row.clinic_id == clinic_id`，不符一律丟棄。
  - 營運關鍵字防護：問句含營運關鍵字（`_CLINIC_OPS_KEYWORDS`，如地址、電話、營業時間等）時直接回傳空證據，不使用診所私有資料；絕不讀取 `clinic_info`、`clinic_hours`、`clinic_custom_notes`。
  - 隱私保護：問句不存庫、不寫入 cache_stats、系統日誌絕不包含問句原文。

- **真實端到端驗收補強與品質防禦（28-10 新增）**：
  - 證據相關度檢核與雙重防禦 (`is_relevant_evidence` / `filter_relevant`)：問句標準化後剔除泛用名詞（`GENERIC_TERMS`，如「照顧、注意、事項、方法、怎麼、可以、在家、平常、哪些、什麼、如何、自己、時候、需要、問題、內容、包含、處理、門診、術後、術前、風險、照護、有沒有、要不要、手術、療程、治療、項目」），取剩餘相鄰 CJK 2-gram 集合（扣除泛用詞 bigrams）。候選資料若與問句無交集即判定不相關（Fail-Closed）；組稿前過濾不相關資料，避免不相干之已核准資料被誤當證據組稿。
  - 模型資料不足輸出攔截 (`looks_insufficient` / `InsufficientEvidenceError`)：若模型組稿輸出包含「資料不足」或（「參考資料」「提供的資料」「現有資料」）且（「無法」「不足」「未提及」「並未」「僅涵蓋」「沒有」），立即拋出 `InsufficientEvidenceError`，自動跳過資料庫預設答覆並放行至 2.24 未審醫學說明路徑，杜絕「現有資料並未提及...」等內部口吻外露。
  - 中性預設追問常數表 (`DEFAULT_FOLLOWUPS["other"]`)：修正為「您目前是否有特定的困擾部位，或想先了解哪方面的照護方式？」，不假設病患諮詢之主題為療程，維持通用中性。
  - 即時組稿提示詞修正與警訊句規範：修正提示詞中「一句具體」錯字，明示警訊句必須包含具體症狀詞（如紅腫、發燒、疼痛、化膿、出血等）與就醫動作，並於 prompt 提供合法示範句（「若傷口出現持續紅腫或化膿，請盡速回診尋求醫師評估。」），大幅提升模型首發警訊句合規良率。
  - 夜間預生成剔除原因結構化細分 (`reject_code_for`)：預生成輸出若表明資料不足（`looks_insufficient`）直接剔除不入庫；驗證失敗原因細分為 `missing_warning`、`price_leak`、`political_phrase`、`simplified_chinese`、`guarantee_phrase`、`dosage_or_prescription`、`sentence_count` 與 `insufficient_evidence`，且日誌 payload 嚴格禁止包含問句或答案原文，兼顧可觀測性與病患隱私。

- **通用衛教與療程專屬追問情境分流（28-11 新增）**：
  - 情境二分原則：追問句依資料來源情境分為療程專用（`procedure`，當且僅當具有診所專屬樹或 FAQ 證據時採用）與中性通用（`general`，2.24 未審醫學說明或僅有通用衛教資料時採用）。
  - 通用中性追問常數表 (`GENERAL_FOLLOWUPS`)：包含六大意圖（`what`, `recovery`, `risk`, `suitable`, `when_to_see_doctor`, `other`）之問句，每句皆經合規檢驗且絕不包含療程專用詞彙（`PROCEDURE_ONLY_TERMS`，如「術後」、「療程」、「手術」、「治療」、「施作」）。
  - 療程術語過濾與安全退回：在 `scope="general"` 情境下，若模型自帶追問包含任一 `PROCEDURE_ONLY_TERMS` 詞彙，立即退回中性預設追問（`GENERAL_FOLLOWUPS`），杜絕通用健康諮詢（如感冒、日常保健）被誤配「術後照護」或「療程安排」追問之違和感；2.24 未審說明裝飾（`decorate_general_answer`）一律強制使用 `scope="general"`。

- **已知限制與維護說明**：
  1. 未設定 `patient_clinic_id` 時，匿名諮詢端點不檢索任何診所資料（只命中一般資料）；正式庫目前推理樹皆為診所專屬，因此未設定 `patient_clinic_id` 時，這些樹來源的預生成內容匿名端點看不到（special 預生成仍可透過 `/api/v1/query` 帶 `clinic_id` 使用）。
  2. 預生成題目標題只來自推理樹的 `title` 或種子 `title`（去除「常見問題」字樣），無中文標題者不進行預生成（計入 `prefill_skipped_no_title`）。
  3. 積壓主題（`prefill_backlog`）受每日主題配額限制，可能跨晚逐步處理。
  4. 未審核之 `pending` 列每 24 小時重新生成會消耗 GPU 計算資源，院所應建立定期審核機制。
  5. 快取統計之未命中關鍵字由 Phase 9 種子機制承接，不在階段 8 預生成內直接使用。

- **測試清單**：
  - `tests/test_patient_consult_latency.py`：延遲修復、finish_reason=length 截斷偵測、單次不重試測試。
  - `tests/test_answer_compose.py`：組稿純函式、句子邊界截斷、就醫警訊優先保留測試。
  - `tests/test_patient_compose.py`：已核准資料組稿、層級標示、確定性降級、2000 字上限測試。
  - `tests/test_consult_jobs.py`：非同步 job 佇列、TTL 過期清理、純記憶體輪詢零資料庫連線、容量上限測試。
  - `tests/test_patient_prefill_plan.py`：24 小時新鮮度規劃層、五意圖模板、簽章規則、受保護列略過測試。
  - `tests/test_patient_prefill_batch.py`：夜間批次階段 8 預生成執行器單元測試、時間預算、待審上限測試。
  - `tests/test_patient_prefill_e2e.py`：夜間批次階段 8 跨日與端到端測試、核准後 0 次模型呼叫直答測試。
  - `tests/test_probe_patient_thinking.py`：本地 LLM 思考關閉實機探測輔助與單元測試。
  - `tests/test_patient_clinic_scope.py`：伺服器固定診所範圍、Fail-Closed、跨診所雙重防禦、忽略請求夾帶、營運關鍵字測試。
  - `tests/test_patient_prefill_special_e2e.py`：special 推理樹預生成核准後直答、未設定不命中、錯誤診所不命中 e2e 測試。
  - `tests/test_general_privacy.py`：一般諮詢隱私守門測試（AST 語法樹靜態掃描確保無 logging、print 或非 SELECT execute）。

### 2.26 一般醫學視覺解說卡（Phase 29 新增）

為協助病患在諮詢時以圖解步驟理解一般醫學原理與照護流程，自 Phase 29 起建立一般醫學視覺解說卡（Visual Explainer Cards）架構：

- **定位與使用者決策**：
  - **純一般醫學知識說明**：解說卡僅提供通用醫學與衛教概念圖解，非個人化診斷，亦非特定診所療效承諾。
  - **合作診所共用資產**：`visual_assets` 資料表最初不設 `clinic_id` 欄位（自 Phase 31 起已擴充 `clinic_id` 欄位，支援診所專屬與一般共用並存，見 2.28 節）。
  - **零個資收集**：解說卡與諮詢頁絕不收集姓名、電話、LINE 或任何表單輸入；預約導流維持既有的單一外部連結 `https://doctor-toolbox.com/`。

- **Typed IR 規格與唯一權威驗證 (`src/visual/ir.py`)**：
  - **結構限制**：頂層鍵必須嚴格為 `{"topic_key", "title", "keywords", "scenes"}`（不允許額外鍵）。`topic_key` 符合 `^[a-z0-9-]{3,64}$`；`title` 為 1～30 字；`keywords` 為 1～8 個（每個 2～12 字）；`scenes` 為 3～5 個場景。
  - **場景與標籤**：每個場景必須含 `{"blueprint", "title", "caption", "labels"}`。`blueprint` 僅限 `"process_diagram"`、`"contrast"`、`"timeline"` 三種固定模板；場景 `title` 1～16 字、`caption` 20～120 字；`labels` 為 0～4 個 `{"text": 1~12字, "tone": "neutral"|"warning"|"optimal"}`。
  - **單一權威驗證 (`validate_ir` / `validate_visual_text`)**：入庫、審核與對外展示前皆強制執行檢驗。除重用 `validate_single_faq(..., check_dosage=True, require_doctor_warning=False)` 與 `deep_mask_prices(text) == text` 攔截價格、簡體字、政治爭議詞、通用保證療效與用藥劑量外，另禁止 HTML 標籤字元（`<`、`>`）、網址（`http://`、`https://`、`www.`、`://`）、`javascript:`、百分比數字（`\d+\s*[%％]`）及視覺卡專屬額外禁詞 `VISUAL_EXTRA_FORBIDDEN`（`永久`、`終身`、`一輩子`、`成為身體一部分`、`百分之`、`存活率`、`保證`、`一定能`、`一定會`、`一定有效`、`絕對`、`完全不會`、`零風險`；刻意不單列「一定」以免誤殺「一定程度」「不一定」「一定時間」）。
  - **零原文錯誤碼**：驗證失敗僅回傳固定英文代碼（`schema_error`、`unknown_blueprint`、`text_unsafe`、`forbidden_phrase`、`price_leak`、`simplified_chinese`、`dosage_prescription`），絕不將違規原文放入錯誤訊息或日誌。

- **資料表與單一來源遷移 (`src/db/clinic_schema.sql`, `scripts/migrate_visual_assets.py`)**：
  - **DDL 位置與回歸保護**：`visual_assets` 與 `visual_stats` 定義於 `src/db/clinic_schema.sql` 最末端 `Sample Data` 標記之後，並以 `-- ===== visual_assets BEGIN/END =====` 包夾，確保舊遷移腳本與 `tests/conftest.py` 的歷史擷取邏輯不含 `visual_` 表。
  - **手動遷移與 Fail-Closed**：正式庫不自動建表，須先備份再執行 `python3 scripts/migrate_visual_assets.py --db-path <path> --confirm-prod-backup`（支援 `--dry-run`）。未遷移時：讀取端（`visible_assets`、`find_visual`）回傳空或 `None`，寫入與審核端拋出 `RuntimeError`，匿名計數端安全回傳 `False`。

- **唯一寫入路徑、預生成與醫師審核 (`src/visual/writer.py`, `src/visual/generator.py`, `src/visual/review.py`)**：
  - **唯一權威寫入 (`upsert_assets`)**：整批先經 `validate_ir` 驗證，任一筆失敗整批拒絕。新列 `review_status` 恆為 `'pending'`；既有列若 `title`、`keywords` 或 `ir_json` 實質變更，重置 `review_status='pending'`、`reviewed_at=NULL` 並遞增 `content_version`；內容未變則冪等跳過。
  - **骨架與本地 LLM 預生成 (`generate_ir`, `load_skeleton`, `build_prompt`, `parse_output`, `scripts/generate_visual_assets.py`)**：場景結構（`blueprint`、場景 `title`、`labels`）由人工於 `data/visual/skeletons/<topic>.json` 定義（目前提供首個主題 `autologous-fat-grafting.json` 自體脂肪移植），本地 LLM 僅負責生成各場景的 `caption` 純文字行（`場景1：…`，且嚴禁含任何阿拉伯數字）。使用 `VISUAL_SAMPLING`（`max_tokens=900`、`enable_thinking=False`），最多嘗試 2 次，受 `GENERATION_LOCK` 與 `nightly_batch_running` 互斥保護（忙碌回 `busy`），寫入狀態一律為 `pending`。
  - **醫師審核閘門 (`set_review_status`, `visible_assets`, `scripts/review_visual.py`)**：提供 `list`、`show`、`approve`、`reject`、`reset` 子指令。`approve` 寫入前強制重跑 `validate_ir`；`visible_assets` 對外查詢 `review_status='approved'` 時逐筆再次執行 `validate_ir`，遭竄改之資料自動略過不外洩。

- **服務端關鍵字比對與諮詢回應帶出 (`src/visual/match.py`, `src/general/patient_consult.py`)**：
  - **確定性子字串比對 (`find_visual`)**：純 `SELECT` 模組（無寫入、無 logging、無 print），對問句與已核准資產之 `keywords` 執行 `NFKC` 正規化並轉小寫後計算命中數；命中 0 回傳 `None`，多筆取命中數最高者（同分取字典序較小之 `topic_key`）。對外整形僅保留 `{"topic_key", "title", "scenes"}`，排除資料庫 `id`、`ir_json` 原文、審核欄位、`metadata` 與 `keywords`。
  - **附帶條件**：`patient_consult` 僅在 `status` 為 `"answered"` 或 `"llm_general"` 的回傳點附加 `find_visual` 結果（並隨 `/api/v1/general/consult` 與 `/api/v1/general/consult/jobs` 回應帶出）；`red_flag`、`no_match`、`busy` 狀態永不附帶動畫（一律為 `None`）。`GET /consult/jobs/{id}` 維持純記憶體輪詢零資料庫連線。

- **匿名事件計數與前端安全渲染 (`src/visual/stats.py`, `src/web/static/consult.html`)**：
  - **匿名日聚合計數 (`record_event`, `POST /api/v1/general/visual/event`)**：僅收白名單事件 `shown` 與 `completed`（由 `VisualEventRequest(extra="forbid")` 與 `AnonymousRoute` 把關，格式不符回固定 422 `{"detail": "請求格式不正確"}`），且 `topic_key` 須為 `visible_assets` 中已核准主題才以獨立連線 UPSERT `visual_stats`（同日同事件 `count + 1`）；未核准主題、缺表或寫入失敗一律全吞並回傳固定 200 `{"ok": true}`，不記 IP、標頭或問句，路徑亦受 `/api/v1/general` 存取日誌過濾器保護。
  - **前端安全與無障礙 (`consult.html`)**：僅當回應 `status` 為 `answered` 或 `llm_general` 且 `visual.scenes` 為 3～5 筆時顯示解說卡；所有動態文字一律以 `textContent` 寫入，三種場景圖解以 `document.createElementNS("http://www.w3.org/2000/svg", ...)` 建立固定 SVG，嚴禁 `innerHTML`、`insertAdjacentHTML`、`document.write`、`eval`、`setInterval` 或外部資源；以「上一步／下一步」按鈕手動切換並支援 `@media (prefers-reduced-motion: reduce)`；卡片底部固定顯示前端常數免責文字「一般醫學知識說明，非個人化診斷；實際狀況須由醫師當面評估」；首次顯示回報 `shown`、首次到達最後一幕回報 `completed`。

- **已知限制**：
  1. 醫學敘述之臨床正確性最終仰賴醫師透過審核工具人工把關核准。
  2. 關鍵字比對採確定性子字串匹配，若病患提問措辭與預設關鍵字差異較大，將不會觸發解說卡顯示。
  3. 目前僅建立 1 個骨架主題（`autologous-fat-grafting` 自體脂肪移植）。
  4. 真實本地 LLM 生成品質與解說卡對預約諮詢之轉換成效**待驗證**。

- **測試清單**：
  - `tests/test_migrate_visual_assets.py`：單一來源遷移、冪等性、未確認備份拒絕、舊遷移與 conftest 不含 `visual_` 回歸測試。
  - `tests/test_visual_ir.py`：Typed IR 結構、三種 blueprint、禁詞、百分比、價格與劑量攔截、錯誤碼零原文洩漏測試。
  - `tests/test_visual_writer.py`：唯一寫入路徑 `upsert_assets`、內容變更重置 `pending`、核准前重驗、`visible_assets` 竄改防禦測試。
  - `tests/test_visual_generator.py`：骨架載入、prompt 組裝、重試上限、生成鎖與夜間批次互斥測試。
  - `tests/test_visual_cli.py`：預生成 CLI 與醫師審核 CLI（`list`/`show`/`approve`/`reject`/`reset`）測試。
  - `tests/test_visual_match.py`：關鍵字比對確定性、輸出整形、Fail-Closed 與 AST 純讀取掃描測試。
  - `tests/test_visual_serving.py`：諮詢回應與非同步 job 帶出解說卡、紅旗/no_match/busy 不附帶、輪詢零資料庫連線測試。
  - `tests/test_visual_stats.py`：匿名事件計數累加、未核准忽略、422 固定訊息、存取日誌過濾與隱私測試。
  - `tests/test_consult_visual_ui.py`：諮詢頁解說卡靜態安全掃描、三種 SVG 模板、免責常數與事件回報測試。

- **2026-10-19 CSP 與前端腳本位置（重要踩雷）**：`/admin` 靜態頁帶 CSP `script-src 'self'`（見 2.17），**瀏覽器會阻擋內嵌 `<script>`**。病人諮詢頁 `consult.html` 自 Phase 27 起以內嵌腳本實作，因此在真實瀏覽器中從未能執行（既有測試只做靜態掃描，未發現）；2026-10-19 以 Playwright 實際操作才查出，已將腳本移至同源 `src/web/static/consult.js`。此後 `consult.html` 不得再有內嵌 `<script>`（`tests/test_patient_consult_ui.py::test_consult_has_no_inline_script_and_loads_external_js` 把關），靜態安全掃描須同時涵蓋 HTML 與 JS。新增前端頁面務必以真實瀏覽器驗證一次，不能只信任靜態測試。

### 2.27 視覺場景引擎（Phase 30 新增）

為將醫療概念定義（骨架 JSON 與文字敘述）與視覺幾何渲染（純 JavaScript 繪圖引擎）解耦，避免任意 LLM 生成 SVG 或程式碼帶來之安全風險，自 Phase 30 起建立資料驅動的視覺場景引擎（Visual Scene Engine）架構：

- **定位與動機**：
  - **資料驅動與純函式渲染**：醫學場景參數由結構化資料定義，前端引擎為進度 $u \in [0, 1]$ 之無狀態純函式，不依賴 LLM 即時生成向量幾何或外部動畫庫。
  - **跨平台一致性**：同一份資產規格同時驅動線上諮詢解說卡動畫、獨立通用播放器檢視與無聲 MP4 影片匯出，確保拖曳、重播與逐格錄影之一致性。
  - **漸進增強與零破壞**：引擎與動畫為視覺卡之增強表現層；未帶參數或引擎不可用時無縫退回靜態圖，不影響病患諮詢與醫療衛教基本功能。

- **Blueprint 參數規格單一來源與向後相容 (`src/visual/blueprints.py`, `src/visual/ir.py`)**：
  - **單一來源註冊表 (`BLUEPRINTS`)**：`src/visual/blueprints.py` 為參數規格唯一權威來源。定義 `process_diagram`（微粒流動、離心分層、針管抽吸）、`contrast`（單點過量脈動 vs 分點少量接觸光圈）、`timeline`（組織基質、微血管生長、里程碑進度）三大模板之參數規格與預設值（`default_params`）。
  - **安全參數型別與語意調色盤 (`PALETTE_TOKENS`)**：參數僅接受列舉值、小整數、短文字、布林值與 10 種語意調色盤代號（`fat`、`oil`、`blood`、`skin`、`neutral`、`accent`、`warn`、`ok`、`gel`、`pale`）；嚴禁接收任意 CSS 顏色代碼、HTML 標籤或自訂腳本。
  - **合併語意與向量測試 (`merge_defaults`)**：物件採遞迴合併、陣列採整體覆寫、`None` 或缺省視為全預設值；跨語言合併行為以 `tests/fixtures/visual_merge_vectors.json` 10 組向量雙向鎖定。
  - **Typed IR 延伸相容 (`validate_ir`)**：`scenes` 允許選填 `params`（dict）與 `duration_sec`（4～12 整數）。未帶 `params` 之資產完全向後相容，既有 Phase 29 IR 驗證行為零改動；提供時委派 `validate_params` 進行型別與邊界嚴格檢驗，違規回傳固定英文錯誤碼。
  - **骨架與生成器整合 (`src/visual/generator.py`)**：`load_skeleton` 嚴格檢驗骨架之選填參數；`generate_ir` 原樣帶入骨架參數，本機 LLM 僅填寫說明文字，完全無法竄改畫面幾何或結構。

- **JavaScript 視覺引擎純函式架構 (`src/web/static/visual_engine.js`)**：
  - **公開介面 (`ClinicVisual`)**：IIFE 封裝導出全域物件，提供 `blueprints`、`PALETTE`（凍結調色盤映射至安全十六進位色碼）、`resolveParams(blueprint, params)`、`sceneDuration(scene)` 與 `mount(svgEl, scenes)`。
  - **純函式與進度 $u$ 推進**：每個 blueprint 的 `draw(ctx, params, u)` 僅依賴進度 $u \in [0, 1]$ 與正規化參數，不保留任何跨影格狀態，拖曳 seek 與亂序重播結果皆 100% 字元級確定。
  - **無依賴幾何計算與確定性雜湊**：微粒隨機感採座標與索引之確定性雜湊；血管生長嚴格使用 SVG `pathLength="100"` 搭配 `stroke-dasharray="100"` 與 `stroke-dashoffset` 換算，**絕不呼叫版面相依之 `getTotalLength()`**。
  - **視窗邊界與字幕安全區**：`mount` 自動綁定 `viewBox="0 0 800 510"`；所有繪圖元素落在 $[5, 795] \times [5, 505]$ 安全區內，所有文字（`text`）元素底部 $y \le 410$，嚴格保留下方字幕安全空間。

- **視覺 Bundle 唯讀匯出工具 (`scripts/export_visual_bundle.py`)**：
  - **嚴格唯讀連線**：以 SQLite URI `mode=ro` 連線開啟資料庫，拒絕任何寫入行為。
  - **正式庫雙重保護**：預設僅匯出審核狀態為 `approved` 之資產；支援 `--allow-pending` 供測試預覽，但若 `--db` 為專案正式庫 `clinic.db` 時，於連線前立即以結束碼 `2` 阻斷。
  - **完整合規檢核**：匯出前強制經由 `validate_ir` 執行醫療合規檢驗，並透過 `merge_defaults` 補齊所有場景之預設 `params` 與 `duration_sec`，輸出為標準 UTF-8 JSON 檔案。

- **通用解說播放器與無聲 MP4 影片匯出 (`demo/visual/`)**：
  - **通用播放器 (`player.html`, `player.js`)**：純外部檔案架構（零內嵌腳本），支援 `?bundle=<path>` 參數載入 bundle JSON。路徑嚴格檢核 `^[A-Za-z0-9][A-Za-z0-9._/-]*\.json$` 且禁止 `..`、`//` 或協定前綴；提供播放、暫停、seek 拖曳、章節切換與結尾預約諮詢外連卡；對外暴露 `window.__player = {seek, total, ready}` 控制介面。
  - **泛化 MP4 影片匯出 (`render_video.py --bundle PATH`)**：啟動本機臨時 HTTP 伺服器載入播放器，透過無頭 Chromium 逐格 seek 截圖，再以 ffmpeg 合成標準 H.264/yuv420p 格式之 MP4 影片（無聲）；遺失相依工具時以結束碼 `2` 清楚提示。

- **正式衛教諮詢解說卡引擎整合與平順降級 (`src/web/static/consult.html`, `consult.js`)**：
  - **雙軌渲染判斷**：`consult.js` 僅在 `window.ClinicVisual` 存在且該資產所有場景皆具備非空 `params` 時啟用引擎動畫；否則自動退回 Phase 29 既有之 480×120 靜態 SVG 圖解。
  - **動畫驅動與互動**：使用 `requestAnimationFrame` 之回呼時間戳推進進度 $u$（不使用 `setInterval` 或 `Date.now`）；維持病患手動點擊「上一步／下一步」翻頁，不自動強制輪播。
  - **無障礙支援**：偵測到 `@media (prefers-reduced-motion: reduce)` 時直接渲染 $u=1$ 最終靜態畫面。
  - **防禦性退回**：渲染過程發生任何未預期例外時，安全清理容器與 rAF 迴圈並退回靜態圖，確保諮詢功能不中斷。

- **第二主題證明（2026-10-20 更正：驗證過程促成引擎補參數）**：
  - 於 `data/visual/skeletons/hyaluronic-acid-filler.json` 定義第二主題「玻尿酸填充原理」（含凝膠分層抽吸、單點過量 vs 分點少量對照、微粒吸收代謝時程）。
  - **事實更正**：agy 的 30-05 摘要曾宣稱「100% 零 JS 改動」，但 Claude 於最後檢查以真實 llama-server 生成並渲染玻尿酸後發現，對照場景寫死了脂肪移植專屬的「中心缺血」「不易獲取充足養分」文字與琥珀色，套到玻尿酸會變成醫學上錯誤的說法。因此補上參數 `contrast.left.core_effect`／`core_label`／`footnote`／`unit_fill`、`contrast.right.footnote`／`unit_fill`、`timeline.unit_fill`（預設值保留脂肪移植畫面，向後相容）。**補完參數之後**，第二主題才達成只靠骨架 JSON 渲染、無需再改引擎；測試以「引擎仍恰為三個 blueprint」與「玻尿酸參數渲染不得出現『缺血』『養分』」把關（`tests/test_visual_engine_browser.py::test_contrast_has_no_hardcoded_fat_graft_text`）。
  - 時間軸血管同時由「自上緣垂下」改為兩側主幹加分支的網路畫法（較貼近實際）。
  - 撰寫標準手冊 `docs/visual-blueprints.md` 定義未來新增 blueprint 之五大標準步驟與防護清單。

- **前端安全規則與靜態防禦**：
  - **CSP 遵循與外部檔案**：配合 `/admin` CSP `script-src 'self'`，所有前端邏輯一律置於同源外部 `.js` 檔案，`consult.html` 與 `player.html` **嚴禁包含任何內嵌 `<script>`**。
  - **嚴格禁用子字串檢驗**：前端 JS（`consult.js`、`visual_engine.js`、`player.js`）與註解嚴禁包含 `innerHTML`、`insertAdjacentHTML`、`document.write`、`outerHTML`、`eval`（含複合單字，如 retrieval）、`localStorage`、`sessionStorage`、`document.cookie`、`setInterval`。**僅 `visual_engine.js` 另外禁用**（因其須為純函式）`setTimeout`、`Date.now`、`Math.random`、`new Date`、`performance.now`、`fetch(`、`XMLHttpRequest`、`import(` 與 `<script`；`consult.js` 與 `player.js` 實際會使用 `setTimeout`／`Date.now`／`fetch`，不受此加嚴規則限制。

- **2026-10-20 真實驗收教訓（兩個缺陷皆由真實瀏覽器加真實模型才抓到，agy 的測試與審計未發現）**：
  1. **主題專屬內容不得寫死在引擎**：第二主題實際渲染才暴露對照場景寫死脂肪移植文字與顏色。新增或修改 blueprint 時，必須用**第二個不同主題**實際渲染並人工檢視，確認沒有寫死的主題文字、醫學說法或顏色。
  2. **場景結尾時間點會落在下一場景起點**：引擎場景區間為左閉右開，`renderAt(startT+dur)` 恰為下一場景的 `u=0`，使 `consult.js` 播完場景 1、2 後顯示成下一場景畫面（最後一場景因夾限剛好正確）。已改以 `SCENE_END_EPSILON` 取略小於邊界的時間。**既有測試只檢查步驟指示與 viewBox，沒檢查畫出的是哪個 blueprint**；回歸測試改以各場景獨特標記字串驗證（`tests/test_consult_engine_browser.py`），並已確認錯誤版本會使其失敗。
  3. 通則：靜態測試與假資料測試通過，不代表畫面正確；有視覺輸出的功能，驗收必須包含真實瀏覽器逐場景截圖檢視。

- **已知限制與待驗證事項**：
  1. **新 Blueprint 需人工設計**：目前提供 3 種通用幾何模板（流程、對照、時程）；若需全新幾何結構仍需由開發人員或 Claude 依照指南手動新增，系統不支援亦不允許由 LLM 自行發明 SVG 結構。
  2. **MP4 影片為無聲圖解**：影片匯出僅錄製畫面幾何演進，不含語音旁白或配樂。
  3. **醫學敘述臨床審核**：預生成之說明文字與衛教正確性最終仍嚴格仰賴執業醫師人工審核簽核。
  4. **正式環境啟用須使用者核准**：正式資料庫 `clinic.db` 之資產目前未套用 Phase 30 參數升級；正式啟用須由使用者明確授權並執行遷移與重新核准，不得自動生效。
  5. **衛教轉換成效待驗證**：視覺引擎動畫對於病患理解度與預約轉換率之實際臨床成效**待驗證**。

- **測試清單**：
  - `tests/test_visual_blueprints.py`：參數規格註冊表、PALETTE_TOKENS、預設值、遞迴合併語意、數值邊界與向量測試。
  - `tests/test_visual_engine_static.py`：`visual_engine.js` 禁用子字串靜態安全掃描、介面符號與調色盤對齊測試。
  - `tests/test_visual_engine_browser.py`：Playwright 瀏覽器契約一致性、向量一致性、進度 u 完全確定性、視窗邊界與字幕安全區測試。
  - `tests/test_visual_bundle.py`：`export_visual_bundle.py` 唯讀連線、預設已核准、正式庫禁止 `--allow-pending`、合規驗證與邊界測試。
  - `tests/test_visual_player.py`：`player.html` 與 `player.js` 靜態安全掃描、路徑注入攔截與 Playwright 播放控制測試。
  - `tests/test_visual_video.py`：`render_video.py --bundle` 路徑安全、相依工具檢查與 ffmpeg MP4 端到端錄製測試。
  - `tests/test_consult_engine_browser.py`：`consult.html` 整合引擎之真實瀏覽器動畫渲染、手動切換、降級退回與 reduced motion 測試。
  - `tests/test_visual_second_topic.py`：玻尿酸填充第二主題 IR 驗證、Bundle 匯出、瀏覽器邊界與引擎未擴充測試。

### 2.28 由 PageIndex 自動生成動畫草稿、待簽核動畫分頁與診所優先（Phase 31 新增）

為使臨床推理樹（`page_index_trees`）已審核之術前／療程／術後衛教內容能自動轉化為「原理與處置過程」視覺解說動畫，並支援一般醫學共用與診所專屬並存、診所優先選取，自 Phase 31 起完成資料模型擴充、約束生成、管理審核 API 與審核介面分頁：

- **資料庫擴充與唯一鍵無損重建遷移 (`src/db/clinic_schema.sql`, `scripts/migrate_visual_assets.py`)**：
  - `visual_assets` 資料表擴充 `clinic_id TEXT REFERENCES clinic_info(clinic_id)` 欄位（`NULL` 代表一般醫學跨診所共用資產，有值代表特定診所專屬資產）。
  - 單一欄位 `topic_key UNIQUE` 重建為複合唯一約束 `UNIQUE(clinic_id, topic_key)`，並搭配 Partial Unique Index `CREATE UNIQUE INDEX idx_visual_assets_general_topic ON visual_assets(topic_key) WHERE clinic_id IS NULL`，以及在 `writer.py`、`review.py` 中以 `WHERE clinic_id IS ? AND topic_key = ?` 正確處理 `NULL` 去重語意。
  - 遷移腳本偵測舊表缺少 `clinic_id` 或仍為單欄唯一索引時，於單一交易內無損搬移既有資料列（保留原 `id`、`review_status`、`content_version`、`created_at`，既有列 `clinic_id` 設為 `NULL`），支援 `--confirm-prod-backup`、`--dry-run` 與冪等重跑。

- **診所優先比對規則 (`src/visual/match.py:find_visual`, `src/visual/review.py:visible_assets`)**：
  - 當查詢帶有 `clinic_id`（於 `patient_consult` 由 `resolve_patient_clinic` 解析）時，`visible_assets(conn, clinic_id=clinic_id)` 同時取出該診所已核准專屬資產與 `clinic_id IS NULL` 之一般醫學已核准資產。
  - `find_visual(conn, query, clinic_id=clinic_id)` 排序鍵為 `(tier, -hits, topic_key)`，其中診所專屬為 `tier = 0`、一般醫學共用為 `tier = 1`：**只要診所有已核准且命中關鍵字之相關服務動畫，永遠優先於一般醫學共用動畫**；若診所無命中才自動降級使用一般醫學動畫。
  - 當查詢未帶 `clinic_id` 時，僅檢索 `clinic_id IS NULL` 之一般醫學共用解說卡，並於 SQL 與 Python 雙層過濾，嚴禁跨院外洩他院專屬資產。對外回應結構維持 `{"topic_key", "title", "scenes"}`，不暴露 `clinic_id`。

- **PageIndex 推理樹自動草稿生成 (`src/visual/autodraft.py`, `scripts/autodraft_visual_from_trees.py`)**：
  - **輸入隔離**：`fetch_eligible_trees` 強制套用 `visible_tree_sql`（僅限已核准推理樹），未核准或駁回之樹一律拒絕生成（回傳 `tree_not_approved`）。
  - **受約束三場景生成 (`autodraft_from_tree`)**：呼叫本地 LLM（`VISUAL_SAMPLING`：`max_tokens=900`、`enable_thinking=False`），受 `GENERATION_LOCK` 與 `nightly_batch_running` 互斥保護，將推理樹轉換為固定三場景（`process_diagram` → `contrast` → `timeline`），`topic_key` 正規化為 `tree-<doc_id>`，繼承 `tree.clinic_id`。
  - **零預設文字污染與四層合規**：`parse_and_build_tree_ir` 強制模型填寫所有場景 `params` 文字欄位（`source.label`、`container_layers[].label`、`step_labels`、`left/right` 之 `title/note/core_label/footnote`、`milestones`），非脂肪主題若殘留脂肪移植預設字面值、含任何阿拉伯數字、場景 3 缺少「因人而異／醫師評估」收尾語意，或未通過 `validate_ir`，一律拒絕入庫。
  - **永不自動核准（Human-in-the-Loop）**：透過唯一寫入路徑 `upsert_assets(..., source_type='llm_generated')` 寫入，`review_status` 恆為 `'pending'`，須經執業醫師於審核頁簽核後方可對外生效。

- **管理端動畫審核 API (`src/api/routes/admin.py`, `src/visual/review.py`)**：
  - 掛載於 `/api/v1/admin` 並受 `verify_admin_key` 保護：
    * `GET /api/v1/admin/visuals`：支援 `status`（`pending`/`approved`/`rejected`/`all`）、`clinic_id`、`scope`（`all`/`clinic`/`general`）篩選，每筆附帶即時 `validation` 狀態與補齊預設參數後之 `scenes` 供瀏覽器直接合成播放。
    * `GET /api/v1/admin/visuals/{asset_id}`：取得單筆動畫資產完整詳情。
    * `PATCH /api/v1/admin/visuals/{asset_id}`：在線修訂標題、關鍵字或場景說明文字，儲存前重跑零數字與 `validate_ir` 檢驗，若有變更自動重置 `review_status='pending'` 並遞增 `content_version`。
    * `POST /api/v1/admin/visuals/{asset_id}/approve`：核准前強制重跑 `validate_ir`，不合規回 422。
    * `POST /api/v1/admin/visuals/{asset_id}/reject`：駁回動畫草稿。
    * `POST /api/v1/admin/visuals/autodraft`：指定已核准 `tree_id` 觸發生成待審動畫草稿。
    * `GET /api/v1/admin/review/summary`：新增 `visuals_pending_total` 與 `visuals_approved_total` 指標。

- **管理審核介面「🎬 待簽核動畫」分頁 (`src/web/static/index.html`, `src/web/static/app.js`, `src/web/static/style.css`)**：
  - 頂部導覽列完整提供 7 個頁籤：`📊 總覽儀表板`、`📝 待審衛教草稿簽核`、`🌳 臨床推理樹簽核`、`🎬 待簽核動畫`、`📁 文件拖曳上傳中心`、`🩺 臨床 SOAP 紀錄瀏覽`、`💬 向 LLM 提問`。
  - 以 `<script src="/admin/visual_engine.js"></script>` 外部載入視覺引擎，於審核卡片內透過 `ClinicVisual.mount(svgEl, asset.scenes)` 直接合成播放 SVG 動畫（支援播放／暫停、時間軸滑桿 seek、場景 1/2/3 切換、內聯編輯說明文字、由已核准推理樹一鍵生成草稿、核准與駁回）。
  - 嚴格遵守前端安全規範：零內嵌 `<script>`，所有動態文字以 `textContent` 寫入，零 `innerHTML`、`eval`、`setInterval`。

- **測試清單**：
  - `tests/test_migrate_visual_assets.py`：`clinic_id` 欄位與複合唯一索引無損重建遷移、冪等性測試。
  - `tests/test_visual_writer.py`、`tests/test_visual_match.py`、`tests/test_visual_serving.py`：診所專屬與一般共用隔離、診所優先選取（tier 0 > tier 1）與諮詢端點整合測試。
  - `tests/test_visual_autodraft.py`：推理樹自動生成草稿、未核准樹拒絕、零範本文字污染、零數字與排程互斥測試。
  - `tests/test_visual_admin_api.py`：管理端 API 認證、範圍篩選、內聯修訂重置 `pending`、核准重驗與樹轉草稿測試。
  - `tests/test_visual_review_ui.py`：7 個頁籤與外部腳本靜態安全掃描，以及 Playwright 真實瀏覽器動畫合成播放、修訂、核准與諮詢頁端到端測試。

### 2.29 診所核准即昇華一般醫學與語意動作繪圖引擎 2.0（Phase 32 新增）

為貫徹使用者指示：「各診所審核後就准許進入一般醫學不須再核准」，並徹底根除「圖文不符」、根據文字意義轉寫動態 Code 表現，自 Phase 32 起建立自動昇華機制與 Surgical Action 外科專科繪圖引擎：

- **診所核准即自動昇華機制 (`src/visual/auto_promotion.py`)**：
  - 當專科醫師在管理後台（`/admin`）核准特定診所專屬之視覺資產（`clinic_id IS NOT NULL`）時，系統自動觸發昇華引擎。
  - 昇華引擎將該資產複製一份，並將其 `clinic_id` 設為 `NULL`（代表一般醫學共用資產），同時自動過濾或泛化診所特異性資訊，寫入資料庫作為一般醫學已核准（`review_status = 'approved'`）資產。
  - 全院跨診所與匿名病人端（`/consult`）在未指定診所時，能直接檢索引用該昇華資產，**徹底免除人工二次重複審核的行政負擔**。
  - 複合唯一鍵 `UNIQUE(clinic_id, topic_key)` 保證診所專屬列與一般醫學列和諧並存，增量更新冪等安全。
- **語意動作繪圖引擎升級 (Surgical Action DSL)**：
  - 場景 1 擴充支援 `surgical_action`（專科骨骼手術機轉）：包含下顎骨/頦骨滑移重塑動態（0~15mm）、純鈦板釘剛性旋入鎖定、頦神經解剖孔與彈性保護光暈，以及微創黏膜切開牽引箭頭。
  - 擴充開放外科拉皮 `deep_plane_facelift`（SMAS 筋膜下剝離、維持韌帶鬆解、向量懸吊固定）與頸部馬甲縫合 `corset_platysmaplasty`（闊頸肌前緣靠攏、雙排倒刺線縫合、雙下巴輪廓收緊）。
- **測試清單**：
  - `tests/test_auto_promotion.py`：診所核准即昇華、去診所化清洗、唯一鍵相容、冪等增量與回滾保護測試。
  - `tests/test_visual_engine_browser.py`：`surgical_action` 60fps 向量確定性渲染、骨骼滑移計算、神經保護光暈與純鈦固定測試。

### 2.30 專科解剖對照與修復歷程語意繪圖全面升級（Phase 33 新增）

為落實場景 2（Contrast 對照組）與場景 3（Timeline 歷程組）100% 依臨床文本意義轉寫 Code 動態表現，自 Phase 33 起擴充 5 大專科病理對照、5 大活體修復歷程，並徹底解決場景 3「無圖文變化」之視覺瓶頸：

- **五大專科病理對照模式 (`drawContrast`)**：
  - 體雕抽脂：`tissue_trauma_torn_vessel`（粗鈍抽吸撕裂血管出血凹凸）vs `ultrasonic_emulsification`（超音波乳化保護結締組織網）。
  - 眼袋眼整：`scar_contracture_ectropion`（傳統外切疤痕攣縮下瞼下翻）vs `transconjunctival_fat_reposition`（經結膜內切無外疤平順轉位至淚溝）。
  - 結構隆鼻：`silicone_extrusion_erythema`（矽膠假體重力壓迫鼻尖發紅穿出短鼻）vs `cartilage_triangular_strut`（自體軟骨力學三角支架穩固零穿出）。
  - 假體隆乳：`capsular_contracture_ball`（纖維包膜攣縮變硬球形）vs `dual_plane_natural_teardrop`（雙平面筋膜覆蓋自然水滴垂墜）。
  - 微整針劑：`nodule_clumping`（單點過量結節硬塊表情受阻）vs `micro_droplet_diffusion`（微滴散佈均勻與組織平滑交融）。
- **五大活體生理修復歷程與動態圖文看板 (`drawTimeline`)**：
  - 5 大專科修復模式：`bone_healing`（骨痂形成 ➔ 骨小樑緻密 ➔ 咬合穩固）、`bruise_metabolism`（暗紫血腫 ➔ 膽綠素/膽紅素 ➔ 膚色復原）、`scar_maturation`（切口微凸潮紅 ➔ 水合加壓褪紅 ➔ 隱痕平整細白線）、`nerve_regeneration`（暫時麻木遲滯 ➔ 軸突萌發延伸 ➔ 感覺受體完全接合）、`skin_retraction`（水腫鬆弛 ➔ 垂直纖維隔膜收縮 ➔ 平整回彈貼合）。
  - **場景 3 圖文動態演進看板**：徹底移除預設脂肪球遮蔽，頂部動態階段色彩徽章（`【階段一·初期防護】` ➔ `【階段二·修復重塑】` ➔ `【階段三·穩定隱痕】`），即時專科動態解說文字切換，大畫布專科解剖演繹，底部時間軸活躍節點脈動光環與時程標籤。
  - 輔助光環：`glow_restored`（金色立體組織活力復原光芒）。
- **Local LLM 批次生成與 Hermes 監控規範 (`clinic-visual-batch` Skill)**：
  - 建立 `.agents/skills/clinic-visual-batch/SKILL.md`，定義本地大模型（Qwen3.8-27B-FP8）批次生成、IR 長度約束、零阿拉伯數字與 Hermes Agent 自動自癒、無頭測試之標準作業手冊。
  - 批次生成入口腳本：`scripts/run_hermes_batch_49.py` 支援 49 筆已核准推理樹之全自動自治批次重生成與報告輸出。
- **測試清單**：
  - `tests/test_visual_blueprints.py`：新增 5 組 contrast 模式、5 組 timeline 模式、glow_restored 列舉與參數合併測試。
  - `tests/test_visual_autodraft.py`：專科推理樹對照模式推斷、修復歷程推斷與規則 8 提示詞約束測試。
  - `tests/test_visual_engine_browser.py`：確定性 seek 正向/反向完全一致、邊界與字幕安全區（u=0/0.5/1）、白名單對齊測試。

---

### 2.31 推理樹動畫草稿品質強化（Phase 34）

- **黃金測試集**：`data/visual/golden/tree_blueprints_49.json` 記錄 49 筆已核准推理樹的預期場景 1 模板，由 `scripts/export_golden_tree_blueprints.py` 以唯讀連線產生。`tests/test_visual_golden_49.py` 比對 `infer_scene1_blueprint` 的結果；推斷規則改動若改變任一筆，測試失敗並指出 doc_id。黃金測試不連線資料庫。
- **逐筆渲染驗收**：`scripts/check_draft_renders.py` 以唯讀連線讀取草稿，對每個場景於 u=0/0.5/1 檢查圖元邊界、字幕安全區與確定性，產生接觸表與 `REPORT.md`／`report.json`（每次執行覆寫，不沿用過時報告）。輸出位於 `demo/visual/out/batch_49/`，不進版控。
- **模板覆寫**：`visual_assets.template_override`（預設 NULL）由 `scripts/migrate_visual_template_override.py` 遷移（冪等、交易性）。有值時場景 1 以覆寫值為準，非法值回傳 `unknown_blueprint` 且不呼叫 LLM。正式庫遷移與覆寫寫入須經使用者明確核准。
- **審核排序**：`scripts/review_visual.py list --risk-order` 依風險分數排序（外科骨骼 +3、對照 +2、跨診所同名療程 +1）。排序只影響顯示，不改變任何審核狀態。

### 2.32 動畫連結引用來源與內容歸屬（Phase 34 第二輪）

- **動畫跟著引用的推理樹走**：`src/visual/match.py:visuals_for_tree_sources` 依回答引用的推理樹（T 編號）取得已核准的視覺解說卡，而非只靠關鍵字。`rag_ask` 的回答結果附上 `visuals`。
- **顯示規則**：診所上下文 → 該診所專屬版優先，其次一般醫學共用版（不回傳他院版本）；一般醫學上下文 → 共用版優先。同一療程只回一筆。
- **內容歸屬**：動畫（視覺解說卡）核准後自動昇華為一般醫學共用，對所有診所可用（Phase 32）。**衛教 FAQ 不昇華**，保持每家診所專屬；核准診所 FAQ 不會在一般醫學池新增列（測試：`tests/test_visual_visuals_for_sources.py`）。
- **提示詞**：模型不得自行宣稱資料中沒有圖解或動畫；已核准的動畫由系統另行附上。
- **尚未完成**：病患端諮詢（`patient_consult`）仍以關鍵字比對動畫；管理端問答頁尚未播放附上的動畫（目前只回傳 `visuals`）。

### 2.33 臺灣基層常見疾病 ICD-10 知識庫與視覺藍圖管線（Phase 35 新增）

為滿足臺灣基層診所 6 大專科（耳鼻喉、家醫、兒科、心臟內科、腸胃內科、新陳代謝科）之日常看診衛教需求，自 Phase 35 起導入標準化 ICD-10-CM 疾病目錄與解剖病理管線：
- **基層 36 項疾病目錄 (`data/icd10/primary_care_36_catalog.json`)**：
  - 收錄急性上呼吸道感染（J06.9）、高血壓（I10）、第2型糖尿病（E11.9）、胃食道逆流（K21.9）、急性支氣管炎（J20.9）、急性腸胃炎（A09）、痛風（M10.9）等 36 項常見疾病。
  - 每筆疾病包含 ICD-10-CM 代碼、英文名稱、繁體中文俗稱、主責專科、器官系統（如 `respiratory_mucosa`、`cardiovascular_artery`、`gi_mucosa` 等）、非手術誘因（飲食、感染、生活習慣）及三階段病程特徵。
- **病理機制藍圖 (`pathology_mechanism`)**：
  - 場景 1 突破純外科動作限制，支援發炎紅腫浸潤、血管硬化斑塊、黏膜酸蝕破損等內科常見病理機制向量渲染。
  - 純本地離線豐富腳本 (`scripts/enrich_icd10_primary_care.py`) 透過本地 Qwen 27B 生成並經過 100% 醫療法規過濾（零價格洩漏、無阿拉伯數字、繁體中文）。

### 2.34 ClinicBrain Native Harness² 雙層遞迴自進化馬具（Phase 36 新增）

借鑒 Google Research Harness²（Recursive Agent Harnessing for an Open World）思想，在不修改底層 LLM 權重前提下，針對臨床醫療文本與視覺 IR 生成導入雙層遞迴優化架構 (`src/visual/harness_optimizer.py`)：
- **層級一：任務級遞迴 (Task-level Recursion)**：
  - 支援 `--k` 候選探索預算與 `sequential`（序列批評改進）或 `parallel`（並行探索最佳解）兩種模式。
  - 透過 `score_ir_alignment()` 進行 0~100 分臨床語意與 IR 結構規範評分。
- **層級二：治理級遞迴 (Harnessing-level Recursion)**：
  - 維護跨任務治理記憶庫 (`data/visual/harness_lessons.json`)，將常見缺陷（如遺漏警訊收尾句、器官系統與主題不符、三階段色彩顛倒等）固化為治理經驗。
  - 於 Prompt 組裝時依器官系統及主題動態注入相關治理規則；當審核通過且品質顯著提升時，自動沉澱並晉升新經驗至治理庫。
- **自動化治理檢核腳本 (`scripts/harness_check.sh`)**：
  - 一鍵執行純本地輕量驗證（包含 IR 語意評分、經驗注入、多候選探索與回歸測試），保證自進化機制離線可靠。

### 2.35 36 項基層疾病升格臨床推理樹與 Text Native Harness² 雙層遞迴（Phase 37 新增）

為使基層疾病能全面融入四段式臨床決策樹（`page_index_trees`）架構，並使雙層遞迴拓展至文本問答領域：
- **36 項基層疾病升格 PageIndex 臨床推理樹**：
  - `src/pageindex/db_writer.py:upsert_trees()` 支援 `category="general"` 且 `clinic_id=None` 的跨診所共用推理樹，同時對診所專屬類維持嚴格防護。
  - 由 `src/visual/icd10_catalog.py:entry_to_page_index_tree()` 將基層疾病摘要結構化轉譯為四段式推理樹（`pre_op` 病況評估、`procedure` 治療與用藥指導、`post_op_short` 急性期護理與就醫警訊、`maintenance` 長期慢性調養）。
  - 全數 36 項疾病經審核通過寫入正式 `clinic.db`，使全庫已簽核推理樹增至 **85 筆**（44 筆 general + 41 筆 special）。
  - 自然語言檢索全面支援 FTS5 trigram 與 LIKE 混合分流，並可直接由病人諮詢端點 `/api/v1/general/consult` 動態引用。
- **Text Native Harness² (`src/pageindex/text_harness.py`)**：
  - 拓展雙層遞迴架構至 FAQ 答案生成 (`answer_generator.py`) 與推理樹四段式濃縮提煉 (`tree_distiller.py`)。
  - 內建 `score_faq_answer_alignment()` 與 `score_tree_distillation_alignment()`，強制稽核就醫警訊收尾句、禁止保證療效、禁止價格洩漏與四段式結構齊全度。
  - 提供 `build_faq_critique_prompt()` 與 `build_tree_critique_prompt()` 自我批評機制，支援 `--k` 候選探索與治理經驗動態注入。

### 2.36 全自動診所網站爬取與智能知識提煉引擎（Phase 38 新增）

為免除診所人工手動整理衛教素材上傳的負擔，實現輸入任一診所官網一鍵爬取、清洗與提煉結構化知識：
- **Playwright 動態網頁擷取器 (`src/scraper/playwright_scraper.py`)**：
  - 採用無頭 Chromium，具備 SPA 渲染支援、`domcontentloaded` + `networkidle` 雙重等待，阻擋追蹤碼與大型多媒體資源以提高擷取效率。
  - 自動透過 `Readability` 演算法去除導航列、頁尾與側邊欄廣告，轉化為潔淨 Markdown 內文。
- **同網域廣度探索爬蟲 (`src/scraper/site_crawler.py`)**：
  - 支援同網域子頁面 BFS 探索（預設深度 2、上限 30 頁），自動解析 `sitemap.xml` 作為探索種子。
  - 內建路徑優先級排序（衛教、療程與服務說明優先，登入、購物車與法律條款自動跳過）。
  - 全程經由 `opencc` 轉換為台灣正體中文，並串接 `deep_mask_prices()` 進行零價格洩漏清洗。
- **智能知識提煉管線 (`src/scraper/distill_pipeline.py`)**：
  - 將爬取的 Markdown 內文直接串接 `text_harness.py`、`faq_writer.py` 與 `db_writer.py`。
  - 由本地 Qwen 27B 自動提煉為標準問答對與四段式臨床推理樹，狀態恆為 `pending`（待審核），維護醫療法規安全。

### 2.37 推理樹核准聯動自動生成動畫草稿（Phase 38 增強）

- 醫師在管理後台點選「核准」任一臨床推理樹時，後端透過 FastAPI `BackgroundTasks` 自動非同步觸發 `autodraft_visual_for_tree`。
- 自動生成 3 幕受約束之視覺動畫解說卡草稿，狀態恆為 `pending` 並存入 `visual_assets`，前端即時 Toast 提示並引導醫師至「🎬 待簽核動畫」分頁審核發布。

### 2.38 全部診所（一般醫學管理）跨診所管理支援（Phase 38 增強）

- 在 Web App 管理中心頂部診所切換器、文件上傳中心（`uploadClinicId`）、SOAP 臨床紀錄檢索（`soapClinicId`）與「向 LLM 提問」（`askClinicId`）新增「全部診所（一般醫學管理）」選項。
- 支援將全科或非特定單一診所之衛教資料、病歷摘要直接作為一般醫學跨診所共用知識進行管理與查詢。

### 2.39 Hermes Agent 長時間執行防卡死三道防線（Phase 38 運維強化）

針對本地 Qwen 27B 推理長上下文記憶體快照壓迫導致的逾時問題，建立三層自治防線：
1. **第一道防線（Hermes 輪次配額與自動壓縮）**：配置 `~/.hermes/config.yaml` 之 `max_turns: 45` 與 `threshold_ratio: 0.5`，超過立即自動壓縮上下文。
2. **第二道防線（乾淨執行封裝腳本）**：提供 `~/.local/bin/run_clinic_test.sh`，隔離環境變數與自製臨時腳本死鎖。
3. **第三道防線（Herdr 看門狗自動自癒）**：透過 `scripts/herdr_supervisor.py` 監控終端輸出，檢測到連續超載或無響應時自動發送中斷信號並執行 `/new` 重置。

### 2.40 臺灣健保 200 大疾病動畫批次編譯與專科藍圖（Phase 39 新增）
- **雙模型混合架構**：
  1. 調用 DeepSeek 高效提煉疾病之精確解剖部位與三幕特徵卡（極低 Token 成本）。
  2. 本地 Ornith-1.5-35B（Qwen2.5 衍生 @ localhost:8080）接收特徵事實卡，在本地安全環境將其編譯為合規 3 幕 × 8 秒（嚴格 24 秒循環）之 Typed IR。
- **專科解剖圖元拓展**：
  - 新增牙科口腔組織藍圖（`dental_oral`，支援牙釉質、牙本質、牙髓腔、齲洞充填與牙冠修復）。
  - 新增中醫經絡穴位藍圖（`tcm_meridian`，支援經絡循行、穴位阻滯、針灸得氣與拔罐活血）。
  - 第一幕 `pathology_mechanism` 深度綁定解剖器官（`anatomy_target`）與結構標記。

### 2.41 臨床知識庫資產審核全景矩陣與批量核准強化（Phase 39 新增）
- **批量審核與雙向一致性防禦**：
  - `src/visual/review.py:promote_visual_row` 在將診所專屬資產昇華為通用資產時，強制將外層 `title` 與 `keywords` 深度對齊內部 `ir` 結構，杜絕 `ValueError: 外層 title 與 IR 內 title 不一致` 之報錯中斷。
  - 重啟 API Server 同步載入最新專科藍圖檢驗器，徹底根除動態圖元 422 驗證失敗。
- **後台管理儀表板升級（`index.html` & `app.js`）**：
  - 頂部指標擴增為 8 大卡片，新增「🎬 已發布動畫」即時指標。
  - 實裝「📊 臨床知識庫資產審核全景矩陣 (Knowledge Audit Matrix)」，將 FAQ、推理樹、醫學動畫、SOAP 病歷之待審、已發布、已駁回、總數與核准率全景對稱展示。
  - 「🎬 醫學動畫管理」導航分頁搭載動態數量徽章與快捷狀態切換膠囊（`[⏳ 待簽核 (0)]` `[✅ 已發布 (198)]` `[❌ 已駁回 (2)]` `[全部 (200)]`），點擊時若待簽核為 0 自動導向已發布清單，徹底杜絕空白荒島體驗。

### 2.42 視覺資產全庫去重與歷史舊版淘汰規範（Phase 39 新增）
- **唯一權威主題原則**：
  全庫視覺動畫資產嚴格落實「一項醫學主題僅保留唯一最新、最高品質之權威版本」，杜絕雙寫膨脹與舊版草稿殘留。
- **去重優先順序法則**：
  1. `is_24s`：具備 `[8, 8, 8]` 嚴格 24 秒循環者絕對優先。
  2. `is_not_icd`：Phase 39 具備精確解剖機轉之新版資產絕對優先於 Phase 34 舊版 ICD-10 粗篩草稿。
  3. `is_general`：通用昇華版本（`clinic_id IS NULL`）優先於特定診所舊列，確保全院區與匿名諮詢端點皆可檢索且後台列表不重複。
  4. `content_version`、`updated_at`、`created_at`、流水號 `id` 依序擇優保留。
- **維護與稽核工具**：
  - 維護腳本：`scripts/dedup_visual_assets.py`（支援 `--dry-run` 預檢與安全批次刪除）。
  - 實跑成效：全庫原始 359 筆 approved 資產，成功清理淘汰 161 筆歷史舊版與雙軌冗餘列，完美精簡為 **198 筆唯一權威醫學動畫**，合規率 100%、24 秒循環率 100%、重複率 0%。

### 2.43 臺灣健保 1-400 大基層疾病資料庫索引與 LLM 檢索對齊（Phase 40 新增）
- **1-400 全景疾病目錄與索引架構**：
  - 資料表：`nhi_catalog_1_400`（收錄前 200 項核心診斷與第 201 至 400 項次級盛行疾病，覆蓋西醫 120 項、中醫 50 項、牙醫 30 項，合計 400 筆標準化條目）。
  - 全文檢索：`nhi_catalog_fts` 虛擬表（`tokenize='trigram'`），索引 `name`、`icd10`、`alias`、`keywords`、`clinical_feature` 等多維度臨床資訊。
  - 權威種子檔案：
    - `data/nhi_primary_care_1_400_index.json`：全量 400 筆疾病索引資料庫對應檔。
    - `data/nhi_primary_care_201_400.json`：第 201 至 400 項專科種子目錄。
- **LLM 檢索與選取模組 (`src/query/nhi_index.py`)**：
  - 混合分流：查詢詞 $\ge 3$ 字元走 FTS5 trigram 檢索，小於 3 字元走多欄位 LIKE 備援。
  - 精準查找：支援以編號（1～400）、ID（如 `W201`、`C321`、`D371`）或 `topic_key` 單筆檢索。
  - 結構化提示組裝：`format_nhi_context_for_llm` 將檢索結果輸出為精簡專業之參考索引，標註疾病代碼、分類、核心機轉與 3 幕動畫可用性（`visual_available`），供門診諮詢 LLM 引用選取。
- **次專科動畫規模化管線與安全入庫 (Phase 40 擴充)**：
  - 專門支援第 201 至 400 項特異性臨床主題（眼科、耳鼻喉、泌尿生殖、牙周 GTR、中醫特種針法）。
  - 擴充靜態藍圖規格（`src/visual/blueprints.py`）與向量引擎繪圖（`src/web/static/visual_engine.js`），全面支援 5 大次專科器官、次專科病理對照模式與時序修復連接。
  - 建構任務清單編譯器 (`scripts/build_nhi400_manifest.py`) 與自癒批次生成器 (`scripts/generate_nhi400_visual_batch.py`)，嚴格達成零阿拉伯數字、無保證療效、24 秒三幕循環與自動自癒重試。
  - 完成 Playwright 無頭 Chromium 抽幀審計測試 (`tests/test_nhi400_browser_render.py`)，確認各關鍵影格無半形數字殘留且 forward/reverse seek 100% 確定性。
  - 透過安全入庫腳本 (`scripts/stage_nhi400_to_db.py`) 將 200 筆次專科草稿以 `review_status='pending'` 冪等寫入正式 `clinic.db`，使全庫總資產達到 400 筆（198 approved, 200 pending, 2 rejected），與 1-400 全景索引完美對齊。

### 2.44 動態規格標準化與 3D 臨床解剖探索（Phase 41 新增，2026-11-11 核准）

為進一步提升 PageIndex 臨床推理樹之 3 幕向量動畫解說卡（`clinic-visual-batch`）品質，並評估醫美/外科專科之 3D 互動可視化諮詢潛力，自 Phase 41 起實施三階段推進規範：

1. **第一步（立即實施，高投報）：`motion-prompt` 動態規格與緩動預設抽取整合**
   - 將 `showheyohtaki/motion-prompt` 的 144 個精選動效標準名稱、鏡頭運動（camera zoom/pan）、純 Canvas 2D/CSS 緩動曲線（easing curves）規格抽取為輕量模組，收斂至 `.agents/skills/clinic-visual-batch/resources/motion_vocab.json` 與相關規範文件。
   - 讓本地大模型（Qwen3.8-27B-FP8 / 3.8 Flash）在生成「PageIndex 3 幕衛教卡片」與專科動畫草稿時，具備精確的動效參數與確定性時序，根除文字描述模糊、動態僵硬或抽搐旋轉等缺陷，立即可見品質提升與一次性通過率躍升。
   - 保持純純量與零外部肥大框架依賴，符合診所內網離線輕量渲染與安全性規範。

2. **第二步（沙盒概念驗證 PoC）：`FreedomIntelligence/BodyVista` 專科解剖評估**
   - 於隔離沙盒環境 clone `FreedomIntelligence/BodyVista`，實測檢視其 3D WebGL 模型檔案體積（GLTF/GLB）、載入延遲與資產結構。
   - **專科精細度抽查**：抽查 1~2 個緻妍診所核心療程（例如：顏面拉皮／音波拉提的臉部 SMAS 筋膜層與顏面神經血管走向，或是自體脂肪隆乳／假體植入之胸大肌／乳腺腔隙層次），對比醫美與整形外科臨床衛教需求，評估現有模型是否過於宏觀，或是足以支撐臨床溝通。
   - **法規與環境合規檢核**：
     - 繁簡名詞與台灣醫療術語核對（CUHK-SZ 簡體術語必須經由台灣醫學會名詞庫校準，禁止生搬大陸用語）。
     - 離線自託管可行性（必須 100% 區域網路本機運行，嚴禁外連未授權第三方雲端服務或遙測）。

3. **第三步（架構整合規劃）：3D 解剖檢視器獨立組件與 PageIndex 關聯設計**
   - 若 PoC 評估通過，規劃將 3D 解剖檢視器封裝為獨立前端組件（Consultation 3D Viewer），與病患諮詢前台（`patient_consult`）整合。
   - 建立推理樹 `doc_id` 與 3D 解剖實體 ID（`anatomy_id`）之映射標準，當病患或醫師查詢特定療程時，可自動連動 3D 視角旋轉、層次剝離與病灶/施作部位高亮。
   - **價格與法規防禦線**：3D 組件連動展示之任何文字標籤與解說，一律受到既有 `deep_mask_prices()` 價格清洗與「禁止保證療效」防護機制控管。

### 2.45 自動化動態解說動畫影片佇列（Phase 43 新增，2026-11-11 核准）

為將資料庫已核准之 24 秒醫學向量動畫（398 筆 approved 資產）延伸應用至診間實體多媒體與衛教宣導，自 Phase 43 起建立影片批次渲染佇列：
1. **多媒體應用場景與輸出規格**：
   - **診所電視／看板 (16:9 橫屏)**：解析度 1920×1080，24fps，H.264 MP4（yuv420p），結尾預留 2.5 秒預約卡畫面，支援門診候診區無縫循環播放。
   - **社群媒體／衛教短影音 (9:16 豎屏)**：解析度 1080×1920，供 Instagram Reels、LINE 官方帳號與衛教平板直立觀看。
2. **自動化佇列引擎 (`src/visual/video_queue.py`)**：
   - 直接從 `clinic.db` 之 `visual_assets` 讀取已核准的 `ir_json`，動態生成記憶體/暫存 bundle，透過無頭 Chromium 逐格 seek 渲染，零手動導出負擔。
   - **增量渲染與快取跳過 (Idempotent Cache)**：比對 `ir_json` 之 SHA-256 雜湊與影片輸出檔；若 IR 未改動且影片已存在，自動跳過，杜絕重複消耗 CPU/GPU 資源。
3. **離峰批次與後台整合**：
   - 整合至夜間批次排程（`src/batch/runner.py`）之可選階段，於夜間離峰無人看診時段自動渲染新核准之動畫資產。
   - 管理後台與 API 支援單題即時預覽、影片下載與手動排程。

### 2.46 次世代生動向量視覺引擎全面升級（Phase 44 新增，2026-11-11 核准）

為徹底解決已發布 398 筆醫學動畫卡視覺生硬與機械化線性運動之痛點，在**資料庫零改動、398 筆 Typed IR 零搬遷**的前提下，對純函式確定性繪圖引擎 `src/web/static/visual_engine.js` 實施五大次世代升級：
1. **物理動態數學庫 (`ClinicMotion`)**：
   - 封裝非線性緩動（`easeOutCubic`, `easeInOutQuad`）、組織彈性過衝（`springGentle`，過衝係數 $1.05 \to 1.0$）與蓄力爆發（`anticipate`）。
   - 封裝確定性器官呼吸微動（`createBreathingPulse(u, freq, amp)`，$\pm 1.2\%$ 尺度微搏動）。
2. **2.5D 擬真體積光影與解剖層次**：
   - 導入柔和雙層半透明徑向漸層（Radial Gradient），呈現活體生物組織溫潤透光感（Subsurface Scattering）。
   - 筋膜與器械切口邊緣動態高光流動（Shimmer Sweep）與深淺環境遮擋陰影（Ambient Occlusion）。
3. **活體動態微環境**：
   - 同心圓擴散能量漣漪（Ripple Waves）、血液與脂肪微粒之布朗有機微擾動。
4. **資訊動態聚光燈與階梯浮現**：
   - 動態 Spotlight 跟隨當前執行步驟，相機平滑微推拉（Zoom in 1.15x），標籤文字以 `ease_out_quad` 柔和向上浮現。
5. **對照場景與時間軸趣味演繹**：
   - Scene 2 傳統側警示紅光顫動 vs 微創側翡翠綠流光屏障；Scene 3 里程碑激活爆發金色修復微粒子（Sparkle Dust）。
   - **實施順序策略**：優先完成 Phase 44 引擎升級，使 398 部動畫立即可見生動升級；接續執行的 Phase 43（MP4 離線渲染佇列）將直接產出具備次世代光影與動態之高解析度宣傳短影音。

