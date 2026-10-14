# Plan 23-01 總結：安全網址政策、節流與受限 HTTPS 擷取器

## 執行成果

- **完成日期**：2026-10-14
- **成果狀態**：全部測試通過（28/28 passed），零外部依賴、純標準庫實作，符合所有安全與 TLS 驗證規範。
- **Commit**：`feat(scraper): 實作安全網址政策、節流與受限 HTTPS 擷取器 (Plan 23-01)`

## 產出檔案

1. `data/scraper/sources.json`：白名單條目（使用者確認之 `www.nu-vendome.com` 的 `/location-detail/` 前綴）。
2. `src/scraper/__init__.py`：模組進入點。
3. `src/scraper/policy.py`：
   - `load_allowlist`：載入白名單並建立主機索引。
   - `check_url_allowed`：協議（強制 https）、連接埠（僅 443）、憑證排除、主機與路徑前綴檢查。
   - `check_host_allowed`：主機名稱白名單檢查（供 robots.txt 判定）。
   - `is_public_address`：嚴格公網 IP 檢查（排除私有、迴圈、CGNAT 100.64.0.0/10、IPv4-mapped 等）。
   - `resolve_public_addresses`：A/AAAA 解析與全公網位址斷言。
   - `strip_url_for_storage`：清洗儲存用 URL，支援 `https://` 與 `fixture://`。
   - `DomainThrottle`：逐網域獨立計時節流器（預設 5.0 秒，下限 3.0 秒）。
   - `RobotsPolicy`：robots.txt 解析、快取（1 小時 TTL）與 UA token 匹配。
4. `src/scraper/fetch.py`：
   - `build_user_agent`：產生 `ClinicBrainSiteReader/0.1 (+https://doctor-toolbox.com/clinicBot)`。
   - `assert_tls_config`：強制 `check_hostname is True` 與 `verify_mode == ssl.CERT_REQUIRED`。
   - `_PinnedHTTPSConnection`：釘住已驗證 IP 之底層 HTTPS 連線，杜絕 DNS rebinding。
   - `fetch_page`：受限安全頁面擷取入口，支援重導向重檢、回應大小上限（2 MB）、超時處理與 `pinned_addresses`（CR-23-1 相容）。
5. `tests/conftest.py`：新增 autouse fixture `_block_outbound_network_for_scraper`，保證測試期間無真實外部網路連線。
6. `tests/test_scraper_policy.py`：10 項政策與 SSRF 測試。
7. `tests/test_scraper_fetch.py`：18 項受限擷取與釘住 IP 測試。

## 驗證指標

- `python3 -m pytest tests/test_scraper_*.py`：28 passed in 0.52s。
- 安全審查指令：`grep -rn --exclude-dir="__pycache__" "requests\|httpx\|bs4\|build_opener\|CERT_NONE\|_create_unverified_context\|check_hostname *= *False" src/scraper/` 結果為 0。
- 正式庫 `clinic.db`：SHA-256 維持 `0089ca28795fd0f0f2a41e9fa6b16f840ae794bfaf4e5597576410e9f0cf23db`，零變更零污染。
