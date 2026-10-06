# Plan 13-01 執行成果總結 (Summary)

## 任務執行概述
- **目標**：在本地 `llama-server` 運行環境下，對資料庫獨立複本執行夜間批次真實 LLM 推論實跑（涵蓋 FAQ 生成、臨床推理樹重建與日誌隱私白名單審核），解決技術債 DEBT-04。
- **成果**：建立 `tests/test_real_llm_batch.py`，完成全部 3 項真機端到端實跑驗證；全數通過（3 passed），正式資料庫 `clinic.db` SHA-256 恆定零接觸。

---

## 關鍵技術成果與產出

### 1. 真機測試管線 (`tests/test_real_llm_batch.py`)
- **健康檢查動態略過機制**：模組層級探測 `check_llm_health()`，若本地 `llama-server` 離線或逾時則以 `pytest.mark.skipif` 優雅略過，不影響離線 CI 環境。
- **正式庫雙重防禦 fixture**：每次測試執行前後即時量測 `clinic.db` SHA-256，斷言與基準值 `ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e` 嚴格一致。
- **測試 1（真實 FAQ 生成）**：
  - 以 Qwen3.8-27B 實跑感冒主題常見問答。
  - 生成之問答成功通過五層合規驗證，寫入為 `source_type='llm_generated'` 與 `review_status='pending'`。
  - 驗證可見性閘門：在未經醫師人工核准前，`consult_general` 回傳 `no_match`，自然語言查詢亦不得走快取短路。
- **測試 2（真實臨床推理樹重建）**：
  - 在複本上將 `hifu-lifting` 標記為 `needs_regeneration=1`，手寫植入專屬醫師註記。
  - 執行 `run_batch` 重建：在 `tree_snapshots/` 產生前像 JSON 備份。
  - 重建成功後 `needs_regeneration` 重置為 0，`content_version` 遞增，臨床段落由模型產出有效內容。
  - 醫師權威指令防線：重建後 `pre_op_physician_notes` 完整保留，未被覆蓋。
- **測試 3（日誌隱私白名單審核）**：
  - 逐行解析生成的 `nightly-*.log` 結構化日誌。
  - 嚴格校驗所有 JSON 鍵名絕不含敏感詞彙（`query`, `question`, `answer`, `prompt`, `raw`, `text`, `content`），保證零隱私外洩。

### 2. 本地 LLM 適配器與提示詞優化
- **`src/pageindex/llm_client.py`**：
  - 調整 `local_llm_call` 預設超時為 360 秒，`max_tokens` 提升至 6144，加入 `reasoning_effort: "low"`，適配 27B 大模型在複雜醫療任務下的長鏈思考與完整輸出。
  - 補強錯誤例外資訊，包含 `finish_reason`、`rc_len` 與 `usage`。
- **`src/batch/faq_generator.py`**：
  - 整合 `to_traditional()`，模型生成文本於驗證前自動套用 OpenCC `s2twp` 正規化，防範繁簡混合誤判。
  - 在提示詞中提供具體就醫警訊收尾示範，引導模型天然生成合規衛教建議。
- **`src/pageindex/prompt_template.py`**：
  - `generate_tree` 加入 `to_traditional()` 正規化。
  - `_FEW_SHOT_DOC_IDS` 精簡為單一代表性範例，並於提示詞中約束各段字數與精簡思考，推論效率由 5+ 分鐘縮減至約 130-150 秒完成。

---

## 驗證結果
- `python3 -m pytest tests/test_real_llm_batch.py -v -s`：3 passed in 200.12s。
- `sha256sum -c .planning/phases/13-real-llm-batch-verification/prod.sha256`：`clinic.db: 成功`。
