# Phase 29 CONTEXT：一般醫學視覺解說卡（MVP）

## 來源與決策（使用者 2026-10-19）
- 來源構想：`planmotion.md`（動態視覺化 + 智慧客服留資）。經評估後縮小為 MVP。
- 決策 1：**不在本系統收個資**。動畫 CTA 只導向 doctor-toolbox.com 預約連結；不做 LINE／手機留資、CRM 同步、PII 清洗。
- 決策 2：醫學概念為**說明性質、非教學**，不要求高學術標準（不需文獻引用、不做存活率量化）；用途為**預生成供合作診所共用**（資產不綁特定診所）。
- 保留：合規規則不因門檻降低而放寬（價格、簡體、保證療效禁詞、就醫警訊語意、AGENTS 對外內容須醫師核准）。

## MVP 範圍
- 1 個主題：自體脂肪移植（`topic_key=autologous-fat-grafting`）。3 個固定場景模板：process_diagram、contrast、timeline。
- **Typed IR（結構化 JSON）**：LLM 只填各場景的說明文字，不產生任何程式碼／HTML／SVG；前端以固定模板渲染。
- 資產表 `visual_assets`（共用，不含 clinic_id）；一律 `pending`，醫師核准後才對外。
- 嵌入 `/consult` 頁：回答命中資產關鍵字時，於答案下方顯示可逐步切換的解說卡；固定標示「一般醫學知識說明，非個人化診斷」。
- 匿名計數 `visual_stats`（顯示次數、看完次數；不記問句、不記 IP）。
- 不做：MP4／TTS／Remotion／HyperFrames／R2／Postgres／第二個模型／夜間批次階段／留資。

## 硬性約束
- `src/general/` 受 `tests/test_general_privacy.py` 管制（只准 SELECT、無 logging、無持久化）；寫入統計與資產的程式一律放 `src/visual/`。
- 輪詢端點 `GET /consult/jobs/{id}` 不得連資料庫；動畫資料在 job 完成時一併放入結果。
- 未遷移的庫 Fail-Closed：缺表時不顯示動畫、不報錯。
- 不得直接寫正式庫；遷移腳本須 `--confirm-prod-backup`；不得啟用 systemd；不得重啟 llama-server。
- 前端所有動態文字以 `textContent` 寫入；不使用 innerHTML。

## 需求編號
P29-SCHEMA、P29-IR、P29-GEN、P29-REVIEW、P29-SERVE、P29-UI、P29-STATS、P29-DOC
