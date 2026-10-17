# Phase 28 Plan 07: 本地 LLM 思考關閉與解碼速率實機探測紀錄

## 1. 探測基本資訊

- **探測日期**：2026-10-17 14:38:52 (UTC+8) / 2026-10-17T06:38:52Z
- **伺服器端點**：`http://127.0.0.1:8080/v1/chat/completions`
- **載入模型**：`/home/hsu/llama.cpp/models/Qwen3.8-27B-UD-Q4_K_XL.gguf`
- **測試提示詞來源**：`/tmp/probe-clinic-copy.db`（資料庫副本，唯讀模式 `mode=ro` 開啟）
- **核准狀態**：使用者明確核准實機探測（`--i-approve-live-probe`，`--db-copy` 隔離副本）

---

## 2. 三變體實測結果數據

| 變體代碼 (Variant) | 思考控制參數配置 | reasoning_chars | content_chars | finish_reason | 耗時 (秒) | completion_tokens | tokens/秒 (Decode) | 思考是否關閉 |
|---|---|---|---|---|---|---|---|---|
| **變體 1** (`reasoning_effort_none`) | `{"reasoning_effort": "none"}` | 938 | 117 | `stop` | 33.736 | 716 | 22.17 | ❌ 否（無效） |
| **變體 2** (`enable_thinking_false`) | `{"chat_template_kwargs": {"enable_thinking": false}}` | 0 | 118 | `stop` | 4.628 | 78 | 22.52 | ✅ 是（完全關閉） |
| **變體 3** (`both`) | 兩者並用 | 0 | 118 | `stop` | 3.586 | 78 | 22.54 | ✅ 是（生效） |

---

## 3. 探測判準與分析結論

1. **思考關閉控制有效性判準**：
   - 計畫判準：`reasoning_content` 字元數對應小於 100 tokens 且總耗時小於 60 秒為有效。
   - 變體 1（`reasoning_effort: "none"`）：產出 938 字元思考推演，耗費 638+ 思考 tokens，總耗時高達 33.7 秒。證實 **`reasoning_effort` 參數對本機 llama-server 之 Qwen3.8 GGUF 完全無效**。
   - 變體 2（`chat_template_kwargs.enable_thinking = False`）：`reasoning_content` 完全為 0（0 字元、0 token），總耗時僅 4.628 秒，成功直出衛教回覆。證實 **`chat_template_kwargs: {"enable_thinking": false}` 能 100% 關閉本機思考**。
   - 變體 3（兩者並用）：效果與變體 2 相同，`reasoning_effort` 為冗餘參數。

2. **實際解碼速率 (Decode Speed)**：
   - 實測解碼速度為 **22.17 ～ 22.54 tok/s**（平均約 **22.5 tok/s**）。
   - 與先前研究推論（約 21～22 tok/s）完全一致。
   - 舊版文件中提及之「Speed: ~90 tok/s decode」經實測確定並非生成解碼速度（90 tok/s 實為 Prompt 處理速度 prompt_per_second），真實生成輸出解碼速率為約 22.5 tok/s。

3. **取樣常數收緊依據 (Task 3)**：
   - 觀察到關閉思考後的實際生成 tokens 數：`completion_tokens = 78`。
   - 依據 28-07-PLAN.md Task 3 規格：「max_tokens 設為觀察到的最大 completion_tokens 的 1.5 倍，上下限 600～3000」：
     $$78 \times 1.5 = 117 \text{ tokens} \implies \text{低於下限 600，初版暫採下限 } 600 \text{ tokens}$$
   - **調整方案**：
     - 移除無效之 `"reasoning_effort": "none"` 參數。
     - 保留並確認有效之 `"chat_template_kwargs": {"enable_thinking": False}`。

4. **複審調整（Claude 最後審查修正）**：
   - **單一 78 token 樣本不具代表性**：探測時所用的單一衛教問答較簡短（約 118 字元），而病人端組稿（價值回答 2～4 句＋追問＋警訊句）與 2.24 一般醫學說明（JSON 格式內答案字數依規則允許達 100～600 字）在真實情境下的生成長度遠大於 78 tokens。若硬性收緊至 600 tokens，合規的長回答極易觸發 `finish_reason: "length"`（拋出 `LLMTruncatedError`），導致原本能正常運作的路徑意外降級為 `no_match`。
   - **調整後之 max_tokens 設定**：
     - `PATIENT_COMPOSE_SAMPLING["max_tokens"] = 800`：給予即時組稿充足之安全邊界。於 22.5 tok/s 下，最壞情況延遲約 **35.5 秒**（800 / 22.5），仍遠低於端點 240 秒逾時上限。
     - `PATIENT_GENERAL_SAMPLING["max_tokens"] = 1500`：容納完整 JSON 格式與長篇未審衛教說明。於 22.5 tok/s 下，最壞情況延遲約 **66.7 秒**（1500 / 22.5），亦遠在 240 秒逾時內。
   - **後續收緊規劃**：若日後夜間批次或真實使用累積更多組稿題目的 `completion_tokens` 分布數據，且確認長篇回答上限未達此閾值，可再視實測分布進一步收緊。
