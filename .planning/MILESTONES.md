# Milestones

## v1.3 臨床語音與 SOAP 紀錄擷取 (Shipped: 2026-10-07)

**Phases completed:** 1 phase（Phase 14）, 3 plans + 剩餘項目強化管線　**Requirements:** 5/5　**Tests:** 919 → 945 passed (SOAP 專屬 69/69 passed)  
**Archive:** [ROADMAP](milestones/v1.3-ROADMAP.md) · [REQUIREMENTS](milestones/v1.3-REQUIREMENTS.md)

**Key accomplishments:**

- **官方推播與 SOAP 安全儲存**：提供 `POST /api/v1/soap/records` 支援 doctor-toolbox.com 臨床文字與語音聽寫推播，寫入 `soap_records` 與 trigram `soap_records_fts`，提供唯讀連線 `PRAGMA query_only=ON` 醫師檢索。
- **嚴格去識別化與隱私防護 (deid)**：遮蔽台灣身分證（10 碼）、電話（09 開頭 10 碼）、中文姓名；金額數字全面清洗為 `[請致電診所確認]`；患者識別碼採 HMAC-SHA256 偽名化衍生。
- **確定性 S/O/A/P 結構切分 (section_parser)**：單字母標記強制行首與標點、成對粗括號放寬切分、排除 `P: 80` 脈搏衝突、無標記純文字安全退化至 subjective。
- **特徵擷取與否定防禦**：納入 `r/o`、`rule out`、`疑似`、`鑑別診斷` 排除詞表；Assessment 為空時 conditions 保持 `[]` 留空降級；後置否定容許寬容度比對。
- **遷移工具安全防護**：`scripts/migrate_soap_schema.py` 支援 `--dry-run` 免確認旗標純記憶體 DDL 預覽。

---

## v1.2 診所資料優先與一般疾病簡易資訊 (Shipped: 2026-10-06)

**Phases completed:** 4 phases（Phase 10–13）, 15 plans　**Requirements:** 11/11　**Tests:** 578 → 919 passed  
**Archive:** [ROADMAP](milestones/v1.2-ROADMAP.md) · [REQUIREMENTS](milestones/v1.2-REQUIREMENTS.md)

**Key accomplishments:**

- **技術債清理與單一來源 (Phase 10)**：遷移腳本 ALTER 動態由 `clinic_schema.sql` 擷取，移除未使用的 `default_clinic_id` 孤兒設定。
- **診所資料優先檢索 (Phase 11)**：Tiered 兩階段判定，帶 `clinic_id` 優先查診所 special FAQ，短路自查率提升至 38/40，清楚標示資料層級 (`clinic` / `general`)。
- **一般疾病內容生成與審核 (Phase 12)**：17 題疾病種子，DX-1~5 劑量與處方攔截器，就醫警訊強制檢驗與免責聲明，`review_faq` 主題批次審核工具與 `mark-regen` 重生成標記。
- **真實本地 LLM 批次實跑驗證 (Phase 13)**：在資料庫複本上以真實 llama-server (Qwen 27B) 完整實跑驗證夜間批次流程，正式庫 SHA-256 恆定未變。

---

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
