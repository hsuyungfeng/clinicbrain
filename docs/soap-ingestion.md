# SOAP 紀錄與語音聽寫推播串接手冊 (SOAP Ingestion & Clinical Retrieval)

本手冊說明 **clinicbrain** 臨床語音與 SOAP 紀錄擷取模組（Phase 14）之規格、安全去識別化防線、資料庫寫入機制與專屬醫師檢索 API。

---

## 1. 系統架構與目標

* **串接來源**：外部雲端平台（如 `https://doctor-toolbox.com/`）或院內語音聽寫推播系統。
* **主要功能**：
  1. **S/O/A/P 自動切分**：支援結構化 JSON 或純文字語音逐字稿（`raw_text` / `transcript`）自動段落正則切分。
  2. **一般醫學特徵擷取**：自動從臨床文本中辨識常見一般疾病、症狀與居家衛教處置，歸納為標籤與特徵摘要（`general_insights_summary`）。
  3. **去識別化與價格防禦**：身分證字號、手機、市話、姓名遮蔽為 `[已遮蔽]`；價格數字以 `deep_mask_prices()` 遮蔽為 `[請致電診所確認]`；病患識別使用 HMAC-SHA256 偽名化 `patient_token`。
  4. **專屬醫師 FTS5 全文檢索**：支援依診所代碼（`clinic_id`）、關鍵字與標籤進行病歷檢索，與大眾公開自然語言查詢端點嚴格隔離。

---

## 2. API 端點規格

所有 SOAP 端點位於 `/api/v1/soap/` 前綴下，**強制要求管理員金鑰認證**（`X-API-Key` 標頭）。

### 2.1 推播接收端點

* **路徑**：`POST /api/v1/soap/records`
* **標頭**：
  * `X-API-Key`: 院所管理員金鑰
  * `Content-Type`: `application/json`
* **請求主體**：
  ```json
  {
    "clinic_id": "3503190424",
    "records": [
      {
        "external_id": "dt-rec-20261006-001",
        "patient_id": "A123456789",
        "raw_text": "S: 病患主訴咳嗽發燒喉嚨痛三天。O: 體溫 38.5 度，喉嚨紅腫。A: 上呼吸道感染，感冒。P: 給予普拿疼與止咳藥水，多喝水充分休息，費用 500 元。",
        "tags": ["感冒", "門診"]
      }
    ]
  }
  ```
  * `external_id` (必填): 外部系統唯一辨識識別碼。
  * `patient_id` / `patient_token` (可選): 若傳入 `patient_id`，系統將自動以 HMAC-SHA256 雜湊轉換為偽名化 `patient_token`，明文不入庫。
  * `raw_text` / `transcript` 或 `subjective`, `objective`, `assessment`, `plan` (至少其一)。
* **回應主體**：
  ```json
  {
    "success": true,
    "summary": {
      "inserted": 1,
      "updated": 0,
      "unchanged": 0
    },
    "general_insights_summary": {
      "total_extracted": 1,
      "conditions_detected": ["感冒"],
      "symptoms_detected": ["咳嗽", "發燒", "喉嚨痛"],
      "home_care_detected": ["多喝水", "充分休息"]
    },
    "message": "成功處理 1 筆 SOAP 紀錄"
  }
  ```

### 2.2 醫師專用全文檢索端點

* **路徑**：`POST /api/v1/soap/search`
* **標頭**：
  * `X-API-Key`: 院所管理員金鑰
  * `Content-Type`: `application/json`
* **請求主體**：
  ```json
  {
    "clinic_id": "3503190424",
    "query": "喉嚨紅腫",
    "tag": "感冒",
    "limit": 20
  }
  ```
  * `query` (可選): FTS5 繁體中文檢索詞彙（採用 trigram tokenizer 分詞）。
  * `tag` (可選): 標籤過濾。
* **回應主體**：
  ```json
  {
    "total": 1,
    "records": [
      {
        "id": 1,
        "clinic_id": "3503190424",
        "external_id": "dt-rec-20261006-001",
        "patient_token": "a1b2c3d4...",
        "subjective": "病患主訴咳嗽發燒喉嚨痛三天。",
        "objective": "體溫 38.5 度，喉嚨紅腫。",
        "assessment": "上呼吸道感染，感冒。",
        "plan": "給予普拿疼與止咳藥水，多喝水充分休息，費用 [請致電診所確認]。",
        "raw_text": "...",
        "tags": ["感冒", "門診", "症狀:咳嗽", "症狀:發燒", "症狀:喉嚨痛", "病症:感冒", "照護:多喝水", "照護:充分休息"],
        "created_at": "2026-10-06 17:00:00",
        "updated_at": "2026-10-06 17:00:00"
      }
    ]
  }
  ```

### 2.3 單筆紀錄調閱端點

* **路徑**：`GET /api/v1/soap/records/{external_id}?clinic_id=3503190424`
* **標頭**：
  * `X-API-Key`: 院所管理員金鑰
* **回應主體**：單筆 `SoapRecordItem` 物件。

---

## 3. 安全與去識別化規範 (De-identification)

為確保醫療紀錄符合台灣個人資料保護法與醫療法規，系統強制套用三層防護：

1. **個人識別碼遮蔽 (`src/soap/deid.py`)**：
   * **身分證字號**：正則匹配 `[A-Z][1289]\d{8}`，經台灣身分證校驗碼檢查確認有效者，遮蔽為 `[已遮蔽]`。
   * **行動電話與市話**：匹配 `09\d{2}-?\d{3}-?\d{3}`、`09\d{8}` 及台灣區碼市話，遮蔽為 `[已遮蔽]`。
   * **病患姓名**：匹配「病患姓名：」、「患者：」等臨床前綴之姓名，遮蔽為 `[已遮蔽]`。
2. **價格全面屏蔽**：
   * 呼叫既有 `deep_mask_prices()`，所有具體數字金額（例如 `500元`、`NT$1,200`、`自費3000`）全面替換為 `[請致電診所確認]`。
3. **病患代碼偽名化 (`patient_token`)**：
   * 外部 `patient_id` 不得直接儲存於資料庫。
   * 系統透過 `generate_patient_token(patient_id, clinic_id)`，以 HMAC-SHA256 搭配 `CLINICBRAIN_ADMIN_API_KEY`（或預設 salt）計算不可逆匿名代碼。
4. **公開查詢嚴格隔離**：
   * 大眾匿名諮詢端點（`/api/v1/general/query`）與公開自然語言端點（`/api/v1/query`）完全不包含 `soap_records` 表的任何讀取或聯集查詢邏輯。

---

## 4. 資料庫架構與維護

### 4.1 表結構與 FTS5 觸發器 (`clinic.db`)

* `soap_records`：基礎資料表，唯一約束 `UNIQUE(clinic_id, external_id)`。
* `soap_records_fts`：SQLite FTS5 虛擬表，分詞指定 `tokenize='trigram'`。
* 觸發器：
  * `soap_records_ai`：INSERT 後自動寫入 FTS5。
  * `soap_records_ad`：DELETE 後自動刪除 FTS5 對應列。
  * `soap_records_au`：UPDATE 後自動重整 FTS5 索引。

### 4.2 正式資料庫手動遷移

正式環境 `clinic.db` 遷移不隨代碼部署自動執行。使用者需先手動備份：
```bash
cp clinic.db clinic.db.bak-$(date +%Y%m%d)
python3 scripts/migrate_soap_schema.py --confirm-prod-backup
```
* 遷移腳本直接動態解析 `src/db/clinic_schema.sql` 中的 DDL，落實單一事實來源（Single-Source-of-Truth）。
