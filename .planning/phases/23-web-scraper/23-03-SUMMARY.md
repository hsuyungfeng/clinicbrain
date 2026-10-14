# Plan 23-03 總結：批次編排、CLI 守門、操作手冊與端到端驗收

## 執行成果

- **完成日期**：2026-10-14
- **成果狀態**：全套網站擷取器測試通過（85/85 passed in 1.39s），涵蓋單元、CLI 守門與 E2E 完整生命週期。
- **Commit**：`feat(scraper): 實作批次編排、CLI 守門、操作手冊與端到端驗收 (Plan 23-03)`

## 產出檔案

1. `src/scraper/report.py`：
   - `path_hint(url)`：安全截取前兩段路徑，徹底剔除 query string、fragment 與憑證。
   - `UrlOutcome`：單一網址擷取結果，`to_dict()` 嚴格限定輸出白名單 keys（host, path_hint, status, reason, drafts_count, rejected_count, schema_drift, doctors_count, html_bytes），絕不外洩內文與醫師資訊。
   - `BatchReport`：批次報告與 JSON 序列化，`summary` 彙整 total, ok, failed, schema_drift, drafts_written, unchanged, skipped_by_policy, skipped_locked, fetched_count, total_html_bytes。
   - `safe_log_line(outcome)`：結構化安全日誌單行。
2. `src/scraper/runner.py`：
   - `check_ownership_confirmation`：擁有權授權確認檔檢驗（存在、格式、`confirmed_by_user=True`、`domain` 涵蓋白名單主機）。
   - `ScrapeOptions`：選項資料結構（10 碼 `clinic_id` 格式驗證，不設頁數截斷上限）。
   - `run_scrape_urls`：
     - 擁有權閘門：存在 https 網址時於任何網路與探測前檢驗。
     - 寫入模式抓取前探測鎖（D-C18）：`try_acquire` 探測，若持鎖則立即回報 `skipped_locked`（零網路請求）。
     - 第一階段完整抓取所有網址至記憶體清單（先抓後寫，單頁失敗不中斷批次）。
     - 第二階段寫入模式權威取鎖（持有至寫入完成釋放）。
     - 統一解析、抽取與草稿處理；每網址獨立交易（失敗 rollback 不影響其他網址）。
   - `scrape_one_url`：單筆便利函式。
3. `scripts/scrape_site.py`：
   - CLI 入口（結束碼 0/1/2 規範）。
   - 節流下限檢查（`< 3.0` 拒絕）。
   - 模式互斥檢查（`--fixture-dir` 與 `--live` 互斥，`--fixture-dir` 與網址清單互斥）。
   - 生產庫守門（`os.path.realpath` 比對加上 `os.path.samefile` 硬連結防護；寫入需 `--allow-prod-db` 與 `--confirm-prod-backup`）。
   - Dry-run 以 `mode=ro` URI（路徑經過 URL 編碼）開啟，提供 `schema_preflight` 預檢。
   - 寫入正式庫成功後提示 `clinic.db` 受 git 追蹤、勿直接 git add。
4. `docs/web-scraper.md`：
   - 完整操作手冊，包含架構、擁有權確認流程、網路防禦、探測鎖與權威鎖、dry-run 與正式庫寫入指引、醫師審核流程、改版告警處置與禁止事項。
   - 全文不含真實目標網址（通過 `nu-vendome` 零字樣檢驗）。
5. `tests/test_scraper_runner.py`：19 項報告結構與批次編排單元測試。
6. `tests/test_scraper_cli.py`：15 項 CLI 參數驗證、生產庫守門與離線模式單元測試。
7. `tests/test_scraper_e2e.py`：端到端整合測試（離線草稿入庫、審核前隱蔽、`set_review_status` 醫師核准流、冪等重跑）。

## 驗證指標

- `python3 -m pytest tests/test_scraper_*.py -q`：85 passed in 1.39s。
- `grep -rn "nu-vendome" docs/web-scraper.md src/scraper scripts/scrape_site.py | wc -l`：結果為 0。
- 正式庫 `clinic.db`：SHA-256 維持 `0089ca28795fd0f0f2a41e9fa6b16f840ae794bfaf4e5597576410e9f0cf23db`，零變更零污染。
