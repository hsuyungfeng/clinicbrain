---
gsd_state_version: 1.0
milestone: v1.3
milestone_name: 臨床語音與 SOAP 紀錄擷取
status: completed_milestone
stopped_at: Milestone v1.3 / Phase 14（含剩餘項目改善管線）已圓滿完成，全套回歸測試 945 passed (SOAP 專屬 69 passed)，正式資料庫 SHA-256 恆定未變
last_updated: "2026-10-07T15:15:00.000Z"
last_activity: 2026-10-07 -- Phase 14 剩餘項目強化完成（Dry-Run 修復、切分標記嚴格化、否定防禦），全量測試通過
progress:
  total_phases: 1
  completed_phases: 1
  total_plans: 3
  completed_plans: 3
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-02)

**Core value:** 在符合台灣醫療法規（絕對價格遮蔽、全繁體中文、無保證療效）的前提下，提供診所高精準度、低延遲、隱私優先（純本地推理）的臨床衛教與藥品檢索。
**Current focus:** Milestone v1.4 推進中；已完成 Phase 15 及端到端業務閉環驗證，準備進入 Phase 16（定時自動化同步與批次提煉排程）

## Current Position

Phase: 17 of 18（定時一般醫學知識補充與批次擴充）-- COMPLETED
Plan: 17-01、17-02、17-03 均已實作、加固與全套回歸驗證通過
Status: Phase 17 Completed (Milestone v1.4 進行中，下一個為 Phase 18)
Last activity: 2026-10-08 -- 完成 Phase 17 通用種子庫擴充（8 主題 32 題）、general-only 批次調度與斷點續跑、審核 CLI 篩選與 E2E 驗收；通過 Claude 4 項加固；全套回歸 1012 測試全數通過；正式庫 SHA-256 恆定未變

Progress: [█████████░] 94%

## Performance Metrics

**Velocity:**

- Total tasks completed: 56+
- Tests passing: 1012 passed, 1 skipped, 3 deselected (Phase 17 專屬與加固全過)
- SQLite records: 7,573 drugs, 2,669 services, 6 PageIndex trees, 40 FAQs, 15 種子主題 (32+ 題)，soap_records/soap_records_fts (trigram) 支援，clinic.db SHA-256 (5fb8328d...) 零污染

## Accumulated Context

### Decisions

- [Phase 15 2026-10-07]: 完成臨床 SOAP 衛教提煉與審核流（Herdr 多 Agent 流程：Agy 實作、Claude 對抗性審查加固、Hermes 驗收）。實作 `src/soap/distiller.py` 居家照護特徵聚合與價格/劑量二次清洗；擴充 `faq_writer.py` 支援 `source_type='soap_distilled'` 與 `metadata` 欄位；確立法規防禦「正式庫寫入路徑絕不自動 ALTER」，透過 `scripts/migrate_faq_metadata.py` 採 DDL 單一來源遷移；修復重複提煉重設審核狀態 Bug（內容未變僅更新 metadata 不重設 status）；修復 SQLite NULL 三值邏輯隔離漏洞；擴充 `review_faq.py` 與 `faq_review.py` 支援 `--source soap_distilled` 篩選與臨床病歷溯源顯示；新增 `distill_soap_faqs.py` 支援 `--dry-run` 唯讀連線模式；全套單元與端到端測試 10/10 PASS，正式庫 `clinic.db` SHA-256 維持 `ad24426cadd84db7`。
- [Phase 14 2026-10-07]: 使用者五項醫療語意決策全數採納：疑似/R/O 排除（方案 A）、Assessment 為空 conditions 留空（方案 A）、英文縮寫不擅自映射（方案 A）、取消單字母空白分隔並強制標點（方案 A）、行內單字母標記不承認（保守規則，僅行首與成對括號承認，排除脈搏 P: 80 衝突）；粗括號放寬前導切分；後置否定容許最多 4 個非標點字元；migrate_soap_schema 支援 --dry-run 純記憶體預覽。
- [Phase 14 2026-10-06]: 支援外部推播（doctor-toolbox.com）與語音聽寫紀錄入庫；section_parser 自動切分 S/O/A/P 並安全退化至 subjective；extract_general_medical_insights 自動萃取一般醫學特徵、症狀與居家照護摘要；deid 模組遮蔽台灣身分證、電話、姓名，並套用 deep_mask_prices 洗清金額；patient_token 採 HMAC-SHA256 偽名化衍生；soap_writer 提供唯一權威 upsert；FastAPI /api/v1/soap/records、/search、/records/{external_id} 強制 verify_admin_key 認證與診所隔離；公開端點嚴格隔離；單一來源遷移腳本維護 trigram FTS5 虛擬表與 3 觸發器。
- [Phase 12 複審補強 2026-10-06]: 劑量層 DX-2 涵蓋只有數量的句子、否定詞須緊鄰動詞才豁免、詞庫補劑型與英文學名；警訊層排除勸人別就醫的反向句並支援條列式；DEBT-03 補 `mark-regen --seed`（種子外題目拒絕標記）、`list` 顯示「待重生」、批次日誌記 unchanged/failed 列 id。
- [Phase 11]: 診所資料優先檢索（Tiered 兩階段判定），帶 clinic_id 優先查 special FAQ，短路率 24/40 -> 38/40；相近阻斷下限 CLINIC_RELATED_FLOOR = 0.4；回應結構新增 data_level 標示層級；無 clinic_id 查詢排除所有診所 FAQ。
- [Phase 10]: 遷移腳本 ALTER 改自 clinic_schema.sql 動態擷取單行定義（消除 DDL 雙寫）；移除 APIConfig.default_clinic_id 孤兒設定，堅持 clinic_id 明確傳入原則。

### Pending Todos

- 正式環境資料庫遷移：需由管理員備份正式庫後執行 `python3 scripts/migrate_soap_schema.py --confirm-prod-backup`。
- 使用者待辦：請醫師合併正式庫 id 4 與 id 19 重複問句（或區分情境），合併後短路率可由 38/40 達 40/40。
- 下一階段規劃：Phase 15（臨床 SOAP 衛教提煉與審核流）。

## Session Continuity

Last session: 2026-10-07
Stopped at: Milestone v1.3 完成封裝歸檔
Resume file: 無
