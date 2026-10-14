# clinicbrain 網站素材擷取器操作手冊

本手冊說明 clinicbrain 網站素材擷取器（Web Scraper）之運作架構、安全防禦、執行步驟與醫師審核規範。

---

## 1. 用途與範圍

- **主要用途**：擷取已取得授權之醫療機構官網特定衛教/療程頁面，結構化萃取療程項目與衛教內容，經醫療法規多重防禦檢驗後，產生待審核的常見問答草稿（`faq_cache`，`source_type='web_upload'`，`review_status='pending'`）。
- **服務對象**：緻妍外科診所（`clinic_id = '3503190424'`）或其他經正式建置之院所。
- **處理範圍**：
  - 本工具**僅產出 FAQ 草稿**，不生成 PageIndex 臨床推理樹（`page_index_trees`），亦不執行多頁爬行或全站鏡像。
  - 診所機構名稱、地址、電話、營業時間僅記錄於草稿的 `metadata.extracted`，**絕不進入問句與答案**（避免對話身分混淆）。
  - 醫師姓名與專長僅於記憶體中比對身分防禦（`identity_leak`），**絕不持久化至資料庫或 metadata**。

---

## 2. 擷取對象確認流程與擁有權防線

### 2.1 白名單與授權確認

1. **白名單檔案**：`data/scraper/sources.json`。
   - 所有欲擷取的網域與路徑前綴必須預先由人工維護加入白名單。
   - 白名單僅允許 `https` 協議與 `443` 連接埠，嚴禁任何未授權之外部主機。
2. **白名單通過不等於擁有權確認**：
   - 外部網站之智慧財產權與服務條款（Terms of Service）由操作人員負法律責任。
   - 系統設有**擁有權確認書面防線**：任何包含真實 `https` 網址的擷取（含 dry-run），必須預先存在 `data/scraper/ownership_confirmation.json`，且內容經使用者明確確認（`confirmed_by_user: true`）且涵蓋白名單主機。
   - 缺少擁有權授權檔時，系統在任何網路請求與排隊前立即以結束碼 `2` 拒絕執行（`ownership_unconfirmed`）。
3. **裸網域與重導向網域**：
   - 若目標網站涉及裸網域（如 `example.com` 重導向至 `www.example.com`），兩者必須分別列入白名單與擁有權確認檔，嚴禁跨未授權網域跳轉。

---

## 3. 安全與網路防禦規範

- **User-Agent 識別**：固定格式為 `ClinicBrainSiteReader/0.1 (+https://doctor-toolbox.com/clinicBot)`，以網址方式提供聯絡窗口，不暴露個人信箱。
- **逐請求節流**：
  - 預設請求間隔 5.0 秒，強制下限 3.0 秒（低於 3.0 秒 CLI 直接退出）。
  - 節流計時為逐網域獨立維護，涵蓋 `robots.txt` 查詢、首跳頁面與每一次重導向請求。
- **Robots.txt 遵循**：
  - 每次存取新網域前自動檢查並快取 `robots.txt`（快取 TTL 1 小時）。
  - 若 `robots.txt` 抓取失敗（網路錯誤、5xx）或明確 Disallow，立即中斷該網域之擷取（`robots_denied`）。
- **SSRF 與 DNS Rebinding 防禦**：
  - 嚴格解析 A/AAAA 記錄，全面排除私有 IP（RFC 1918）、迴圈（127.0.0.0/8）、CGNAT（100.64.0.0/10）與 IPv4-mapped IPv6。
  - 首跳直連採用釘住 IP（`_PinnedHTTPSConnection`），後續重導向於連線前重新解析與判定。
- **TLS 憑證檢驗**：強制啟用 `check_hostname=True` 與 `verify_mode=ssl.CERT_REQUIRED`，杜絕任何不安全連線。

---

## 4. 批次編排與跨行程檔案鎖

- **寫入模式抓取前探測鎖**：
  - 在 `write=True` 模式下，於發出任何 HTTP 請求或 robots 請求之前，先探測跨行程互斥鎖（`clinic.db.nightly.lock`）。
  - 若夜間批次正在持鎖執行，探測立即得知並回報 `skipped_locked`（結束碼 0），**零網路請求、零計算資源浪費**。
- **先全部抓取後統一解析**：
  - 批次作業先循序抓取所有網址至記憶體清單中，抓取期間不持有資料庫鎖（避免長時間網路延遲阻礙夜間批次）。
  - 全部抓取完畢後，寫入階段再度以非阻塞方式取得權威鎖，進行交易寫入。
- **失敗隔離與交易邊界**：
  - 批次中任一網址發生網路逾時、狀態碼異常或結構改版，僅記錄於報告，其餘合法網址照常解析與入庫。
  - 每一筆網址為獨立交易：若該筆寫入發生例外則自動 rollback，不影響其他網址之提交。

---

## 5. 操作步驟指南

### 5.1 正式資料庫前置條件

正式資料庫 `clinic.db` 必須已手動完成以下結構遷移（系統寫入路徑絕不自動 ALTER，防範非預期異動）：
1. `scripts/migrate_faq_metadata.py`（新增 `metadata` 欄位）。
2. `scripts/migrate_faq_review_status.py`（新增 `review_status` 與 `reviewed_at` 欄位）。

### 5.2 Dry-Run 預覽演練（強烈建議）

在執行實質寫入前，一律先使用 `--dry-run` 模式進行安全檢驗：
```bash
python3 scripts/scrape_site.py \
  --clinic-id 3503190424 \
  --url "https://<已確認網域>/location-detail/branch/" \
  --live \
  --dry-run \
  --report-json scratchpad/report_preview.json
```
- Dry-run 以 SQLite `mode=ro`（URL 編碼路徑）唯讀開啟資料庫，絕不產生任何寫入交易。
- 輸出報告包含 `schema_preflight`，供確認正式庫結構是否具備寫入資格。

### 5.3 實質寫入正式庫

寫入正式資料庫時，必須雙重附加 `--allow-prod-db` 與 `--confirm-prod-backup` 旗標：
```bash
# 1. 先行手動備份正式資料庫
cp clinic.db clinic.db.bak-$(date +%Y%m%d)

# 2. 執行實質擷取入庫
python3 scripts/scrape_site.py \
  --clinic-id 3503190424 \
  --url "https://<已確認網域>/location-detail/branch/" \
  --live \
  --write \
  --allow-prod-db \
  --confirm-prod-backup \
  --report-json scratchpad/report_write.json
```
> [!IMPORTANT]
> **資料庫版本控管警示**：`clinic.db` 受 git 追蹤。擷取寫入後**請勿直接 `git add clinic.db`**，請先檢視 `git status`，並由醫師完成初審確認後，再決定是否提交版本庫。

---

## 6. 醫療法規防線與醫師審核流程

### 6.1 合規過濾順序

在草稿寫入資料庫前，所有萃取出的服務項目均需依序通過嚴格防護：
1. **正體中文轉換**：透過 OpenCC `s2twp` 轉為台灣繁體中文醫療慣用語。
2. **個資去識別化與價格屏蔽**：
   - 濾除身份證、病歷號與聯絡資訊。
   - 若服務描述內含具體價格（如 `NT$ 1500`、`1500元`），在結構抽取層直接清空該欄位；若有殘餘價格樣式則於草稿層剔除（原因碼 `price_pattern`）。
3. **保證療效禁詞檢查**（原因碼 `guarantee_phrase`）：
   - 比對 13 項法定保證療效禁詞（如「保證有效」、「保證根除」、「永久根除」、「百分之百有效」等），一經比對立即剔除。
4. **身分外洩檢查**（原因碼 `identity_leak`）：
   - 問句與答案中嚴禁出現外部診所機構名稱、門市地址、代表電話或醫師個人姓名。
5. **醫療常規檢驗**（`validate_single_faq`）：
   - 強制檢驗劑量數字（`check_dosage=True`）、答案長度需達 30 字以上。

### 6.2 審核前完全隱蔽與醫師簽核

- **審核前隱蔽**：所有寫入之草稿標記為 `source_type='web_upload'` 與 `review_status='pending'`。在未經醫師正式核准前，自然語言查詢端點（`POST /api/v1/query`）與快取短路檢索（`faq_shortcut`）以 `visible_faq_sql` 條件全面隱蔽，對外完全不可見。
- **醫師審核操作**：
  ```bash
  # 列出所有待審核之網站上傳草稿
  python3 scripts/review_faq.py list --source web_upload --status pending

  # 檢視單筆詳細內容（包含 metadata 來源資訊）
  python3 scripts/review_faq.py show <ID>

  # 醫師核准通過
  python3 scripts/review_faq.py approve <ID> --notes "醫師核定衛教內容合格"

  # 醫師駁回剔除
  python3 scripts/review_faq.py reject <ID> --notes "用語不符合本院醫療處置方針"
  ```

---

## 7. 改版告警（Schema Drift）處置

若目標網頁 HTML 結構大幅改動（例如改為 SPA 全客戶端渲染、更換 CSS class 名稱或移除服務區塊）：
- 系統將自動偵測出 `schema_drift=True`，原因碼標記為 `schema_drift`。
- **處置原則**：該網址不寫入任何草稿，批次報告記錄失敗。操作人員應檢視該頁面原始碼變更，**切勿為了強行抓取而隨意放寬解析標準**，應另案評估修改 `src/scraper/extract.py` 之解析邏輯。

---

## 8. 已知限制與禁止事項

- **已知限制**：
  1. 不支援 JavaScript 渲染（SPA 動態加載之內容無法取得）。
  2. 頁面內嵌之表格型圖片與海報不自動執行 OCR。
  3. 全批次頁面讀入記憶體清單後統一處理，時間與記憶體隨網址清單增長（總量記憶體上限待使用者進一步指示）。
- **絕對禁止事項**：
  1. **嚴禁標記為 `clinic_upload`**：網站擷取素材一律標記為 `web_upload`，不得標記為具備醫師權威之院所手動上傳。
  2. **嚴禁自動核准**：所有素材進入資料庫必須為 `pending`，絕不允許程式端繞過醫師自動設為 `approved`。
  3. **嚴禁未獲書面確認前執行真實網域擷取**。
