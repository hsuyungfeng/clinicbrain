---
phase: 09-nightly-batch
status: passed
verified: 2026-10-02
verifier: Claude（與執行者 antigravity 分離的獨立驗證）
requirements: [BATCH-01, BATCH-02, BATCH-03, BATCH-04]
---

# Phase 9 驗證報告：夜間批次生成與維護

## 成功標準對照

| # | 標準 | 結果 | 證據 |
|---|---|---|---|
| 1 | 讀取未命中統計 + 手動清單產生主題，不用簡體 SFT | ✅ | `faq_seeds.json` 4 主題／11 題（使用者核准）；dry-run 計畫輸出含 `reason: manual` 的 common-cold-home-care；`topic_selection_info` 顯示 stats 可用狀態 |
| 2 | 預生成 FAQ 經四層驗證後以 llm_generated 寫入；失敗不入庫 | ✅（以測試與複本驗證） | 假 LLM 注入的 `tests/test_batch_faq_generator.py`；複本實測：llm_generated 寫入後 `review_status='pending'` |
| 3 | needs_regeneration=1 的樹重建且 physician_notes 不變 | ✅（以測試驗證） | `tests/test_batch_tree_rebuild.py`（含證明 `upsert_trees` 陷阱的對照組、還原機制）；**未對真實 LLM 與正式庫實跑** |
| 4 | --dry-run 不寫庫；LLM 不可用優雅跳過 | ✅ | 複本實跑：dry-run 結束碼 0 且不寫庫；非 dry-run 在 LLM 逾時時狀態 `llm_unavailable`、結束碼 0、不崩潰 |
| 5 | systemd timer 範本、每次留日誌 | ✅（範本層） | `clinicbrain-nightly.service/.timer` 只在 repo 根目錄；非註解行 0 個 `systemctl`；未安裝到 `~/.config/systemd`；**未實際啟用排程** |

## 審核閘門實測（核心安全機制，用正式庫複本）
- 遷移冪等；正式庫不帶旗標拒絕（結束碼 2，雜湊不變）。
- pending 草稿查不到 → 核准後查得到（`content_version` 1→2）→ 駁回後又查不到；重複駁回為 `no_change`。
- 既有 40 筆 clinic_upload FAQ 仍可查；短路 24/40 零回歸。
- 同步匯出不含 pending 草稿。

## 正式庫遷移（使用者手動執行，2026-10-02）
- `review_status`／`reviewed_at` 新增成功，40 筆全為 approved；integrity ok；FTS 觸發器與完整性檢查通過。
- 備份與正式庫在 FAQ／樹／藥品／服務項目／診所資訊／營業時間六組內容雜湊完全一致（`.backup` 與原檔位元組不同屬正常）。

## 驗證中發現的問題
- 執行者（antigravity）回報「正式庫雜湊全程不變」引用的是遷移前舊雜湊，不能作為證據；已改以當下實測值驗證。
- 全量測試 578 passed（獨立重跑）。

## 已知缺口（技術債）
- 樹重建不走審核閘門：被標記的手寫樹會被 LLM 內容取代（保護：前像快照、physician_notes 還原、`tree_overwrote_handwritten` 警告）。
- `local_llm_call` 逾時被視為 LLM 不可用；llama-server 單 slot 被其他工具佔用時批次會提前結束（結束碼 0）。
- `/sync/import` 以 clinic_upload 寫入，與既有 pending/rejected 的 llm 列同鍵且內容不同時會覆寫並變 approved。
- 未實際用真實 LLM 在複本上完整跑過一次批次生成；夜間排程尚未啟用（依使用者決策）。
