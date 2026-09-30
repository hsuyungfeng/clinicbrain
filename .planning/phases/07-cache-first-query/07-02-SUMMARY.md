# 07-02-SUMMARY: 快取統計聚合表與冪等遷移工具 (CACHE-03 資料層)

## 執行成果摘要

本階段已完成匿名快取統計資料表 `cache_stats` 的 Schema 規範、權威寫入與唯讀彙總函式、以及安全的資料庫遷移腳本：

1. **資料表 Schema 擴充 (`src/db/clinic_schema.sql`)**：
   - 於 `sync_logs` 之後、`Sample Data` 標記之前新增 `cache_stats` 資料表與 `idx_cache_stats_date` 索引。
   - 欄位結構：`id, clinic_id, stat_date, outcome, keyword, count, updated_at`。
   - 唯一鍵約制：`UNIQUE(clinic_id, stat_date, outcome, keyword)`。
   - 嚴格隱私性：絕無存放問句全文之文字欄位，僅存放聚合計數與日統計。

2. **單一權威寫入與唯讀彙總實作 (`src/query/cache_stats.py`)**：
   - `record_query_outcome`：
     - `clinic_id` 存在於 `clinic_info` 才記錄，否則填入空字串（防範透過標頭注入自由文字）。
     - `matched_keywords` 僅記錄存在於 `ROUTE_KEYWORD_VOCAB`（三類路由固定關鍵字）者，詞表外文字一律於寫入時拋棄。
     - 參數化 UPSERT 累加計數，單一交易自動 commit。
   - `get_cache_stats`：
     - 支援 `clinic_id` 與 `since_date` 動態篩選。
     - 僅執行 `SELECT` 查詢，完全相容於 `PRAGMA query_only = ON` 唯讀連線。
     - 正確計算 `hit`、`miss`、`total`、`hit_rate`（四捨五入至小數點後 4 位）與 `top_miss_keywords`。

3. **冪等遷移腳本 (`scripts/migrate_cache_stats.py`)**：
   - 支援 `--db`、`--dry-run`、`--confirm-prod-backup` CLI 參數。
   - 單一權威來源：直接自 `src/db/clinic_schema.sql` 擷取 DDL 語句，腳本內零重複硬編碼 DDL。
   - 防禦式安全：對正式庫 `clinic.db` 預設拒絕執行（退出碼 2），必須明確帶上 `--confirm-prod-backup` 旗標；拒絕分支先於任何 `sqlite3.connect` 連線。

4. **單元與遷移測試套件 (`tests/test_cache_stats.py`)**：
   - 共 18 個測試案例，涵蓋欄位結構、hit 累加、miss 與關鍵字記錄、全表文字掃描隱私驗證、clinic_id 校驗、唯讀連線相容性、資料不變性、正式庫連線前拒絕測試與 dry-run 測試，全數通過。

---

## ⚠️ 正式資料庫手動套用與注意事項

依安全設計，本執行計畫**嚴格禁止亦未對正式 `clinic.db` 執行任何遷移動作**。
當準備套用至正式資料庫時，請由管理員手動執行下列兩步驟：

```bash
# 步驟 1：建立正式庫日期備份
cp clinic.db clinic.db.bak-$(date +%Y%m%d)

# 步驟 2：明確帶上確認旗標套用遷移
python3 scripts/migrate_cache_stats.py --confirm-prod-backup
```

**已知限制與運作語意**：
1. **未遷移前之行為**：在正式庫執行上述遷移前，API 層的統計寫入將因找不到 `cache_stats` 資料表而失敗，但會被例外隔離機制忽略，不影響查詢回應（於 07-03 落實）；統計查詢端點將回傳 503 並提示執行遷移。
2. **hit_rate 統計語意**：`hit_rate = hit / (hit + miss)`。分子為短路命中次數，分母僅包含「有資格短路」之查詢（含營運關鍵字如營業時間、地址等問句因本質不短路，不計入 miss）。
3. **外部灌數限制**：由於自然語言查詢端點為公開開放端點，統計計數可能受外部請求影響，僅供診所營運熱門主題參考，非安全審計依據。

---

## 驗證結果

- `tests/test_cache_stats.py`: 18 passed
- 臨時目錄複本遷移驗證：`exit=0`、再次執行 `exit_again=0`（冪等驗證通過）。
- 正式庫未被寫入。
