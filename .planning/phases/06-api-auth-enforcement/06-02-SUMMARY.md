# 06-02-SUMMARY: API 認證強制化自動化驗收與文件更新 (AUTH-01)

## 執行成果摘要

本階段已完成 API 認證強制化（AUTH-01）之全自動化驗收測試、systemd 範本註解說明與專案規範文件更新：

1. **自動化驗收測試套件 (`tests/test_api_auth_enforcement.py`)**：
   - 建立共 14 個測試案例（超出原本預估的 12 個，額外涵蓋審查備註之加強項）。
   - **成功標準 1（無金鑰拒絕啟動）**：
     - `test_script_refuses_without_key`：subprocess 測試腳本在無金鑰無旗標時以結束碼 `2` 退出，輸出繁體中文引導指引，無 Uvicorn 啟動日誌。
     - `test_script_blank_key_also_refuses`：純空白金鑰視為未設定，以結束碼 `2` 退出。
     - `test_main_refuses_in_process`：程序內呼叫 `main()` 觸發 `SystemExit(2)`。
     - `test_lifespan_refuses_without_key`：FastAPI `lifespan` 阻斷啟動，拋出 `AuthConfigError`。
     - `test_direct_uvicorn_refuses`：直接執行 `uvicorn src.api.app:app` 被 `lifespan` 阻斷退出，輸出含金鑰錯誤訊息。
   - **成功標準 2（開發旗標放行與警告）**：
     - `test_main_allow_no_auth_flag_warns_and_runs`：CLI `--allow-no-auth` 同步寫入環境變數與組態，輸出繁體中文警告，啟動 Uvicorn。
     - `test_main_env_flag_runs_without_cli_flag`：透過環境變數 `CLINICBRAIN_ALLOW_NO_AUTH=1` 啟動並輸出警告。
     - `test_main_with_key_no_warning`：設定金鑰時正常啟動，不印停用警告。
     - `test_lifespan_allows_dev_mode`：開發模式下 `lifespan` 順利通過，`/health` 回應 200。
     - `test_subprocess_env_flag_allows_subprocesses`：驗證子行程繼承 `CLINICBRAIN_ALLOW_NO_AUTH=1` 時評估為 `dev_no_auth`。
   - **成功標準 3（金鑰設定下端點權限劃分）**：
     - `test_sync_requires_key_when_configured`：同步端點缺少金鑰回 401、錯誤金鑰回 401、正確金鑰回 200。
     - `test_query_and_health_open_without_key`：查詢端點與 `/health` 維持公開開放，不需認證。
     - `test_verify_admin_key_503_when_misconfigured`：未設定金鑰且無開發旗標時，`verify_admin_key` 拋出 503 fail-closed。
   - **單元邏輯**：
     - `test_check_auth_config_unit`：純函式測試金鑰優先、空白金鑰與無金鑰拋錯邏輯。

2. **Systemd 服務範本註解更新 (`clinicbrain-api.service`)**：
   - 於 `[Service]` 區段補充繁體中文指引。
   - 明確說明本範本進版控不得含有金鑰明文，使用者部署時應透過 `systemctl --user edit clinicbrain-api` 加入環境變數。
   - **嚴格合規保證**：非註解行零金鑰明文、零 `systemctl --user enable` 指令，未代為重啟或啟用任何服務。

3. **專案規範文件更新 (`AGENTS.md`)**：
   - 新增 `2.7 API 認證強制化（Phase 06 新增）` 節，詳細記錄啟動雙重防線、開發旗標映射、同步與查詢端點權限劃分、測試慣例與未涵蓋規劃。
   - 於第 4 節目錄結構補充 `src/api/security.py` 條目。

4. **資料庫與測試隔離**：
   - 所有測試皆經由 `isolated_db_path` 或臨時檔案路徑執行，正式 `clinic.db` 零寫入、零污染。

---

## ⚠️ 重要部署與運作注意事項

- **正式服務重啟說明**：
  若目前本機環境已在背景常駐執行舊版 `clinicbrain-api` 服務，在下次重啟時將會因為未提供金鑰而啟動失敗（此為預期之 Fail-Closed 安全防護）。
  請使用者在需要重啟時：
  1. 使用 `systemctl --user edit clinicbrain-api` 於 override 檔案中加入：
     ```ini
     [Service]
     Environment="CLINICBRAIN_ADMIN_API_KEY=<請自行產生的長隨機字串>"
     ```
  2. 手動執行 `systemctl --user restart clinicbrain-api` 重啟服務。
  本執行計畫**完全未觸碰任何 systemctl 指令，亦未重啟任何常駐服務**。

---

## 驗證結果

- **全量測試套件回歸**：
  - `python3 -m pytest -q`：`172 passed, 1 warning`（158 既有測試 + 14 新增認證強制化測試全部通過）。
- **版本庫變更檢核**：
  - `git check-ignore clinic.db` 確認資料庫維持 gitignored，正式庫零變更。
