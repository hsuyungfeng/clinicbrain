# Phase 48 獨立審查報告（Hermes Tester Report）

**專案**：clinicbrain — 診所臨床 PageIndex RAG 系統（Zhiyan Aesthetic Clinic）
**審查階段**：48-icd10-trend-gap-checker（ICD-10 趨勢缺口偵測與夜間批次預生成補強）
**審查身分**：獨立 Tester（比照 Phase 47 的 `47-HERMES-TESTER-REPORT.md` 模式）
**審查日期**：2026-11-16
**約束**：全程只讀審查。**未修改任何 `src/`、`scripts/`、`tests/` 程式碼；未寫入正式 `clinic.db`。** 所有查證皆為讀取原始碼簽名與執行既有模組之 pytest，探针與查證均未碰正式資料庫。

---

## 0. 審查範圍與讀取檔案

| 檔案 | 行數 / 大小 | 狀態 |
|---|---|---|
| `.planning/phases/48-icd10-trend-gap-checker/48-CONTEXT.md` | 2,053 chars | 已讀 |
| `.planning/phases/48-icd10-trend-gap-checker/48-RESEARCH.md` | 2,990 chars | 已讀 |
| `.planning/phases/48-icd10-trend-gap-checker/48-01-PLAN.md` | 3,977 chars | 已讀 |
| `.planning/phases/48-icd10-trend-gap-checker/48-02-PLAN.md` | 5,761 chars | 已讀 |

對照參考：`47-HERMES-TESTER-REPORT.md`（Phase 47 既有 tester 報告，用作結構與嚴謹度基準）。

---

## 1. 基線 pytest 結果（既有模組）

以下為計畫所依賴既有模組之對應測試，以 `.venv/bin/python -m pytest <files> -q -p no:cacheprovider` 執行（未改任何程式碼）：

| 測試檔 | 對應被測模組 | 結果 |
|---|---|---|
| `tests/test_nhi_index.py` | `src/query/nhi_index.py` | ✅ 含於 51 passed |
| `tests/test_search.py` | `src/query/search.py` (`escape_like`) | ✅ 含於 51 passed |
| `tests/test_patient_prefill_plan.py` | `src/batch/patient_prefill_plan.py` (`INTENT_TEMPLATES`) | ✅ 含於 51 passed |
| `tests/test_batch_faq_generator.py` | `src/batch/faq_generator.py` (`generate_topic_faqs`/`upsert_faqs`) | ✅ 含於 51 passed |
| `tests/test_soap_deid_parser.py` | `src/soap/deid.py` (`deidentify_text`) | ✅ 含於 48 passed |
| `tests/test_scraper_policy.py` | `src/scraper/policy.py` | ✅ 含於 48 passed |
| `tests/test_faq_review_soap.py` | `src/pageindex/faq_writer.py` / faq_review | ✅ 含於 48 passed |

**總計：99 passed，0 failed。** 全部既有被依賴模組基線全綠，未發現既有行為被破壞。

> 註：計畫提及的 `test_faq_writer.py` 在本專案並不存在；`faq_writer` 已透過 `test_batch_faq_generator.py` 與 `test_faq_review_soap.py` 涵蓋。`test_patient_prefill.py` 亦不存在，實際為 `test_patient_prefill_plan.py`（已跑）及 `test_patient_prefill_batch.py`/`test_patient_prefill_e2e.py`（同模組不同切面，未單跑但屬同一被測模組）。

---

## 2. 計畫引用符號查證（是否存在 + 介面相容）

逐符號查證結果（讀取原始碼簽名比對計畫调用方式）：

| 計畫引用符號 | 所在模組 : 函式 | 真實存在? | 實際簽名 | 相容? |
|---|---|---|---|---|
| `escape_like` | `src/query/search.py:41` | ✅ 是 | `escape_like(term: str) -> str` | ✅ 相容（回傳 LIKE 跳脫字串，配 `ESCAPE '\'`） |
| `search_nhi_catalog` | `src/query/nhi_index.py:24` | ✅ 是 | `search_nhi_catalog(conn, query, limit=5, system=None) -> List[Dict]` | ✅ 相容；plan 用 `conn, label, limit=1`，回傳 dict 含 `icd10` 欄位（line 47 確認） |
| `INTENT_TEMPLATES` | `src/batch/patient_prefill_plan.py:39` | ✅ 是 | `dict[str, str]`（5 個 key，含自驗證） | ✅ 相容（見 §4.2 確認） |
| `generate_topic_faqs` | `src/batch/faq_generator.py:223` | ✅ 是 | `generate_topic_faqs(conn, topic, llm_call) -> TopicGenResult` | ✅ 相容 |
| `existing_questions` | `src/batch/faq_generator.py:127` | ✅ 是 | `existing_questions(conn, clinic_id, topic_key, *, exclude_regen_marked=False) -> set[str]` | ✅ 相容 |
| `upsert_faqs` | `src/pageindex/faq_writer.py:37` | ✅ 是 | `upsert_faqs(conn, faqs, source_type, commit=True) -> tuple[int,int,int]` | ✅ 相容；`source_type='llm_generated'` 時自動 `review_status='pending'`（Fail-Closed） |
| `deidentify_text` | `src/soap/deid.py:82` | ✅ 是 | `deidentify_text(text: str) -> str` | ✅ 相容（內部已呼叫 `deep_mask_prices`） |
| `deep_mask_prices` | `src/api/routes/query.py:57` | ✅ 是 | `deep_mask_prices(obj: Any) -> Any` | ✅ 相容（遞迴清洗巢狀結構） |
| `visible_tree_sql` | `src/pageindex/tree_review.py:42` | ✅ 是 | `visible_tree_sql(conn) -> str` | ✅ 相容 |
| `validate_single_faq` | `src/ingestion/generate_faq.py:80` | ✅ 是 | `validate_single_faq(item: dict, *, check_dosage=False, require_doctor_warning=False) -> Tuple[bool, Optional[str]]` | ✅ 相容；回傳 `(is_valid, reason_if_invalid)`，與 plan 描述一致 |
| `to_traditional` | `src/ingestion/convert_chinese.py:36` | ✅ 是 | `to_traditional(text: str) -> str` | ✅ 相容 |
| policy 安全面（plan 稱「HTTPS/SSRF 防護」） | `src/scraper/policy.py` | ✅ 是（函式群） | `check_url_allowed`（強 HTTPS/443/白名單）、`check_host_allowed`、`is_public_address`、`resolve_public_addresses`（DNS+SSRF）、`strip_url_for_storage`（強 https/fixture://）、`DomainThrottle`、`RobotsPolicy`、`PolicyError`、`load_allowlist` | ⚠️ 精神相容，但 **plan 所指名稱 `validate_url_safety` 不存在**（見 §4.1） |

### ⚠️ 唯一未找到符號：`validate_url_safety`

- **位置**：`48-02-PLAN.md` Task 2（trend_fetcher 實作）line 52 明確寫道：「透過 `src/scraper/policy.py`（`validate_url_safety` / HTTPS / SSRF 防護）安全抓取」。
- **查證**：`src/scraper/policy.py` **沒有** `validate_url_safety` 這個符號（全模組仅 §1 所列函式/類別）。全域 `grep` 亦無任何 `def validate_url_safety`。
- **最接近的既有符號**：
  - `src/scraper/policy.py:check_url_allowed(url, allowlist)` —— 強制 HTTPS、443、白名單、禁止憑證（plan 描述的「HTTPS / 白名單」防護即此）。
  - `src/scraper/policy.py:resolve_public_addresses(host, resolver)` + `is_public_address(ip)` —— DNS 解析後斷言全公網 IP，即 plan 的「SSRF 防護」。
  - `src/ingestion/url_guard.py:validate_public_url` —— 名稱最接近（含 `validate_url`），但**不同模組**（`url_guard` 非 `scraper.policy`），且簽名/用途未讀取證實。
- **風險等級**：**P1（必須在動 Task 2 前修）**。implementer 需自行定義 `validate_url_safety(url, allowlist)` 為 `check_url_allowed` + `resolve_public_addresses` 的薄包裝，或把 plan 符號重映射到既有函式；並需補對應測試。

---

## 3. Plan ↔ Implementation 對照（Task 層級）

### 48-01 子計畫 1：`src/batch/patient_prefill_plan.py`
| Plan 聲明 | 實作查證 | 結論 |
|---|---|---|
| `INTENT_TEMPLATES` 5 個意圖：`what`/`suitable`/`risk`/`recovery`/`when_to_see_doctor` | line 39-45 確認為此 5 key | ✅ 符合 |
| 「自帶 `to_traditional()` + `validate_single_faq()` 自我驗證」 | `_self_validate_templates()` (line 48) 於**模組載入時**（line 75 `_self_validate_templates()`）執行，使用 `to_traditional` + `validate_single_faq`，不合規即 `raise RuntimeError` | ✅ **完全属实** |
| 意圖展開後問句全繁體、無數字、恰一問號 | line 56-71 強制檢驗 | ✅ 符合 |

### 48-01 子計畫 2：`src/query/nhi_index.py`
| Plan 聲明 | 實作查證 | 結論 |
|---|---|---|
| `search_nhi_catalog(conn, label, limit=1)` 回傳 dict 含 `icd10` 欄位 | line 24 簽名相容；line 46-47 SELECT 含 `c.icd10` | ✅ 符合 |

### 48-01 子計畫 3：`scripts/run_daily_patient_prefill.py`
- 全新排程腳本（`run_daily_patient_prefill(conn, *, dry_run)` 為 implementer 寫入）；依賴上游 `generate_topic_faqs` + `upsert_faqs`（皆已確認存在），無新符號缺口。

### 48-02 子計畫 1：`src/batch/gap_checker.py`
| Plan 聲明 | 實作查證 | 結論 |
|---|---|---|
| 缺口分類 `covered`/`partial`/`uncovered`（依 `topic_key`+`icd10` 比對 `faq_cache.question`） | 新邏輯，implementer 寫入 | 🆕 待寫 |
| `run_gap_check` 回傳 `GapCheckReport`（含 `covered`/`partial`/`uncovered`） | 新邏輯 | 🆕 待寫 |

### 48-02 子計畫 2：`src/batch/trend_fetcher.py`
| Plan 聲明 | 實作查證 | 結論 |
|---|---|---|
| `reference_from_tree(conn, tree_doc_id)` 取得已屏蔽價格 summary 作參考上下文 | **已存在**於 `faq_generator.reference_from_tree`（line 165-183），且已用 `visible_tree_sql` + `mask_prices` | ✅ **已有現成範本**，可直接複用 |
| `search_nhi_catalog` 供 ICD-10 對照 | 已確認 | ✅ 符合 |
| 安全抓取 `validate_url_safety`/HTTPS/SSRF | **符號不存在**（見 §4.1） | ⚠️ P1 待修 |
| 文字經 `to_traditional`/`deidentify_text`/`deep_mask_prices` 清洗 | 三者皆存在且簽名相容 | ✅ 符合（需注意 `deidentify_text` 需 `CLINICBRAIN_DEID_KEY` 金鑰，Fail-Closed；見 §4.3） |

### 48-02 子計畫 3：`scripts/run_daily_gap_check.py`
- 全新 CLI（`--db`/`--clinic-id`/`--icd-json`/`--dry-run`/`--json`）。`--dry-run` 不寫入、`--json` 透傳 `deep_mask_prices`（已確認），設計合理。

---

## 4. 獨立 tester 關鍵發現

### 4.1 未找到符號：`validate_url_safety` —— P1 必須修（主要發現）
- Plan 48-02 Task 2 把「HTTPS/SSRF 防護」掛在 `src/scraper/policy.py` 的 `validate_url_safety`，但该符号不存在。
- policy.py **精神**已提供 plan 所需防護：`check_url_allowed`（HTTPS/443/白名單/禁憑證）+ `resolve_public_addresses`/`is_public_address`（DNS 解析後斷言全公網、拒 private/loopback/link-local/reserved，即 SSRF 防護）+ `strip_url_for_storage`（storage-only，強 https 或 `fixture://`）+ `DomainThrottle`（≥3s 節流）+ `RobotsPolicy`。
- 建議 implementer 二選一：(a) 定義 `validate_url_safety(url, allowlist)` 薄包裝 `check_url_allowed` + `resolve_public_addresses`，(b) 直接把 plan 符號重映射成既有函式呼叫。**兩者皆需補測試**（含非 https 遭拒、private IP 遭拒、白名單不符遭拒）。
- 附帶：`url_guard.py:validate_public_url` 名稱最接近，但不同模組， implementer 選型時需釐清。

### 4.2 相容性極佳 / 已有可复用模式（正面）
- `faq_generator.reference_from_tree`（`visible_tree_sql` + `mask_prices` 取 summary）已是 48-01 Task 1 與 48-02 Task 3 的**現成範本**——plan 的「中轉參考」設計與之完全吻合，implementer 可直接借鏡，降低 Task 1/3 風險。
- `upsert_faqs` 對 `source_type='llm_generated'` 會自動把 `review_status` 設為 `'pending'`（Fail-Closed，faq_writer.py:55），為 48-02 Task 3 的「pending → 醫師審核 → 核發」流程提供可靠基礎，無需 implementer 自行維護審核狀態。
- `INTENT_TEMPLATES` 於 import 期強制自驗證，把非法模板擋在程式載入前，避免壞資料入庫 —— 這是 plan 48-01 Task 1 的一個安全亮點，tester 建議保留並擴大到 `test_patient_prefill_plan.py` 內（應已涵蓋）。

### 4.3 次要 / 非阻塞建議（供 implementer 參考）
1. **`deidentify_text` 的金鑰 Fail-Closed**：`deid.generate_patient_token` 在未設 `CLINICBRAIN_DEID_KEY`（或 fallback `CLINICBRAIN_ADMIN_API_KEY`）時拋 `DeidKeyError`。48-02 Task 2 若呼叫去識別化路徑，夜間批次環境須確保金鑰存在，否則整批中斷。建議 `run_daily_gap_check --dry-run` 明確報告金鑰狀態。
2. **clinic_rank 來源未定**：48-02 TrendTopic 含 `clinic_rank`（plan 言「按診所使用頻率排名前 3」）。`nhi_catalog_1_400` 本身**無 clinic_rank 欄位**（search_nhi_catalog 回傳的是索引欄位）。clinic_rank 應來自他處（如 `clinic_info`/用量統計/既有排序），implementer 需釐清其資料來源，避免誤解為 catalog 自有欄位。
3. **allowlist 來源**：`policy.load_allowlist(path)` 需 JSON 白名單檔（含 `allowed_domains`）。trend_fetcher 的 `allowlist_path` 實機來源 plan 未指定；`--dry-run` 預設不連網（plan 已註明），故 allowlist 檔可延後，但實機 mode 需提供。
4. **`strip_url_for_storage` 接受 `fixture://`**：對 trend_fetcher 測試友好（測試可用 fixture 檔模擬抓取），實機則限 https。建議在 `run_daily_gap_check` 的 `--json` 報告區分 source_kind（實抓 vs fixture）。
5. **`search_nhi_catalog` 的 `system` 參數**：plan 未傳 `system`（用預設 None，全系統搜尋）。若日後要西/中/牙分隔，需補傳。目前無害。

---

## 5. 結論

- **既有符號查證：12 / 13 確認存在且介面相容。** 唯一缺口為 `validate_url_safety`（plan 48-02 Task 2 引用，实际不存在於 `scraper/policy.py`）——歸 **P1**，implementer 需在動 Task 2 前定義薄包裝或重映射到 `check_url_allowed` + `resolve_public_addresses`，並補測試。
- **基線 pytest：99 passed，0 failed。** 全部被依賴既有模組（nhi_index、search/escape_like、patient_prefill/INTENT_TEMPLATES、faq_generator、faq_writer、deid、scraper/policy）基線全綠，無既有行為損壞。
- **Plan ↔ implementation 對照良好。** 48-01 三 Task 的既有符號全部到位；`reference_from_tree` 已成 48-02 Task 3 的现成範本；`upsert_faqs` 的 Fail-Closed pending 語意直接支撐 48-02 Task 3 審核流程。
- **總體評估：計畫對既有系統的依賴鏈健全，風險集中於 Task 2 的 URL 安全抓取符號。** 建議 implementer 優先澄清 §4.1（`validate_url_safety`）與 §4.3-2（`clinic_rank` 來源）後再展開實作。

---

## 附錄：查證命令記錄（全部為讀取 / 執行既有測試，未改程式碼、未寫正式 DB）
- `grep -n "def escape_like" src/query/search.py` → `41:def escape_like(term: str) -> str`
- `grep -n "def search_nhi_catalog" src/query/nhi_index.py` → `24`；SELECT 含 `c.icd10`（line 46）
- `grep -n "def upsert_faqs" src/pageindex/faq_writer.py` → `37`；回傳 `(inserted, updated, unchanged)`
- `grep -n "def deidentify_text" src/soap/deid.py` → `82`
- `grep -n "def deep_mask_prices" src/api/routes/query.py` → `57`
- `grep -n "def visible_tree_sql" src/pageindex/tree_review.py` → `42`
- `grep -n "def validate_single_faq" src/ingestion/generate_faq.py` → `80`（回傳 `Tuple[bool, Optional[str]]`）
- `grep -n "def to_traditional" src/ingestion/convert_chinese.py` → `36`
- `grep -rn "def validate_url_safety" src/` → **0 matches**
- `grep -nE "^def |^class " src/scraper/policy.py` → `load_allowlist/check_url_allowed/check_host_allowed/is_public_address/resolve_public_addresses/strip_url_for_storage/DomainThrottle/RobotsPolicy/PolicyError`
- `sed -n '39,75p' src/batch/patient_prefill_plan.py` → `INTENT_TEMPLATES` + `_self_validate_templates()` 於 import 期執行
- pytest（51）：`tests/test_nhi_index.py tests/test_search.py tests/test_patient_prefill_plan.py tests/test_batch_faq_generator.py` → `51 passed in 5.00s`
- pytest（48）：`tests/test_soap_deid_parser.py tests/test_scraper_policy.py tests/test_faq_review_soap.py` → `48 passed in 2.01s`
