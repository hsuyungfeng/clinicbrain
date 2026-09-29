# Roadmap: clinicbrain — Taiwan Clinic Medical PageIndex RAG System

## Overview

從台灣健保開放資料出發，建立結構化資料庫與四段式 PageIndex 臨床推理樹，進而串接本地 LLM 推理引擎、多診所健保機構代碼架構、診所營運文件自動化擷取，最終具備向外整合官方醫事 API 的完整診所智慧知識庫系統。

## Phases

- [x] **Phase 1: Taiwan PageIndex RAG** — 健保藥品/給付項目資料庫、四段式臨床推理樹、OTC 本地化、FTS5 trigram 檢索與基礎評估測試。
- [x] **Phase 2: Local LLM Layer** — 串接本地 llama-server (Qwen3.8-27B)，加入立場中立規則與雙層驗證防禦，完成端到端推理樹生成。
- [x] **Phase 3: Document Ingestion (Stage 1)** — 診所文件（docx/xlsx）擷取、簡繁轉換、自動 Q&A 生成、faq_cache 表與 40 筆真實 FAQ 匯入（Stage 2 OCR 與掃描教材經評估後結案關閉）。
- [x] **Phase 4: Multi-Clinic Support** — 健保機構代碼遷移與必填化、FAQ 快取查詢整合（TASK-00~03 全部完成，commit `bb46697`）。
- [ ] **Phase 5: doctor-toolbox.com API Integration** — 官方雙向 API 對接，實現診所資料安全匯入與匯出。

## Phase Details

### Phase 1: Taiwan PageIndex RAG
**Goal**: 建立健保資料庫、四段式 PageIndex 樹、OTC 本地化與安全檢索。
**Status**: Completed (`0ac396d` ~ `a09e829`)
**Plans**: 8 tasks
- [x] 01-01: TASK-001 SQLite schema + seed from OriginalData
- [x] 01-02: TASK-003 PageIndex schema + 6 筆手寫臨床推理樹範本
- [x] 01-03: SCHEMA-INCREMENTAL 增量更新機制與內容版號
- [x] 01-04: TASK-004 LLM prompt 範本與驗證器
- [x] 01-05: TASK-005 查詢介面與 special/general 路由分流
- [x] 01-06: TASK-006 OTC 藥品學名繁中本地化（68 種成分）
- [x] 01-07: TASK-007 診所自訂備註與營運資料庫整合
- [x] 01-08: TASK-008 評估與回歸測試套件（91 個測試）

### Phase 2: Local LLM Layer
**Goal**: 接入本機 llama-server，落實隱私優先推理與政治立場防禦。
**Status**: Completed (`ff04197`)
**Plans**: 4 tasks
- [x] 02-01: TASK-01 `llm_client.py` 串接本機 llama-server
- [x] 02-02: TASK-02 Prompt 範本加入中立立場第 7 條規則
- [x] 02-03: TASK-03 驗證器加入 `_POLITICAL_STANCE_PHRASES` 防禦
- [x] 02-04: TASK-04 端到端推理生成真實療程樹（隔離驗證）

### Phase 3: Document Ingestion
**Goal**: 從診所上傳文件自動化萃取衛教與 Q&A 快取。
**Status**: Stage 1 Completed (`625593d`, `35a71a5`); Stage 2/教材 OCR 結案關閉
**Plans**: 4 tasks
- [x] 03-01: TASK-00 `faq_cache` 表、FTS5 trigram 與 `faq_writer.py`
- [x] 03-02: TASK-01 docx/xlsx 文件文字擷取模組
- [x] 03-03: TASK-02 opencc 簡繁轉換（s2twp）
- [x] 03-04: TASK-03 LLM 生成 FAQ、四層安全驗證與 40 筆正式資料匯入
- [x] 03-05: Stage 2 圖片 OCR 與教科書抽查評估（判定不值得展開，正式結案）

### Phase 4: Multi-Clinic Support
**Goal**: 支援多診所架構，將機構代碼標準化並強化查詢邊界與 FAQ 檢索整合。
**Status**: Completed (`f487763`, `625593d`, TASK-03)
**Plans**: 4 tasks
- [x] 04-00: `page_index_trees` 補齊 `clinic_id` 與 `doc_id` 去前綴
- [x] 04-01: `clinic_id` 數值全庫遷移至健保代碼 `3503190424`
- [x] 04-02: 查詢函式移除過期預設值，改為必填參數
- [x] 04-03: FAQ 快取查詢整合與多診所檢索分流（`search_faq_cache` + `QueryResponse.faq_hits`）

### Phase 5: doctor-toolbox.com API Integration
**Goal**: 建立 FastAPI 服務層、封裝 handle_query 查詢端點，並透過官方 API 達成雙向醫事資料同步契約。
**Status**: In Progress (規格書已展開)
**Plans**: 4 tasks
- [x] 05-01: TASK-01 FastAPI 基礎骨架、Pydantic Schema 與健康檢查 (`GET /health`)
- [x] 05-02: TASK-02 自然語言查詢端點封裝 (`POST /api/v1/query` + 多診所動態路由與價格二次遮蔽)
- [ ] 05-03: TASK-03 doctor-toolbox.com 雙向同步契約實作 (Export/Import 規格、權威寫入與 `sync_logs`)
- [ ] 05-04: TASK-04 端到端整合測試、資料庫零污染驗證與服務啟動器 (`scripts/run_api_server.py`)

## Progress

| Phase | Tasks Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Taiwan PageIndex RAG | 8/8 | Complete | 2026-09-21 |
| 2. Local LLM Layer | 4/4 | Complete | 2026-09-22 |
| 3. Document Ingestion | 4/4 (Stage 1) | Stage 1 Complete / OCR Closed | 2026-09-23 |
| 4. Multi-Clinic Support | 4/4 | Complete | 2026-09-29 |
| 5. doctor-toolbox.com API | 2/4 | In Progress | - |


