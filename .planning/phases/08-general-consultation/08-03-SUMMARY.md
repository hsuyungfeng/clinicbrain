# Phase 08-03 總結報告：一般醫療諮詢 API 端點與存取日誌過濾

## 執行概述

本計畫為 Phase 08（一般醫療諮詢）之 Wave 3 任務，完成了對外匿名端點 `POST /api/v1/general/query`、Pydantic 請求與回應模型、uvicorn 存取日誌過濾器（防止問句與 IP 外洩）、`AnonymousRoute` 錯誤攔截保護，並以最小變更（+2 行）將路由掛載至 `src/api/app.py`。

---

## 交付成果清單

### 1. 核心實作
- **Pydantic 模型 (`src/api/models/general.py`)**：
  - `GeneralQueryRequest`：1-300 字元長度限制，strip 後純空白拒絕；不含 `clinic_id` 欄位。
  - `GeneralFaqItem` / `GeneralGuideItem`：問答與指引結果資料模型。
  - `GeneralConsultResponse`：包含 `status`, `red_flag_level`, `message`, `disclaimer`, `faq_hits`, `guide_hits`；**刻意不回顯 `query` 欄位**，落實隱私保護。
- **存取日誌過濾器 (`src/api/access_log_filter.py`)**：
  - `ExcludeGeneralPathFilter`：針對 `uvicorn.access` logger，攔截所有 `/api/v1/general` 開頭的路徑（包含問句 query string 與呼叫端 IP），整行丟棄；其他正常業務端點不誤傷。
  - `install_access_log_filter()`：具備冪等性的安裝函式。
- **一般諮詢 API 路由 (`src/api/routes/general.py`)**：
  - `AnonymousRoute(APIRoute)`：自訂路由子類，攔截所有 `RequestValidationError`，一律回傳固定繁體中文 `{"detail": "請求格式不正確"}`（HTTP 422），防範 FastAPI 預設錯誤回顯使用者問句（`detail[].input`）。
  - `POST /api/v1/general/query`：匿名對外端點，不要求 `X-API-Key`，不要求 `clinic_id`，不接受 GET 請求（405）。
  - 二次價格清洗：回傳資料經由 `deep_mask_prices()` 徹底杜絕金額洩漏。
- **應用實例掛載 (`src/api/app.py`)**：
  - 僅附加 2 行（import 與 `include_router`），不影響既有路由與啟動流程。

### 2. 測試套件
- **存取日誌過濾測試 (`tests/test_general_access_log_filter.py`)**：5 個測試全部通過。
  - POST 請求與帶問句之 GET 請求存取日誌整行丟棄。
  - `/api/v1/query` 與 `/health` 日誌不受影響。
  - 冪等性與端對端日誌攔截驗證。
- **API 整合測試 (`tests/test_api_general.py`)**：12 個測試全部通過。
  - 匿名諮詢成功與回應不回顯 query 欄位。
  - 三種狀態皆附帶免責聲明。
  - 無資料誠實回應。
  - 紅旗短路緊急就醫提示（monkeypatch 驗證未執行檢索且未走舊查詢路徑）。
  - 診所隔離（special FAQ 與機構標記不外洩、body 與 Header 夾帶 `clinic_id` 被忽略）。
  - 無需金鑰驗證（正式模式下不帶金鑰仍放行，對照 sync 端點 401）。
  - 僅允許 POST（GET 回傳 405）。
  - 輸入驗證與 7 種畸形格式 422 不回顯哨兵字串測試。
  - 回應二次價格清洗測試。
  - 唯讀且不記快取統計測試（檔案 hash 與列數未變）。
  - 路由掛載附加性檢驗。

---

## 驗收結果

- `python3 -m pytest tests/test_api_general.py tests/test_general_access_log_filter.py tests/test_general_consult.py tests/test_general_red_flags.py tests/test_general_disclaimer.py -q`：**191 passed**
- `git diff --stat src/api/app.py`：恰為 `2 insertions(+)`
- 路由禁用字串 grep 閘門：無 `import logging`、無 `handle_query`、無 `cache_stats`、無 `verify_admin_key`、無 `X-Clinic-ID`
- 正式庫零污染：未修改 `clinic.db`
