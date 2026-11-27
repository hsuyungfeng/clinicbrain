# 57-R 規格：夜間動畫草擬階段（重新設計，非還原）

**背景**：原 `runner.py` 與 `autodraft.py` 的未提交修改已無法完整還原（見 `~/clinicbrain-discarded-20261127/README.txt`）。
本規格是新的設計，須重新實作並獨立審閱，不得視為還原。

## 範圍

1. `src/visual/autodraft.py`
   - 新增 `find_trees_missing_visual_assets(conn, clinic_id, limit) -> list[dict]`
     - 回傳沒有對應 `visual_assets` 列的 `page_index_trees` 樹（以 `doc_id` 對應 `topic_key`，規則寫明於程式註解）。
     - 結果順序須確定（依 `doc_id` 排序），`limit` 為上限。
   - 新增 `autodraft_tree_to_pending(conn, tree, llm_call) -> dict`
     - 以既有的 IR 生成流程產生草稿，寫入 `visual_assets`，`review_status='pending'`、`source_type='llm_generated'`。
     - **不得**寫入 `approved`，**不得**寫入任何已發布狀態。
     - 同一 `topic_key` 已存在列時不得覆寫，直接回傳 `skipped`。
     - 回傳 `{"status": "ok"|"skipped"|"failed", "code": str}`，例外需被捕捉並轉為 `failed`。
2. `src/batch/runner.py`
   - 新增階段 `visual_autodraft`，位於 `patient_prefill` 之後。
   - 新增設定：`enable_visual_autodraft: bool = False`（預設關閉）、`max_visual_autodraft: int = 3`。
   - 階段行為：
     - 關閉時直接跳過，不產生任何摘要差異。
     - LLM 不可用時設定 `status = "llm_unavailable"`，停止該階段，回傳 `True`（與既有階段語意一致）。
     - 單筆失敗只計入 `visual_autodraft_failed`，不中斷批次。
   - `BatchSummary` 新增：`visual_autodraft_planned`、`visual_autodraft_generated`、`visual_autodraft_failed`，預設 0。
3. `scripts/run_nightly_batch.py`
   - 新增旗標 `--enable-visual-autodraft` 與 `--max-visual-autodraft`，並傳入 `BatchConfig`。
   - 不改動其他既有旗標的預設值。

## 不做的事

- 不改動 `nhi200`／`nhi400` 批次與 `--blueprint-mode` 行為。
- 不改動 `fixed` 模式的任何輸出。
- 不核准任何草稿，不改動既有 `visual_assets` 列。

## 測試（`tests/test_visual_autodraft_nightly.py`）

- `find_trees_missing_visual_assets`：有無對應列、`limit`、排序穩定。
- `autodraft_tree_to_pending`：成功時狀態為 `pending`；既有列時回傳 `skipped` 且不覆寫；LLM 例外時回傳 `failed`。
- runner：預設關閉時不呼叫任何 LLM；啟用且 LLM 不可用時回傳 `llm_unavailable`；單筆失敗不中斷。
- 所有測試使用臨時資料庫（複製 schema，不使用 `clinic.db`）與假 LLM，不得有網路呼叫。
- 既有測試不得退化：`test_nightly_general_batch.py` 的結果需與改動前相同（已知的 `test_general_only_batch` 失敗除外）。

## 驗收條件

1. 新增測試全部通過。
2. `clinic.db` 的 sha256 在執行前後相同。
3. `visual_assets` 中不產生任何 `approved` 列（測試驗證）。
4. `fixed` 模式快照測試（`tests/test_nhi_fixed_snapshot.py`）通過。
5. 未執行 `git commit` / `git push`。
6. SUMMARY 需列出：與原版的差異、預設值、以及哪些行為是本次新設計而非還原。

## 回報

依 AGENTS.md §4.4：寫入 `57-R-AUTODRAFT-SUMMARY.md`，並執行
`/home/hsuyungfeng/DevSoft/infra/herdr/report-to-claude.sh "[herdr-report from=agy] phase57-R <DONE|FAIL|BLOCKED>｜<SUMMARY 路徑>｜阻斷：<無或簡述>" wB:p1`。
