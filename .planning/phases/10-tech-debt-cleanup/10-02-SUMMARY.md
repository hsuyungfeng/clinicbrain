# Phase 10 Plan 02 Summary: 移除孤兒設定 default_clinic_id（DEBT-02）

## 執行成果概述
本計畫（10-02）徹底清理未被讀取之孤兒設定 `default_clinic_id`，落實「clinic_id 必須明確傳入，不靜默查到別家診所」之安全原則（DEBT-02）：
1. **API 設定精簡 (`src/api/config.py`)**：
   - 移除 `default_clinic_id` 欄位與環境變數 `CLINICBRAIN_DEFAULT_CLINIC_ID` 預設值讀取。
   - 更新模組 docstring，明確指出查詢必須明確帶入 `clinic_id`（Path/Body 或 Header `X-Clinic-ID`），不暗示任何預設診所代碼。
2. **服務啟動 Banner 更新 (`scripts/run_api_server.py`)**：
   - 移除預設診所代碼列印，改為印出 `🏢 診所識別:       無預設診所，請求須帶 clinic_id 或 Header X-Clinic-ID`，保留 `--help` 與參數解析功能完整。
3. **Systemd 範本清理 (`clinicbrain-api.service`)**：
   - 移除 `Environment=CLINICBRAIN_DEFAULT_CLINIC_ID=3503190424` 這一行，僅修改 repo 根目錄範本，未碰觸實機 systemd 目錄。
4. **示範常數改名 (`src/clinic/custom_notes.py`)**：
   - 檔案底部示範用的 `DEFAULT_CLINIC_ID` 常數與引用更名為 `DEMO_CLINIC_ID`，與全專案 grep 守門原則一致，業務邏輯不變。
5. **架構邊界嚴格遵守**：
   - 依計畫未修改 `src/api/routes/query.py`、`src/query/router.py`、`src/query/faq_shortcut.py`、`src/api/dependencies.py`，保持現有路由行為。

## 測試覆蓋與驗證
- **新增與改寫測試**：
  - `tests/test_api_server_cli.py:test_cli_print_banner_output`：改寫以驗證輸出含「無預設診所」，且不含「預設診所代碼」或「default_clinic」。
  - `tests/test_api_query.py` 新增 5 個測試：
    - `test_config_has_no_default_clinic`：驗證 `APIConfig` 欄位不含預設診所屬性，環境變數亦無效果。
    - `test_get_query_special_missing_clinic_id_returns_400`：驗證 GET special 查詢未帶 Header 400。
    - `test_post_query_special_header_blank_clinic_id_returns_400`：驗證 POST special 查詢夾帶純空白 Header 400。
    - `test_body_clinic_id_takes_priority_over_header`：驗證 Body 優先於 Header 順序。
    - `test_handle_query_special_without_clinic_id_raises_value_error`：驗證底層 `handle_query` 在 special 缺少 `clinic_id` 時拋出 `ValueError`。
- **守門檢查全數通過**：
  - `tests/test_api_query.py`, `tests/test_api_server_cli.py`, `tests/test_custom_notes.py`, `tests/test_api_auth_enforcement.py` 共 44 測試全綠。
  - 全專案 grep 守門：搜尋 `default_clinic_id` 與 `DEFAULT_CLINIC_ID` 計數為 0（排除 .git, .planning, OriginalData, __pycache__, graphify-out, .pytest_cache, clinic.db*, AGENTS.md）。
  - `python3 -c "from src.api.config import config; print(hasattr(config,'default_clinic_id'))"` 輸出 `False`。
  - 正式庫 `clinic.db` SHA-256 驗證完全不變。
