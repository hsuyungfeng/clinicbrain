# Phase 31 Plan 02: 推理樹自動生成視覺解說卡草稿模組與 CLI 工具執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `31-02-PLAN.md` 規格，建立由已核准 PageIndex 臨床決策推理樹自動生成「原理與手術／處置過程」視覺解說卡草稿的核心模組 [`src/visual/autodraft.py`](file:///home/hsu/Desktop/clinicbrain/src/visual/autodraft.py) 與命令列工具 [`scripts/autodraft_visual_from_trees.py`](file:///home/hsu/Desktop/clinicbrain/scripts/autodraft_visual_from_trees.py)：

1. **Task 1: 推理樹動畫草稿生成器（P31-AUTODRAFT）**：
   - 實作 `normalize_tree_topic_key(doc_id: str) -> str`：小寫英數連字號正規化，固定帶 `tree-` 前綴，長度夾限於 3..64，非法格式拋出 `ValueError("schema_error")`。
   - 實作 `fetch_eligible_trees(conn, *, tree_id=None, doc_id=None, clinic_id=None) -> list[dict]`：
     * 套用 `visible_tree_sql(conn)` 條件，保證僅讀取已核准（對外可見）之推理樹；未核准（pending/rejected）或不存在時回傳空清單。
   - 實作 `build_tree_visual_prompt(tree: dict) -> str`：
     * 擷取推理樹之 `title`、`summary_text`、`pre_op`、`procedure`、`post_op_short`、`maintenance` 臨床內容。
     * 動態注入 `VISUAL_EXTRA_FORBIDDEN` 禁詞清單與 10 種 `PALETTE_TOKENS` 調色盤代號。
     * 明確規範「零阿拉伯數字」、「僅說明原理與手術過程」、「第 3 場景包含因人而異或醫師評估收尾語意」及固定 3 場景輸出規格。
   - 實作 `parse_and_build_tree_ir(raw: str, topic_key: str, fallback_title: str) -> tuple[dict | None, str]`：
     * 清理思考標籤 `<think>...</think>` 與 markdown 區塊，解析 JSON。
     * **強制執行零預設文字污染檢查**：嚴格檢驗 `source.label`、`container_layers[].label`、`step_labels`、`left.title/note/core_label/footnote`、`right.title/note/footnote`、`milestones` 等所有中文字串皆由模型明確提供，絕不退回寫死的自體脂肪預設文字。
     * 遞迴檢查全結構絕無任何阿拉伯數字（`\d`），並以 `validate_ir` 執行四層醫療合規檢驗。
   - 實作 `autodraft_from_tree(conn, tree_id_or_dict, llm_call=None, *, max_attempts=2, db_path=None, commit=True) -> dict`：
     * 驗證樹是否為已核准樹，未核准回傳 `{"status": "error", "code": "tree_not_approved"}`，不存在回 `tree_not_found`。
     * 排程互斥：檢測 `nightly_batch_running(db_path)` 與非阻塞 `GENERATION_LOCK`，忙碌回傳 `busy`。
     * 支援至多重試 2 次；成功後呼叫 `upsert_assets(..., source_type="llm_generated")`，`review_status` 恆為 `pending`，保留該樹之 `clinic_id`，永不自動核准。

2. **Task 2: CLI 批次與單筆生成工具（P31-AUTODRAFT）**：
   - 實作 [`scripts/autodraft_visual_from_trees.py`](file:///home/hsu/Desktop/clinicbrain/scripts/autodraft_visual_from_trees.py)：
     * 支援 `--db`、`--doc-id`、`--clinic-id`、`--dry-run`、`--allow-prod-db` 參數。
     * 正式庫防護：目標為正式 `clinic.db` 且非 `--dry-run` 時，未帶 `--allow-prod-db` 於連線前立即以結束碼 `2` 阻斷。
     * 支援 `--dry-run` 唯讀預覽模式（顯示目標推理樹與前 200 字提示詞預覽，不呼叫 LLM 亦不寫入）。

---

## 2. 測試與驗收結果

- **Task 1 & 2 單元測試**：
  `uv run pytest -q -p no:cacheprovider tests/test_visual_autodraft.py`
  -> **10 passed in 0.66s**。
- **31-02 完整驗收套件**：
  `uv run pytest -q -p no:cacheprovider tests/test_visual_autodraft.py tests/test_visual_ir.py tests/test_visual_blueprints.py`
  -> **47 passed in 0.69s**。
- **正式資料庫保護**：
  `sha256sum clinic.db`: `2f66cd1b42fd927bca22a847b537c4cc43fb80c6a139aafb67669caaf25daf66`（完全未變更、未遷移）。

---

## 3. 改動檔案清單

- `src/visual/autodraft.py`：推理樹視覺解說卡草稿生成模組。
- `scripts/autodraft_visual_from_trees.py`：自動生成命令列工具。
- `tests/test_visual_autodraft.py`：生成器、合規檢查、零污染與 CLI 測試套件。
- `.planning/phases/31-visual-autodraft-and-approval/31-02-SUMMARY.md`：本執行摘要。

---

## 4. 遵守規則聲明

1. 依序完成 31-02 並建立 `31-02-SUMMARY.md`。
2. 嚴格遵守規定，未執行任何 `git reset`, `git checkout`, `git stash`, `git clean`, `git restore`。
3. 嚴禁修改或遷移正式庫 `clinic.db`，所有測試皆使用 `isolated_db_path` 隔離複本，不呼叫真實 LLM。
4. 依指示**未自行執行 git commit**，保留工作區改動等待 hermes 測試與 argon 審查。
