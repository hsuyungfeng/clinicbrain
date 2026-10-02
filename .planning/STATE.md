---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: 診所資料優先與一般疾病簡易資訊
status: completed_phase
stopped_at: Phase 10 已完成（3 份計畫全數驗收通過）；準備進入 Phase 11
last_updated: "2026-10-02T08:55:00.000Z"
last_activity: 2026-10-02 -- Phase 10 execution complete (589/589 tests passed)
progress:
  total_phases: 4
  completed_phases: 1
  total_plans: 3
  completed_plans: 3
  percent: 25
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-02)

**Core value:** 在符合台灣醫療法規（絕對價格遮蔽、全繁體中文、無保證療效）的前提下，提供診所高精準度、低延遲、隱私優先（純本地推理）的臨床衛教與藥品檢索。
**Current focus:** v1.2 診所資料優先與一般疾病簡易資訊（Phase 10–13）；Phase 10 完成，準備 Phase 11

## Current Position

Phase: 11 of 13（診所資料優先檢索）
Plan: TBD
Status: Ready to plan Phase 11
Last activity: 2026-10-02 -- Phase 10 execution complete (589/589 tests passed)

Progress: [██▌░░░░░░░] 25%

## Performance Metrics

**Velocity:**

- Total tasks completed: 27+
- Tests passing: 589/589 (100%)
- SQLite records: 7,573 drugs, 2,669 services, 6 PageIndex trees, 40 FAQs

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Phase 10]: 遷移腳本 ALTER 改自 clinic_schema.sql 動態擷取單行定義（消除 DDL 雙寫）；移除 APIConfig.default_clinic_id 孤兒設定，堅持 clinic_id 明確傳入原則。

- [Phase 04]: `clinic_id` 全面標準化為健保代碼 `'3503190424'`，查詢函式強制必填，避免跨診所資料洩漏。
- [Phase 03]: `faq_cache` 採獨立扁平表，正式庫套用完成並匯入 40 筆真實 FAQ（`source_type='clinic_upload'`）。
- [Phase 03]: 結案 Stage 2 圖片 OCR 與 `美容醫學/` 掃描教科書，判定投資報酬率極低且非衛教素材，不展開 OCR 管線。
- [Phase 09]: LLM 預生成 FAQ 預設 pending，需醫師核准才可被查詢/匯出；樹重建不走閘門（前像快照 + physician_notes 保護 + 手動標記）。
- [Phase 08]: 一般諮詢端點匿名、不查診所資料、紅旗詞表經使用者定稿（自傷輕生不納入）。
- [Phase 07]: 查詢路徑維持純檢索；未命中統計只記路由關鍵字聚合計數。
- [Phase 02]: 本機 llama-server (Qwen3.8-27B) 維持使用，採 Prompt + 驗證器雙層防禦過濾政治立場內容。
- [v1.2 路線圖]: DEBT-01/02 先行（獨立低風險）；CF 動檢索順序獨立成 Phase 11 並須完整回歸；GC-01~04 與 DEBT-03 併 Phase 12（共用 review_faq）；DEBT-04 真實 LLM 實跑置最後，待新驗證層就緒。

### Pending Todos

- 執行 Phase 10（/gsd-execute-phase 10）
- 之後可考慮：2~3 字滑動窗改善檢索、應用層速率限制、AUTH-03/04（見 REQUIREMENTS.md Future）

### Blockers/Concerns

- `src/query/router.py` 的 `extract_search_terms()` 仍非完整中文斷詞：2 字通用詞已由 `_GENERIC_TERMS` 降權（2026-09-30），但「動詞+名詞」黏連殘渣片段（如「音波拉提維持」「甲溝炎要」）尚未過濾，僅浪費一次查詢，不影響結果正確性。
- Phase 11 擴大 FAQ 候選集會碰到 Phase 7 的 faq_shortcut 保守門檻，需對抗性回歸測試。
- Phase 13 需 `llama-server` 空閒，且只能在資料庫複本上進行。

## Session Continuity

Last session: 2026-10-02
Stopped at: Phase 10 規劃完成（3 份計畫，2 個 wave）；準備執行 Phase 10
Resume file: 無
