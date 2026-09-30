# 06-01-SUMMARY: API 認證強制化核心實作 (AUTH-01)

## 執行成果摘要

本階段已完成 API 認證強制化（AUTH-01）之核心邏輯：
1. **新增認證組態與檢核模組 (`src/api/security.py`)**：
   - 實作單一檢核邏輯 `check_auth_config`，統一由啟動腳本與 FastAPI `lifespan` 呼叫，杜絕直接 `uvicorn` 繞過可能。
   - 提供 `is_key_configured`、`build_refusal_message`、`build_dev_warning`，錯誤訊息皆為繁體中文處置指引。
2. **組態擴充 (`src/api/config.py`)**：
   - 新增 `allow_no_auth: bool` 欄位，預設為 `False`，讀取 `CLINICBRAIN_ALLOW_NO_AUTH` 環境變數。
3. **管理員認證 Fail-Closed (`src/api/dependencies.py`)**：
   - `verify_admin_key` 調整為三態邏輯：有金鑰且比對通過放行、無金鑰但在開發模式放行、無金鑰且未啟用開發模式時拋出 `HTTPException(503)` 拒絕放行。
4. **FastAPI Lifespan 檢核 (`src/api/app.py`)**：
   - 透過 `@asynccontextmanager async def lifespan` 於伺服器啟動時呼叫 `check_auth_config()`，未設定金鑰且未開啟開發旗標時拋出 `AuthConfigError`，阻斷服務啟動。
   - 開發模式下於啟動日誌輸出繁體中文警告。
5. **啟動腳本整合 (`scripts/run_api_server.py`)**：
   - 新增 `--allow-no-auth` CLI 旗標。
   - 於 `main()` 中在啟動 Uvicorn 前執行 `check_auth_config()`，未合格時以結束碼 `2` 退出並輸出處置說明至 `stderr`。
   - 開發旗標啟用時同步寫入環境變數 `CLINICBRAIN_ALLOW_NO_AUTH=1`，確保 `--reload` 與多 worker 子行程設定一致。
6. **測試套件相容性保證 (`tests/conftest.py`, `tests/test_api_health.py`)**：
   - `conftest.py` 加入 autouse fixture `_default_allow_no_auth`，讓既有 158 個測試預設在開發模式放行，維持測試穩定性。
   - `test_api_health.py` 改寫並新增 503 fail-closed 與明確啟用開發模式之斷言。

---

## 驗證結果

- **未設定金鑰且無旗標測試**：
  `env -u CLINICBRAIN_ADMIN_API_KEY -u CLINICBRAIN_ALLOW_NO_AUTH python3 scripts/run_api_server.py --port 8791`
  - 結束碼為 `2`。
  - `stderr` 輸出繁體中文引導說明（含長隨機字串產生指令）。
  - 未啟動 Uvicorn 服務。
- **全量既有測試回歸**：
  - `python3 -m pytest -q`：`158 passed, 1 warning`（零失敗、零退化）。
