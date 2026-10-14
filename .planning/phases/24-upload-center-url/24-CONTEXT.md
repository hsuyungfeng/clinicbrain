# Phase 24 CONTEXT：上傳中心增強（名稱欄位與網址解析選項）

> 本文件由 gsd-planner 依 `24-PRD.md`、ROADMAP Phase 24、`23-PRD.md`、`23-CONTEXT.md` 與 Phase 23 最新計畫（23-01／23-02／23-03）產出。
> 修訂版號：**rev-3**（2026-10-14，依檢查員阻擋項修正）。rev-2 之 D-05、D-13、D-15、D-17 與 CR 表已被本版取代，以本版為準。
> 24-PRD 的需求 R1–R5 視為 locked decisions（下列 D-01 至 D-21 為實作層落地決策）。

## 現況（已讀程式碼確認）

- `src/api/routes/admin.py` `upload_admin_file`（`POST /api/v1/admin/upload`，為 **`async def`**，定義於第 112 行）：
  - 副檔名 `.docx/.xlsx/.pdf`、15MB（`MAX_FILE_SIZE`）、檔頭魔術位元組、`clinic_info` 存在性（404）。
  - 主題鍵現況為 `doc_topic = Path(filename).stem[:80]`，`topic_key = f"doc-{doc_topic}"`；同名檔以相同 `(clinic_id, topic_key, question)` 互相覆蓋（既有行為，PRD 已知限制）。
  - 內文管線：`to_traditional` → `deidentify_text` → `deep_mask_prices` → 以空行切段 → `_Q_PREFIXES` 判斷問答 → 無問答者以 `【診所文件】{doc_topic} - 指示 N` 為題 → `validate_single_faq` 四層驗證 → `upsert_faqs(source_type="web_upload")`（審核閘門來源，恆 `pending`）。
  - `preview_only` 為 `Form(False)`；預覽回傳 `faqs_preview`，不寫庫。寫入 `RuntimeError`（未遷移審核欄位）回 503。
- `src/pageindex/faq_review.py`：`has_review_status(conn)`（第 32 行）、`has_metadata_column(conn)`（第 40 行）、`REVIEW_GATED_SOURCES`（第 51 行）。`src/pageindex/faq_writer.py:29` 亦有 `has_metadata_column`。
- `src/web/static/app.js`：`// 上傳佇列`（第 705 行）與 `// 6. SOAP 瀏覽`（第 904 行）為既有靜態測試切片標記；`addUploadFiles`（第 717 行）、`renderUploadQueue`（第 741 行）、`initUploadSection`（第 790 行）。
- **Phase 23 尚未實作**：`src/scraper/`、`data/scraper/` 目前不存在（已 `ls` 確認）。Phase 24 所有 Phase 23 相依皆須於 Phase 23 實作後以 grep 與 contract test 確認。
- 靜態測試慣例：`tests/test_web_ui_v2.py::test_upload_center_supports_multi_file_and_folder` 以字串切片檢查無 `innerHTML|insertAdjacentHTML|document.write|outerHTML|eval(`。新程式碼必須落在此切片區間內。
- 既有 fixture：`tests/conftest.py` 的 `isolated_db_path`（隔離複本）；`tests/test_admin_api.py` 的 `client` 與 `_upload` helper。
- 去識別化：`src/soap/deid.py:deidentify_text`、`is_safe_identifier`；價格：`src/api/routes/query.py:deep_mask_prices`（第 57 行）；簡轉繁：`src/ingestion/convert_chinese.py:to_traditional`。

## Decisions

### 名稱欄位（R1）

- **D-01 名稱欄位語意（檔案模式）**：`/upload` 新增選填 `name: Optional[str] = Form(None)`。
  - 未提供或空白 → 行為與現況**逐位元相同**：`doc_topic = Path(filename).stem[:80]`（向後相容，PRD「舊行為保留為預設值」）。
  - 提供 → `doc_topic = name`（已驗證），`topic_key = f"doc-{name}"`，佔位題 `【診所文件】{name} - 指示 N` 同步使用 `name`。
- **D-02 名稱驗證（R1 安全）**：共用函式 `validate_display_name(raw) -> Optional[str]`：
  - NFKC 正規化後去頭尾空白；空字串回 `None`；長度 > 80 字元 → 400。
  - 字集白名單：CJK 統一表意文字、英數、空白、`-_·（）()[]`；控制字元、換行、`/ \ ? # % < > " ' ; \`` 與其他字元 → 400。
  - `deidentify_text(name) != name`（疑似身分證、電話、病患姓名標籤）或 `deep_mask_prices(name) != name`（含金額數字）→ 400。
  - 錯誤訊息為固定繁體中文字串，**不回顯**名稱原文。
- **D-03 同名處理（R4）**：名稱為使用者指定時，同一主題下仍以既有 `(clinic_id, topic_key, question)` UNIQUE 規則覆寫。未填名稱的同檔名重傳維持舊行為（覆寫同題、回 `updated`），由回歸測試鎖定（24-01 Task 3）。**批量上傳**（多檔）UI 規定名稱只在單檔佇列可編輯（見 D-12），多檔一律不送 `name`、自動帶檔名；同檔名（不含副檔名）於前端只收第一個，因後端以檔名為主題鍵。批量行為由 24-01 Task 3（後端逐檔獨立、單檔失敗隔離、同名覆寫）與 24-03 Task 2（前端規則，node 行為測試）共同鎖定。

### 網址解析（R2、R3、R5）

- **D-04 獨立端點**：新增 `POST /api/v1/admin/upload-url`，Form：`url`（預設 `""`）、`clinic_id`、`name`（預設 `""`，網址模式必填，空白 → 400）、`target`（預設 `"faq"`，非 `faq` → 400）、`preview_only`。**以 `def`（同步）實作**，因擷取含節流 sleep 與阻塞 I/O，不得為 `async def`。預設值為空字串，使缺漏欄位由端點自身回 400，而非 FastAPI 422 回顯。不改動 `/upload` 檔案路徑。
- **D-05 SSRF 與擷取把關（分層，rev-3）**：
  - 第一層（Phase 24，`src/ingestion/url_guard.py:validate_public_url`）：
    - scheme **僅 `https`**（rev-3 移除 localhost 測試旗標，見 D-22）。
    - 無 userinfo；**port 未指定或 443**（與 Phase 23 D-C5 一致，CR-23-4 未採納）。
    - 長度 ≤ 2048、主機非空。
    - 位址判定**不另立規則**：呼叫 Phase 23 `src/scraper/policy.py:resolve_public_addresses(host, resolver=...)`，其內部以 `is_public_address`（`is_global`、CGNAT、IPv4-mapped 解開）判定（CR-23-3，單一來源）。PolicyError → 400。
    - 回傳 `ValidatedUrl`（含已驗證 IP 集合 `addresses`）。**本層不含網域白名單**。
  - 第二層（Phase 23，權威）：所有擷取經 Phase 23 `fetch_page(allowlist=…, robots=…, throttle=…)`。白名單、robots.txt、節流、每一跳重新導向之重驗皆由 Phase 23 執行。Phase 24 **不得**繞過白名單；`nu-vendome.com` 之白名單啟用屬 Phase 23 `data/scraper/sources.json` 範圍，Phase 24 不修改該檔。
  - 固定 IP（DNS rebinding，見 D-17）：本版宣稱的固定 IP 保證**依賴 Phase 23 CR-23-1**（`fetch_page` 新增 `pinned_addresses`）。未實作前 Phase 24 **不得**宣稱此保證。
- **D-06 預覽與寫入（R3）**：`preview_only` 語意與 `/upload` 完全相同——`True` 回傳 `faqs_preview` 且不寫庫；`False` 以 `web_upload` 寫入 `pending`。
- **D-07 來源溯源（rev-3，與 Phase 23 D-C3 對齊）**：URL 模式寫入的 FAQ `metadata` 為 JSON：
  `{"origin":"web_scrape","source_url":<原始請求 URL 去除 query、fragment、userinfo 之結果，使用 Phase 23 strip_url_for_storage>,"fetched_at":<ISO 8601 UTC，取自 FetchResult.fetched_at>,"schema_version":"1","extracted":{"institution_name":<S>,"address":<S>,"phone":<S>,"business_hours":<S>}}`，其中 `S(x) = deep_mask_prices(deidentify_text(to_traditional(x)))`。
  - `extracted` 改為四鍵（rev-2 缺 `business_hours`，rev-3 與 Phase 23 D-C3 對齊，記入 SUMMARY）。
  - `source_url` 一律以**原始請求 URL** 為準，不採重導向終點，避免終點 query 外洩。
  - 電話**不豁免**遮蔽（見 D-18）。
  - `doctors` 不寫入 metadata（較 Phase 23 D-C3 嚴格，為有意偏離，記入 SUMMARY）。
- **D-08 寫入前置條件（Fail-Closed 溯源）**：`preview_only=false` 且 `has_metadata_column(conn)` 為假 → 503，且**於任何擷取請求之前**即中止。
- **D-09 Phase 23 介面契約（rev-3 以 Phase 23 計畫實際介面為準）**：
  - Phase 24 直接使用 Phase 23 的 `ExtractedClinicPage`（`src/scraper/extract.py`）與 `FetchResult`（`src/scraper/fetch.py`）；不再定義 Phase 24 專屬頁面型別。
  - 唯一適配器 `src/pageindex/web_source_adapter.py`：`fetch_clinic_page(url, *, deps, pinned_addresses=None) -> UrlPageResult`，內部呼叫 `fetch_page` 與 `extract_clinic_page`，不做任何 HTTP、不寫庫、不使用 logger。
  - 失敗以 `UrlFetchError(reason)` 表達，reason 取自 Phase 23 `FetchResult.reason`（不含訊息文字）。
  - **注入點（rev-3）**：Phase 23 `fetch_page` 的注入參數為 `http_get`（假 HTTP 實作）、`resolver`（DNS）、`connector`、`ssl_context`；**沒有 `opener`**（Phase 23 已移除 urllib opener，見 23-CONTEXT D-C4 修正）。Phase 24 之 `UrlFetchDeps` 以 `http_get` 與 `resolver` 欄位對齊之。
- **D-10 草稿內容範圍**：
  - 送入 `_text_to_faq_drafts` 的 `raw_text` **只包含**服務項目與營業時間（`build_service_text`）。機構名稱、地址、電話、醫師姓名**不得**進入 `raw_text`，亦不得進入答案。
  - 機構身分資訊只存在於 metadata（D-07）。
  - 身分洩漏檢查：機構名稱、地址、電話之原始值與其 `to_traditional` 版本若出現於任何 faq 的 question 或 answer，該 faq 剔除並計入 `rejected_paragraphs`（縱深防禦）。
  - schema 缺必填欄位（`ExtractedClinicPage.is_usable()` 為假：機構名稱或服務項目缺失）→ **422**，不產生任何草稿、不寫庫（與 Phase 23 D-C10 一致）。
  - 非必要欄位（address、phone、business_hours、doctors）缺漏不阻擋，於回應 `missing_fields` 列出，供 UI 顯示「解析不完整」。
  - 來源 `source_type` 為 `web_upload`，**不得**標記為 `clinic_upload`（Phase 23 D-RISK-3）。
- **D-11 管線重構**：將 `upload_admin_file` 內第 4–5 步抽為 `_text_to_faq_drafts(raw_text, topic, clinic_id) -> (faqs, paragraphs_count, rejected_count)`，檔案與 URL 兩端共用。**改動前須先取得 golden 基準**（D-19）。
- **D-12 UI 行為**：
  - 「提煉與解析目標」下方新增來源切換 radio `uploadSource`（`file`／`url`，預設 `file`）。
  - `url` 模式：隱藏拖曳區與清單，顯示 `uploadUrl`（`type="url"`）；送出改呼叫 `/api/v1/admin/upload-url`；沿用 `chkPreviewOnly`。
  - 名稱欄位 `uploadName`：`file` 模式單檔時可編輯（預設帶入檔名 stem，清空即採舊行為）；多檔時唯讀並顯示「多檔將自動以檔名命名」；`url` 模式必填。
  - `uploadTarget=tree` 時 `url` radio 停用並提示「網站解析目前僅支援常見問答 FAQ」；後端亦以 `target` 欄位強制拒絕（D-04）。
  - 所有伺服器回傳與使用者輸入一律以 `textContent`／`value` 寫入；`missing_fields` 經固定中文對照表轉換，不顯示伺服器字串。
- **D-13 錯誤映射（rev-3，移除聯絡方式 503 列，新增 bad_allowlist 與 http_status）**：

  | 情境 | HTTP | detail（固定） |
  |---|---|---|
  | clinic_id 不存在 | 404 | 既有 /upload 訊息 |
  | target 非 faq | 400 | 網址解析目前僅支援常見問答 FAQ 草稿 |
  | name 驗證失敗或空白 | 400 | 24-01 固定訊息 |
  | URL 格式、scheme、userinfo、port、非公網位址（validate_public_url） | 400 | 網址不允許解析（僅接受已授權之公開 https 網址） |
  | Phase 23 policy：not_allowlisted、scheme、port、credentials、private_address、bad_url、too_many_redirects | 400 | 同上 |
  | robots.txt 不允許（robots_denied） | 403 | 該網站之 robots.txt 不允許擷取 |
  | 必填欄位缺失（schema_drift） | 422 | 網站內容無法解析（必要欄位缺失，疑似網站改版），未產生草稿 |
  | metadata 欄位未遷移且寫入模式 | 503 | 資料庫尚未完成 metadata 欄位遷移，暫無法寫入網址來源草稿 |
  | Phase 23 白名單檔無法讀取（bad_allowlist） | 503 | 網站擷取器白名單設定無法讀取 |
  | Phase 23 未就緒（NotImplementedError／ImportError） | 503 | 網站擷取器尚未就緒 |
  | 同步擷取進行中（D-14） | 429 | 網站擷取進行中，請稍後再試 |
  | 網路、逾時、content-type、超過 2 MB、http_status（非 200 且非重導向）、unexpected、其他未知 | 502 | 網站擷取失敗，請稍後再試 |

  所有錯誤均不回傳例外內容、URL、主機或 IP。
- **D-14 並行、單例與日誌**：
  - 模組層級 `_URL_FETCH_LOCK`（`threading.Lock`），非阻塞取得，忙碌回 429。理由：Phase 23 節流為單執行緒循序擷取，且 `DomainThrottle` 為行程內狀態。
  - **節流與 robots 快取為行程內單例**（rev-3 新增）：`web_source_adapter.py` 以模組層級變數持有單一 `DomainThrottle` 與單一 `RobotsPolicy`（`get_shared_throttle()`、`get_shared_robots()`），跨請求共用；若每次請求新建，節流間隔將無法跨請求生效。
  - **統一日誌規則**：URL 模式端點**不產生任何日誌行**。`url_guard.py`、`web_source_adapter.py` 與端點亦無任何 logger 呼叫。唯一允許記錄網域層級資訊者為 Phase 23 CLI 的 runner（`safe_log_line`）。
  - 連接埠規則：{443}（與 Phase 23 D-C5 一致）。
- **D-15 聯絡方式（rev-3 取代 rev-2）**：User-Agent 固定為 Phase 23 `build_user_agent()` 之無參數回傳值 `ClinicBrainSiteReader/0.1 (+https://doctor-toolbox.com/clinicBot)`。**不讀取任何環境變數**，**不設定 `CLINICBRAIN_SCRAPER_CONTACT`**，未設定不會回 503。
- **D-16 合規檢驗單一來源**：URL 模式草稿不另立合規規則，全部經 `_text_to_faq_drafts`（含 `validate_single_faq`、價格遮蔽、去識別化）。Phase 23 的 `build_faq_drafts` 不被本 phase 呼叫，避免兩條草稿產生路徑；差異（題目樣式、topic_key 形式）記入 SUMMARY。
- **D-17 DNS rebinding 處置（rev-3，待使用者書面確認）**：
  - 預設方案：Phase 24 預檢所得之 `addresses` 以 `pinned_addresses` 傳入 `fetch_page`，**依賴 CR-23-1**。
  - 若 CR-23-1 未採納：Phase 24 **不得**宣稱固定 IP；殘餘風險為「Phase 24 預檢解析」與「實際連線解析」可能不同。**Phase 23 每一跳仍對其本次實際解析之位址執行 `is_global` 判定並釘住該次結果**，因此內網位址仍不可達（此為既有防線，不是 rev-2 宣稱的保證）。殘餘風險須使用者書面接受，並於 24-02 SUMMARY 記錄。
- **D-18 電話遮蔽（已定案）**：使用者確認維持遮蔽、不豁免。本 phase 中電話只存在於 metadata，且必為遮蔽後字串。
- **D-19 golden 基準順序**：24-01 Task 1 的第一步為 golden 擷取，必須在任何 `admin.py` 修改之前執行，並以獨立 commit 提交 `tests/fixtures/upload_pipeline_golden.json`。
- **D-20 回歸：未填名稱之同名檔覆寫**：24-01 Task 3 新增 `test_same_filename_no_name_overwrites_legacy`。
- **D-21 requirement ID**：`24-R1`…`24-R5` 暫作為 plan 的 `requirements` 欄位（ROADMAP Phase 24 未列 REQ-ID）。**尚未回寫 `.planning/REQUIREMENTS.md`**，列為待辦。
- **D-22 localhost 測試旗標（rev-3 刪除）**：`CLINICBRAIN_URL_ALLOW_LOCALHOST` 不存在。CR-23-2 未採納，故 Phase 24 不實作任何 localhost 例外；`http://localhost` 與 `https://localhost` 皆於 validate_public_url 拒絕。本 phase 的離線測試改用 Phase 23 的離線 fixture 與注入之 `http_get`／`resolver`（見 D-23）。
- **D-23 注入點與測試隔離（rev-3 新增）**：
  - **唯一注入點**：`src/api/routes/admin.py:get_url_fetch_deps`（回傳 `UrlFetchDeps`，欄位含 `resolver` 與 `http_get`）。`get_url_resolver` 不存在；validate_public_url 與 fetch_page 皆使用 `deps.resolver`。測試只覆寫 `get_url_fetch_deps` 一個依賴。
  - 測試不得 monkeypatch `socket` 模組。網路與 DNS 防護由 Phase 23 `tests/conftest.py` 的 autouse fixture 負責（非 loopback 之 socket 與 getaddrinfo 會 raise RuntimeError）。Phase 24 測試依賴此 fixture 存在（contract test 確認）。
  - 端點內之 `fetch_clinic_page` 可被 monkeypatch 於部分「端點語意」測試（例如 fetched_at 固定）；但離線流程測試須走真實 `fetch_clinic_page` → `fetch_page`，僅替換 `http_get`。

## 跨 Phase 變更請求（rev-3，須 Phase 23 採納）

| 編號 | 內容 | 採納狀態 | 對 Phase 23 的要求 | 理由 | 未採納之降級 |
|---|---|---|---|---|---|
| CR-23-1 | `fetch_page` 新增 `pinned_addresses: tuple[str, ...] \| None = None`（可選）。語意：套用於 host 與原始請求 host 相同之請求（robots 與原始頁面）；連線目標為 `pinned_addresses[0]`，每個 pinned IP 仍須通過 `is_public_address`，否則 `private_address`；SNI／Host 維持原主機名；**跨 host 之重導向每跳仍重新解析並驗證**；白名單與 robots 檢查不因 pinned 而略過 | **部分採納**：Phase 23 計畫文字目前無此參數，須 Phase 23 新增 | 新增參數與上述語意；新增 contract test（見 24-02 Task 2 a） | DNS rebinding 預設防線（D-17）；讓 Phase 24 預檢與實際連線使用同一組已驗證 IP | 僅能依 D-17 降級：Phase 24 不宣稱固定 IP；Phase 23 每跳 `is_global` 與釘住本次解析仍生效；殘餘風險需使用者書面接受 |
| CR-23-2 | `check_url_allowed` 新增 `allow_localhost_http`（測試用）以放行 localhost | **未採納** | 無 | 使用者決定刪除 localhost 測試旗標 | 不適用；Phase 24 刪除所有 localhost 旗標與相關測試，改用 Phase 23 離線 fixture（D-22、D-23） |
| CR-23-3 | 公網判定以 `not ipaddress.ip_address(x).is_global` 為準（含 CGNAT 100.64.0.0/10），取代 `is_private`／`is_reserved` 組合 | **已採納**：Phase 23 23-01 Task 1 之 `is_public_address` 計畫文字已以 `addr.is_global` 為準並明確排除 CGNAT | 實作時維持 `is_public_address` 為唯一位址判定函式，Phase 24 不另立判定 | 與 Phase 24 D-05 一致；單一來源 | 不適用 |
| CR-23-4 | 連接埠允許集合改為 {443, 80} | **未採納** | 無，維持 Phase 23 D-C5 之 {443} | 使用者決定：https 搭配 80 為非標準組合，不允許 | 不適用；Phase 24 之 port 規則為 {443}（24-02 Task 1） |

**前置條件（阻塞）**：
- 24-01 獨立，可先行。
- 24-02 **只在 Phase 23 的 23-01、23-02、23-03 實作完成，且 CR-23-1 與 CR-23-3 已實作後**才可執行。CR-23-2、CR-23-4 不影響執行。
- 24-03 依賴 24-01 與 24-02。

## Phase 23 實際介面快照（以 23-01／23-02／23-03 計畫文字為準；執行前以 grep 再確認）

- `src/scraper/policy.py`（23-01）：`PolicyError(reason)`、`load_allowlist(path) -> dict`（缺檔或格式錯 → `bad_allowlist`）、`check_url_allowed(url, allowlist)`、`check_host_allowed(host, allowlist)`、`is_public_address(ip) -> bool`、`resolve_public_addresses(host, resolver=socket.getaddrinfo) -> list[str]`、`strip_url_for_storage(url) -> str`、`DomainThrottle(min_interval=5.0, clock=..., sleep=...)`、`RobotsPolicy()`、`DEFAULT_CONTACT_URL`。
- `src/scraper/fetch.py`（23-01）：`FetchResult(ok, url, final_url, status, html, fetched_at, reason, error_class)`；`build_user_agent(contact=DEFAULT_CONTACT_URL) -> str`；`fetch_page(url, *, allowlist, throttle, robots, user_agent, resolver=None, http_get=None, connector=None, ssl_context=None, now=None, timeout=10.0, max_bytes=2*1024*1024, max_redirects=3, pinned_addresses=None) -> FetchResult`（`pinned_addresses` 為 CR-23-1 新增）。
- `FetchResult.reason` 代碼（23-01）：`not_allowlisted`、`scheme`、`port`、`credentials`、`private_address`、`bad_url`、`robots_denied`、`too_many_redirects`、`bad_content_type`、`too_large`、`timeout`、`network`、`http_status`、`unexpected`。
- `src/scraper/extract.py`（23-02）：`SCHEMA_VERSION = "1"`；`ExtractedClinicPage(institution_name, address, phone, business_hours, services, doctors, schema_drift, drift_fields, schema_version)`；`is_usable()`；`to_dict()`；`extract_clinic_page(html)`。
- `src/scraper/drafts.py`（23-02，本 phase 不呼叫，見 D-16）。
- `data/scraper/sources.json`（23-01）：白名單，唯一條目 `www.nu-vendome.com` 之 `/location-detail/`。Phase 24 只讀取其路徑常數，不修改。
- `tests/conftest.py`（23-01）：autouse fixture 攔截非 loopback 之 socket 與 DNS。

## 不在本 Phase 範圍（Deferred / Out of Scope）

- Phase 23 擷取器本身（HTTP 客戶端、robots.txt、節流、解析器、白名單檔）——屬 Phase 23。
- 網址解析產生 PageIndex 樹草稿（tree 目標）——使用者決策：不支援，後端與前端皆拒絕。
- 批量網址（多 URL 佇列）與排程擷取——未列於 PRD。
- 正式庫 `clinic.db` 任何遷移或寫入——本 phase 所有測試僅使用 `isolated_db_path` 隔離複本。
- 跨行程之 `db_lock` 於網址寫入路徑——現況 `/upload` 亦未取得，本 phase 不擴大範圍；列為待確認（Open Q6）。

## Claude's Discretion

- 名稱字集的精確 regex、是否允許全形英數（建議允許 NFKC 正規化後比對）。
- `url_guard` 的錯誤碼內部命名。
- `UrlFetchDeps`、`UrlPageResult` 以 dataclass 實作。

## 使用者決定（已定案）

1. 網域 `nu-vendome.com` 由 Phase 23 白名單啟用；Phase 24 不得自行繞過白名單。
2. 網址解析 tree 目標不支援，只支援 FAQ 草稿。
3. 電話遮蔽維持，不豁免。
4. DNS rebinding：本版採「固定已驗證 IP」為預設，依賴 CR-23-1；未經書面確認前標註為待確認（D-17）。
5. REQ-ID `24-R1`…`24-R5` 暫留於 plan frontmatter，未回寫 REQUIREMENTS.md。
6. （rev-3 新增）CR-23-2 未採納 → 刪除 localhost 測試旗標（D-22）。
7. （rev-3 新增）CR-23-4 未採納 → port 僅 443。
8. （rev-3 新增）UA 固定為 `build_user_agent()`；刪除 `CLINICBRAIN_SCRAPER_CONTACT` 與其 503 行為（D-15）。

## Phase 23 配合清單（rev-3）

Phase 24 執行前，Phase 23 須完成下列項目（以 24-02 Task 2 a 的 contract test 逐項確認）：

1. **CR-23-1（部分採納，需新增參數）**：`fetch_page(..., pinned_addresses=None)`，語意依 CR-23-1 表。
2. `resolve_public_addresses(host, resolver=...)` 與 `is_public_address` 保持公開名稱不變（Phase 24 url_guard 直接呼叫，CR-23-3 單一來源）。
3. `fetch_page` 的 `http_get` 與 `resolver` 注入參數保持不變（Phase 24 測試與 deps 依賴）；**不新增 opener 參數**。
4. `FetchResult.reason` 代碼清單保持穩定（見上），Phase 24 映射表以此為準。
5. `tests/conftest.py` 的 autouse 網路攔截 fixture 保留，並對 Phase 24 測試生效。
6. `DomainThrottle` 與 `RobotsPolicy` 為可長期持有之行程內實例（Phase 24 單例，D-14）。
7. `load_allowlist` 讀取失敗回 `PolicyError(reason="bad_allowlist")`（Phase 24 映射為 503）。

## Open Questions（需使用者或 Phase 23 確認）

1. **DNS rebinding（D-17）**：CR-23-1 是否由 Phase 23 採納？若否，是否書面接受殘餘風險（accept）？
2. **多 worker 節流**：`DomainThrottle`、`_URL_FETCH_LOCK` 與 robots 單例為行程內狀態；若服務改為多 worker，同一網域節流不跨行程。目前 `scripts/run_api_server.py` 預設為單 worker。
3. **診所電話**：本版依使用者決定遮蔽；醫師審核時如需顯示，屬人工編修，不由系統豁免。
4. **聯絡方式（UA）**：UA 網址 `https://doctor-toolbox.com/clinicBot` 是否為使用者本人可回應擷取者的頁面？若實際為預約表單入口，須於 Phase 23 另行確認（UA 由 Phase 23 固定，Phase 24 不再設定）。
5. **併發與 db_lock**：網址寫入是否需取得 `<db>.nightly.lock`（與 Phase 23 CLI 一致）？現況 `/upload` 未取得；本版不擴大範圍，待確認。
6. **doctors 不入 metadata**：為本版偏離 Phase 23 D-C3 之決定，需使用者確認是否接受。
