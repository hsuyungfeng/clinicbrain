# Phase 28：病人端對話式諮詢與預生成 QA — Context

**Gathered:** 2026-10-16
**Status:** Ready for planning
**Source:** 使用者實測四方比較 + 指示（交談內容）

<domain>
## Phase Boundary
病人端 `/api/v1/general/consult` 的回答品質、速度與對話結構。不含留資表單／doctor-toolbox.com 整合（階段二）。
</domain>

<decisions>
## 已鎖定決策
- 實測比較（果凍矽膠隆乳）：本機 LLM 一般醫學（75 秒、1572 token）內容豐富但有事實錯誤（BIA-ALCL 名稱錯、捏造「RFID 安全門」、編造比例）；Gemini 含價格違規；診所文件＋雲端 LLM 語氣最佳（短、人性化、結尾單一追問），但外送雲端不可用；clinicbrain RAG 合規但重複句多、且**被截斷**（「若出現胸」）。
- 架構三層：(1) 預生成 QA（夜間批次，pending→醫師核准→公開，命中即回）；(2) 即時組稿：已核准診所專屬資料＋已核准一般醫學資料，由本機 LLM 依固定結構生成；(3) 未命中時的未審一般說明沿用 AGENTS 2.24 例外（標示未審，不進公開快取）。
- 回答結構：價值回答 2～4 句 → 單一追問 → 預約／留資邀請（先提供價值、後獲取資訊）。每次只問一個問題，不要求姓名／電話。
- 960 秒生成耗時視為異常（同模型 1572 token 僅 75 秒），先查根因（reasoning／max_tokens／重試），再決定是否需要背景生成＋輪詢。
- 使用 FAITHFUL_SAMPLING（AGENTS 2.19）與長度上限；紅旗短路與免責聲明維持。
- 收集越多診所專屬資料與病人問答主題（去識別化、標準化，不存原文），越多預生成相似 QA。
- **（2026-10-16 新增）24 小時預先生成主體醫學資訊**：PageIndex 建好後，每個療程／主題的「主體醫學資訊」（什麼是、適合誰、風險、術後照護、就醫警訊）須在 24 小時內由本機 LLM 預先生成（夜間批次，pending→醫師核准→公開），讓病人詢問時直接命中預生成內容，只需少量即時組稿（診所專屬資料＋追問＋預約邀請），縮短反應時間。範圍涵蓋所有已建檔 PageIndex 主題；以 `topic_key` 為單位追蹤「上次生成時間」，超過 24 小時或內容版本變更者重新排入佇列；仍受 `--max-faq-topics`、`--time-budget-seconds` 與審核閘門限制，永不自動核准。
- **執行分工（使用者指示）**：agy（executor）執行計畫 → hermes 測試 → Claude 最後檢查；三者依序，不得由同一方自我核准。
- 限制：不得直接寫正式庫；不得啟用 systemd；不得重啟 llama-server；價格屏蔽；繁體中文；文件以繁體中文撰寫；測試不得呼叫真實 LLM（除明確標記的實機驗證，且用副本庫）。

### Claude's Discretion
- 非同步機制細節（in-memory job vs 其他）、截斷偵測方式、相似 QA 生成演算法、測試切分。
</decisions>

<canonical_refs>
## Canonical References
- `AGENTS.md` §2.9、§2.19、§2.20、§2.21、§2.24 — 一般諮詢、FAITHFUL_SAMPLING、背景補齊、病人先答後導例外
- `.planning/phases/26-patient-consult-stage1/26-01-PLAN.md`
- `.planning/phases/27-patient-consult-ui/27-01-PLAN.md`
- `.planning/ROADMAP.md` Phase 28
- `src/api/routes/general.py`、`src/general/consult.py`、`src/pageindex/general_fallback.py`、`src/pageindex/rag_ask.py`、`src/pageindex/llm_client.py`、`src/batch/`
</canonical_refs>

<specifics>
理想風格範例：「…（簡短價值說明）… 實際狀況還是要讓醫師看過您的條件才能判斷。您比較在意的是手術後的恢復期，還是不同切口方式的優缺點呢？」
</specifics>

<deferred>
- 留資表單與 doctor-toolbox.com 整合（階段二）
- 反向代理速率限制實際套用
- 完整測試套件 18 失敗／3 錯誤排查（另案）
</deferred>
