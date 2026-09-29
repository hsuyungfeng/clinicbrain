# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-29)

**Core value:** 在符合台灣醫療法規（絕對價格遮蔽、全繁體中文、無保證療效）的前提下，提供診所高精準度、低延遲、隱私優先（純本地推理）的臨床衛教與藥品檢索。
**Current focus:** Phase 5: doctor-toolbox.com 官方 API 整合與 HTTP 服務層架構規劃

## Current Position

Phase: 5 of 5 (doctor-toolbox.com API Integration)
Plan: Phase 05 PLAN.md & TASK-PLAN.md 規格書已定案，待展開實作
Status: Phase 5 in progress (Specs ready)
Last activity: 2026-09-29 — Phase 05 完成 FastAPI 服務架構、handle_query HTTP 封裝與雙向同步契約 (PLAN.md, TASK-PLAN.md) 規格撰寫

Progress: [█████████░] 90% (Phase 01~04 完工，Phase 05 規格已定案)

## Performance Metrics

**Velocity:**
- Total tasks completed: 20+
- Tests passing: 128/128 (100%)
- SQLite records: 7,573 drugs, 2,669 services, 6 PageIndex trees, 40 FAQs

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Phase 04]: `clinic_id` 全面標準化為健保代碼 `'3503190424'`，查詢函式強制必填，避免跨診所資料洩漏。
- [Phase 03]: `faq_cache` 採獨立扁平表，正式庫套用完成並匯入 40 筆真實 FAQ（`source_type='clinic_upload'`）。
- [Phase 03]: 結案 Stage 2 圖片 OCR 與 `美容醫學/` 掃描教科書，判定投資報酬率極低且非衛教素材，不展開 OCR 管線。
- [Phase 02]: 本機 llama-server (Qwen3.8-27B) 維持使用，採 Prompt + 驗證器雙層防禦過濾政治立場內容。

### Pending Todos

- 展開 Phase 05: doctor-toolbox.com 官方 API 整合與 HTTP 服務層架構規劃（FastAPI 路由封裝、認證機制、雙向同步合約）

### Blockers/Concerns

- `src/query/router.py` 的 `extract_search_terms()` 使用簡單關鍵字與 CJK 長度切分，非完整中文斷詞。一般性 2 字詞（如「維持」）可能在 LIKE-fallback 中帶入雜訊，已納入回歸測試保護。

## Session Continuity

Last session: 2026-09-29 12:40 (Resumed)
Stopped at: Context restored from HANDOFF.json & Plan.md; ready for next phase selection
Resume file: .planning/HANDOFF.json
