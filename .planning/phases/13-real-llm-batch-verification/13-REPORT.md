# Phase 13 真機本地 LLM 夜間批次實跑品質與安全審計報告書 (13-REPORT.md)

## 一、 測試執行背景與目的

在 Phase 09（夜間批次與審核閘門）與 Phase 12（一般疾病內容生成與多層合規防禦）開發過程中，所有批次管線與生成單元測試均採用 Mock LLM 進行。
**DEBT-04** 的核心目標是在本地真實 `llama-server`（Qwen 27B）推論服務環境下，對資料庫獨立複本執行端到端實跑，全面檢驗大模型在真實臨床提示詞下的生成耗時、五層醫療安全驗證表現、醫師註記保護機制與日誌隱私合規性，並嚴格確保正式資料庫零接觸。

---

## 二、 運行環境與硬體配置

- **作業系統**：Linux x86_64
- **推論伺服器**：`llama.cpp/llama-server` (b1279-fdb2c11c) 運行於 `http://127.0.0.1:8080`
- **載入模型**：`Qwen3.8-27B-UD-Q4_K_XL.gguf`
  - 運算核心：CUDA0（NVIDIA GeForce RTX 2080 Ti 22GB 顯存）
  - 模型參數規模：27B 參數，Q4_K_XL 量化，占用顯存約 18,982 MiB
  - 上下文長度：`-c 65536 -ctk q8_0 -ctv q8_0 -n 8192 -fa on -np 1`
- **適配器與介面**：
  - 模組：`src/pageindex/llm_client.py`
  - 健康檢查：`check_llm_health()`
  - 推論呼叫：`local_llm_call(prompt: str, timeout: int = 360) -> str`
  - 推論參數：`temperature: 0.2`、`max_tokens: 6144`、`reasoning_effort: "low"`

---

## 三、 真機實跑測試結果總覽

測試檔案：[`tests/test_real_llm_batch.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_real_llm_batch.py)
全套 3 項端到端真機實跑測試全數通過（3 passed in 200.12s）。

| 測試案例 | 驗證項目 | 推論耗時 | 執行結果 | 安全守衛斷言 |
|:---|:---|:---:|:---:|:---|
| `test_real_llm_faq_generation` | 單一主題 FAQ 真機生成與五層合規檢核 | ~32 秒 | **PASSED** | 寫入為 `pending`，對外完全隱蔽 |
| `test_real_llm_tree_rebuild` | 臨床推理樹（音波拉提）真機重建 | ~140 秒 | **PASSED** | 快照已建立，醫師手寫註記 100% 保留 |
| `test_real_llm_log_privacy` | 結構化批次日誌隱私白名單審計 | ~30 秒 | **PASSED** | 所有 JSON 鍵名與內容零敏感洩漏 |

---

## 四、 關鍵合規與防禦層評估

### 1. 五層醫療安全驗證防禦
在真實提示詞下，Qwen 27B 生成之一般疾病衛教問答經由 `parse_and_validate_faq` 逐項檢核：
- **層 1（價格洩漏防禦）**：未檢出任何金額數字；若涉及費用一律依提示詞規範改寫為「請致電診所確認」。
- **層 2（繁簡中文鐵則）**：透過 `to_traditional()` 套用 OpenCC `s2twp` 正規化，完全符合台灣醫療用語（如「體溫」、「持續」），無簡體殘留。
- **層 3（政治立場防禦）**：立場中立，無任何爭議敏感字樣。
- **層 4（保證療效禁詞）**：使用「通常具有自限性」、「依個人膚況與目標」等客觀醫學語彙，無「保證有效」、「一定能消除」等禁詞。
- **層 5（用藥劑量與處方攔截）**：嚴格遵守「用藥請由醫師或藥師評估」之規範，零特定藥名與劑量數字。
- **就醫警訊收尾（DX-06）**：答案結尾正確包含就醫警訊（「若出現胸悶、呼吸困難或體溫超過38.5度且持續3天，請儘速就醫。」）。

### 2. 審核閘門防線（Fail-Closed）
- 批次生成的 FAQ 項目在 `faq_cache` 中以 `source_type='llm_generated'` 與 `review_status='pending'` 存儲。
- 呼叫 `consult_general()` 查詢該題時，系統誠實回傳 `status='no_match'`。
- 呼叫 `handle_query()` 進行自然語言統一查詢時，回應來源為非快取（`source != 'cache'`），杜絕未審內容流入公眾查詢。

### 3. 臨床推理樹重建與醫師註記保護
- 重建標記前植入之客製醫師手寫註記 `【真機測試專用醫師指引：術前務必確認皮膚厚度與神經走向】`。
- 重建執行期間，系統在 `tree_snapshots/` 自動備份前像 JSON 檔案（記錄 `old` 與 `new`）。
- 重建完成後，資料庫列之 `needs_regeneration` 重置為 0，`content_version` 遞增，臨床段落由 Qwen 27B 重新生成有效內容；而醫師手寫註記**完全吻合、零覆蓋**。

### 4. 日誌隱私白名單審核
- 對 `nightly-*.log` 的所有 JSON 行進行鍵名遞迴審計：
  - 白名單檢驗：包含 `batch_start`, `topic_selection_info`, `faq_plan`, `faq_topic_done`, `tree_plan`, `tree_rebuilt`, `batch_summary` 等結構化營運事件。
  - 黑名單攔截：嚴禁出現 `query`, `question`, `answer`, `prompt`, `raw`, `text`, `content` 等鍵名，日誌無病患個資或提示詞原文。

---

## 五、 正式資料庫完整性驗證

- 基準 SHA-256：`ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e`
- 實跑測試前後 SHA-256 量測結果：
  ```bash
  $ sha256sum clinic.db
  ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e  clinic.db
  $ sha256sum -c .planning/phases/13-real-llm-batch-verification/prod.sha256
  clinic.db: 成功
  ```
- 證明全套實跑完全在獨立測試複本隔離環境內執行，正式資料庫零接觸、零污染。

---

## 六、 結論與建議

DEBT-04 驗收圓滿達成。本系統在真機 27B 大模型推論下具備高度穩定性與合規防禦能力。
後續在進入臨床語音與 SOAP 病歷擷取管線（Phase 14）時，可直接複用此套嚴謹之多層合規防禦與審核閘門架構。
