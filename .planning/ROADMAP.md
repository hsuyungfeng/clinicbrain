# Roadmap: clinicbrain — Taiwan Clinic Medical PageIndex RAG System

## Overview

從台灣健保開放資料出發，建立結構化資料庫與四段式 PageIndex 臨床推理樹，串接本地 LLM、多診所健保機構代碼架構、文件擷取、官方 API 整合，並完成認證強制、快取優先查詢、匿名一般諮詢與醫師審核閘門下的夜間批次。v1.3 新增臨床端能力，支援外部系統（doctor-toolbox.com）推播文字與語音紀錄，確定性 S/O/A/P 切分、特徵擷取、個資去識別化與專屬醫師檢索。

## Milestones

- ✅ **v1.0 Taiwan PageIndex RAG 基礎系統** — Phase 1–5（2026-09-29 完成）— [歸檔](milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 上線就緒與成本優化** — Phase 6–9（2026-10-02 完成）— [歸檔](milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 診所資料優先與一般疾病簡易資訊** — Phase 10–13（2026-10-06 完成）— [歸檔](milestones/v1.2-ROADMAP.md)
- ✅ **v1.3 臨床語音與 SOAP 紀錄擷取** — Phase 14（2026-10-07 完成）— [歸檔](milestones/v1.3-ROADMAP.md)
- ✅ **v1.4 臨床衛教提煉與進階防護** — Phase 15–18（2026-10-08 完成）
- 🚧 **v1.5 臨床操作體驗與 AI 協同工作流** — Phase 19+（進行中）

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 10. 技術債基礎清理 | 3/3 | Complete | 2026-10-02 |
| 11. 診所資料優先檢索 | 4/4 | Complete | 2026-10-03 |
| 12. 一般疾病內容生成與審核 | 6/6 | Complete | 2026-10-05 |
| 13. 真實 LLM 批次實跑驗證 | 2/2 | Complete | 2026-10-06 |
| 14. 臨床語音與 SOAP 紀錄擷取 | 3/3 | Complete | 2026-10-07 |
| 15. 臨床 SOAP 衛教提煉與審核流 | 3/3 | Complete | 2026-10-07 |
| 16. 定時自動化同步與批次提煉排程 | 3/3 | Complete | 2026-10-08 |
| 17. 定時一般醫學知識補充與批次擴充 | 3/3 | Complete | 2026-10-08 |
| 18. 各診所資料上傳與管理 Web App | 3/3 | Complete | 2026-10-08 |
| 19. Web 管理介面臨床體驗升級與 AI 輔助生成 | 3/3 | Complete | 2026-10-08 |
| 20. LLM 空閒時間衛教答案自動生成器 | 3/3 | Complete | 2026-10-12 |
| 21. 臨床決策推理樹提煉、審核與檢索擴展 | 3/3 | Complete | 2026-10-12 |
| 22. RAG 提問檢索優化、BM25 排序與結構化衛教生成 | 3/3 | Complete | 2026-10-14 |
| 23. 競品／合作機構網站擷取器 | 3/3 | Complete | 2026-10-14 |
| 24. 上傳中心增強（名稱欄位與網址解析） | 0/3 | Planned | - |

## Phase Details

### Phase 15: 臨床 SOAP 衛教提煉與審核流 (已完成)

**Goal**: 在維持公開端點嚴格隔離的前提下，建立醫師審核工具，將去識別化之 SOAP Assessment/Plan 臨床照護摘要提煉轉化為衛教問答草稿（pending 狀態），經醫師簽核後方可發布至診所 FAQ 或推理樹供查詢引用。
**Status**: Complete (10/10 單元測試、5/5 步驟業務閉環實機通過)

### Phase 16: 定時自動化同步與批次提煉排程 (已完成)

**Goal**: 建立夜間自動化排程機制，整合外部系統（doctor-toolbox.com / EHR）推播同步，於離峰時間自動對未提煉之 SOAP 紀錄執行分組提煉並生成 pending 草稿，支援醫師晨間審核通報。
**Status**: Complete (1002/1002 測試通過、Fail-Closed 防護、正式庫零污染)
**Scope**:
  1. 擴充 `src/batch/runner.py` 與 `scripts/run_nightly_batch.py`，整合前置 SOAP 衛教提煉。
  2. 實作 `src/sync/soap_sync_runner.py` 前置增量同步，強化去識別化與 URL 防護。
  3. 提供 Systemd Timer 排程範本與 `scripts/review_faq.py pending-summary` 晨間通報工具。

### Phase 17: 定時一般醫學知識補充與批次擴充 (已完成)

**Goal**: 建立通用醫學知識庫之定時自動補充機制，透過本地 LLM 離峰批次生成常見疾病衛教與健保給付指引，經既有審核閘門安全擴增 general 知識庫。
**Status**: Complete (1012/1012 測試通過、種子擴充至 15 主題、斷點續跑、正式庫零污染)
**Scope**:
  1. 擴充通用疾病種子清單（高血壓、糖尿病、氣喘、蕁麻疹等 8 大主題、32 題）。
  2. 自動化離峰批次生成管線（支援 `--general-only`、`--skip-general` 與斷點續跑）。
  3. 待審一般衛教問答審核流擴充（支援 `--category` 篩選）與 E2E 閉環驗收。

### Phase 18: 各診所資料上傳與管理 Web App (已完成)

**Goal**: 提供直覺友善的輕量 Web 介面，供各診所人員上傳診所文件（DOCX/XLSX/PDF）、檢視 SOAP 紀錄與溯源、並提供視覺化醫師簽核與營運資訊管理介面。
**Status**: Complete (15/15 測試通過、全套回歸 1013 通過、Fail-Closed 隔離、正式庫零污染)
**Scope**:
  1. 檔案上傳與自動處理介面（DOCX / XLSX / PDF 上傳、去識別化與價格清洗）。
  2. 視覺化醫師簽核儀表板（pending 草稿卡片、溯源病歷對照、一鍵核准/駁回）。
  3. 獨立 source_type='web_upload' 審核閘門防禦（避免 clinic_upload 恆可見造成 Fail-Open）。
  4. 多診所權限隔離與 verify_admin_key 認證安全。

### Phase 19: Web 管理介面臨床體驗升級與 AI 輔助生成 (已完成)

**Goal**: 依據臨床實機操作回饋，全面美化 Web App 管理介面，並新增「全選／反選／批量簽核」與「本地 LLM 自動生成衛教解答」功能，打通從純題目到完整衛教問答之高效率審核閉環。
**Status**: Complete (32/32 測試全過、批量簽核、AI 輔助生成、全選反選與浮動工具列)
**Scope**:
  1. 批量簽核 API（`POST /api/v1/admin/review/batch`）與單題 AI 生成衛教答案 API（`generate-answer`）。
  2. UI 全面美化（現代醫療科技感、微陰影與流暢卡片、讀取狀態骨架屏）。
  3. 簽核列表批量控制項（全選、反選、清除選取、浮動快捷操作列）。
  4. 待審卡片「🤖 AI 生成答案」與「內聯編輯 (Inline Edit)」支援。

### Phase 20: LLM 空閒時間衛教答案自動生成器 (已完成)

**Goal**: 建立雙軌答案自動補齊機制，利用本機 LLM 空閒時間（Web 非同步單佇列背景 Worker 與夜間批次離峰排程），自動將上傳文件或種子中「答案待補齊」之 pending 題目逐題生成合規繁體衛教解答，實現醫師晨間「零等待」直接審核閉環。
**Status**: Complete (25/25 專屬測試通過、跨行程 flock 互斥、480s 逾時放寬、Prompt 思考長度優化、Fail-Closed 待審隔離)
**Depends on**: Phase 19 (Web 批量簽核與單題生成 API), Phase 16 (夜間批次排程)
**Scope**:
  1. 後端背景非同步序列 Worker（`src/pageindex/batch_answer_job.py`）與排程端點（`POST /review/autofill/all`）。
  2. Web App 介面「🚀 一鍵背景自動補齊所有答案」控制按鈕、即時進度條橫幅與 3 秒狀態輪詢。
  3. 夜間批次第 7 階段整合：自動掃描未補齊解答之 pending 題目並離峰批次生成。
  4. 多 Agent 流水線驗收（Agy 3.6 Flash 實作 ➔ Claude 5.5 對抗性審查加固 ➔ 終端全套驗收）。

### Phase 21: 臨床決策推理樹提煉、審核與檢索擴展 (已完成)

**Goal**: 擴展核心四段式臨床推理樹（`page_index_trees`），支援自診所上傳文件與醫療長文自動提煉四段式決策樹草稿（`pending`），在 Web 管理介面新增決策樹視覺化檢視與醫師權威醫囑（`*_physician_notes`）簽核流，並提供嚴格的 Fail-Closed 檢索隔離與 RAG 擴展。
**Status**: Complete (31/31 專屬測試通過、全套回歸通過、Fail-Closed 通道、醫囑保護、正式庫零污染)
**Depends on**: Phase 20 (LLM 答案生成與推論優化), Phase 18 (診所管理 Web App), Phase 01 (PageIndex 核心)
**Scope**:
  1. 資料庫結構擴充與審核核心（`scripts/migrate_page_index_review.py`、`src/pageindex/tree_review.py`、`tree_distiller.py`、後端 Admin API）。
  2. Web App 介面「🌳 臨床推理樹簽核」分頁、四段式卡片視覺化、醫師專屬醫囑填寫與上傳提煉分流。
  3. 多 Agent 流水線驗收（Agy 3.6 Flash 實作 ➔ Claude 5.5 對抗性審查加固 ➔ 終端全套驗收）。

### Phase 22: RAG 提問檢索優化、BM25 排序與結構化衛教生成

**Goal**: 優化臨床衛教提問檢索與本機 LLM 生成品質。在 `search_text` 與 `search_faq_cache` 引入 FTS5 BM25 相關度評分排序（`ORDER BY rank`），擴大 `retrieve_evidence` 檢索召回筆數（4 ➔ 8 筆），並調校 `rag_ask` 衛教 Prompt，使本機模型在嚴守台灣醫療法規（零處方、零價格）前提下，能針對門診處置、日常照護與預防注意事項生成分段結構化且詳盡之回答。
**Status**: Complete (16/16 專屬測試通過、BM25 subquery JOIN 升級、多詞交集加權、MAX_FAQ=8、結構化衛教生成、正式庫零污染)
**Depends on**: Phase 20 (LLM 答案生成與推論優化), Phase 21 (臨床推理樹擴展), Phase 01 (全文檢索核心)
**Scope**:
  1. 全文檢索排序升級：`search_text` 支援 FTS5 BM25 `ORDER BY rank`，改善目前僅依 rowid 順序回傳導致舊資料遮蔽高相關資料之缺陷。
  2. 檢索召回與 Context 擴充：`retrieve_evidence` 放寬 `MAX_FAQ` 由 4 筆擴增至 8 筆（Qwen 128k context 負荷良好），增加居家照護與預防衛教之召回率。
  3. 衛教 Prompt 結構化與長度調校：調整 `build_ask_prompt`，由原 100~250 字放寬為 250~450 字，並引導模型以「門診處置」、「日常/術後照護」、「預防注意」分段說明。
  4. 醫療法規合規與防護回歸：確保擴大字數與檢索後，依然通過 DX-1~6、保證療效、價格屏蔽等所有安全防線，並補充單元測試與端到端測試。


---
### Phase 23: 競品／合作機構網站擷取器（PageIndex 素材自動化）

**Goal**: 建立可設定的網站擷取器，從指定診所網頁（範例：`https://www.nu-vendome.com/location-detail/Taichung/`）擷取結構化資訊（名稱、地址、服務項目、醫師、營業時間等），轉為 PageIndex／FAQ 草稿素材，減少人工逐頁抄錄的人力。
**Status**: Complete (85/85 專屬測試通過、安全網址政策、釘住 IP、節流與 robots、HTML 結構抽取、合規檢驗、唯一寫入路徑、批次編排與抓取前探測鎖、CLI 守門、正式庫零污染)
**Depends on**: Phase 18 (文件上傳與草稿審核), Phase 21 (推理樹審核閘門)
**Scope**:
  1. 擷取器只讀取公開頁面，遵守 `robots.txt`、請求節流與 User-Agent 標示；失敗降級，不影響既有流程。
  2. 擷取結果一律以 `web_upload`（或新審核來源）進入 `pending` 草稿，**不得直接對外可見**；價格、療效、藥品劑量經既有合規檢驗與價格屏蔽。
  3. 擷取來源 URL 與擷取時間寫入 `metadata` 溯源，不保存外部頁面的個人資料（醫師私人聯絡方式等）。
  4. 提供 CLI 與 Web 入口（與 Phase 24 的網址解析選項共用同一擷取模組）。

---
### Phase 24: 上傳中心增強（名稱欄位與網址解析選項）

**Goal**: 於「文件拖曳上傳中心」新增「名稱」欄位，並新增「網站解析」選項，允許貼入網址，由 Phase 23 擷取器解析後進入既有草稿審核流程。
**Status**: Complete (86/86 專屬測試通過、名稱欄位驗證與共用管線抽出、POST /api/v1/admin/upload-url 雙層 SSRF 防禦與 Phase 23 適配器、前端來源切換/名稱欄位/Node 行為測試、正式庫零污染)
**Depends on**: Phase 18 (文件上傳), Phase 23 (網站擷取器)
**Scope**:
  1. 名稱欄位：上傳與網址解析皆須填寫名稱，作為主題／來源顯示名稱（取代僅依檔名產生 `doc-<檔名>` 的限制；舊行為保留為預設值）。名稱需通過去識別化與安全字元檢查。
  2. 網站解析選項：在「提煉與解析目標」旁新增來源切換（檔案／網址），貼入網址後呼叫擷取器，回傳預覽再寫入 `pending` 草稿。
  3. 預覽模式（不寫入資料庫）沿用既有 `preview_only` 語意。
  4. 既有檔案上傳、同名覆蓋與批量上傳行為不得退化；補上相關回歸測試。



---
### Phase 25: 機構代碼選擇、網址解析修復與收尾

**Goal**: 讓上傳中心、臨床 SOAP、向 LLM 提問三處共用可選擇的已建檔診所清單（可新增診所）；修復網址解析的 resolver 錯誤；完成凡登整形外科診所建檔與基本資料。
**Status**: In progress（功能與測試已完成，`25-01-PLAN.md` 已交接 Antigravity；服務內容擷取與營業時間待使用者決定，變更尚未 commit）
**Depends on**: Phase 24 (上傳中心網址解析), Phase 23 (網站擷取器)
**Scope**:
  1. 機構代碼下拉選單與「新增診所」對話框；`GET/POST /api/v1/admin/clinics`，新增不覆寫既有診所。
  2. 網址解析 resolver 修復（`resolver=None`），並補上回歸測試。
  3. 凡登整形外科診所（3503264627）建檔，基本資料來源為地點頁。
  4. 測試隔離：測試後刪除 45 MB 的資料庫副本，避免 `/tmp` 配額耗盡。
  5. 2026-10-15 決定：白名單擴充至 `/service/`（guard 測試已同步）；門診表解析器（`src/scraper/timetable.py`，僅開/休診狀態、不含醫師姓名）已完成並通過測試，寫入 `clinic_hours` 待正式規格。

---
### Phase 26: 病人「先答後導」諮詢流程（階段一，不收集個資）

**Goal**: 建立病人端諮詢的路由規格與可測試邏輯：紅旗 → 已核准診所 FAQ → 已核准一般 FAQ → 沒有資料時誠實說明並送草稿佇列 → 固定預約方式（電話／LINE／官網）。
**Status**: Planned（`26-01-PLAN.md` 已寫，尚未執行；兩項衝突待使用者決定）
**Depends on**: Phase 25 (機構代碼與診所管理), Phase 12/17 (一般衛教 FAQ 與審核閘門)
**Scope**:
  1. 規格文件 `docs/skills/patient-consult-stage1.md`，含醫療廣告禁用語清單。
  2. 路由純函式（不呼叫 LLM），沿用既有審核可見性規則。
  3. 沒有資料時只存問題進草稿佇列，不即時生成答案。
  4. 不收集姓名、電話、身分證、照片；不存對話；不做打分與自動推播。
  5. 待決策：C1 即時 LLM 答案不得直接給病人（採不即時生成）；C2 留資表單屬階段二。
