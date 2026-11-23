# Phase 54 Research: 每日權威醫學新知自動巡檢與待審提案管線

**Date**: 2026-11-20
**Repo**: `/home/hsuyungfeng/DevSoft/clinicbrain`

## 1. 現有資產規模與安全邊界
- 已核准（`approved`）正式知識庫：`faq_cache` **1,081** 筆、`page_index_trees` **88** 棵、`visual_assets` **397** 支（外加 1 筆 `rejected`）。
- 依 [AGENTS.md](file:///home/hsuyungfeng/DevSoft/clinicbrain/AGENTS.md) 強制規範：
  - 唯一權威寫入路徑：`faq_writer.upsert_faqs()`、`db_writer.upsert_trees()`，不可繞過或使用 `INSERT OR REPLACE`。
  - `page_index_trees` 的 `*_physician_notes` **絕不可由 LLM 生成或覆寫**。
  - `visual_assets` 的 `organ_system` 與 `anatomy_target` 必須維持 Phase 52 鎖定，不可因文案更新跑偏。
  - 所有內容必須經 `opencc s2twp` 繁體轉換、`deep_mask_prices()` 與禁詞／政治敏感詞檢核。

## 2. 可用技術元件（已實測確認）
- HTTP 客戶端：`httpx`、`lxml` 已安裝於 `.venv`（無須額外安裝 `bs4` 或 `feedparser`，可用標準庫 `xml.etree.ElementTree` + `lxml.html` 解析官方 RSS/Atom 與 PubMed E-utilities）。
- SSRF／網路防護：[src/scraper/policy.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/scraper/policy.py) 與 [src/scraper/fetch.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/scraper/fetch.py) 已存在；Phase 54 另加**嚴格網域白名單（Fail-Closed）**，只允許官方與學術網域。
- 本機 LLM：`Ornith-1.5-35B-Q5_K_M` 運行於 `127.0.0.1:8080`（`local_llm_call`）。
- 管理後台架構：[src/api/routes/admin/__init__.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/api/routes/admin/__init__.py) 掛載管理子路由（含 `verify_admin_key` 認證與 CSP 中介軟體保護）。

## 3. 設計決策
1. **Shadow Draft 模式**：每日搜尋只寫入 `knowledge_refresh_proposals (status='pending')`，絕不直接修改 `approved` 主表。
2. **免費免金鑰雙軌官方來源**：
   - **PubMed E-utilities API**（`eutils.ncbi.nlm.nih.gov`）：依主題關鍵字取得最新實證文獻標題與摘要。
   - **台灣官方醫療／公衛網域**（`cdc.gov.tw`、`mohw.gov.tw`、`fda.gov.tw`、`nhi.gov.tw`、`hpa.gov.tw` 及醫學中心衛教網域）：以 RSS／公開頁面擷取最新公告。
3. **每日分層輪巡配額**：每天預設處理 15 題（優先挑 `cache_stats` 高頻 `miss` 與最久未檢核主題），無實質新醫學證據時僅更新 `last_verified_at`，不產生假提案。
