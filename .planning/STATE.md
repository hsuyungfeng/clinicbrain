---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: 上線就緒與成本優化
status: complete-pending-archive
last_updated: "2026-10-02T00:00:00.000Z"
last_activity: 2026-10-02
progress:
  total_phases: 4
  completed_phases: 4
  total_plans: 16
  completed_plans: 16
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-29)

**Core value:** 在符合台灣醫療法規（絕對價格遮蔽、全繁體中文、無保證療效）的前提下，提供診所高精準度、低延遲、隱私優先（純本地推理）的臨床衛教與藥品檢索。
**Current focus:** v1.1 全部 Phase 完成；待使用者執行 Phase 9 正式庫遷移後歸檔里程碑

## Current Position

Phase: 9 of 9 (夜間批次生成與維護) — v1.1 四個 Phase 全部完成
Plan: 16/16 plans 完成（Phase 6: 2、Phase 7: 4、Phase 8: 4、Phase 9: 6）
Status: Complete — 待使用者手動遷移正式庫 review_status 後歸檔
Last activity: 2026-10-02 — Phase 6–9 已執行、獨立驗證、commit 並 push（078d4dc）

## Performance Metrics

**Velocity:**

- Total tasks completed: 24+
- Tests passing: 578/578 (100%)
- SQLite records: 7,573 drugs, 2,669 services, 6 PageIndex trees, 40 FAQs

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Phase 04]: `clinic_id` 全面標準化為健保代碼 `'3503190424'`，查詢函式強制必填，避免跨診所資料洩漏。
- [Phase 03]: `faq_cache` 採獨立扁平表，正式庫套用完成並匯入 40 筆真實 FAQ（`source_type='clinic_upload'`）。
- [Phase 03]: 結案 Stage 2 圖片 OCR 與 `美容醫學/` 掃描教科書，判定投資報酬率極低且非衛教素材，不展開 OCR 管線。
- [Phase 09]: LLM 預生成 FAQ 預設 pending，需醫師核准才可被查詢/匯出；樹重建不走閘門（前像快照 + physician_notes 保護 + 手動標記）。
- [Phase 08]: 一般諮詢端點匿名、不查診所資料、紅旗詞表經使用者定稿（自傷輕生不納入）。
- [Phase 07]: 查詢路徑維持純檢索；未命中統計只記路由關鍵字聚合計數。
- [Phase 02]: 本機 llama-server (Qwen3.8-27B) 維持使用，採 Prompt + 驗證器雙層防禦過濾政治立場內容。

### Pending Todos

- 使用者手動：Phase 9 正式庫 review_status 遷移（先停服務、sqlite3 .backup 備份、遷移前後各量 sha256sum、--confirm-prod-backup）
- 歸檔里程碑：/gsd-complete-milestone（一次歸檔 v1.0 與 v1.1）
- 之後可考慮：general 類內容目前 0 筆（需批次生成 + 醫師核准）、2~3 字滑動窗改善檢索、應用層速率限制、AUTH-03/04

### Blockers/Concerns

- `src/query/router.py` 的 `extract_search_terms()` 仍非完整中文斷詞：2 字通用詞已由 `_GENERIC_TERMS` 降權（2026-09-30），但「動詞+名詞」黏連殘渣片段（如「音波拉提維持」「甲溝炎要」）尚未過濾，僅浪費一次查詢，不影響結果正確性。

## Session Continuity

Last session: 2026-10-02（Resumed）
Stopped at: v1.1 Phase 6–9 完成；等待使用者遷移正式庫與歸檔
Resume file: .planning/HANDOFF.json（保留至遷移與歸檔完成）
