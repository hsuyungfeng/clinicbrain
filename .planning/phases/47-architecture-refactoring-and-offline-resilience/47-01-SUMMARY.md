# Phase 47-01 Summary — Wave 1: 搜尋防禦、LLM 連線池與合規正則

- **`escape_like()` 防禦**：於 `src/query/search.py` 新增 `escape_like()`，套用至 `search.py` 與 `src/query/nhi_index.py` 所有 `LIKE ? ESCAPE '\\'` 查詢；`tests/test_search.py` 與 `tests/test_nhi_index.py` 新增 `%`/`_` 測試（`28 passed`）。
- **`llm_client.py` 連線池與組態彈性化**：支援 `CLINICBRAIN_LLM_BASE_URL` 環境變數、改用模組級 `httpx.Client` keep-alive 連線池，並以 60 秒 TTL 快取 `/v1/models` 健康探測；`tests/test_llm_client.py` `10 passed`。
- **`medical_safety.py` 正則檢核**：確認 `check_dosage_prescription` 等正則皆已於模組載入時預編譯。
