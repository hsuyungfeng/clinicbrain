# Phase 38: 全自動診所網站爬取與智能知識提煉引擎 (Automated Clinic Web Scraper & Distiller) - 研究報告

## 1. 現況分析與痛點調查

### 1.1 現有網站解析管線之限制
- **現行實作**：`src/scraper/` (`fetch.py`, `extract.py`) 與 `src/pageindex/web_source_adapter.py`。
- **痛點 1（SPA/動態渲染盲區）**：使用純 Python `urllib` 與 `HTMLParser`，面對現代診所網站常見的 React / Vue / Webflow / Wegic 等單頁應用（SPA），僅能下載到 `<div id="root"></div>` 空殼，因查無字數 $\ge 30$ 的服務項目而判定為 `schema_drift` 並拋出 HTTP 422。
- **痛點 2（單頁侷限）**：現有後端僅處理單一靜態 URL，缺乏自動探索與抓取站內療程子頁面（`/service/`, `/faq/`, `/about/` 等）的能力。
- **痛點 3（同步等待逾時風險）**：Web 爬取與本地 LLM 提煉耗時（約 15~40 秒），HTTP 同步請求容易造成前端 Timeout。

### 1.2 既有可用基礎建設
1. **Playwright 環境已就緒**：專案環境已安裝 `playwright`，並於 Phase 30~33 成功用於無頭 Chromium 動畫截圖與契約驗證。
2. **醫療法規防禦庫已完備**：
   - 價格遮蔽：`src/pageindex/web_source_adapter.py` 中的 `deep_mask_prices()`。
   - 簡繁轉換：`src/ingestion/convert_chinese.py`（基於 `opencc` `s2twp`）。
   - 身分保護：過濾診所電話、地址與醫師私人聯絡資訊。
3. **知識提煉與雙層遞迴系統已建立**：
   - FAQ 生成：`src/pageindex/generate_faq.py`。
   - 推理樹四段式蒸餾：`src/soap/distiller.py` 與 `src/pageindex/prompt_template.py`。
   - 文本自進化馬具：`src/pageindex/text_harness.py`（強制檢核就醫警訊、禁止保證療效、禁止價格洩漏）。
   - 權威寫入路徑：`src/pageindex/faq_writer.py` 與 `src/pageindex/db_writer.py`。

---

## 2. 核心技術選型與架構設計

### 2.1 Playwright 動態頁面擷取器 (`src/scraper/playwright_scraper.py`)
- 使用 `async_playwright` 或同步 `sync_playwright`，啟動無頭 Chromium：
  - 設定 `headless=True`、注入標準 Desktop User-Agent。
  - 等待機制：`wait_until="networkidle"` 或等待 DOM 文字長度穩定的超時退避策略（Fallback）。
  - 安全沙盒防護：阻斷外連資源（如第三方廣告、追蹤代碼），僅允許 HTML/JS/CSS，加速渲染。
  - 抽取完整乾淨的 `inner_text` 與 HTML。

### 2.2 同網域子頁面自動探索與過濾 (`src/scraper/site_crawler.py`)
- **同源網域限制**：嚴格限定同 Hostname，絕不跨站爬取。
- **Sitemap 與深度探索 (BFS, max_depth=2, max_pages=8~10)**：
  - 優先順序佇列：路徑包含 `service`, `treatment`, `faq`, `about`, `orthopedic`, `case` 者優先。
  - 排除黑名單：過濾 `#`, `javascript:`, `mailto:`, `tel:`, `.jpg`, `.pdf`, 隱私政策, 人才招募等無關頁面。
- **內文整合與降噪**：
  - 移除共通導航欄與 Footer 版權文字。
  - 經由 `opencc` 轉換為台灣正體中文，並經由 `deep_mask_prices` 清洗價格數字為 `[請致電診所確認]`。

### 2.3 智能知識提煉對接 (`src/scraper/distill_pipeline.py`)
- **FAQ 生成**：將清洗後的站點文字分塊，透過本地 Qwen 27B 提煉為常見問答，經由 `score_faq_answer_alignment` 評分，寫入 `faq_cache`（`review_status='pending'`）。
- **PageIndex 推理樹生成**：針對識別出的核心療程主題，提煉標準四段式結構（`pre_op`, `procedure`, `post_op_short`, `maintenance`），經由 `score_tree_distillation_alignment` 評分，寫入 `page_index_trees`（`review_status='pending'`）。

### 2.4 後台非同步作業與進度查詢 (API & UI)
- **非同步 Job 機制**：類似 `batch_answer_job.py`，啟動背景執行緒處理爬取與提煉，提供 `POST /api/v1/admin/crawler/start` 與 `GET /api/v1/admin/crawler/status/{job_id}`。
- **管理後台 UI 整合**：在 `static/index.html` 貼入網址後，顯示即時進度條（爬取中 ➔ 清洗中 ➔ 提煉中 ➔ 完成），完成後自動導向待簽核分頁。

---

## 3. 測試與驗證策略
- 單元測試：針對 Playwright 渲染、子頁面發現過濾、文字清洗進行 Mock 測試。
- 端到端測試：使用本地臨時 HTTP 伺服器模擬 SPA 網站，驗證爬取 ➔ 提煉 ➔ 存入 `pending` 之全流程。
- 零污染原則：測試全面使用隔離資料庫 `isolated_conn`，正式 `clinic.db` 不受污染。
