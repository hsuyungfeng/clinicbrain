# 57-R 執行總結：夜間動畫草擬階段重新設計與實作

**執行狀態**：`DONE`  
**依據規格**：`/home/hsuyungfeng/DevSoft/clinicbrain/.planning/phases/57-visual-blueprint-classification-narration-ab/57-R-AUTODRAFT-SPEC.md`  
**實作原則**：全新重新設計與獨立實作（非還原）  
**目標分支**：`main`（未 commit、未 push）  

---

## 1. 驗收條件核對表

| 項次 | 驗收條件 | 結果 | 驗證證據 |
| :--- | :--- | :---: | :--- |
| 1 | 新增測試全部通過 | **PASS** | `tests/test_visual_autodraft_nightly.py` 8 項測試 100% 通過 (0.91s) |
| 2 | `clinic.db` sha256 前後一致 | **PASS** | 執行前：`aa27566b...4043ee`，執行後：`aa27566b...4043ee`（完全一致） |
| 3 | `visual_assets` 不產生任何 approved 列 | **PASS** | 程式強制寫入 `pending`，資料庫寫入後斷言檢驗，測試斷言全庫 approved 為 0 |
| 4 | `fixed` 模式快照測試通過 | **PASS** | `tests/test_nhi_fixed_snapshot.py` 3 筆測試全數 PASS |
| 5 | 未執行 git commit / git push | **PASS** | `git status` 確認為 unstaged / untracked，未提交任何 commit |
| 6 | SUMMARY 詳列差異、預設值與新設計行為 | **PASS** | 詳見第 2、3 節 |

---

## 2. 本次新設計架構與原版差異（非還原說明）

原先 `runner.py` 與 `autodraft.py` 的未提交修改已無法完整還原，本次依據 `57-R-AUTODRAFT-SPEC.md` 進行全新設計與實作，主要架構差異與新特性如下：

### 2.1 `src/visual/autodraft.py`：純查詢與安全單筆生成函式
1. **新增 `find_trees_missing_visual_assets(conn, clinic_id=None, limit=None)`**：
   - **明確對應規則**：於程式註解與邏輯中確立 `page_index_trees.doc_id` 透過 `normalize_tree_topic_key(doc_id)` 與 `visual_assets.topic_key` 之一對一對應關係（去除頭尾空白、轉小寫、前綴保證為 `tree-`）。
   - **資格篩選**：僅選取通過審核且具備可見性之推理樹（複用 `fetch_eligible_trees`，排除未核准樹）。
   - **穩定排序與截斷**：嚴格以 `doc_id ASC` 升冪排序，確保夜間批次順序具確定性（Deterministic）；支援 `limit` 限制。
2. **新增 `autodraft_tree_to_pending(conn, tree, llm_call=None)`**：
   - **既有列防覆寫保護**：若目標 `topic_key` 已存在於 `visual_assets` 中，絕不覆寫既有資料，直接回傳 `{"status": "skipped", "code": "already_exists"}`。
   - **狀態與來源鎖定**：寫入 `visual_assets` 時恆為 `review_status = 'pending'` 與 `source_type = 'llm_generated'`，寫入後立即以 SQL 查詢進行斷言驗證，非 pending 立即 rollback。
   - **全面例外防禦**：內部安全捕捉所有例外（包含格式、LLM 例外、SQL 錯誤等），轉為 `{"status": "failed", "code": str}`，確保單筆失敗不使外部排程中斷崩潰。

### 2.2 `src/batch/runner.py`：標準化批次階段插槽
1. **新增 `_stage_visual_autodraft` 階段**：
   - 插入順序：置於 `_stage_patient_prefill` 之後、`_stage_video_render` 之前（標準階段列表第 11 個階段）。
   - **預設防護**：若 `not cfg.enable_visual_autodraft`（或 `soap_only`、`general_only`、`dry_run`），直接靜默跳過，不呼叫任何 LLM，不改變摘要。
   - **LLM 不可用語意一致性**：若捕獲 `LocalLLMUnavailableError` 或函式回傳 `code == "llm_unavailable"`，設定 `summary.status = "llm_unavailable"`，累計 failed 並中斷該階段，回傳 `True`（與既有 FAQ/Tree 階段語意一致）。
   - **單筆失敗隔離**：個別樹解析或生成失敗只累計 `summary.visual_autodraft_failed += 1`，批次正常繼續下一筆。
2. **組態與摘要結構擴充**：
   - `BatchConfig` 新增：`enable_visual_autodraft: bool = False`, `max_visual_autodraft: int = 3`。
   - `BatchSummary` 新增：`visual_autodraft_planned: int = 0`, `visual_autodraft_generated: int = 0`, `visual_autodraft_failed: int = 0`。

### 2.3 `scripts/run_nightly_batch.py`：CLI 參數與摘要輸出
- 新增命令列旗標：`--enable-visual-autodraft`（action="store_true", default=False）、`--max-visual-autodraft`（正整數, default=3）。
- 完整傳入 `BatchConfig`，維持所有既有旗標之預設值不變。
- 終端機執行摘要中增加視覺草稿規劃、草擬與失敗統計顯示。

---

## 3. 預設值清單

| 參數 / 屬性 | 位置 | 預設值 | 說明 |
| :--- | :--- | :--- | :--- |
| `enable_visual_autodraft` | `BatchConfig` / CLI | `False` | 預設關閉，確保不影響既有夜間排程行為 |
| `max_visual_autodraft` | `BatchConfig` / CLI | `3` | 單次夜間批次草擬之最大視覺資產數量上限 |
| `review_status` | `visual_assets` 寫入 | `'pending'` | 恆為待審核，嚴禁核准 |
| `source_type` | `visual_assets` 寫入 | `'llm_generated'` | 明確標註來源為本機模型生成 |
| `visual_autodraft_planned` | `BatchSummary` | `0` | 規劃筆數 |
| `visual_autodraft_generated` | `BatchSummary` | `0` | 成功生成草稿筆數 |
| `visual_autodraft_failed` | `BatchSummary` | `0` | 失敗筆數 |

---

## 4. 測試執行與品質保證

### 4.1 新增單元與整合測試 (`tests/test_visual_autodraft_nightly.py`)
- `test_find_trees_missing_visual_assets`: 驗證缺失樹篩選、排除已存在資產與未核准樹、依 `doc_id` 升冪排序、`limit` 截斷（PASS）。
- `test_autodraft_tree_to_pending_success_and_never_approved`: 驗證草稿產生入庫為 `pending`、`llm_generated`，全庫無 `approved`（PASS）。
- `test_autodraft_tree_to_pending_skipped_if_exists`: 驗證同一 `topic_key` 存在時回傳 `skipped` (code=`already_exists`) 且不覆寫（PASS）。
- `test_autodraft_tree_to_pending_llm_exceptions`: 驗證一般例外與 `LocalLLMUnavailableError` 安全捕捉轉為 `failed`（PASS）。
- `test_runner_visual_autodraft_disabled_by_default`: 驗證預設關閉時 0 呼叫 LLM、摘要全為 0（PASS）。
- `test_runner_visual_autodraft_enabled_flow`: 驗證啟用時正常草擬且受 `max_visual_autodraft` 限制，全為 pending（PASS）。
- `test_runner_visual_autodraft_llm_unavailable`: 驗證 LLM 不可用時設定 `summary.status = "llm_unavailable"` 並提前結束（PASS）。
- `test_runner_visual_autodraft_single_failure_does_not_halt_batch`: 驗證單一樹失敗累計 failed，批次繼續並成功完成其餘樹（PASS）。

### 4.2 既有全套回歸測試驗證
```
tests/test_visual_autodraft_nightly.py ........                          [ 29%]
tests/test_nhi_fixed_snapshot.py ...                                     [ 40%]
tests/test_blueprint_registry.py .......                                 [ 66%]
tests/test_blueprint_classifier.py .........                             [100%]
============================== 27 passed in 1.87s ==============================
```
- `tests/test_nightly_general_batch.py`: 6 passed, 1 failed（已知既有的 `test_general_only_batch` 種子路徑斷言失敗，與修改前完全相同，無退化）。
- `clinic.db` sha256 再次比對確認：`aa27566b0f9f1887375094350241b315e54acc52d74b1f92b6878fd0c54043ee`（零受損、零寫入）。
