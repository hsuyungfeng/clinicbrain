# Phase 48 實作驗收報告（Hermes E2E Report）

**專案**：clinicbrain — 診所臨床 PageIndex RAG 系統（Zhiyan Aesthetic Clinic）
**驗收階段**：48-icd10-trend-gap-checker（ICD-10 趋势缺口偵測與夜間批次預生成補強）
**驗收身分**：獨立 Tester（承接上階 `48-HERMES-TESTER-REPORT.md` 審查建議）
**驗收日期**：2026-11-16
**約束（嚴格遵守）**：全程**只讀**。**未修改任何 `src/`、`scripts/`、`tests/` 程式碼；未寫入正式 `clinic.db`。** 所有查證皆為讀原始碼、執行既有/新單元測試與**唯讀 URI 連線**（`file:clinic.db?mode=ro` + `PRAGMA query_only=ON`），探针與 CLI 皆為唯讀模式。

> 上階 tester 三項建議之落實追蹤（implementer 已全數採納）：
> - **P1 未找到符號 `validate_url_safety`** → ✅ 已於 `src/batch/gap_checker.py` 實作。
> - **DeidKeyError 處理** → ✅ 已於 `_sanitize_public_text` 回退 `deep_mask_prices`。
> - **clinic_rank 來源未定** → ✅ 已貫穿 `TrendTopic → GapItemReport` 並寫入 metadata。

---

## 0. 驗收範圍與程式版本

| 實作檔案 | 狀態 | 查證方式 |
|---|---|---|
| `src/soap/icd10_stats.py`（319 行） | ✅ 已讀 | 簽名逐行審查 |
| `src/batch/gap_checker.py`（22,018 字） | ✅ 已讀 | 簽名逐行審查 |
| `scripts/run_daily_gap_check.py`（2,798 字） | ✅ 已讀 | 簽名逐行審查 |
| `tests/test_icd10_stats.py`（201 行） | ✅ 已讀 | — |
| `tests/test_gap_checker.py`（190 行） | ✅ 已讀 | — |

`git diff --stat HEAD -- src scripts tests` = **空** → 未改任何既有源碼；`git status` 僅見新增 48 檔案（未追蹤）+ `ROADMAP.md`（implementer 改）。

---

## 1. 新單元測試（Phase 48 兩檔）

`.venv/bin/python -m pytest tests/test_icd10_stats.py tests/test_gap_checker.py -v` → **9 passed in 1.47s**

| 測試 | 涵蓋功能 | 結果 |
|---|---|---|
| `test_extract_icd10_codes_normalizes_and_deduplicates` | ICD-10 擷取正規化/去重、黑名單（B12） | ✅ PASSED |
| `test_rank_icd10_from_soap_and_missing_table` | soap 排行、缺失表安全回 `[]`、clinic 過濾 | ✅ PASSED |
| `test_rank_icd10_from_aggregated_merges_and_filters` | 聚合合併/過濾、負數無效排除 | ✅ PASSED |
| `test_align_icd10_exact_prefix_and_label_fallback` | 精確/3碼前綴/label 三層對齊、uncovered topic_key 生成 | ✅ PASSED |
| `test_get_top_clinic_diseases_combines_sources` | soap+aggregate 合併、`source='mixed'` | ✅ PASSED |
| `test_validate_url_safety_rejects_non_https_and_private_ip` | **P1 已修**：非 https、private IP（127.0.0.1）均拋 `PolicyError` | ✅ PASSED |
| `test_fetch_daily_health_trends_sanitizes_simplified_and_prices` | 簡繁轉換（預防→預防）、價格遮罩（500元→）、DeidKeyError 路徑 | ✅ PASSED |
| `test_check_topic_coverage_covered_partial_uncovered` | 三狀態切換、missing 計數、`<3字` LIKE fallback | ✅ PASSED |
| `test_run_gap_check_dry_run_and_pending_queue_write` | dry-run 不寫（count=0）、實寫入 5 pending、metadata 含 `clinic_rank`/`gap_status`/`needs_answer` | ✅ PASSED |

重點解讀：
- `test_validate_url_safety_...` 直接驗證上階 P1 已修復（`check_url_allowed` + `resolve_public_addresses` 薄包裝對非 https / private IP 阻斷）。
- `test_run_gap_check_...` 確認 **dry-run 全程不寫入**（`SELECT COUNT(*) FROM faq_cache == 0`），非 dry-run 則入庫 5 筆 `review_status='pending'`（Fail-Closed），`metadata.clinic_rank` 已標記（我的 clinic_rank 建議）。

---

## 2. 相關回歸測試（未破壞既有模組）

`.venv/bin/python -m pytest tests/test_nhi_index.py tests/test_search.py tests/test_patient_prefill_plan.py tests/test_batch_faq_generator.py tests/test_soap_deid_parser.py tests/test_scraper_policy.py tests/test_faq_review_soap.py -q` → **99 passed in 6.89s**

與上階 tester 基線一致（原 99 passed），Phase 48 未引入任何既有行為損壞。

---

## 3. CLI E2E 唯讀驗證

**指令**：`.venv/bin/python scripts/run_daily_gap_check.py --db clinic.db --clinic-id 3503190424 --dry-run --json`

| 檢查點 | 結果 |
|---|---|
| 結束碼 | ✅ `exit=0` |
| stderr | ✅ **空**（無異常/ traceback） |
| JSON 結構 | ✅ `total/covered/partial/uncovered/inserted_pending/dry_run/checked_at/items` 完整 |
| **clinic.db 唯讀** | ✅ **mtime 前後完全一致**（`2026-11-16 10:36:40.928530375`、`52080640` 字節，before == after） |
| `inserted_pending` | ✅ `0`（dry-run 確未寫入） |
| `total` | ⏺ `0`（見下方說明） |

### 3.1 `total=0` 為正確行為（非 bug）
實機查證（唯讀 URI）：`soap_records` = **0 筆**（`faq_cache`=1174、`page_index_trees`=91、`nhi_catalog_1_400`=400）。`run_daily_gap_check` 在**未傳 `--trend-url` 與 `--aggregated`**、且診所 soap 紀錄為空時，`get_top_clinic_diseases(...)` 回 `[]`，故 `run_gap_check` 安全回傳 empty report（`total=0`）。此與上階 `test_run_gap_check` 給定 `aggregated_icd10` 即產出 topic 的路徑一致，屬資料面而非程式面問題。

### 3.2 唯讀 E2E 對齊真實目錄（補充驗證）
以 `nhi_catalog_1_400`（400 筆，含 icd10）作聚合輸入、`align_icd10_with_nhi_catalog` 對齊正式庫（**唯讀**）：
- **20/20 matched=True**，`clinic_rank` 1–20 連續、`topic_key`（如 `nhi-w001-j06-9`）、`system` 全對應正確。
- `get_top_clinic_diseases(clinic_id="3503190424")` = `0`，與 CLI 完全一致，佐證 soap_records 為空是 `total=0` 根因。

---

## 4. 程式碼面審查（源碼逐行）

### 4.1 上階三建議之落實（全部符合）
| 上階建議 | 源碼落點 | 符合度 |
|---|---|---|
| P1 `validate_url_safety` | `gap_checker.validate_url_safety`（line 116-139）：`check_url_allowed(url, effective_allowlist)` + `resolve_public_addresses(host, resolver)`；default `{"open": True}` allowlist，免白名單檔 | ✅ 完整 |
| DeidKeyError | `_sanitize_public_text`（line 363-411）：`try: deidentify_text(...)` → `except DeidKeyError: return deep_mask_prices(...)` | ✅ 完整 |
| clinic_rank 來源 | `TrendTopic.clinic_rank`（line 63）+ `run_gap_check` 傳入（line 308/358）+ `GapItemReport.clinic_rank`（line 98）+ `metadata.clinic_rank`（line 373） | ✅ 完整 |

### 4.2 Fail-Closed 審核管道
- `run_gap_check` 寫庫走 `upsert_faqs(conn, pending_rows, source_type="llm_generated")`（line 378）→ `faq_writer.upsert_faqs` 自動把 `review_status` 設為 `pending`（承接上階確認）。
- 寫入僅 `if not dry_run and pending_rows`（line 378），dry-run 絕對不碰寫入路徑。

### 4.3 資料面安全
- `_sanitize_public_text` 三重清洗：`to_traditional` → `deep_mask_prices` → `deidentify_text`（含簡繁、價格、PII）。
- `_strip_rss_tags`、`_slugify_title`、`_merge_clinic_and_trend_topics` 結構清晰。
- CLI：`--db/clinic-id` 必填、`--dry-run`（預設 True）、`--json`（透傳 `deep_mask_prices`）、`--since-days`、`--limit`、`--trend-url`（可選）、`--list-trends`（預設 False）；連線為 `sqlite3.connect(db, timeout=30, check_same_thread=False)`，唯讀模式執行。

---

## 5. 獨立 tester 次要觀察（非阻塞）

1. **`_slugify_title` 用 Python 內建 `abs(hash(title))`**：str hash 具 process-level randomization，故 web trend 之 `topic_key` 每次執行不穩定（clinic_icd10 topic 則用 nhi 固定 `topic_key`，不受影響）。對本次 CLI（soap 空、無 trend-url）無感；但若日後靠 web slug 跨 run 去重，建議改用穩定 hash（如 `hashlib.sha256`）。**影響低，列為建議。**
2. **`run_gap_check` 未顯式 `commit()`**：非 dry-run 寫入依賴 `upsert_faqs` 內部 `commit=True`（line 378）持久化；CLI 僅在 `finally` 關閉連線。功能正確，但建議 implementer 於 CLI 加 `conn.commit()` 使責任明確（本次 dry-run 不觸及）。**影響低。**
3. **`check_topic_coverage` 的 FTS review_clause 字串替換**（`review_status.replace('review_status','c.review_status')`）功能正確但稍顯隱晦；可加註解說明 `review_clause` 來自外部。**風格建議。**
4. **`get_top_clinic_diseases(3503190424)=0`** 反映正式庫 `soap_records` 目前為空——此為 Phase 48 夜間批次/資料匯入前的自然狀態。待 soap_records 有資料或傳入 `--aggregated`/`--trend-url` 後，gap 盤點即可產出實際 coverage。**非 bug。**

---

## 6. 結論

**驗收通過（ACCEPT）。**

- **上階三項審查建議全部落實**：`validate_url_safety`（P1）、`DeidKeyError` 處理、`clinic_rank` 標記均已進源碼且有對應測試涵蓋。
- **單元測試 9/9 全通過**（含 P1 阻斷、簡繁/價格/PII 清洗、covered/partial/uncovered 狀態機、dry-run 不寫 + pending 入庫）。
- **回歸測試 99 passed**，未破壞既有模組。
- **CLI E2E 唯讀驗證通過**：`--dry-run --json` exit=0、無 stderr、JSON 完整；**clinic.db mtime 前後一致證明未寫入**；`total=0` 係正式庫 soap_records 為空的正確行為（已唯讀查證）。
- **對真實 400 筆目錄的對齊 E2E 通過**：20/20 matched，`clinic_rank`/`topic_key` 正確。
- **全程未修改任何 src/scripts/tests**（`git diff` 為空），未寫正式 clinic.db。
- 次要觀察（`_slugify_title` hash randomization、明確 commit）列於 §5，**皆非阻塞**。

**建議 implementer**：待 soap_records 匯入資料或夜間批次接入後，以相同 CLI 指令（去掉 `--dry-run` 或傳入 `--aggregated`/`--trend-url`）做一次有資料的 end-to-end 驗證；本次唯讀模式已證明 machinery 健全。

---

## 附錄：查證命令記錄（全部唯讀，未改程式碼、未寫正式 DB）
- `.venv/bin/python -m pytest tests/test_icd10_stats.py tests/test_gap_checker.py -v` → `9 passed in 1.47s`
- `.venv/bin/python -m pytest <7 regression files> -q` → `99 passed in 6.89s`
- `.venv/bin/python scripts/run_daily_gap_check.py --db clinic.db --clinic-id 3503190424 --dry-run --json` → exit=0、空 stderr、JSON `total=0/inserted_pending=0/dry_run=True`
- `stat clinic.db` before=`2026-11-16 10:36:40.928530375 52080640`，after=`2026-11-16 10:36:40.928530375 52080640`（**一致 → 唯讀**）
- 唯讀 URI 查證：`soap_records=0` / `faq_cache=1174` / `page_index_trees=91` / `nhi_catalog_1_400=400`
- 唯讀 E2E：`align_icd10_with_nhi_catalog(nhi前20)` → `20/20 matched`，`clinic_rank` 1–20 正確；`get_top_clinic_diseases(3503190424)=0`
- `git diff --stat HEAD -- src scripts tests` = 空（未改既有源碼）
