# Milestones

## v1.1 上線就緒與成本優化 (Shipped: 2026-10-02)

**Phases completed:** 4 phases（Phase 6–9）, 16 plans　**Requirements:** 13/13　**Tests:** 158 → 578 passed
**Archive:** [ROADMAP](milestones/v1.1-ROADMAP.md) · [REQUIREMENTS](milestones/v1.1-REQUIREMENTS.md) · [AUDIT](milestones/v1.1-MILESTONE-AUDIT.md)

**Key accomplishments:**

- **API 認證強制化**：未設 `CLINICBRAIN_ADMIN_API_KEY` 時拒絕啟動（結束碼 2），單一檢核函式涵蓋啟動腳本與 lifespan；提供明確的本機開發放行旗標。
- **快取優先查詢**：保守 FAQ 短路（覆蓋率雙門檻 + 數字單位/否定/時序/人群詞風險特徵），24 個對抗變形零誤短路；匿名命中統計只記路由關鍵字聚合計數。
- **匿名一般醫療諮詢**：`POST /api/v1/general/query`，紅旗症狀分級偵測（不走 LLM）、固定免責聲明、422 不回顯問句、access log 過濾。
- **醫師審核閘門與夜間批次**：LLM 生成 FAQ 預設 pending，核准後才可被查詢與匯出；批次支援 dry-run、LLM 離線優雅降級、樹重建保護 `physician_notes`。
- **稽核與測試衛生**：整合檢查全數 WIRED；測試與正式庫資料狀態脫鉤；AGENTS.md 與程式碼對齊。

**Known tech debt:** 見 [v1.1-MILESTONE-AUDIT.md](milestones/v1.1-MILESTONE-AUDIT.md)（AUTH-03/04 延後、短路命中率上限約 60%、general 內容 0 筆、夜間排程尚未啟用等）。

---

## v1.0 Taiwan PageIndex RAG 基礎系統 (Shipped: 2026-09-29)

**Phases completed:** 5 phases（Phase 1–5）, 24 tasks
**Archive:** [ROADMAP](milestones/v1.0-ROADMAP.md)（無獨立 REQUIREMENTS 與稽核；完成於 GSD 驗證流程導入之前）

**Key accomplishments:**

- **健保資料庫與 PageIndex 臨床推理樹**：7,573 筆藥品、2,669 筆服務項目，FTS5 trigram 中文檢索；四段式推理樹與增量 UPSERT。
- **查詢路由與法規合規**：special/general 分流、價格屏蔽、OTC 藥品繁中本地化。
- **本地 LLM 推理層**：接入 llama-server (Qwen3.8-27B)，立場中立規則與雙層驗證防禦。
- **文件擷取與 FAQ 快取（Stage 1）**：docx/xlsx 擷取、簡繁轉換、四層驗證、40 筆真實 FAQ 入庫；Stage 2 圖片 OCR 評估後結案。
- **多診所架構與官方 API 整合**：機構代碼 `3503190424` 標準化、FastAPI 服務層、doctor-toolbox.com 雙向同步契約與審計紀錄。

---
