# Phase 18 Research: 各診所資料上傳與管理 Web App

## 1. 既有技術資產與架構對接

### 1.1 文件解析與前處理管線
- **既有模組**：
  - `src/ingestion/extract_text.py`：純 Python 處理 docx / xlsx 文字萃取。
  - `src/ingestion/markdown_convert.py`：支援 docx / xlsx / pdf 之 Markdown 結構化轉換。
  - `src/ingestion/medical_safety.py` / `src/query/router.py`：`deep_mask_prices()` 價格清洗。
  - `src/soap/deid.py`：`deidentify_text()` 個資去識別化。
- **Web 端點設計**：
  - `POST /api/v1/admin/upload`：
    - 接收 `UploadFile`（限制大小，如 15MB）。
    - 支援檔案格式：`.docx`, `.xlsx`, `.pdf`。
    - 參數：`clinic_id`（必填，防範跨診所竄改）。
    - 安全防禦：副檔名白名單、記憶體暫存寫入安全臨時檔、路徑穿越防禦。
    - 處理管線：解析文字 ➔ 去識別化 ➔ 價格數字遮蔽 ➔ 存入待審草稿或回傳解析預覽。

### 1.2 醫師審核 API
- **既有模組**：
  - `src/pageindex/faq_review.py` 提供權威審核函式：`approve_faq`, `reject_faq`, `mark_for_regeneration`, `list_faqs`, `count_by_status`。
- **Web 端點設計**：
  - `GET /api/v1/admin/review/faqs`：分頁取得待審或已審 FAQ，支援 `status`（pending/approved/rejected）、`category`（special/general）、`clinic_id` 篩選。
  - `POST /api/v1/admin/review/faqs/{faq_id}/approve`：核准發布，立即入庫生效。
  - `POST /api/v1/admin/review/faqs/{faq_id}/reject`：駁回草稿。
  - `GET /api/v1/admin/review/summary`：提供儀表板統計數字（待審總數、各疾病草稿數、SOAP 病歷數）。

### 1.3 臨床 SOAP 病歷檢視 API
- **既有模組**：
  - `src/api/routes/soap.py` 已經有 `/api/v1/soap/records`、`/search` 等。
  - Web 端點直接串接或重用唯讀查詢，支援依 `clinic_id`、診斷條件與時間檢視 S/O/A/P 結構化紀錄。

### 1.4 前端技術架構選型
- **原則**：輕量、零前端構建工具（No Node/Webpack）、即開即用。
- **方案**：
  - FastAPI `StaticFiles` 掛載於 `/admin` 或 `/app`。
  - 單頁應用（SPA，HTML + Tailwind CSS CDN + Alpine.js / Vanilla JS）。
  - 功能頁籤：
    1. 📊 **總覽儀表板 (Dashboard)**：待審草稿總數、診所病歷摘要、近期活動。
    2. 📝 **待審草稿簽核 (Review)**：卡片式列表、顯示標籤、病歷溯源關聯、一鍵核准/駁回按鈕。
    3. 📁 **文件上傳管理 (Upload)**：拖拉上傳 DOCX/XLSX/PDF、顯示解析結果與自動清洗狀態。
    4. 🩺 **臨床 SOAP 瀏覽 (SOAP)**：檢視結構化病歷、居家照護摘要、去識別化標籤。
  - 認證機制：登入對話框輸入 Admin API Key，儲存於 `sessionStorage`，隨後請求自動夾帶 `X-API-Key` 標頭。

---

## 2. 審查加固重點（Claude 角色指引）
- **CSRF & XSS 防護**：文字渲染避免 `innerHTML` 未跳脫，HTML 實體編碼防禦。
- **檔案上傳安全**：檔名清洗（防 Directory Traversal）、檔案大小嚴格上限（15MB）、記憶體溢出防範。
- **連線隔離**：查詢端點一律唯讀連線（`PRAGMA query_only = ON;`），寫入端點使用交易與明確 rollback。
- **Fail-Closed 隔離**：確保未核准草稿絕無法透過公開 API 存取。
