# Phase 18 Context: 各診所資料上傳與管理 Web App

## 1. 業務背景與核心價值
clinicbrain 目前已具備完整的臨床 SOAP 紀錄擷取（Phase 14）、衛教特徵提煉（Phase 15）、夜間定時同步與批次排程（Phase 16）以及通用醫學知識庫（Phase 17）。

然而，診所人員與主治醫師在操作上仍須仰賴終端 CLI（如 `review_faq.py pending-summary`、`curl` 端點推播）或手動執行腳本。為了讓診所人員與醫師能在診間或行政電腦上直覺操作：
1. **診所文件上傳**：允許診所行政人員上傳衛教文件、項目清單或問答手冊（支援 DOCX / XLSX / PDF），自動化清洗並轉為待審草稿。
2. **臨床 SOAP 紀錄檢視**：提供病歷與照護重點可視化查詢與標籤過濾。
3. **視覺化醫師簽核儀表板**：展示待簽核衛教草稿（pending），提供病歷溯源對照、一鍵核准（approve）或駁回（reject），並即時反映至快取短路庫。

---

## 2. 協同模式與多 Agent 流水線（Mandatory Process）
本階段嚴格落實使用者指示之 **Herdr 多 Agent 流水線機制**：
1. **實作端 (Agy 3.6 Flash, `w5:p2`)**：負責 API 路由、前端介面元件、資料庫操作與單元/整合測試之初步實作。
2. **審查與加固端 (Claude 5.5 Sonnet, `w5:p3`)**：在 3.6 Flash 實作完成後，由 Claude 接力進行深度對抗性代碼審查，檢查 CSRF、XSS、路徑穿越、檔案上傳大小限制、連線外洩、Fail-Closed 隔離有效性，並直接加固修復代碼與同步 `AGENTS.md`。
3. **終端驗收端 (Hermes Agent, `w5:p4`)**：跑全套回歸測試、確認正式資料庫 `clinic.db` SHA-256 恆定未變、工作區乾淨度檢查並輸出 PASS/FAIL 驗收結論。

---

## 3. 核心安全與架構原則
1. **Fail-Closed 認證防禦**：
   - 所有 Web 管理端點必須受到 `verify_admin_key`（API Key 或管理權限）保護，未授權者無法存取。
2. **零價格洩漏與去識別化**：
   - 任何上傳的文件與回傳的內容，均必須通過 `deep_mask_prices()` 與 `deidentify_text()`。
3. **輕量無依賴前端**：
   - 前端採用純 HTML5 / Vanilla JS / 現代 CSS（可搭配 Tailwind CDN），無繁重的 Node.js / npm build 工具鏈，由 FastAPI 直接提供服務，確保本機部署輕量穩定。
4. **正式庫絕對安全**：
   - 測試全程使用 `tmp_path`，正式資料庫 `clinic.db` 雜湊前綴 `5fb8328d...` 嚴禁任何污染。
