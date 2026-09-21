# Phase 02：本地 LLM 推理層

## 現況盤點（2026-09-21 實測，非假設）

機器上**已經有一個運行中的本地 LLM 推理服務**，不需要重新部署：

- 進程：`/home/hsu/llama.cpp/build/bin/llama-server`（PID 會變動，指令本身固定）
- 模型：`Qwen3.8-27B-UD-Q4_K_XL.gguf`，27B 參數 Q4 量化，32768 context window
- GPU：跑在 RTX 2080 Ti（22GB，此服務占用 17GB），`-ngl 99` 全層 GPU 加速
- 另有一張 GTX 1060 6GB 幾乎閒置（383MB），未來若需要跑第二個較小模型可用
- API：OpenAI 相容格式，監聽 `0.0.0.0:8080`，`/v1/chat/completions` 已實測可用
- 實測生成速度：約 22.7 tokens/sec（predicted_per_second）
- 回應格式含非標準 `reasoning_content` 欄位（thinking 過程），呼叫端需要只取 `message.content`，忽略 `reasoning_content`

本機也已安裝 `ollama 0.6.1`（但未見到有服務在跑），以及 `torch`/`transformers` 等 Python ML 套件（用途未探查，超出本次盤點範圍）。

### ⚠️ 已知風險：模型立場輸出

實測「台灣的首都是哪裡？」這類政治敏感問題，模型回傳了中國官方立場內容（「台灣是中國不可分割的一部分」）。這代表底層模型存在不可控的立場假設/審查傾向。

**使用者決策**：繼續使用這個既有 Qwen 服務（不重新部署、不換模型），但透過 prompt 層強制規範來防禦，依賴 `prompt_template.py` 既有的 `parse_and_validate()` 驗證層做最後把關。

## 目標

讓 Phase 01 已經寫好但從未測試過的 `src/pageindex/prompt_template.py` 的 `generate_tree()`，能真正接上這個本地服務跑出結果，並確保：
1. 生成內容不含政治/意識形態立場表述（新增的防禦要求）
2. 仍然滿足 Phase 01 既有的全部 CONSTRAINT（繁體中文、無價格洩漏、無保證療效用語等）
3. 雲端 API 備援路徑有清楚的介面，即使暫不實作，至少介面設計上要能接

## 具體任務

### TASK-01：`llm_call` adapter 實作

在 `src/pageindex/` 新增一個模組（例如 `llm_client.py`），實作符合 `generate_tree(procedure_name, llm_call, ...)` 介面的本地 LLM 呼叫函式：

```python
def local_llm_call(prompt: str) -> str:
    """呼叫本機 llama-server（port 8080）的 /v1/chat/completions，
    回傳 message.content（忽略 reasoning_content）。"""
```

- 使用標準庫 `urllib.request` 或既有已安裝的 `requests`（若有）發送請求，不要引入新的重量級依賴
- 需要處理逾時、連線失敗（服務未啟動時應該給出清楚錯誤訊息，而非模糊的例外）
- 不要把 `http://127.0.0.1:8080` 這個位址寫死在多處，集中成一個常數/設定

### TASK-02：Prompt 層立場規範強化

修改 `src/pageindex/prompt_template.py` 的 `PROMPT_TEMPLATE`，新增一條明確規則（放在既有的「嚴格規則」清單裡，跟繁體中文、價格遮罩等規則同一層級）：

- 禁止輸出任何政治、主權、意識形態相關立場表述——僅生成醫療衛教內容，不回應/不延伸任何超出療程衛教範疇的話題
- 若生成內容意外離題（不論任何原因），應僅輸出空白或最基本的衛教資訊，不得附和任何政治性敘述

### TASK-03：輸出驗證層新增立場檢測

修改 `parse_and_validate()`，比照既有的 `_FORBIDDEN_PHRASES`（保證有效、一定能消除等）機制，新增一組政治敏感詞彙偵測（如「不可分割」「一個中國」「台灣地區」等常見官方立場用語樣本），命中即拋出 `TreeValidationError`，不寫入資料庫。這不保證 100% 攔截，但作為 CONSTRAINT 驗證層的自然延伸，符合現有架構模式。

### TASK-04：端到端驗證

用 `local_llm_call` 實際跑 `generate_tree()` 生成 2-3 筆真實療程樹（挑跟現有 6 筆手寫範本不同的療程，例如「淨膚雷射」「電音波」等），驗證：
- 輸出通過 `parse_and_validate()` 全部檢查
- 內容品質與既有手寫範本的水準相近（人工判讀，非自動化指標）
- 用 `db_writer.upsert_trees(conn, [row], source_type='llm_generated')` 正確寫入**測試用資料庫複本**（不要污染正式 `clinic.db`，比照 TASK-008 的隔離規則）

## CONSTRAINT

- 沿用 `AGENTS.md` 全部既有規則（繁體中文、價格遮罩、FTS5 trigram 等，本任務不太會觸及 FTS5 但仍要注意）
- 新增本 phase 的立場中立要求，優先級與既有 CONSTRAINT 同級
- 不要修改 `llama-server` 本身的啟動參數或模型（那是既有運行中的服務，任何調整都可能影響其他正在使用它的程序）
- 呼叫本地服務前，若服務未啟動或無回應，`local_llm_call` 應該清楚報錯，不要靜默失敗或用假資料代替

## 不在本 Phase 範圍內

- 雲端 API 備援的實際串接（僅設計介面預留位置）
- OCR 文件擷取（Phase 03）
- 夜間批次生成排程（Phase 04）
- 探查/使用 GTX 1060 或已安裝的 ollama/torch/transformers（若未來需要才處理）

## 待決事項

- 立場檢測用的關鍵詞清單需要多完整、要不要交給使用者審閱後才定案——目前只是初步樣本，可能有漏網或誤判
- 是否要在系統啟動時自動檢查 `llama-server` 是否存活（health check），或交由呼叫端每次自行處理
