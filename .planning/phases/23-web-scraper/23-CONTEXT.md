# Phase 23 CONTEXT：網站擷取器（PageIndex 素材自動化）

> 本檔由 gsd-planner 依 `23-PRD.md` 與 ROADMAP Phase 23 產出。Locked decisions 即 PRD 內容，規劃期間不得改寫；Claude's discretion 為規劃者的實作選擇，可於執行時再調整但需記錄。
> 2026-10-14 第一次修訂：依使用者指示套用阻擋項目修正（見「修正紀錄」）。
> 2026-10-14 第二次修訂：依檢查員剩餘阻擋項目修正（見「第二次修正紀錄」）。

## Locked Decisions（來自 PRD，不可變更）

- **D-R1** 輸入網址，擷取頁面中的結構化欄位：機構名稱、地址、電話、營業時間、服務項目、醫師姓名與專長。
- **D-R2** 擷取結果轉為草稿（FAQ 草稿與／或 PageIndex 樹草稿），寫入 `pending`，醫師審核後才對外可見。
- **D-R3** 遵守 `robots.txt`、請求間隔節流、明確 User-Agent；單頁失敗不中斷批次。
- **D-R4** 不保存外部頁面的非必要個資；每筆草稿於 metadata 保存來源 URL 與擷取時間。
- **D-R5** 價格、療效保證、藥品劑量等內容必須經既有合規檢驗與價格屏蔽。
- **D-R6** 提供 CLI 入口；Web 入口由 Phase 24 串接（本 Phase 不做 Web UI）。
- **D-RISK-1** 規劃前須由使用者確認擷取對象清單（見 Open Questions）。未經確認之網域不得被擷取。
- **D-RISK-2** 網站改版造成解析失效須有欄位缺失偵測與告警。
- **D-RISK-3** 外部內容不可直接當作診所權威來源，**不得標記為 `clinic_upload`**。

## 來自 ROADMAP 的補充範圍（與 PRD 一致，無衝突）

- 擷取器只讀公開頁面；失敗降級，不影響既有上傳與審核流程（對應 D-R3）。
- 草稿以 `web_upload`（既有審核閘門來源）進入 `pending`，不得直接對外可見（對應 D-R2）。

### 與 ROADMAP 的範圍差異（需使用者知悉）

- ROADMAP Phase 23 Scope 第 4 點寫「提供 CLI 與 Web 入口」，PRD R6 明定「Web 入口由 Phase 24 串接」。本規劃**以 PRD 為準**：Phase 23 只交付 CLI 與可供 Phase 24 呼叫的純函式介面，不交付 Web UI。

## Claude's Discretion（規劃者決定，執行時依此實作）

- **D-C1 來源審核標記**：沿用既有 `web_upload`（已在 `REVIEW_GATED_SOURCES`，且 `upsert_faqs` 直接以 `pending` 寫入），不新增來源類型。外部來源身分改以 `metadata.origin='web_scrape'` 區分。理由：新增來源需同步改 `REVIEW_GATED_SOURCES`、`VALID_SOURCE_TYPES`、`visible_faq_sql` 與所有遷移，風險大於收益；且 `web_upload` 已通過 Phase 18 的 Fail-Closed 驗證。
- **D-C2 本 Phase 只寫 FAQ 草稿，不寫 PageIndex 樹草稿**：`faq_cache` 已有 `metadata` 欄位（`scripts/migrate_faq_metadata.py`），可保存 R4 要求的溯源；`page_index_trees` 目前**沒有** `metadata` 欄位，寫入樹草稿將無法保存來源 URL 與擷取時間，違反 D-R4。樹草稿列為後續項目（需先為 `page_index_trees` 新增 metadata 欄位並走單一來源遷移）。
- **D-C3 identity 欄位不進入任何對外答案**（2026-10-14 修正；第二次修訂擴充）：機構名稱、地址、電話、醫師姓名屬「他方機構資訊」。擷取後只保存於草稿 `metadata.extracted`，且**僅含機構層級欄位**（機構名稱、地址、電話、營業時間）；**醫師姓名與專長不寫入任何持久化欄位**。**答案與問句文字禁止出現擷取到的機構名稱、地址、電話字串，亦禁止出現醫師姓名**（以確定性檢查攔截，reason=`identity_leak`）。`clinic_info` 為本診所權威資料，**本 Phase 絕不寫入 `clinic_info`**。
- **D-C4 HTTP 客戶端**：repo 未宣告 `requests`／`httpx`／`bs4`（無 requirements 檔）。採標準庫 `http.client`、`urllib.robotparser`、`urllib.parse`、`ipaddress`、`socket`、`ssl`、`html`，避免新增依賴；若執行者認為需要更強解析，須先停下回報，不得自行安裝套件（符合 package legitimacy gate）。不使用 `urllib.request` opener（見 D-C5 補充）。
- **D-C5 SSRF 防護**：只允許 `https` 與 443 埠；解析主機所有 A/AAAA 位址，任一非全域可路由（`is_global` 為假，含 100.64.0.0/10 CGNAT；IPv4-mapped IPv6 先解開）即拒絕；每次請求（含 robots 與每跳重導向）重新檢查；最多 3 次重導向；連線與讀取逾時 10 秒；回應上限 2 MB；僅接受 `text/html`。
  - **D-C5 補充（2026-10-14）**：DNS rebinding 防護採「每次請求解析並驗證，連線釘住已驗證 IP」，以 `http.client.HTTPSConnection` 子類別實作（覆寫 `connect()`，TLS SNI 與 Host 標頭仍為原主機名），不使用 urllib opener，避免環境 proxy 變數繞過 IP 釘住。
  - **D-C5 補充（第二次修訂）**：TLS 驗證不可關閉。`check_hostname` 必須為 True、`verify_mode` 必須為 `CERT_REQUIRED`，於連線前斷言；不符 → `tls_config`，且不發出任何請求。
- **D-C6 robots.txt 策略（fail-closed）**：`robots.txt` 回 404 視為允許；回 401／403／5xx、逾時、無法解析視為**不允許**；快取於記憶體 1 小時；使用 `urllib.robotparser`，以我方 User-Agent 比對。（2026-10-14 補充：robots.txt 請求同樣經白名單 host 檢查與節流，但不受 path_prefixes 限制。）
- **D-C7 節流**：同一網域請求間隔預設 ≥ 5 秒（可由 CLI 參數調高、不可調低於 3 秒）；全程單執行緒循序擷取。（2026-10-14 補充：節流逐 HTTP 請求套用，robots、頁面、每跳重導向皆計入。）
- **D-C8 User-Agent**（2026-10-14 修正）：固定為 `ClinicBrainSiteReader/0.1 (+https://doctor-toolbox.com/clinicBot)`，只使用網址、不含 email。`build_user_agent` 拒絕含 `@`、`mailto:` 或非 https 的 contact；CLI 不提供 `--contact` 參數。
- **D-C9 白名單**（2026-10-14 修正）：擷取對象以 `data/scraper/sources.json` 列明網域與允許路徑前綴。目前唯一條目為 `www.nu-vendome.com` 的 `/location-detail/` 路徑前綴（使用者確認，見下方使用者回覆）。未列入者 CLI 以結束碼 2 拒絕。裸網域 `nu-vendome.com` 未列入，待另行確認。**白名單通過不等於擁有權確認**，見 D-C17。
- **D-C10 欄位缺失偵測**：必填欄位（機構名稱、服務項目至少 1 筆）缺失視為解析失效，該頁標記 `schema_drift`，不產生草稿，並寫入批次摘要（stderr 與 JSON 報告）。
- **D-C11 去識別化**：擷取文字一律經 `to_traditional` → `deidentify_text` → `deep_mask_prices`（比照 `src/api/routes/admin.py` 上傳流程）；醫師私人聯絡（個人手機、私人信箱、LINE ID）整段丟棄，不進入 metadata。
- **D-C12 日誌隱私**：日誌只記 URL 網域、HTTP 狀態碼、例外類別與計數；不記頁面內文、答案、醫師姓名。
- **D-C13 生產庫保護**：CLI 比照 `scripts/distill_soap_faqs.py`：`--dry-run` 以 `mode=ro` 開庫、零寫入；正式庫寫入需 `--allow-prod-db` 與 `--confirm-prod-backup`，缺一於連線前以結束碼 2 退出。（2026-10-14 補充：正式庫判定以 realpath 比對；dry-run URI 路徑做 URL 編碼。第二次修訂：另加 `os.path.samefile` 防硬連結。）
- **D-C14 寫入唯一路徑**：FAQ 草稿只經 `src/pageindex/faq_writer.py:upsert_faqs(conn, faqs, source_type='web_upload')`；禁止直接 INSERT；禁止 `INSERT OR REPLACE`。
- **D-C15 合規檢驗**（第二次修訂擴充）：每筆草稿需依序通過兩道檢驗：
  1. **草稿前置保證療效禁詞檢查**（新增，reason=`guarantee_phrase`）：對 question 與 answer（經 `to_traditional` 後）比對完整禁詞表，該表至少涵蓋 AGENTS §2.5 所列「保證有效、保證根除、百分之百有效、徹底根除、一定有效」與 `src/api/routes/sync.py:_FORBIDDEN_PHRASES` 之全部條目（含簡體變體）。**不依賴** `validate_single_faq` 的內建清單，因其 `_FORBIDDEN_PHRASES`（`src/ingestion/generate_faq.py:37`）僅含 5 項，缺「保證根除」「百分之百有效」等，且計畫禁止修改 `validate_single_faq`。
  2. `src/ingestion/generate_faq.py:validate_single_faq(item, check_dosage=True, require_doctor_warning=<general 類為 True>)`。
  違規項目單筆剔除並計入報告，不影響同批其他項目。
- **D-C16 服務項目與價格**：價格資訊於解析階段直接丟棄（描述欄位清空），不以遮蔽後字串充當資料；草稿層再以價格樣式二次檢查。
- **D-C17 擁有權與授權確認（第二次修訂新增；第四輪依使用者指示調整）**：白名單條目與使用者口頭回覆原則上做為內部開發依據。使用者第四輪指示「目前只是要做軟體先不需要授權限制」：在軟體研發、測試與 CLI 工具建置階段，不再要求硬性存在 `ownership_confirmation.json` 作為程式執行的中斷條件。法律授權文件回歸診所實際營運前置程序，不阻礙軟體研發與測試。但 `--live` 仍明示為真實網域擷取，且嚴格遵守 `robots.txt`、請求節流（≥5 秒）、SSRF 釘住 IP 防護與合規價格遮蔽。
- **D-C18 夜間批次持鎖探測（第二次修訂新增）**：寫入模式下，`run_scrape_urls` 於**第一筆頁面請求之前**即以 `db_lock.try_acquire` 探測；取不到 → `skipped_locked`，不發出任何請求。探測成功後立即釋放（`db_lock.release`），寫入階段再以同一方式取得權威鎖；寫入階段取不到仍回 `skipped_locked` 且不寫入。探測為 best-effort（存在 TOCTOU 空窗），權威判定在寫入階段。
- **D-C19 fixture:// 來源定義（第二次修訂新增）**：`strip_url_for_storage` 僅接受 `https://<host>/<path>`（host 白名單外由 check_url_allowed 另行拒絕）與 `fixture://<安全檔名>`（檔名符合 `^[\w\-.]{1,128}$`，不含路徑分隔符）；其他 scheme、含 port（非 443）、路徑穿越 → `bad_url`。fixture 來源輸出為 `fixture://<檔名>`，不含 query、fragment。
- **D-C20 總量上限（第二次修訂新增，屬 Open Question，非已接受）**：本 Phase 不實作任何記憶體總量上限（使用者僅取消頁數上限）。報告必須回報 `total_html_bytes`（僅計數）以利使用者決策；STRIDE 處置標為「待使用者決定」，**不得視為已接受**。

## Canonical Refs（檔案路徑）

- 需求來源：`.planning/phases/23-web-scraper/23-PRD.md`
- 路線圖：`.planning/ROADMAP.md`（Phase 23、24、25 區段）
- 合規規則：`/home/hsu/Desktop/clinicbrain/AGENTS.md`（§2.4、§2.5、§2.10、§2.17、§3、§5）
- 審核閘門：`src/pageindex/faq_review.py`（`REVIEW_GATED_SOURCES`、`visible_faq_sql`、`has_review_status`（:32）、`set_review_status`）
- 唯一寫入路徑：`src/pageindex/faq_writer.py:upsert_faqs`、`src/pageindex/db_writer.py:upsert_trees`
- 合規驗證：`src/ingestion/generate_faq.py:validate_single_faq`（:80，`_FORBIDDEN_PHRASES` 於 :37，本計畫不修改）、`src/ingestion/medical_safety.py`
- 保證療效禁詞完整來源（比對參考）：`src/api/routes/sync.py`（`_FORBIDDEN_PHRASES`，約 :50–66）
- 去識別化與價格：`src/soap/deid.py:deidentify_text`（:82）、`src/api/routes/query.py:deep_mask_prices`（:57）、`src/ingestion/convert_chinese.py:to_traditional`（:25）
- 鎖：`src/batch/db_lock.py`（`nightly_lock_path`、`try_acquire`、`release(fd)`；釋放函式為 `release`，非 `release_lock`）
- 正式庫路徑：`src/api/config.py:23`（`config.db_path`，環境變數 `CLINICBRAIN_DB_PATH`）
- 上傳流程範本（Phase 24 將共用其概念）：`src/api/routes/admin.py`（`/upload`，約第 111–300 行）
- 認證：`src/api/security.py`、`src/api/routes/admin.py`（`verify_admin_key`）
- CLI 範本：`scripts/distill_soap_faqs.py`（`--dry-run`、`--confirm-prod-backup`）
- 欄位遷移：`scripts/migrate_faq_metadata.py`（`faq_cache.metadata`）
- Schema 權威來源：`src/db/clinic_schema.sql`
- 新增檔（本 Phase 產出）：`src/scraper/`（`__init__.py`、`policy.py`、`fetch.py`、`extract.py`、`drafts.py`、`report.py`、`runner.py`）、`scripts/scrape_site.py`、`data/scraper/sources.json`、`tests/fixtures/scraper/*.html`、`tests/test_scraper_*.py`、`tests/conftest.py`（autouse 網路攔截，修改既有檔）、`docs/web-scraper.md`
- 擁有權確認檔（使用者書面確認後才會存在，執行者不得預先建立）：`data/scraper/ownership_confirmation.json`

## Multi-Source Coverage Audit

| 來源 | 項目 | 覆蓋計畫 |
|------|------|----------|
| GOAL | 可設定的網站擷取器，產出 PageIndex／FAQ 草稿素材，減少人工抄錄 | 23-02（抽取與草稿）、23-03（CLI 端到端） |
| REQ R1 | 結構化欄位擷取（名稱、地址、電話、營業時間、服務項目、醫師） | 23-02 Task 1–2（醫師僅記憶體，不持久化） |
| REQ R2 | 草稿寫入 pending（web_upload） | 23-02 Task 3、23-03 Task 2 |
| REQ R3 | robots.txt、節流（robots 計入）、UA、單頁失敗隔離 | 23-01 Task 1–2、23-03 Task 2（探測於抓取前） |
| REQ R4 | 不保存非必要個資、保存去參數來源 URL 與擷取時間 | 23-01 Task 1（strip_url_for_storage 含 fixture://）、23-02 Task 2（metadata 機構層級限定） |
| REQ R5 | 價格、療效、劑量合規與價格屏蔽 | 23-02 Task 2（草稿前置禁詞、validate_single_faq、deep_mask_prices） |
| REQ R6 | CLI 入口；Web 由 Phase 24 串接 | 23-03 Task 3–4 |
| RISK 1 | 擷取對象白名單（使用者確認）＋擁有權書面確認 | 23-01 Task 1（sources.json）、23-03 Task 3（--live 閘門）、23-03 Task 4 硬性前置條件、Open Questions 7 |
| RISK 2 | 欄位缺失告警 | 23-02 Task 1（schema_drift）、23-03 報告 |
| RISK 3 | 不標記 clinic_upload | 23-02 Task 3 測試斷言、23-03 grep 驗證 |
| CONTEXT D-C1～D-C20 | 見上 | 分別見 23-01／23-02／23-03 |
| 排除（非缺口） | 網頁 Web UI（Phase 24）、樹草稿（D-C2 延後）、批次自動核准（永不） | 明確不在本 Phase |
| 待決（非已接受） | 總量（記憶體）上限 | Open Questions 8、D-C20、T-23-16（待使用者決定） |

## Open Questions（須使用者回覆後再執行）

1. **擷取對象與法遵**：（已回覆，見使用者回覆 1）。
2. **聯絡方式**：（已回覆，見使用者回覆 2）。
3. **草稿歸屬**：（已回覆，見使用者回覆 3）。
4. **樹草稿延後**：（已回覆，見使用者回覆 4）。
5. **正式庫前置條件**：（已回覆，見使用者回覆 5；執行前仍須以 dry-run 的 schema_preflight 實際查證）。
6. **抓取頻率上限**：（已回覆，見使用者回覆 6；頁數上限已取消）。
7. **【已解除】擁有權／授權書面確認**：使用者於第四輪明確指示「目前只是要做軟體先不需要授權限制」。軟體研發與實作測試階段解除書面授權檔案的硬性阻擋閘門，法律文件由診所營運層面處理，不阻礙軟體研發。
8. **【待決】總量（記憶體）上限（第二次修訂新增）**：使用者已取消頁數上限；先完整抓取全部頁面的總記憶體上限是否要設定？**狀態：未決，不視為已接受。** 本 Phase 不實作上限，報告回報 `total_html_bytes`；若使用者要求上限，須另行決定（分段抓取會違反「先全部抓完再統一處理」的指示）。

## 使用者回覆（Open Questions 已回答）

1. **擷取對象與法遵**：使用者確認網站為公開資訊、無個資問題；可列入 `nu-vendome.com`（路徑 `/location-detail/` 下）。仍須遵守 robots.txt 與節流。
2. **聯絡方式（UA）**：使用者提供 `https://doctor-toolbox.com/clinicBot`。UA 僅使用網址，採用 `ClinicBrainSiteReader/0.1 (+https://doctor-toolbox.com/clinicBot)`。使用者決定不將 email 放入 UA，避免個人信箱隨每次請求送到被擷取網站。（注意：此網址可能是使用者本人的 clinicBot 頁面，若實際上要用於預約表單的入口，請再確認。）
3. **草稿歸屬**：同意綁定本診所 `clinic_id`，只產生服務項目衛教題，機構身分欄位只留在 metadata。
4. **樹草稿延後**：同意，本 Phase 只產 FAQ 草稿。
5. **正式庫前置條件**：使用者確認正式庫已套用 faq_cache 相關遷移（`migrate_faq_metadata`、`migrate_faq_review_status`）。仍需在執行前實際查證 schema。
6. **抓取頻率與批次**：使用者要求「爬蟲須全部資料再處理」，即先完整抓取全部頁面，再統一處理，**不設每批 20 頁上限**。節流（每網域間隔）仍維持。（規劃者確認：與 D-C7 節流及 RISK 規則不衝突；取消的是頁數上限而非節流。）

## 修正紀錄（2026-10-14 第一次修正，依使用者指示套用）

使用者指示：只修改 `.planning` 文件；不改原始碼；不碰正式 clinic.db；不 git commit。

| 編號 | 阻擋項目 | 套用方式 | 落點 |
|------|----------|----------|------|
| 1 | robots.txt 必須經節流 | robots、頁面、每跳重導向每次 HTTP 請求前皆呼叫 `DomainThrottle.wait_turn`；測試以事件序列斷言 | 23-01 Task 2 Test 12 |
| 2 | SSRF 防護不可被 DNS rebinding 繞過 | 每次請求先解析並驗證，連線以 `_PinnedHTTPSConnection` 釘住已驗證 IP，保留 SNI 與 Host；取代 urllib opener | 23-01 Task 2 Test 10、11 |
| 3 | 私有位址判斷 | 先解開 IPv4-mapped IPv6，以 `is_global` 判定，並明確排除 100.64.0.0/10 | 23-01 Task 1、2 |
| 4 | source_url 去 query 與 fragment（D-R4） | `strip_url_for_storage` 去除 query、fragment、userinfo；drafts 寫入前強制套用 | 23-01 Task 1、23-02 Test 8 |
| 5 | metadata.extracted 不存醫師姓名 | 僅含機構層級欄位；醫師僅記憶體計數、不進報告文字 | 23-02 Task 2 Test 7、23-03 Task 1 |
| 6 | --db-path realpath 與 mode=ro URL 編碼 | CLI 以 realpath 比對正式庫；dry-run URI 做 URL 編碼 | 23-03 Task 3 Test 4、7 |
| 7 | 測試網路攔截改 autouse fixture | `tests/conftest.py` 新增 autouse fixture；刪除 `-p no:socket` | 23-01 Task 2 action 1 |
| 8 | 正式庫 clinic.db 受 git 追蹤 | 文件明載禁止 `git add clinic.db`；CLI 寫入正式庫後於 stderr 提示 | 23-03 Task 3、Task 4 |

連帶修正：白名單內容（使用者確認之單一條目）；robots 路徑豁免（僅 host 檢查）；UA 網址形式；20 頁上限取消；寫入階段才取鎖；既有 API 核對。

## 第二次修正紀錄（2026-10-14，檢查員剩餘阻擋項目，gsd-planner 修訂）

| 編號 | 阻擋項目 | 套用方式 | 落點 |
|------|----------|----------|------|
| 1 | 02 T2 禁詞不完整（validate_single_faq 的 `_FORBIDDEN_PHRASES` 缺「保證根除」「百分之百有效」等） | 不改 `validate_single_faq`；於 drafts 前置加入完整禁詞檢查（對 question 與 answer，經 to_traditional 後），reason=`guarantee_phrase`；新增「表涵蓋 AGENTS §2.5 與 sync.py 全部條目」的斷言測試與逐項拒絕測試 | D-C15；23-02 must_haves、Task 2 action 5a、Test 4、Test 12、Test 14 |
| 2 | identity_leak 僅比對機構欄位 | 除機構名稱、地址、電話外，比對醫師姓名（經 to_traditional 後）於 question 與 answer；醫師姓名僅記憶體，比對後不持久化；測試 | D-C3；23-02 Task 2 action 5、Test 13 |
| 3 | 真實寫入前須有書面確認 | 03 T4 新增硬性前置條件；CLI `--live` 與寫入皆需 `data/scraper/ownership_confirmation.json`（D-C17）；未確認前只允許 fixture 與 fixture dry-run；Open Questions 7 | D-C17；23-03 Task 3（Test 13）、Task 4 前置條件、checkpoint、T-23-27 |
| 4 | 夜間批次持鎖探測需在抓取前 | 寫入模式下第一筆請求前探測（try_acquire 後立即 release）；取不到不發請求；寫入階段權威取鎖 | D-C18；23-03 Task 2 step 2–3、Test 7、Test 7b |
| 5 | ssl_context 未明定 TLS 驗證 | 明定 check_hostname=True、verify_mode=CERT_REQUIRED；連線前斷言；不符 → tls_config 且不發請求；測試 | 23-01 Task 2 action、Test 11、17、18、19 |
| 6 | 守門路徑比對 | realpath 加 `os.path.samefile`（防硬連結）；測試 | 23-03 Task 3 step 4、Test 4b |
| 7 | frontmatter 缺 RISK-3；fixture:// 行為未定義 | 02 frontmatter 補 RISK-3（與 RISK-2）；`strip_url_for_storage` 對 fixture:// 明確定義並測試 | D-C19；23-01 frontmatter 與 Task 1 Test 11b；23-02 frontmatter；23-03 frontmatter |
| 8 | 無頁數與總量上限 | 頁數上限維持取消（使用者決定）；總量上限維持 Open Question 8，STRIDE 處置改為「待使用者決定」，不寫成 accept；報告回報 total_html_bytes | D-C20；23-03 threat model T-23-16、Task 2 報告欄位 |

### 仍需使用者決定（第二次修訂後）

1. **擁有權書面確認（Open Question 7，阻擋）**：是否確認 `nu-vendome.com` 為本診所自有網站或另行授權？未確認前不得 live 擷取或寫入。
2. **總量（記憶體）上限（Open Question 8）**：是否設定上限？未決。
3. **裸網域 `nu-vendome.com`**：是否加入白名單（第一次修正之仍未解問題 1）。
4. **UA 網址用途**：`https://doctor-toolbox.com/clinicBot` 是否為使用者本人可回應擷取者的頁面（第一次修正之仍未解問題 2）。
5. **醫師欄位解析**：醫師姓名仍由擷取層解析進記憶體以做 identity_leak 比對（第二次修訂因此擴充用途）；若希望連記憶體都不解析，需改 R1 範圍。
6. **正式庫 schema 與 clinic_info**：`3503264627` 尚未建立於正式庫 `clinic_info`；是否新增列須另行授權與備份（屬正式庫寫入）。

---

## 使用者提供之目標機構（2026-10-14）

- 醫事機構代碼：`3503264627`
- 機構完整名稱：凡登整形外科診所
- 正式庫現況（唯讀查證）：`clinic_info` 僅有 `3503190424`（緻妍外科診所）；`3503264627` 尚未建立，`faq_cache` 亦無此機構資料。
- 待確認：是否要在正式庫新增 `clinic_info` 列（屬正式庫寫入，需另行授權與備份）。
- 注意：凡登（Vendome）與擷取對象 nu-vendome.com 的名稱相近，需確認該網站是否為本診所自有網站（見 Open Question 7）；若是，擷取的法遵風險較低，但仍須遵守 robots.txt 與節流。

---


## 使用者第三輪回覆（2026-10-14）

- 擷取對象身分：**非本診所自有網站，但已取得授權擷取**。書面確認閘門（ownership_confirmation）需改為「授權證明」，內容須包含授權人、授權範圍（網域與路徑）、授權期間。授權文件本身尚未提供，在收到前仍禁止真實擷取與寫入。

---

## 使用者第四輪回覆（2026-10-14）

- **解除開發期授權限制**：使用者指示「目前只是要做軟體先不需要授權限制」。軟體研發、爬蟲解析邏輯、資料清洗合規檢驗、CLI 與測試等實作，不因未取得第三方書面授權合約而阻擋。原本硬性中斷之 `ownership_confirmation.json` / 授權證明閘門在軟體實作階段解除，系統聚焦於爬蟲工程本身與技術防線（robots.txt、節流、SSRF 防護、去識別化與價格遮蔽維持嚴格執行）。

---

## Deferred Ideas（不納入本 Phase）

- Web 上傳中心的網址輸入（Phase 24）。
- 樹草稿（`page_index_trees` 寫入擷取內容）與其 metadata 遷移。
- 排程自動擷取（夜間批次整合）。
- 多頁爬行（crawl 鏈結追蹤）；本 Phase 只抓使用者指定的 URL 清單。
