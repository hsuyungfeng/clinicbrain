# Phase 13: 真實 LLM 批次實跑驗證 (DEBT-04) 研析與技術合約

## 執行背景與目標

在 Phase 09（夜間批次與審核閘門架構）與 Phase 12（一般疾病內容生成與多層合規防禦）中，夜間批次管線（`src/batch/runner.py`）與 FAQ 生成引擎（`src/batch/faq_generator.py`）的所有單元測試與端對端驗收測試，皆是透過 Mock LLM 進行。
**DEBT-04** 的核心目標是：
在 `llama-server` 處於正常運行的真實環境下，對資料庫獨立複本執行真實夜間批次實跑，檢驗本機 27B 大模型在真實提示詞下的輸出品質、五層醫療安全驗證（DX-1~5、就醫警訊、價格、簡體字、保證療效）的攔截與通過情況、推論耗時與資源開銷，並保證正式資料庫零接觸。

---

## 現行環境與組件調研

1. **本地推論服務狀態**：
   - 服務端點：`http://127.0.0.1:8080`（`llama-server`）
   - 當前載入模型：`/home/hsu/llama.cpp/models/Qwen3.8-27B-UD-Q4_K_XL.gguf`
   - 連線適配器：`src/pageindex/llm_client.py:check_llm_health()` 與 `local_llm_call()`
   - 實測推論健康度：正常存活

2. **批次執行器配置 (`BatchConfig`)**：
   - 入口腳本：`scripts/run_nightly_batch.py` 或程式化呼叫 `src/batch/runner.py:run_batch`
   - 目標資料庫：必須指向暫存複本（例如 `/tmp/clinic_real_test.db`），絕不傳入正式 `clinic.db`
   - 控制規模：設定 `--max-faq-topics 1`（或 2），避免長時間佔用推論資源；單一主題推論時間約 20~40 秒
   - 樹重建：在複本上將指定臨床推理樹（例如 `hifu-lifting`）標記為 `needs_regeneration=1`，設定 `--max-trees 1`，驗證真機樹重建、前像快照備份與 `*_physician_notes` 醫師註記保護

3. **安全防護與隱私審計**：
   - 正式庫保護：執行前後即時比對 `clinic.db` SHA-256（基準：`ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e`）
   - 審核閘門檢驗：真實模型產出之問答一律寫入為 `pending`，在未獲醫師核准前，一般諮詢與自然語言短路查詢皆不可見
   - 日誌隱私：檢查產出的 JSONL 日誌，確認未記錄未經白名單過濾之病患問句原型或提示詞本文

---

## 計畫分解 (Plans Decomposition)

Phase 13 拆解為 2 份計畫：

1. **Plan 13-01 (自動化真機實跑測試與防禦管線)**：
   - 實作 `tests/test_real_llm_batch.py`：具備 `check_llm_health()` 條件略過機制（若推論服務離線則 `@pytest.mark.skipif`，不破壞離線測試）。
   - 在測試複本上執行真實 `run_batch`（涵蓋 1 個 general 主題 FAQ 生成與 1 棵樹重建）。
   - 驗證真實產出符合 JSON 結構、通過/拒絕邏輯正常運行、正式庫 SHA-256 全程未變。

2. **Plan 13-02 (實跑品質審計、報告書產出與 Milestone v1.2 結案)**：
   - 執行實跑測試並收集推論品質數據（包括各題回答內容、各層驗證結果、耗時毫秒數、顯存與資源狀況）。
   - 產出 `13-REPORT.md` 實跑分析報告書。
   - 更新 `AGENTS.md`、`docs/nightly-batch.md`，完成 Phase 13 與 Milestone v1.2 之整體收尾。
