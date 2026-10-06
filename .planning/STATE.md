---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: 診所資料優先與一般疾病簡易資訊
status: completed_phase
stopped_at: Phase 12 已完成並經複審補強（5714714、c32abdc）；Phase 13 已規劃（2 份計畫），由 antigravity 執行中，待檢查
last_updated: "2026-10-06T12:00:00.000Z"
last_activity: 2026-10-06 -- Phase 12 複審補強完成（劑量/警訊層漏洞修正、DEBT-03 可觀測性），890 passed
progress:
  total_phases: 4
  completed_phases: 3
  total_plans: 13
  completed_plans: 13
  percent: 75
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-02)

**Core value:** 在符合台灣醫療法規（絕對價格遮蔽、全繁體中文、無保證療效）的前提下，提供診所高精準度、低延遲、隱私優先（純本地推理）的臨床衛教與藥品檢索。
**Current focus:** v1.2 診所資料優先與一般疾病簡易資訊（Phase 10–13）；Phase 12 完成（含複審補強），Phase 13 規劃完成、執行中

## Current Position

Phase: 13 of 13（真實模型夜間批次預生成實跑與驗證）
Plan: 13-01、13-02 已規劃（無 SUMMARY），antigravity 執行中
Status: Executing Phase 13（待 antigravity 完成後由 Claude 檢查並修正）
Last activity: 2026-10-06 -- Phase 12 複審補強完成（890 passed，排除慢速真實 LLM 測試）

Progress: [███████░░░] 75%

## Performance Metrics

**Velocity:**

- Total tasks completed: 37+
- Tests passing: 890/890（排除 tests/test_real_llm_batch.py；該檔 3 項失敗待 Phase 13 檢查）
- SQLite records: 7,573 drugs, 2,669 services, 6 PageIndex trees, 40 FAQs

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Phase 12 複審補強 2026-10-06]: 劑量層 DX-2 涵蓋只有數量的句子、否定詞須緊鄰動詞才豁免、詞庫補劑型與英文學名；警訊層排除勸人別就醫的反向句並支援條列式；DEBT-03 補 `mark-regen --seed`（種子外題目拒絕標記）、`list` 顯示「待重生」、批次日誌記 unchanged/failed 列 id。詞庫仍為封閉式，最終靠醫師審核。
- [Phase 12]: GC-01 疾病種子 17 題簽核入庫；GC-02 獨立實作 DX-1~5 劑量與處方攔截器（正例 47/47 攔截，負例 50/50 放行，診所 FAQ 回掃 0 誤拒）；GC-03 就醫警訊強制檢驗（正例 15/15 通過，負例 17/17 攔截）+ disclaimer 查詢回應欄位純加法擴充 + /sync/import general 前置檢驗；GC-04 審核工具增強（list --topic、show 來源與相近診所 FAQ 檢視、approve 警訊強制、faq_coverage 共用純函式）；DEBT-03 駁回題目手動標記重生成（mark-regen 子命令、一次標記一次嘗試、相同答案清除旗標）。
- [Phase 11]: 診所資料優先檢索（Tiered 兩階段判定），帶 clinic_id 優先查 special FAQ，短路率 24/40 -> 38/40；相近阻斷下限 CLINIC_RELATED_FLOOR = 0.4；回應結構新增 data_level 標示層級；無 clinic_id 查詢排除所有診所 FAQ。
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

- 使用者待辦：請醫師合併正式庫 id 4 與 id 19 重複問句（或區分情境），合併後短路率可由 38/40 達 40/40。
- 等 antigravity 完成 Phase 13，再檢查實作、查 `tests/test_real_llm_batch.py` 的 3 項失敗並修正
- 待確認（W4）：special 類答案是否也要求就醫警訊、sync 匯出與非 FAQ 回應是否附免責（目前僅 general 要求）
- 之後可考慮：2~3 字滑動窗改善檢索、應用層速率限制、AUTH-03/04（見 REQUIREMENTS.md Future）

### Blockers/Concerns

- `src/query/router.py` 的 `extract_search_terms()` 仍非完整中文斷詞：2 字通用詞已由 `_GENERIC_TERMS` 降權（2026-09-30），但「動詞+名詞」黏連殘渣片段（如「音波拉提維持」「甲溝炎要」）尚未過濾，僅浪費一次查詢，不影響結果正確性。
- Phase 11 擴大 FAQ 候選集會碰到 Phase 7 的 faq_shortcut 保守門檻，需對抗性回歸測試。
- Phase 13 需 `llama-server` 空閒，且只能在資料庫複本上進行。

## Session Continuity

Last session: 2026-10-06
Stopped at: Phase 12 補強已 commit；等待 antigravity 完成 Phase 13
Resume file: 無
