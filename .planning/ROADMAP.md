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
| 15. 臨床 SOAP 衛教提煉與審核流 | 3/3 | Complete | 2026-10-07 |
| 16. 定時自動化同步與批次提煉排程 | 0/3 | Planned | - |
| 17. 定時一般醫學知識補充與批次擴充 | 0/2 | Planned | - |
| 18. 各診所資料上傳與管理 Web App | 0/4 | Planned | - |

## Phase Details

### Phase 15: 臨床 SOAP 衛教提煉與審核流 (已完成)

**Goal**: 在維持公開端點嚴格隔離的前提下，建立醫師審核工具，將去識別化之 SOAP Assessment/Plan 臨床照護摘要提煉轉化為衛教問答草稿（pending 狀態），經醫師簽核後方可發布至診所 FAQ 或推理樹供查詢引用。
**Status**: Complete (10/10 單元測試、5/5 步驟業務閉環實機通過)

### Phase 16: 定時自動化同步與批次提煉排程

**Goal**: 建立夜間自動化排程機制，整合外部系統（doctor-toolbox.com / EHR）推播同步，於離峰時間自動對未提煉之 SOAP 紀錄執行分組提煉並生成 pending 草稿，支援醫師晨間一鍵簽核。
**Depends on**: Phase 15 (SOAP 衛教提煉器與審核流), Phase 09 (夜間批次架構)
**Scope**:
  1. 擴充 `scripts/run_nightly_batch.py`，納入 SOAP 衛教提煉子任務。
  2. 整合 Systemd Timer 與 Cron 排程範本，支援自動排程與離線重試。
  3. 新增批次提煉審計日誌與摘要報表輸出。

### Phase 17: 定時一般醫學知識補充與批次擴充

**Goal**: 建立通用醫學知識庫之定時自動補充機制，透過本地 LLM 離峰批次生成常見疾病衛教與健保給付指引，經既有審核閘門安全擴增 general 知識庫。
**Depends on**: Phase 12 (一般疾病種子與審核), Phase 16 (批次排程)
**Scope**:
  1. 擴充通用疾病與常見症狀種子清單。
  2. 自動化離峰批次生成管線，支援斷點續跑與安全防禦。
  3. 待審一般衛教問答批次簽核支援。

### Phase 18: 各診所資料上傳與管理 Web App

**Goal**: 提供直覺友善的輕量 Web 介面，供各診所人員上傳診所文件（DOCX/XLSX/PDF）、檢視 SOAP 紀錄與溯源、並提供視覺化醫師簽核與營運資訊管理介面。
**Depends on**: Phase 05 (FastAPI 服務層), Phase 15 (審核工具)
**Scope**:
  1. 檔案上傳與自動處理介面（DOCX / XLSX / PDF）。
  2. 視覺化醫師簽核儀表板（pending 草稿卡片、溯源病歷對照、一鍵核准/駁回）。
  3. 診所營運資料管理（門診時間、自訂備註、診所資訊編輯）。
  4. 多診所權限隔離與管理員認證。
