# Plan 14-03 執行成果總結 (Summary)

## 任務執行概述
- **目標**：建立 FastAPI SOAP 路由與 Pydantic 資料模型，串接切分、去識別化與寫入模組；實作醫師專屬 FTS 檢索端點；落實認證與權限隔離；撰寫端到端驗收測試與營運文件。
- **成果**：
  1. 建立 `src/api/models/soap.py`：
     - 定義 `SoapRecordInput`、`SoapIngestRequest`、`SoapIngestResponse`、`SoapRecordItem`、`SoapSearchRequest`、`SoapSearchResponse` 資料模型。
  2. 建立 `src/api/routes/soap.py` 並掛載於 `src/api/app.py`（前綴 `/api/v1/soap`）：
     - `POST /api/v1/soap/records`：接收外部推播，支援結構化或純文字逐字稿，自動進行 S/O/A/P 切分、一般醫學特徵擷取、個資去識別化與二次價格防禦清洗，透過權威寫入函式 `upsert_soap_records` 冪等入庫。
     - `POST /api/v1/soap/search`：專屬醫師檢索端點，透過 FTS5 trigram 全文檢索與標籤過濾查詢病歷。
     - `GET /api/v1/soap/records/{external_id}`：依外部 ID 調閱單筆 SOAP 紀錄。
     - 全端點強制掛載 `verify_admin_key` 與 `clinic_id` 嚴格隔離，公開大眾端點（`/api/v1/query`、`/api/v1/general/query`）嚴格隔離，無法存取 SOAP 資料。
  3. 撰寫端到端整合測試 `tests/test_soap_api.py`（6 項測試全部通過）：
     - 驗證推播入庫、純文字自動切分、個資遮蔽、價格清洗、重複推播冪等性。
     - 驗證未授權訪問拒絕（401）、無效診所代碼拒絕（400）、跨診所存取隔離。
     - 驗證 FTS 專屬檢索與公開自然語言查詢端點嚴格隔離。
  4. 產出營運與系統文件：
     - 撰寫 `docs/soap-ingestion.md` 詳述串接規格、去識別化原則、檢索端點與維護指引。
     - 更新 `AGENTS.md`：2.1 節新增資料表說明、2.13 節新增模組規範、第 4 節更新模組與測試目錄索引。
  5. 全量回歸測試通過（919 passed），正式資料庫 `clinic.db` SHA-256 全程未變。

---

## 驗收數據
- `python3 -m pytest tests/test_soap_api.py -v`：6 passed in 0.75s。
- `python3 -m pytest -q --ignore=tests/test_real_llm_batch.py`：919 passed, 1 skipped, 1 warning in 26.41s。
- `sha256sum -c .planning/phases/13-real-llm-batch-verification/prod.sha256`：`clinic.db: 成功` (`ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e`)。
