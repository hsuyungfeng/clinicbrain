# clinicbrain — Taiwan Clinic Medical PageIndex RAG System

## What This Is

緻妍外科診所（Zhiyan Aesthetic Clinic，機構代碼 `3503190424`）的專屬 PageIndex 臨床推理與 RAG 查詢系統。系統整合台灣健保（NHI）藥品、醫療服務給付項目與診所自費療程衛教，透過四段式臨床推理樹與 FAQ 快取提供結構化檢索，並具備 OTC 藥品本地化與嚴格的台灣醫療法規合規機制。

## Current Milestone: v1.2 診所資料優先與一般疾病簡易資訊

**Goal:** 診所自己提供的資料永遠優先被查；一般問題則有本地 LLM 生成、經醫師審核的疾病簡易資訊可答。

**Target features:**
- **診所資料優先查詢（clinic-first）**：有 clinic_id 時，不論關鍵字分流結果，一律先查該診所自己的 FAQ／推理樹／備註，查不到才退到 general（解決短路命中率上限約 60%、16/40 FAQ 被誤分流而查不到）
- **一般疾病簡易資訊（本地 LLM 生成）**：沿用 v1.1 批次與審核閘門（general 類、預設 pending、醫師核准後才被查詢），擴充常見疾病種子清單
- **技術債清理**：DDL 雙寫收斂、孤兒設定 `default_clinic_id`、駁回題目可否重新生成、批次對真實 LLM 的實跑驗證（僅複本）、紅旗詞表殘餘漏報（須使用者審閱）

**不在範圍：** 健保給付規定類問答（審查注意事項，列為後續）；簡體 `medical_o1_sft_Chinese.json` 與英文 ICD 檔不使用。

**已知前提：** 已出貨 v1.1（2026-10-02）與 v1.0（2026-09-29）；本機 FastAPI 服務（127.0.0.1，手動啟動）。

## Core Value

在符合台灣醫療法規（絕對價格遮蔽、全繁體中文、無誇大保證療效、政治立場中立）的前提下，提供診所高精準度、低延遲、隱私優先（純本地推理）的臨床衛教與藥品檢索。

## Requirements

### Validated

- ✓ **NHI 健保藥品與服務給付項目資料庫**：7,573 筆藥品 + 2,669 筆服務項目，FTS5 trigram 檢索 (Phase 01)
- ✓ **PageIndex 臨床推理樹**：四段式架構（術前/療程/術後短期/長期維持）與增量 UPSERT 機制 (Phase 01)
- ✓ **OTC 藥品本地化**：68 種常用成分中文別名對照 (Phase 01)
- ✓ **查詢路由器與法規過濾**：`special`/`general` 路由、分詞分流、`mask_prices()` 價格屏蔽 (Phase 01)
- ✓ **診所營運資料整合**：門診時間、診所資訊、自訂備註 (`clinic_custom_notes`) (Phase 01)
- ✓ **91 個完整測試案例**：覆蓋查詢分流、FTS 分詞、價格屏蔽、UPSERT 等關鍵路徑 (Phase 01)
- ✓ **本地 LLM 推理層**：接入本機 llama-server (Qwen3.8-27B)，加入立場中立規範與驗證防禦 (Phase 02)
- ✓ **多診所架構重構**：`clinic_id` 欄位補全、`doc_id` 去前綴、值遷移為健保代碼 `3503190424`、函式預設值移除並設為必填 (Phase 04 TASK-00~02)
- ✓ **文件擷取與 FAQ 管線 Stage 1**：docx/xlsx 擷取、opencc 簡繁轉換、LLM FAQ 生成、`faq_cache` 表與 40 筆正式資料寫入 (Phase 03 Stage 1)
- ✓ **穩定測試套件**：123 個 pytest 測試全數通過，正式資料庫安全隔離驗證 (Phase 01~04)
- ✓ **API 認證強制化**：未設金鑰拒絕啟動、fail-closed、本機開發旗標 (Phase 06)
- ✓ **快取優先查詢**：保守 FAQ 短路、source 標示、匿名關鍵字聚合統計、短路回答仍過價格遮蔽 (Phase 07)
- ✓ **匿名一般醫療諮詢**：不綁診所端點、紅旗分級偵測（不走 LLM）、免責聲明、422 不回顯問句 (Phase 08)
- ✓ **醫師審核閘門與夜間批次**：LLM FAQ 預設 pending、批次 dry-run/優雅降級、樹重建保護 physician_notes (Phase 09)
- ✓ **穩定測試套件**：578 個 pytest 全過，測試與正式庫資料狀態脫鉤 (Phase 01~09)

### Active

- [ ] **CLINIC-FIRST**：診所資料優先查詢，不受關鍵字分流限制
- [ ] **GENERAL-CONTENT**：LLM 生成的一般疾病簡易資訊（經審核閘門）
- [ ] **DEBT**：v1.1 稽核技術債清理

### Out of Scope

- **圖片 OCR 管線 (Phase 03 Stage 2)**：經抽查診所 47 張圖片，多為行銷文宣或儀器參數圖表，投資報酬率低且文字混雜圖表，判定不展開，維持人工審核謄寫。
- **整本醫學教材 OCR (`一般醫學/美容醫學/`)**：抽查確認為簡體中文掃描版專業教科書，無文字層，不適合作為大眾衛教素材，正式結案不展開。
- **雲端 LLM 依賴**：堅持本機優先與病患隱私，不使用外部商用 API 作為預設依賴。
- **舊系統 MITM 流量攔截**：未來與 doctor-toolbox 整合一律走官方 API，不採用舊版透明代理攔截方案。

## Context

- 本專案為舊系統 `DrtoolboxLocalServer`（GitHub `hsuyungfeng/DrtoolboxLocalServer`）的精簡重構與升級。
- 本地環境具備雙 GPU 與運作中的 llama-server（127.0.0.1:8080，Qwen3.8-27B-UD-Q4_K_XL）。
- 既有測試套件採嚴格資料庫隔離（`shutil.copy2`），確保測試不污染正式 `clinic.db`。

## Constraints

- **價格屏蔽**：任何 LLM 輸出絕對嚴禁包含價格數字或促銷組合，一律轉換為「請致電診所確認」。
- **全繁體中文**：嚴禁簡體中文輸出或未經轉換的簡體內容進入資料庫。
- **FTS5 分詞**：SQLite 虛擬表必須指定 `tokenize='trigram'`，並以 `extract_search_terms()` 分詞後查詢。
- **單一權威寫入路徑**：`upsert_trees()` 與 `upsert_faqs()` 為唯一合法寫入接口，嚴禁 `INSERT OR REPLACE` 覆寫。
- **clinic_id 約束**：目前唯一合法健保代碼為 `'3503190424'`，查詢與資料庫關聯必須嚴格維護。

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 雙層資料架構 (NHI 通用 + 診所專屬) | 職責分離，健保資料與診所營運資料可獨立更新 | ✓ Good |
| 路由分流 (`special` vs `general`) | 避免資訊過載並防止診所私有資訊外洩至通用查詢 | ✓ Good |
| 絕對價格屏蔽規則 | 符合台灣醫療法規限制，防範醫療爭議 | ✓ Good |
| 本地 LLM 優先 (llama-server) | 延續隱私第一原則，無雲端費用與資料外洩疑慮 | ✓ Good |
| Qwen 模型立場防禦 (Prompt + Validator) | 模型具特定立場傾向，採雙層防禦過濾違規用語 | ✓ Good |
| 健保機構代碼 `3503190424` 取代 slug | 標準化機構識別碼，便於未來對接官方醫事系統 | ✓ Good |
| `faq_cache` 獨立扁平結構 | Q&A 扁平問答與四段式臨床推理樹結構不同，分表清晰 | ✓ Good |
| 結案 Stage 2 圖片 OCR 與教科書 OCR | 投資回報率低、教科書不適合衛教且多為掃描簡體 | ✓ Good |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-10-02 after v1.2 milestone start*
