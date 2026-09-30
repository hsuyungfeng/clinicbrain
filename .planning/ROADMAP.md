# Roadmap: clinicbrain — Taiwan Clinic Medical PageIndex RAG System

## Overview

從台灣健保開放資料出發，建立結構化資料庫與四段式 PageIndex 臨床推理樹，進而串接本地 LLM 推理引擎、多診所健保機構代碼架構、診所營運文件自動化擷取，最終具備向外整合官方醫事 API 的完整診所智慧知識庫系統。

## Milestones

- v1.0 Phase 1-5（已完成）
- v1.1 上線就緒與成本優化 Phase 6-9（進行中）

## Phases

### v1.0

- [x] **Phase 1: Taiwan PageIndex RAG** — 健保藥品/給付項目資料庫、四段式臨床推理樹、OTC 本地化、FTS5 trigram 檢索與基礎評估測試。
- [x] **Phase 2: Local LLM Layer** — 串接本地 llama-server (Qwen3.8-27B)，加入立場中立規則與雙層驗證防禦，完成端到端推理樹生成。
- [x] **Phase 3: Document Ingestion (Stage 1)** — 診所文件（docx/xlsx）擷取、簡繁轉換、自動 Q&A 生成、faq_cache 表與 40 筆真實 FAQ 匯入（Stage 2 OCR 與掃描教材經評估後結案關閉）。
- [x] **Phase 4: Multi-Clinic Support** — 健保機構代碼遷移與必填化、FAQ 快取查詢整合（TASK-00~03 全部完成，commit `bb46697`）。
- [x] **Phase 5: doctor-toolbox.com API Integration** — 官方雙向 API 對接，實現診所資料安全匯入與匯出。

### v1.1 上線就緒與成本優化

- [ ] **Phase 6: API 認證強制化** - 未設管理金鑰時拒絕啟動，確保對外服務預設安全。
- [ ] **Phase 7: 快取優先查詢** - 高信心 FAQ 命中短路回答、標示來源、匿名聚合命中統計，且不繞過價格遮蔽。
- [ ] **Phase 8: 一般醫療諮詢入口** - 不綁診所的匿名 general 端點，附免責聲明與不走 LLM 的紅旗症狀偵測。
- [ ] **Phase 9: 夜間批次生成與維護** - 依未命中統計與手動清單預生成 FAQ、重建過期樹，由 systemd timer 排程。

## Phase Details

### v1.0 Phase 詳情

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
**Status**: Completed (`3bf1436`, `816e3c2`, `5c4f96c`, TASK-04)
**Plans**: 4 tasks
- [x] 05-01: TASK-01 FastAPI 基礎骨架、Pydantic Schema 與健康檢查 (`GET /health`)
- [x] 05-02: TASK-02 自然語言查詢端點封裝 (`POST /api/v1/query` + 多診所動態路由與價格二次遮蔽)
- [x] 05-03: TASK-03 doctor-toolbox.com 雙向同步契約實作 (Export/Import 規格、權威寫入與 `sync_logs`)
- [x] 05-04: TASK-04 端到端整合測試、資料庫零污染驗證與服務啟動器 (`scripts/run_api_server.py`)

### Phase 6: API 認證強制化
**Goal**: 服務只能在金鑰保護下對外上線，本機開發則需明確選擇關閉。
**Depends on**: Phase 5
**Requirements**: AUTH-01
**Success Criteria** (what must be TRUE):
  1. 未設定 `CLINICBRAIN_ADMIN_API_KEY` 且未指定開發旗標時，執行 `scripts/run_api_server.py` 會拒絕啟動並印出繁體中文錯誤說明
  2. 指定本機開發旗標可在無金鑰下啟動，且啟動時印出繁體中文警告
  3. 設定金鑰後，未帶或帶錯 `X-API-Key` 呼叫同步端點得到 401/403，帶正確金鑰則成功
**Plans**: 2 plans（06-01 實作核心、06-02 測試與文件）

### Phase 7: 快取優先查詢
**Goal**: 查詢命中高信心 FAQ 時直接回覆 FAQ 原文，並能以匿名方式量測命中率，全程維持純檢索與價格遮蔽。
**Depends on**: Phase 6
**Requirements**: CACHE-01, CACHE-02, CACHE-03, CACHE-04
**Success Criteria** (what must be TRUE):
  1. 查詢已收錄的常見問題時，回應直接是 FAQ 原文，不附帶大量樹狀資料，且查詢路徑不呼叫 LLM
  2. 每個回應含來源欄位（`cache` / `pageindex` / `llm`），使用者可分辨答案出處
  3. 命中與未命中次數可被查詢，但資料庫中查不到任何問句全文或個資，僅有聚合計數或 topic_key
  4. 內含金額的 FAQ 經快取捷徑回覆時，價格數字仍被替換為「請致電診所確認」
**Plans**: TBD

### Phase 8: 一般醫療諮詢入口
**Goal**: 民眾可匿名詢問一般醫療問題，得到附免責聲明的回答，危急症狀則直接被引導就醫。
**Depends on**: Phase 6
**Requirements**: GENERAL-01, GENERAL-02, GENERAL-03, GENERAL-04
**Success Criteria** (what must be TRUE):
  1. 呼叫一般諮詢端點無需提供 `clinic_id`，且只回傳 general 類資料，不含診所私有資訊
  2. 每則 general 回答都附繁體中文免責聲明（非醫囑、建議就醫）
  3. 輸入含紅旗症狀（如胸痛、呼吸困難）的問題時，回傳固定就醫提示，且該次請求未呼叫 LLM
  4. 送出諮詢後檢查資料庫與日誌，查不到問句全文、個資或提問歷史
**Plans**: TBD

### Phase 9: 夜間批次生成與維護
**Goal**: 系統每晚自動擴充 FAQ 並更新過期臨床樹，且安全、可預演、可追蹤。
**Depends on**: Phase 7
**Requirements**: BATCH-01, BATCH-02, BATCH-03, BATCH-04
**Success Criteria** (what must be TRUE):
  1. 批次讀取「快取未命中統計（topic_key）+ 手動清單」產生待生成主題，不使用簡體 SFT 資料
  2. 預生成的 FAQ 經四層驗證器後才以 `source_type='llm_generated'` 寫入 `faq_cache`；驗證失敗者不入庫
  3. `needs_regeneration=1` 的樹被重建並通過驗證，且 `*_physician_notes` 欄位內容前後完全不變
  4. `--dry-run` 只輸出預計動作而不寫入資料庫；LLM 不可用時批次優雅跳過並記錄日誌，不崩潰
  5. systemd timer 可啟用夜間排程，每次執行留下執行日誌
**Plans**: TBD

## Progress

| Phase | Tasks Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Taiwan PageIndex RAG | 8/8 | Complete | 2026-09-21 |
| 2. Local LLM Layer | 4/4 | Complete | 2026-09-22 |
| 3. Document Ingestion | 4/4 (Stage 1) | Stage 1 Complete / OCR Closed | 2026-09-23 |
| 4. Multi-Clinic Support | 4/4 | Complete | 2026-09-29 |
| 5. doctor-toolbox.com API | 4/4 | Complete | 2026-09-29 |
| 6. API 認證強制化 | 0/0 | Not started | - |
| 7. 快取優先查詢 | 0/0 | Not started | - |
| 8. 一般醫療諮詢入口 | 0/0 | Not started | - |
| 9. 夜間批次生成與維護 | 0/0 | Not started | - |


