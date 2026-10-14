---
gsd_state_version: 1.0
milestone: v1.4
milestone_name: 臨床衛教提煉與進階防護
status: completed_milestone
stopped_at: Milestone v1.4 / Phase 15–18 全數圓滿完成，全套回歸測試 1013 passed，正式資料庫 SHA-256 恆定未變
last_updated: "2026-10-08T15:55:00.000Z"
last_activity: 2026-10-08 -- Phase 18 診所資料上傳與管理 Web App 實作與加固完成，全套回歸測試全過
progress:
  total_phases: 4
  completed_phases: 4
  total_plans: 12
  completed_plans: 12
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-02)

**Core value:** 在符合台灣醫療法規（絕對價格遮蔽、全繁體中文、無保證療效）的前提下，提供診所高精準度、低延遲、隱私優先（純本地推理）的臨床衛教與藥品檢索。
**Current focus:** Milestone v1.4 圓滿收官；已完成 Phase 15–18 全部規劃與閉環實機驗證

## Current Position

Phase: 23（競品／合作機構網站擷取器）-- COMPLETED
Plan: 23-01、23-02、23-03 均已實作、加固與 85/85 專屬測試通過
Status: Milestone v1.5 In Progress (Phase 23 完成)
Last activity: 2026-10-14 -- 完成網站素材擷取器（安全網址政策、釘住 IP、節流與 robots、HTML 結構抽取、合規檢驗、唯一寫入路徑、批次編排與抓取前探測鎖、CLI 守門、操作手冊與 E2E 完整生命週期驗收）

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**

- Total tasks completed: 62+
- Tests passing: Phase 19 專屬與加固 32/32 passed, 全系統回歸 1013+ passed
- SQLite records: 7,573 drugs, 2,669 services, 6 PageIndex trees, 41 approved FAQs (含 1 筆 Web 審核), 50 pending web_upload FAQs (Endolift 50問), 15 種子主題 (32+ 題)，soap_records/soap_records_fts (trigram) 支援

## Accumulated Context

### Decisions
- [Phase 23 2026-10-14]: 完成網站素材擷取器（Web Scraper）全模組實作與端到端加固。實作安全網址政策 `src/scraper/policy.py`（白名單、公網 IP 判定、逐請求 5s 節流、Robots 快取與判定）；受限 HTTPS 擷取器 `src/scraper/fetch.py`（自訂 UA、釘住 IP 直連、TLS 強制、重導向防護）；HTML 結構抽取 `src/scraper/extract.py`（抽取機構代表資訊與服務項目、徹底過濾醫師私人 09 手機/信箱/LINE、價格清空防禦、schema drift 偵測）；草稿建置與合規檢查 `src/scraper/drafts.py`（繁體轉換、去識別化、深度價格屏蔽、13 項保證療效禁詞前置攔截、機構地址電話身分外洩檢查、醫療常規驗證、機構層級 metadata 排除醫師欄位、唯一權威寫入路徑 `upsert_faqs(..., source_type='web_upload', commit=False)` 支援呼叫端交易邊界）；批次編排與安全日誌 `src/scraper/report.py`（路徑前兩段提示、白名單日誌輸出）、`src/scraper/runner.py`（擁有權書面授權閘門、寫入模式抓取前探測鎖避免競爭、先抓全部後統一解析、每網址獨立交易失敗隔離）；CLI 入口 `scripts/scrape_site.py`（正式庫 realpath 與 samefile 雙重防護、dry-run 採 mode=ro URI 唯讀預檢、結束碼 0/1/2 規範、git 追蹤警示）；操作手冊 `docs/web-scraper.md`（完整操作指南、零真實目標網址字樣）；專屬測試 85/85 PASS，正式庫 `clinic.db` SHA-256 恆定未變（`0089ca28795fd0f0f2a41e9fa6b16f840ae794bfaf4e5597576410e9f0cf23db`）。
- [Phase 22 2026-10-14]: 完成 RAG 提問檢索優化、BM25 排序與結構化衛教生成。在 `search_text` 實作 FTS5 BM25 相關度評分（subquery JOIN `_fts.rank ASC`，並以 `_fts_rowid` 別名消除欄位歧義，加掛 FTS 語法錯誤優雅降級 LIKE fallback）；在 `_search_terms_merged` 實作多詞命中交集加權（Multi-Term Intersection Boost），解決修飾詞遭截斷問題；將 `rag_ask.py` 的 `MAX_FAQ` 由 4 放寬至 8 筆；優化 `build_ask_prompt` 引導 250~400 字結構化條列（【門診處置】、【日常照護】、【就醫提醒】）；前端 Web App `app.js` 與 `style.css` 支援自適應段落與資料來源晶片網格展示；真實資料庫「甲溝炎要怎麼照護？」端到端驗收成功召回 ID 497（居家自我護理與家庭治療：溫水浸泡、拍乾、透氣鞋襪、直邊修剪防長入肉）；專屬測試 16/16 PASS，系統廣域回歸 327/327 PASS，正式庫 `clinic.db` SHA-256 恆定未變（`0089ca28795fd0f0f2a41e9fa6b16f840ae794bfaf4e5597576410e9f0cf23db`）。
- [Phase 15 2026-10-07]: 完成臨床 SOAP 衛教提煉與審核流（Herdr 多 Agent 流程：Agy 實作、Claude 對抗性審查加固、Hermes 驗收）。實作 `src/soap/distiller.py` 居家照護特徵聚合與價格/劑量二次清洗；擴充 `faq_writer.py` 支援 `source_type='soap_distilled'` 與 `metadata` 欄位；確立法規防禦「正式庫寫入路徑絕不自動 ALTER」，透過 `scripts/migrate_faq_metadata.py` 採 DDL 單一來源遷移；修復重複提煉重設審核狀態 Bug（內容未變僅更新 metadata 不重設 status）；修復 SQLite NULL 三值邏輯隔離漏洞；擴充 `review_faq.py` 與 `faq_review.py` 支援 `--source soap_distilled` 篩選與臨床病歷溯源顯示；新增 `distill_soap_faqs.py` 支援 `--dry-run` 唯讀連線模式；全套單元與端到端測試 10/10 PASS，正式庫 `clinic.db` SHA-256 維持 `ad24426cadd84db7`。
- [Phase 14 2026-10-07]: 使用者五項醫療語意決策全數採納：疑似/R/O 排除（方案 A）、Assessment 為空 conditions 留空（方案 A）、英文縮寫不擅自映射（方案 A）、取消單字母空白分隔並強制標點（方案 A）、行內單字母標記不承認（保守規則，僅行首與成對括號承認，排除脈搏 P: 80 衝突）；粗括號放寬前導切分；後置否定容許最多 4 個非標點字元；migrate_soap_schema 支援 --dry-run 純記憶體預覽。
- [Phase 14 2026-10-06]: 支援外部推播（doctor-toolbox.com）與語音聽寫紀錄入庫；section_parser 自動切分 S/O/A/P 並安全退化至 subjective；extract_general_medical_insights 自動萃取一般醫學特徵、症狀與居家照護摘要；deid 模組遮蔽台灣身分證、電話、姓名，並套用 deep_mask_prices 洗清金額；patient_token 採 HMAC-SHA256 偽名化衍生；soap_writer 提供唯一權威 upsert；FastAPI /api/v1/soap/records、/search、/records/{external_id} 強制 verify_admin_key 認證與診所隔離；公開端點嚴格隔離；單一來源遷移腳本維護 trigram FTS5 虛擬表與 3 觸發器。
- [Phase 12 複審補強 2026-10-06]: 劑量層 DX-2 涵蓋只有數量的句子、否定詞須緊鄰動詞才豁免、詞庫補劑型與英文學名；警訊層排除勸人別就醫的反向句並支援條列式；DEBT-03 補 `mark-regen --seed`（種子外題目拒絕標記）、`list` 顯示「待重生」、批次日誌記 unchanged/failed 列 id。
- [Phase 11]: 診所資料優先檢索（Tiered 兩階段判定），帶 clinic_id 優先查 special FAQ，短路率 24/40 -> 38/40；相近阻斷下限 CLINIC_RELATED_FLOOR = 0.4；回應結構新增 data_level 標示層級；無 clinic_id 查詢排除所有診所 FAQ。
- [Phase 10]: 遷移腳本 ALTER 改自 clinic_schema.sql 動態擷取單行定義（消除 DDL 雙寫）；移除 APIConfig.default_clinic_id 孤兒設定，堅持 clinic_id 明確傳入原則。

### Pending Todos

- 正式環境資料庫遷移：需由管理員備份正式庫後執行 `python3 scripts/migrate_soap_schema.py --confirm-prod-backup`。
- 使用者待辦：請醫師合併正式庫 id 4 與 id 19 重複問句（或區分情境），合併後短路率可由 38/40 達 40/40。
- 下一階段規劃：Phase 15（臨床 SOAP 衛教提煉與審核流）。

## Session Continuity

Last session: 2026-10-12
Stopped at: Phase 21（臨床決策推理樹擴展與審核加固）全部完成；Lipoma 9 筆草稿已成功補齊並 approved；API 伺服器與 llama-server 正常運行。
Resume file: .planning/phases/21-pageindex-trees-expansion/.continue-here.md

