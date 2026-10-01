# Phase 08-02 總結報告：一般醫療諮詢業務層模組

## 執行概述

本計畫為 Phase 08（一般醫療諮詢）之 Wave 2 任務，完成了 GENERAL-01（免責聲明附帶）、GENERAL-02（急重症紅旗短路防護）與 GENERAL-04（診所私有資料嚴格隔離）的核心業務入口 `consult_general()` 與結果資料結構 `GeneralConsultResult`。

---

## 交付成果清單

### 1. 核心實作
- **一般諮詢業務入口 (`src/general/consult.py`)**：
  - `GeneralConsultResult` 資料結構：包含 `status`（`"red_flag"` / `"answered"` / `"no_match"`）、`red_flag_level`、`message`、`disclaimer`、`faq_hits`、`guide_hits`。
  - `consult_general(conn, query, limit=5)`：
    1. 紅旗短路檢查：優先呼叫 `detect_red_flag`，命中立即回傳固定就醫指示，完全不進行分詞、不存取資料庫。
    2. 資料庫檢索隔離：未命中紅旗時，透過 `extract_search_terms` 擷取詞彙，僅查詢 `category='general' AND clinic_id IS NULL` 之問答快取與衛教指引樹。
    3. 欄位白名單與隱私防護：排除所有特定機構識別碼、內部 ID 與醫師內部註解。
    4. 價格防禦：對所有檢索結果字串套用 `mask_prices` 清洗。
    5. 誠實回應：無命中時回傳 `NO_MATCH_MESSAGE`，並附帶 `DISCLAIMER_TEXT`。

### 2. 測試套件
- **業務層單元測試 (`tests/test_general_consult.py`)**：9 個測試全部通過。
  - 紅旗短路測試（monkeypatch 斷言完全不呼叫檢索函式與分詞）。
  - 紅旗短路不存取連線測試（傳入 closed connection 仍正常回應）。
  - 一般命中測試（general FAQ 與 general 樹正常回傳與欄位白名單檢驗）。
  - 無命中誠實回應測試。
  - 診所隔離測試（special FAQ 與 special 樹絕不外洩、不查詢藥品與服務給付項目）。
  - 價格防禦清洗測試。
  - FTS 語法錯誤容錯測試（OperationalError 安全略過）。
  - limit 截斷測試。
  - PRAGMA query_only = ON 唯讀連線執行測試。

---

## 驗收結果

- `python3 -m pytest tests/test_general_consult.py tests/test_general_red_flags.py tests/test_general_disclaimer.py -q`：**170 passed**
- 模組禁用字串 grep 閘門：無 `import logging`、無 `handle_query`、無 `llm_client`、無診所專屬資料表或健保藥品表參照
- 正式庫零污染：未修改 `clinic.db`
