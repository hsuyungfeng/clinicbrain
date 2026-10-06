# Roadmap: clinicbrain — Taiwan Clinic Medical PageIndex RAG System

## Overview

從台灣健保開放資料出發，建立結構化資料庫與四段式 PageIndex 臨床推理樹，串接本地 LLM、多診所健保機構代碼架構、文件擷取、官方 API 整合，並完成認證強制、快取優先查詢、匿名一般諮詢與醫師審核閘門下的夜間批次。v1.2 讓診所自己的資料永遠優先被查，並以本地 LLM 生成、經醫師審核的一般疾病簡易資訊補足一般問題。

## Milestones

- ✅ **v1.0 Taiwan PageIndex RAG 基礎系統** — Phase 1–5（2026-09-29 完成）— [歸檔](milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 上線就緒與成本優化** — Phase 6–9（2026-10-02 完成）— [歸檔](milestones/v1.1-ROADMAP.md)
- 🚧 **v1.2 診所資料優先與一般疾病簡易資訊** — Phase 10–13（進行中）

## Phases

- [x] **Phase 10: 技術債基礎清理** - 收斂 migration 與 schema 的雙寫、處理孤兒設定 `default_clinic_id`。
- [x] **Phase 11: 診所資料優先檢索** - 有 `clinic_id` 時先查診所自己的 FAQ，未命中才退到已審核 general，並標示資料層級。
- [x] **Phase 12: 一般疾病內容生成與審核** - 擴充疾病種子、新增用藥劑量攔截與就醫警訊驗證層、改善審核與駁回重生成工具。
- [x] **Phase 13: 真實 LLM 批次實跑驗證** - 在資料庫複本上以真實 llama-server 完整驗證批次流程。
- [x] **Phase 14: 臨床語音與 SOAP 紀錄擷取** - 接收外部推播臨床文字、切分 S/O/A/P、萃取一般醫學特徵、去識別化與專屬醫師檢索。

## Phase Details

### Phase 10: 技術債基礎清理

**Goal**: schema 定義只有單一來源，且設定檔中不再有無作用的設定項。
**Depends on**: Nothing（v1.2 第一個 phase；與其他 phase 無相依，風險低）
**Requirements**: DEBT-01, DEBT-02
**Success Criteria** (what must be TRUE):

  1. `migrate_faq_review_status` 執行的 ALTER 內容由 `clinic_schema.sql` 擷取而來，原始碼中不再有與 schema 重複手寫的欄位定義；對測試複本執行遷移後，欄位與 schema 建出的新庫一致
  2. 修改 schema 中該欄位定義後，遷移腳本行為隨之改變，不需同步改第二處
  3. `config.default_clinic_id` 要嘛在查詢解析順序中真正作為最後後備（未帶 Path/Body/Header 時以它解析），要嘛已從設定移除；兩種結果皆有測試覆蓋
  4. AGENTS.md 2.6 的診所識別解析順序描述與程式碼實際行為一致

**Plans**: 3 plans
Plans:
**Wave 1**

- [x] 10-01-PLAN.md — DEBT-01：遷移腳本 ALTER 改由 clinic_schema.sql 擷取（單一來源）+ 證明測試
- [x] 10-02-PLAN.md — DEBT-02：移除 config.default_clinic_id 及 banner/systemd 範本引用 + 行為測試

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 10-03-PLAN.md — AGENTS.md 對齊、全量回歸與正式庫不變驗收

### Phase 11: 診所資料優先檢索

**Goal**: 帶診所身分的查詢一律先查該診所自己的資料，診所沒有答案才退到已審核的一般內容，且使用者能分辨答案層級。
**Depends on**: Phase 10
**Requirements**: CF-01, CF-02, CF-03
**Success Criteria** (what must be TRUE):

  1. 帶 `clinic_id` 的查詢，即使問句不含任何 special 路由關鍵字，仍能命中該診所 special FAQ；正式庫 40 筆 FAQ 以原文自查短路數由 24/40 提升到 38/40（原先被誤分流為 general 的 16 筆中，扣除 id 4 與 id 19 兩筆問句相同但答案不同而 ambiguous 者，其餘 14 筆可被短路）；該 2 筆為資料重複問題，待使用者請醫師合併，不以放寬門檻處理
  2. 診所 FAQ 未命中時，回應退到已審核（approved）的 general 內容；未核准（pending/rejected）內容絕不出現
  3. 每個回應明確標示資料層級（`clinic` 或 `general`），一般衛教內容不會被呈現為診所意見
  4. 營運資訊問句（門診時間、地址等）仍走營運路由；風險特徵、歧義邊界、價格遮蔽、審核閘門行為不變，Phase 7 既有測試與全套測試（基線 588 passed + 1 skipped，以執行當下實測為準）無回歸，並新增針對擴大候選集的對抗性回歸測試；診所低覆蓋時若診所有相近內容（覆蓋率 >= 0.4）不得退到 general，避免一般通則冒充診所規定；沒有 clinic_id 時不得列出任何診所專屬 FAQ

**Plans**: 4 plans (11-01 檢索順序、11-02 跨層級 short-circuit、11-03 查詢回應結構、11-04 驗收)

### Phase 12: 一般疾病內容生成與審核

**Goal**: 本地 LLM 能生成安全、含就醫警訊的一般疾病簡易資訊，並由醫師以順手的工具審核後才上線。
**Depends on**: Phase 11（general 內容消費端就位；生成與驗證層本身可獨立開發）
**Requirements**: GC-01, GC-02, GC-03, GC-04, DEBT-03
**Success Criteria** (what must be TRUE):

  1. 疾病種子清單涵蓋「這是什麼／常見症狀／何時就醫／日常照護」四類問題，所有問題由人撰寫、載入時通過四層檢查，且問題文字已由使用者審閱定稿
  2. 提示詞禁止具體用藥劑量與處方建議；驗證器新增攔截層，含劑量或處方語句的模擬輸出被拒絕、不入庫（含誤放行負例與正例測試）
  3. 每筆生成答案必含「何時該就醫」警訊段落，缺少者被驗證器拒絕；所有對外回覆附免責聲明
  4. 審核工具 `review_faq` 可依主題批次檢視，並顯示每筆的生成來源與驗證結果；審核 general FAQ 時列出覆蓋率相近的診所 FAQ 供人工比對是否衝突；生成結果一律為 `pending`，核准前對外完全隱蔽
  5. 被駁回的題目可由人明確指令觸發重新生成；夜間批次預設仍不自動重生成被駁回項目

**Plans**: 6 plans (12-01 驗證層、12-02 種子［需使用者閘門，已簽核］、12-03 重生成、12-04 免責與 sync、12-05 審核工具、12-06 驗收)

### Phase 13: 真實 LLM 批次實跑驗證

**Goal**: 確認夜間批次在真實本地 LLM 下端到端可運作，且全程不碰正式庫。
**Depends on**: Phase 12（新驗證層與審核流程就緒後再實跑）
**Requirements**: DEBT-04
**Success Criteria** (what must be TRUE):

  1. 在 `llama-server` 空閒時，對資料庫複本執行完整批次，產出的 FAQ 與樹經驗證後以 `pending` 寫入複本，過程無未預期例外
  2. 實跑前後正式 `clinic.db` 的雜湊值完全一致（未被寫入）
  3. 實跑結果（通過／被驗證器攔截的筆數、逾時情形、日誌隱私檢查）有書面紀錄，發現的問題已列入後續待辦

**Plans**: 2 plans (13-01 自動化實跑測試、13-02 品質審計報告與結案)

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 10. 技術債基礎清理 | 3/3 | Complete | 2026-10-02 |
| 11. 診所資料優先檢索 | 4/4 | Complete | 2026-10-03 |
| 12. 一般疾病內容生成與審核 | 6/6 | Complete | 2026-10-05 |
| 13. 真實 LLM 批次實跑驗證 | 2/2 | Complete | 2026-10-06 |
| 14. 臨床語音與 SOAP 紀錄擷取 | 3/3 | Complete | 2026-10-06 |

### Phase 14: 臨床語音與 SOAP 紀錄擷取

**Goal**: 透過官方 API 接收外部系統（如 doctor-toolbox.com）推播之臨床文字，安全解析切分為 S/O/A/P 結構並入庫至專屬 SQLite 資料表與 FTS5 虛擬表，提供院所醫師內部全文檢索與個資去識別化防護。
**Depends on**: Phase 13
**Requirements**: D-01, D-02, D-03, D-04, D-05, D-06, D-07, D-08, D-09
**Success Criteria** (what must be TRUE):

  1. `soap_records` 資料表與 `soap_records_fts`（`tokenize='trigram'`）虛擬表結構正確建立，且三向觸發器保持全文檢索即時同步。
  2. 具備單一權威寫入函式 `upsert_soap_records`，依 `(clinic_id, external_id)` 實現冪等 UPSERT 與內容比對。
  3. `section_parser` 能正確切分繁體中文常見臨床段落前綴；未標記文本安全 fallback 至 subjective。
  4. 醫療個資防禦就緒：台灣身分證字號、手機號碼、市話、姓名自動遮蔽；金額數字自動清洗為 `[請致電診所確認]`；生成不可逆之 `patient_token`。
  5. API 端點 `POST /api/v1/soap/records` 支援結構化或純文字推播；`POST /api/v1/soap/search` 與 `GET /api/v1/soap/records/{external_id}` 支援醫師內部 FTS5 檢索與權限隔離；公開自然語言端點絕無存取權限。
  6. 全量回歸測試通過，正式 `clinic.db` SHA-256 全程未變。

**Plans**: 3 plans

Plans:
- [x] 14-01-PLAN.md — SOAP 資料庫結構、trigram FTS5 虛擬表、觸發器、單一來源遷移與權威寫入模組
- [x] 14-02-PLAN.md — 臨床文字 S/O/A/P 結構切分器、台灣病患個資去識別化與價格清洗守衛
- [x] 14-03-PLAN.md — FastAPI 接收與檢索端點、醫師權限隔離、端到端驗收測試與營運文件
