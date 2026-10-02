---
phase: 06-api-auth-enforcement
status: passed
verified: 2026-09-30
verifier: Claude（與執行者 antigravity 分離的獨立驗證，非執行者自我回報）
requirements: [AUTH-01]
---

# Phase 6 驗證報告：API 認證強制化

## 成功標準對照

| # | 標準 | 結果 | 證據 |
|---|---|---|---|
| 1 | 未設金鑰且無旗標時拒絕啟動並印出繁中說明 | ✅ | 實際執行 `env -u CLINICBRAIN_ADMIN_API_KEY python3 scripts/run_api_server.py --port 8765`：結束碼 **2**，stderr 為繁體中文處置說明 |
| 2 | 旗標可無金鑰啟動並印警告 | ✅ | 部署時以 `CLINICBRAIN_ALLOW_NO_AUTH=1` 啟動，服務日誌印出「管理員認證已停用」繁中警告 |
| 3 | 設金鑰後同步端點缺/錯金鑰 401、正確則成功 | ✅ | `tests/test_api_auth_enforcement.py`（含 `test_sync_requires_key_when_configured`）及既有 `test_sync_admin_api_key_authentication` |

## 驗證項目
- 全量測試：172 passed（158 既有 + 14 新增），獨立重跑確認。
- 無 `systemctl --user enable`；`clinicbrain-api.service` 非註解行無明文金鑰。
- 正式 `clinic.db` 筆數不變（40 FAQ／6 樹）。
- `verify_admin_key` 為 fail-closed：無金鑰且無旗標回 503；金鑰優先於旗標。

## 已知缺口（技術債）
- AUTH-03（systemd `EnvironmentFile`，權限 600）與 AUTH-04（`secrets.compare_digest`）依決策延後，目前比對仍用 `!=`。
- 查詢端點與 `/health` 維持公開（既定範圍）。
