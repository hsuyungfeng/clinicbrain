# Roadmap: clinicbrain — Taiwan Clinic Medical PageIndex RAG System

## Overview

從台灣健保開放資料出發，建立結構化資料庫與四段式 PageIndex 臨床推理樹，串接本地 LLM、多診所健保機構代碼架構、文件擷取、官方 API 整合，並完成認證強制、快取優先查詢、匿名一般諮詢與醫師審核閘門下的夜間批次。v1.3 新增臨床端能力，支援外部系統（doctor-toolbox.com）推播文字與語音紀錄，確定性 S/O/A/P 切分、特徵擷取、個資去識別化與專屬醫師檢索。

## Milestones

- ✅ **v1.0 Taiwan PageIndex RAG 基礎系統** — Phase 1–5（2026-09-29 完成）— [歸檔](milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 上線就緒與成本優化** — Phase 6–9（2026-10-02 完成）— [歸檔](milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 診所資料優先與一般疾病簡易資訊** — Phase 10–13（2026-10-06 完成）— [歸檔](milestones/v1.2-ROADMAP.md)
- ✅ **v1.3 臨床語音與 SOAP 紀錄擷取** — Phase 14（2026-10-07 完成）— [歸檔](milestones/v1.3-ROADMAP.md)
- 🚧 **v1.4 臨床衛教提煉與進階防護** — Phase 15+（進行中）

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 10. 技術債基礎清理 | 3/3 | Complete | 2026-10-02 |
| 11. 診所資料優先檢索 | 4/4 | Complete | 2026-10-03 |
| 12. 一般疾病內容生成與審核 | 6/6 | Complete | 2026-10-05 |
| 13. 真實 LLM 批次實跑驗證 | 2/2 | Complete | 2026-10-06 |
| 14. 臨床語音與 SOAP 紀錄擷取 | 3/3 | Complete | 2026-10-07 |
| 15. 臨床 SOAP 衛教提煉與審核流 | 0/3 | Planned | - |

## Phase Details

### Phase 14: 臨床語音與 SOAP 紀錄擷取 (已完成)

見歸檔：[v1.3-ROADMAP.md](milestones/v1.3-ROADMAP.md)

### Phase 15: 臨床 SOAP 衛教提煉與審核流

**Goal**: 在維持公開端點嚴格隔離的前提下，建立醫師審核工具，將去識別化之 SOAP Assessment/Plan 臨床照護摘要提煉轉化為衛教問答草稿（pending 狀態），經醫師簽核後方可發布至診所 FAQ 或推理樹供查詢引用。
**Depends on**: Phase 14 (SOAP 去識別化與特徵擷取), Phase 12 (審核工具與驗證層)
**Requirements**: SOAP-EDU-01, SOAP-EDU-02, SOAP-EDU-03
**Success Criteria**:
  1. 公開自然語言查詢端點（`/api/v1/query`、`/api/v1/general/query`）維持絕對隔離，零 SOAP 原始紀錄或直接查詢洩漏。
  2. 提煉管線：支援由去識別化 `soap_records` 彙整常見處置與衛教指引，產出繁體中文 FAQ 衛教草稿，預設 `review_status = 'pending'`。
  3. 審核整合：整合 `review_faq` 工具，醫師可檢視提煉來源（含去識別化前文摘要）並簽核核准。
  4. 二次醫療法規防禦：提煉草稿經價格清洗、保證療效禁詞過濾與 DX 劑量攔截器檢驗。
