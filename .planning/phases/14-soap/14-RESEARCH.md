# Phase 14: 臨床語音與 SOAP 紀錄擷取 — 技術研究報告 (Technical Research Report)

本報告針對 **Phase 14 (臨床語音與 SOAP 紀錄擷取)** 進行深入代碼庫與架構探索，嚴格遵循 `AGENTS.md`、`14-CONTEXT.md` 及現有專案設計規範（單一權威寫入路徑、單一來源 DDL 遷移、FTS5 trigram 全文檢索、價格二次遮蔽、Fail-Closed API 認證、測試資料庫雜湊不變保證）。

---

## 1. Schema & FTS5 & Triggers 架構分析 (src/db/clinic_schema.sql)

### 1.1 現有 `page_index_trees` 與 `faq_cache` 結構借鏡
在 `src/db/clinic_schema.sql` 中：
- `page_index_trees`: 具備 `id INTEGER PRIMARY KEY AUTOINCREMENT`, `clinic_id TEXT REFERENCES clinic_info(clinic_id)`, `content_version`, `source_type`, `created_at`, `updated_at`。
- `faq_cache`: 具備 `id INTEGER PRIMARY KEY AUTOINCREMENT`, `clinic_id TEXT REFERENCES clinic_info(clinic_id)`, `UNIQUE(clinic_id, topic_key, question)` 自然鍵複合約束。

### 1.2 FTS5 虛擬表與 Trigram 分詞器語法
根據專案鐵則（`AGENTS.md` §2.3），SQLite FTS5 預設之 `unicode61` 分詞器無法分割中文，所有虛擬表**必須明確指定 `tokenize='trigram'`**。此外，外部內容表（External Content Table）需指定 `content='<base_table>'` 與 `content_rowid='id'`。

### 1.3 FTS5 同步觸發器語法（INSERT, DELETE, UPDATE）
SQLite FTS5 外部內容表的同步有嚴格的特殊語法：
- **INSERT 觸發器** (`_ai`):
  `INSERT INTO <fts_table>(rowid, cols...) VALUES (new.id, new.cols...);`
- **DELETE 觸發器** (`_ad`):
  `INSERT INTO <fts_table>(<fts_table>, rowid, cols...) VALUES ('delete', old.id, old.cols...);`（使用特製第一欄位名傳入 `'delete'`）
- **UPDATE 觸發器** (`_au`):
  先以 `'delete'` 刪除舊值索引，再重新 `INSERT` 新值索引。

### 1.4 Phase 14 提議之 `soap_records` 與 `soap_records_fts` DDL
根據 D-01, D-02, D-03 設計，建議於 `src/db/clinic_schema.sql` 中新增之完整 DDL 如下：

```sql
-- ========================================
-- SOAP Records Tables (Phase 14: 臨床語音與 SOAP 紀錄擷取)
-- ========================================

CREATE TABLE IF NOT EXISTS soap_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id TEXT NOT NULL REFERENCES clinic_info(clinic_id),
    external_id TEXT NOT NULL,               -- doctor-toolbox.com 外部記錄代碼
    patient_token TEXT NOT NULL,             -- 去識別化病患代號（匿名代號或雜湊）
    subjective TEXT,                         -- S: 主訴、病史、病患主觀陳述
    objective TEXT,                          -- O: 客觀檢查、生命徵象、理學檢驗
    assessment TEXT,                         -- A: 評估、診斷、鑑別診斷
    plan TEXT,                               -- P: 處置、衛教、醫囑、追蹤計畫
    raw_text TEXT NOT NULL,                  -- 原始推播文字（供臨床稽核校對）
    tags TEXT NOT NULL DEFAULT '',           -- 處置/科別/ICD-10標籤（字串或逗號分隔）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(clinic_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_soap_records_clinic_id ON soap_records(clinic_id);
CREATE INDEX IF NOT EXISTS idx_soap_records_external_id ON soap_records(external_id);
CREATE INDEX IF NOT EXISTS idx_soap_records_patient_token ON soap_records(patient_token);
CREATE INDEX IF NOT EXISTS idx_soap_records_created_at ON soap_records(created_at);

-- FTS5 for soap_records (trigram tokenizer for CJK matching)
CREATE VIRTUAL TABLE IF NOT EXISTS soap_records_fts USING fts5(
    subjective,
    objective,
    assessment,
    plan,
    tags,
    content='soap_records',
    content_rowid='id',
    tokenize='trigram'
);

-- Trigger for soap_records FTS updates
CREATE TRIGGER IF NOT EXISTS soap_records_ai AFTER INSERT ON soap_records BEGIN
    INSERT INTO soap_records_fts(rowid, subjective, objective, assessment, plan, tags)
    VALUES (new.id, new.subjective, new.objective, new.assessment, new.plan, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS soap_records_ad AFTER DELETE ON soap_records BEGIN
    INSERT INTO soap_records_fts(soap_records_fts, rowid, subjective, objective, assessment, plan, tags)
    VALUES ('delete', old.id, old.subjective, old.objective, old.assessment, old.plan, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS soap_records_au AFTER UPDATE ON soap_records BEGIN
    INSERT INTO soap_records_fts(soap_records_fts, rowid, subjective, objective, assessment, plan, tags)
    VALUES ('delete', old.id, old.subjective, old.objective, old.assessment, old.plan, old.tags);
    INSERT INTO soap_records_fts(rowid, subjective, objective, assessment, plan, tags)
    VALUES (new.id, new.subjective, new.objective, new.assessment, new.plan, new.tags);
END;
```

---

## 2. 單一權威寫入路徑模式 (Single Authority Writer Pattern)

### 2.1 現有 Writer 模式分析
- `src/pageindex/faq_writer.py`: `upsert_faqs(conn, faqs, source_type)`
- `src/clinic/custom_notes.py`: `upsert_clinic_note(conn, clinic_id, section, note)`
- `src/pageindex/db_writer.py`: `upsert_trees(conn, trees, source_type)`

共同設計原則：
1. **輸入前置驗證**：嚴格檢查非空參數與合法列舉值。
2. **唯一性比對 (Natural Key)**：查詢現存記錄。
3. **內容變更偵測 (Idempotence)**：比對內容 tuple，若無任何變更則計入 `unchanged`，不執行任何 SQL UPDATE（避免無意義觸發 FTS 虛擬表重寫）。
4. **顯式交易管理**：使用 `cursor` 操作，成功後統一 `conn.commit()`；發生錯誤時呼叫端回滾。
5. **更新時間戳記**：僅在實質內容異動時更新 `updated_at = CURRENT_TIMESTAMP`，保留 `created_at`。

### 2.2 提議實作：`src/soap/soap_writer.py`
遵循此模式實作 `upsert_soap_records(conn, records, clinic_id)`，輸入為字典清單，進行參數檢查、比對、插入或更新，回傳 `(inserted, updated, unchanged)` 元組。

---

## 3. API 路由與相依注入架構 (src/api/routes/soap.py & models)

### 3.1 權限與連線隔離原則
- **管理者認證**：依賴 `src/api/dependencies.py:verify_admin_key`（未設定金鑰且無開發旗標時回傳 503，有金鑰但比對失敗回傳 401）。
- **寫入連線**：使用 `get_write_db`（支援交易與 `foreign_keys = ON`）。
- **讀取連線**：使用 `get_read_db`（底層強制 `PRAGMA query_only = ON;`，防意外寫入）。
- **二次價格防禦**：調用 `src/api/routes/query.py:deep_mask_prices()` 進行遞迴金額遮蔽。
- **公開查詢隔離**：`/api/v1/query` 與 `/api/v1/general/query` 絕不觸碰 `soap_records`（D-08）。

### 3.3 路由架構
- `POST /api/v1/soap/records` — 接收 doctor-toolbox.com 推播（`verify_admin_key` + `get_write_db`）。
- `POST /api/v1/soap/search` — 院所醫師專用全文檢索（`verify_admin_key` + `get_read_db`，限同 `clinic_id` 範圍）。
- `GET /api/v1/soap/records/{external_id}` — 取得單筆 SOAP 紀錄（`verify_admin_key` + `get_read_db`）。

---

## 4. 原始轉錄文字 S/O/A/P 結構化切分器 (Section Parser)

針對呼叫端僅傳入 `raw_text` 或 `transcript` 的彈性情境（D-05），需於 `src/soap/section_parser.py` 實作確定性正規表達式切分器。

### 4.1 台灣臨床常用段落標記彙整
- **Subjective (S)**: 英文縮寫 `S/Subj/Subjective`；中文 `主訴/主訴問題/病史/病人主訴/病患主訴/自覺症狀/現病史`。
- **Objective (O)**: 英文縮寫 `O/Obj/Objective`；中文 `客觀檢查/客觀發現/理學檢查/體檢/檢驗/檢查/生命徵象`。
- **Assessment (A)**: 英文縮寫 `A/Ass/Assessment`；中文 `評估/診斷/鑑別診斷/臨床診斷/醫師評估/初步診斷`。
- **Plan (P)**: 英文縮寫 `P/Plan`；中文 `計畫/處置/治療計畫/醫囑/用藥/處方/衛教/追蹤計畫`。

### 4.2 切分器規則
- 優先使用傳入已有的 S/O/A/P 結構。
- 若僅有 raw_text，使用行首標記比對。
- 無法辨識部分 fallback 歸入 `subjective`，`raw_text` 永遠完整保留。

---

## 5. 病患代號生成與去識別化守衛 (De-identification)

醫療合規鐵則（`14-CONTEXT.md` D-07 與 `AGENTS.md` §3）：**嚴禁明文身分證字號、姓名、電話、病歷號入庫或記錄日誌**。

### 5.1 台灣個資正規表達式清單
- **身分證統一編號 / 居留證號**: `r"\b[A-Z][1289A-D]\d{8}\b"`
- **行動電話**: `r"\b09\d{2}[-\s]?\d{3}[-\s]?\d{3}\b|\b09\d{8}\b"`
- **市話號碼**: `r"\b0\d{1,2}[-\s]?\d{7,8}\b"`
- **出生年月日**: 民國/西元年正規化檢查
- **姓名與稱謂標記**: `r"(?:姓名|病患|患者)[：:\s]*([\u4e00-\u9fa5]{2,4})"`

### 5.2 `patient_token` 衍生與文字清洗策略 (`src/soap/deid.py`)
- **Token 衍生**：若外部提供明文 `patient_id` 或身分證號，採用以診所為範疇之 HMAC-SHA256 遮蔽：
  `token = "PTK-" + hmac.new(b"clinicbrain_salt", patient_id.encode(), hashlib.sha256).hexdigest()[:12]`
- **文字遮蔽**：在寫入 `raw_text` 與 S/O/A/P 之前，將內文所有匹配個資置換為 `[身分證已遮蔽]`、`[電話已遮蔽]`、`[姓名已遮蔽]`，配合 `deep_mask_prices()` 遮蔽金額為 `[請致電診所確認]`。

---

## 6. 單一來源 DDL 遷移模式 (Single-source DDL Migration)

### 6.1 參照 `migrate_cache_stats.py`
專案鐵則要求：**遷移腳本嚴禁硬編碼 DDL**，必須直接讀取 `src/db/clinic_schema.sql` 擷取目標區塊。
實作 `scripts/migrate_soap_schema.py`，支援 `--db`, `--dry-run`, `--confirm-prod-backup` 參數。

---

## 7. 測試架構與驗收規劃 (Test Fixtures & Acceptance Tests)

### 7.1 Fixtures 設定 (`tests/conftest.py`)
擴充 `_ensure_soap_records(db_path: Path)`，在測試時自動將 SOAP schema 套用到測試複本。

### 7.2 核心驗收測試清單
1. **FTS5 Trigram 與 Triggers 同步測試 (`test_soap_triggers_sync`)**:
   - INSERT / UPDATE / DELETE 驗證 `soap_records_fts` 自動同步。
2. **價格全面遮蔽測試 (`test_soap_price_masking`)**:
   - 價格清洗為 `[請致電診所確認]`。
3. **段落切分器測試 (`test_soap_section_parser`)**:
   - 結構化 JSON vs 中文臨床標記純文字 vs 無標記純文字。
4. **冪等 UPSERT 測試 (`test_soap_idempotent_upsert`)**:
   - 重複推播不重複寫入，內容異動版本遞增。
5. **API 認證與診所隔離測試 (`test_soap_api_auth_and_isolation`)**:
   - 401 拒絕無金鑰，跨診所資料嚴格隔離。
6. **醫師臨床檢索測試 (`test_soap_doctor_search`)**:
   - 症狀/處置 trigram 全文檢索。
7. **正式庫雜湊不變保證 (`test_prod_db_sha256_unmodified`)**:
   - 正式庫 SHA-256 全程保持基準值。
