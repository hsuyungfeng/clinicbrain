# Phase 02 實作計畫：本地 LLM 推理層

> 給執行者（Antigravity）：本文件是完整實作規格，涵蓋 Phase 02 全部 4 個任務。
> 完成後請勿自行 commit — 交回使用者，由 Claude（此計畫作者）驗證後再決定是否提交。
> 請先讀過 `AGENTS.md`（專案根目錄）、`.planning/HANDOFF.json`、
> `.planning/phases/02-local-llm-layer/PLAN.md`（本文件的背景說明），理解既有規範後再開始。

## 背景（已實測確認，非假設）

機器上已有一個運行中的本地 LLM 推理服務：

- `llama-server`（llama.cpp），監聽 `http://127.0.0.1:8080`，OpenAI 相容 API
- 模型：Qwen3.8-27B（Q4 量化），已驗證 `POST /v1/chat/completions` 可正常運作
- 回應的 `message` 物件除了標準 `content` 外，還有非標準的 `reasoning_content`
  （模型的思考過程文字），**只能取用 `content`，`reasoning_content` 不是最終答案**
- 生成速度約 22.7 tokens/sec，屬於中速，單次生成一份療程樹（5 個欄位、數百字）
  預期需要數十秒，請求逾時設定不要設太短（建議至少 60 秒）

**已知風險與使用者決策**：實測發現此模型對政治敏感問題會輸出特定政治立場內容
（例如關於台灣主權地位的表述）。使用者決定**繼續使用此既有服務**，不更換模型、
不重新部署，改用 prompt 規範 + 輸出驗證雙層防禦。這是本計畫 TASK-02/03 的由來。

`src/pageindex/prompt_template.py` 在 Phase 01（TASK-004）已經寫好完整的
prompt 組裝、驗證邏輯，但**從未接上真正的 LLM 測試過**——目前所有測試都是
用假的 `llm_call` 函式模擬。`generate_tree(procedure_name, llm_call, ...)`
的介面設計就是為了讓 Phase 02 直接傳入真正的本地 LLM 呼叫函式，不需要改
prompt/驗證邏輯本身。

## 目標

1. 讓 `generate_tree()` 能接上真正在跑的本地 LLM，產出真實生成內容
2. 新增立場中立防禦（prompt 層規範 + 驗證層檢測）
3. 端到端跑出至少 2-3 筆新療程的 PageIndex 樹，證明整條鏈路可用

## 具體任務

### TASK-01：`llm_call` adapter

新增 `src/pageindex/llm_client.py`：

```python
LLM_ENDPOINT = "http://127.0.0.1:8080/v1/chat/completions"
LLM_MODEL_NAME = "Qwen3.8-27B-UD-Q4_K_XL"  # 或直接讀 /v1/models 動態取得，自行判斷

def local_llm_call(prompt: str, timeout: int = 90) -> str:
    """呼叫本機 llama-server，回傳 message.content（忽略 reasoning_content）。
    連線失敗或逾時應該拋出清楚的例外（自訂 exception class，例如
    LocalLLMUnavailableError），不要吞掉錯誤或回傳空字串假裝成功。
    """
```

- 用標準庫 `urllib.request`（已確認環境未安裝 `requests`，不要新增這個依賴，
  直接用標準庫實作即可）
- 呼叫前建議先打一次 `GET /v1/models` 做健康檢查，服務未啟動時給出「本地 LLM
  服務未啟動於 http://127.0.0.1:8080，請確認 llama-server 是否運行」這類清楚
  訊息，而不是原始的 connection refused traceback
- 這個函式簽章必須完全符合 `generate_tree()` 期待的
  `Callable[[str], str]`（見 `src/pageindex/prompt_template.py` 的
  `generate_tree()` 定義），這樣才能直接傳入不需要包裝

### TASK-02：Prompt 立場中立規範

修改 `src/pageindex/prompt_template.py` 的 `PROMPT_TEMPLATE` 字串常數，在現有
「嚴格規則」清單（目前有 6 條，見檔案第 55-70 行附近）新增第 7 條規則，措辭
風格要跟現有規則一致（現有規則都是「絕對禁止...」「不得...」這種明確禁令句型）：

- 禁止輸出任何政治、主權、國家定位、意識形態相關的立場表述，僅專注於醫療衛教
  內容本身；若生成過程中意外偏離療程主題，應該完全略過該離題內容，不得附和、
  重複或延伸任何政治性敘述

不要改動現有 1-6 條規則的文字，只新增第 7 條，並更新規則清單開頭的說明文字
（若原本寫「違反任何一條視為輸出無效」，改成涵蓋新規則數量後仍然通順即可）。

### TASK-03：輸出驗證層立場檢測

修改 `parse_and_validate()`，比照現有 `_FORBIDDEN_PHRASES` 機制（第 109 行附近
的 `_PRICE_PATTERN`/`_SIMPLIFIED_CHAR_SAMPLE`/`_FORBIDDEN_PHRASES` 這三個
驗證常數的寫法），新增一個新的驗證常數與對應檢查邏輯：

```python
_POLITICAL_STANCE_PHRASES = (
    "不可分割的一部分",
    "一個中國",
    "中國台灣",
    "台灣地區",
    # 可視情況擴充，但避免詞彙過於寬鬆導致誤傷正常醫療用語
    # （例如「地區」單獨出現在其他脈絡下不該被擋，只有跟特定政治語境組合才擋）
)
```

在 `parse_and_validate()` 內比照既有 `_FORBIDDEN_PHRASES` 檢查的寫法（用
`full_text` 逐一比對），命中任一詞彙即拋出 `TreeValidationError`，錯誤訊息要
清楚說明是政治立場檢測觸發（不要跟既有的「禁用詞彙（保證療效用語或誤植欄位
名）」訊息混在一起，讓開發者容易分辨是哪一類違規）。

**這組關鍵詞清單只是初始樣本，不要求窮舉完整**——請在交付說明中明確標註
「此清單非完整涵蓋所有可能的立場化表述，建議後續依實際生成內容持續擴充」，
不需要自己花大量時間研究政治用語，寫出基本、明確、不會誤傷正常醫療內容的
清單即可，這是防禦的其中一層，不是唯一防線。

### TASK-04：端到端驗證

1. 用 `local_llm_call` 實際呼叫 `generate_tree()`，生成至少 2-3 筆**跟現有
   6 筆手寫範本不同的療程**（例如「淨膚雷射」「電音波拉皮」「肉毒瘦臉」等，
   自行挑選合理的醫美診所常見療程，避免跟既有 `src/pageindex/seed_trees.py`
   裡的 `zhiyan-clinic-laser-skin-resurfacing`、`botox-injection`、
   `electrowave-facelift`、`hyaluronic-acid-filler`、`fractional-laser`、
   `hifu-lifting` 這 6 個 doc_id 重複的療程名稱）。
2. 驗證每筆生成結果都能通過 `parse_and_validate()` 全部檢查（若第一次生成
   沒通過驗證、被 `TreeValidationError` 擋下，這是預期行為，記錄下來即可，
   不代表失敗——重點是驗證層真的有在運作、擋下不合格輸出）。
3. 用 `to_upsert_row()` + `db_writer.upsert_trees(conn, [row],
   source_type='llm_generated')` 寫入**測試用資料庫複本**——**絕對不要**寫入
   正式 `clinic.db`。做法比照 TASK-008 建立的 `tests/conftest.py` 隔離模式：
   用 `shutil.copy2()` 複製一份 `clinic.db` 到暫存路徑，對複本操作，測試結束
   後複本可以直接丟棄（不需要清理回收，因為是暫存目錄）。
4. 手動檢查生成內容的合理性（人工判讀，不需要自動化指標）：內容是否符合台灣
   醫美診所衛教文案的口吻、是否有明顯胡謅的醫學細節、格式是否跟手寫範本一致。

## CONSTRAINT（必須遵守，違反視為交付無效）

1. **絕對禁止在任何輸出、註解、commit 訊息中出現簡體中文**。全部繁體中文。
2. **絕對不能讓本任務的測試/驗證過程寫壞正式 `clinic.db`**——比照 TASK-008
   建立的隔離慣例，任何寫入操作都在資料庫複本上進行。Claude 驗收時會檢查
   `clinic.db` 的 hash 是否有變化。
3. **不要修改 `llama-server` 本身的啟動參數、模型檔案，或嘗試重啟/關閉這個
   進程**——它是機器上既有、可能有其他用途正在使用的服務，本任務只是當一個
   呼叫端連進去，不能動它的運行狀態。
4. 不要修改 `src/pageindex/prompt_template.py` 現有的 1-6 條規則文字、
   既有的 `_PRICE_PATTERN`/`_SIMPLIFIED_CHAR_SAMPLE`/`_FORBIDDEN_PHRASES`
   邏輯——只新增，不要重構既有驗證機制。
5. `page_index_trees` 資料表本身、`src/query/`、`src/clinic/` 相關程式碼與
   本任務無關，不要觸碰。
6. Phase 01 既有的 91 個 pytest 測試套件（`tests/`）不應該因為本次改動而
   失敗——交付前請重新執行 `pytest tests/` 確認全數仍然通過。

## 驗收標準（交付時請附上以下驗證結果）

1. `local_llm_call()` 實際打一次 `http://127.0.0.1:8080/v1/models` 與一次
   `/v1/chat/completions`，附上原始回應片段證明服務可正常連通。
2. 修改後的 `PROMPT_TEMPLATE` 完整內容（新增第 7 條規則的實際文字）。
3. 修改後的 `parse_and_validate()` 對至少 1 個刻意構造的政治立場文字輸入
   （例如手動塞入「台灣是中國不可分割的一部分」這句話到模擬輸出中）進行
   測試，證明會被正確攔截拋出 `TreeValidationError`。
4. 至少 2-3 筆用真實本地 LLM 生成、通過驗證、成功寫入測試複本資料庫的
   PageIndex 樹內容（完整 JSON 或格式化輸出皆可）。
5. 執行 `pytest tests/` 的完整輸出，確認 91 個既有測試全數仍然通過。
6. 執行測試前後 `clinic.db` 的 SHA-256 hash 比對，證明正式資料庫未受影響。
7. 交付時附上簡短說明：`llm_client.py` 放在哪裡、逾時/錯誤處理怎麼設計、
   立場檢測關鍵詞清單最終定案內容、生成過程中是否有觸發過驗證失敗（價格/
   簡體字/立場/其他），若有請說明具體是哪一類。

## 不在本任務範圍內（請勿順手處理）

- 雲端 API 備援的實際串接（僅本地服務，雲端 fallback 留待後續）
- OCR 文件擷取管線（Phase 03 範圍）
- 夜間批次生成排程（Phase 04 範圍）
- 探查或使用 GTX 1060、既有安裝的 ollama/torch/transformers（除非本任務
  明確需要，目前判斷不需要）
- 修改 Phase 01 已完成的任何查詢層、資料庫 schema、OTC 本地化邏輯

這是本專案一貫的做法，請避免越界，讓 Phase 02 的第一批任務乾淨收尾。
