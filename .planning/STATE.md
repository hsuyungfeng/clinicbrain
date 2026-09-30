# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-29)

**Core value:** 在符合台灣醫療法規（絕對價格遮蔽、全繁體中文、無保證療效）的前提下，提供診所高精準度、低延遲、隱私優先（純本地推理）的臨床衛教與藥品檢索。
**Current focus:** Phase 5: doctor-toolbox.com 官方 API 整合與 HTTP 服務層架構規劃

## Current Position

Phase: 5 of 5 (doctor-toolbox.com API Integration)
Plan: TASK-04 完成（本機服務啟動腳本 scripts/run_api_server.py、systemd user service 範本 clinicbrain-api.service、全系統端到端測試驗證），Phase 05 圓滿完工！
Status: Phase 5 Complete (TASK-04 Done, 4/4)
Last activity: 2026-09-29 — Phase 05 完工：FastAPI 服務層、handle_query 路由封裝、二次價格遮蔽、雙向同步 RESTful 契約、CLI 啟動腳本與 systemd user service，158 個測試全數通過

Progress: [██████████] 100% (Phase 01~05 全部完工)

## Performance Metrics

**Velocity:**
- Total tasks completed: 24+
- Tests passing: 158/158 (100%)
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

- `src/query/router.py` 的 `extract_search_terms()` 仍非完整中文斷詞：2 字通用詞已由 `_GENERIC_TERMS` 降權（2026-09-30），但「動詞+名詞」黏連殘渣片段（如「音波拉提維持」「甲溝炎要」）尚未過濾，僅浪費一次查詢，不影響結果正確性。

## Session Continuity

Last session: 2026-09-30 (Resumed，已清除過期 HANDOFF.json 與 .continue-here.md)
Stopped at: Phase 05 完工，準備依序執行：部署 API 服務、改善中文斷詞、開下一個里程碑
Resume file: 無（交接檔已清除）
