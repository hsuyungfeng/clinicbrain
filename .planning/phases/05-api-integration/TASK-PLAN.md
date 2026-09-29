# Phase 05 詳細任務實作計畫：FastAPI 服務層與 doctor-toolbox.com 官方雙向同步契約 (TASK-PLAN.md)

> **給執行者（LLM / Coding Agent）**：
> 本文件是 **Phase 05** 的詳細可執行規格書。請在開始實作前仔細研讀 `AGENTS.md`、`.planning/HANDOFF.json` 與 `.planning/phases/05-api-integration/PLAN.md`。
> 所有實作必須維持繁體中文、絕對價格遮蔽、單一權威寫入路徑、測試資料庫 100% 隔離等強制性原則。

---

## 1. 任務概要與執行順序

Phase 05 共拆解為 4 個循序遞進的任務：

| 任務編號 | 模組 / 功能 | 核心目標 | 產出檔案 |
|---|---|---|---|
| **TASK-01** | FastAPI 基礎骨架、組態與健康檢查 | 建立 FastAPI 應用實例、Pydantic 基底模型、唯讀/寫入連線注入與 `GET /health` 端點 | `src/api/config.py`, `src/api/dependencies.py`, `src/api/models/`, `src/api/routes/health.py`, `src/api/app.py`, `tests/test_api_health.py` |
| **TASK-02** | 自然語言查詢端點封裝 | 封裝 `src/query/router.py:handle_query()` 為標準 HTTP 端點，支援多診所解析與價格二次遮蔽 | `src/api/models/query.py`, `src/api/routes/query.py`, `tests/test_api_query.py` |
| **TASK-03** | doctor-toolbox.com 雙向同步契約 | 實作 `POST /api/v1/sync/export` 與 `POST /api/v1/sync/import`，增量同步樹/FAQ/備註，並記錄 `sync_logs` | `src/db/clinic_schema.sql` (增補 sync_logs), `src/api/models/sync.py`, `src/api/routes/sync.py`, `tests/test_api_sync.py` |
| **TASK-04** | 端到端整合驗證與服務啟動器 | 整合全套 pytest 測試、驗證正式 `clinic.db` SHA-256 零變更，提供啟動腳本與服務範本 | `scripts/run_api_server.py`, `clinicbrain-api.service` (範本), 完整回歸驗收報告 |

---

## 2. 具體任務規格

### TASK-01：FastAPI 基礎骨架、組態與健康檢查

#### 1. 環境相依確認
- 系統環境需確認具備 `fastapi`, `uvicorn`, `pydantic` 與 `httpx`（測試專用）。若環境缺少，需透過 pip/uv 進行非破壞性安裝。

#### 2. 組態管理 (`src/api/config.py`)
```python
import os
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class APIConfig:
    host: str = os.getenv("CLINICBRAIN_HOST", "127.0.0.1")
    port: int = int(os.getenv("CLINICBRAIN_PORT", "8000"))
    default_clinic_id: str = os.getenv("CLINICBRAIN_DEFAULT_CLINIC_ID", "3503190424")
    admin_api_key: Optional[str] = os.getenv("CLINICBRAIN_ADMIN_API_KEY", None)
    db_path: str = os.getenv("CLINICBRAIN_DB_PATH", "clinic.db")
    enable_docs: bool = os.getenv("CLINICBRAIN_ENABLE_DOCS", "true").lower() in ("true", "1", "yes")

config = APIConfig()
```

#### 3. 相依注入與連線管理 (`src/api/dependencies.py`)
- `get_read_db()`: 產出 SQLite 唯讀連線。在建立連線後執行 `PRAGMA query_only = ON;`，避免查詢端點發生意外寫入。
- `get_write_db()`: 產出 SQLite 寫入連線，提供 Sync Import 使用。
- `verify_admin_key(x_api_key: Optional[str] = Header(None))`: 若 `config.admin_api_key` 有設定，則強制比對 `X-API-Key` 標頭；若未設定則在開發/本地模式下允許通過（或標記為免認證）。

#### 4. 資料模型與路由實作 (`src/api/models/common.py` 與 `src/api/routes/health.py`)
- `HealthResponse`:
  - `status`: "ok" | "degraded" | "error"
  - `database_connected`: bool
  - `tables_count`: dict[str, int] (包含 drugs, service_items, page_index_trees, faq_cache, clinic_info, clinic_hours, clinic_custom_notes)
  - `llm_available`: bool
  - `version`: str
- `app.py`:
  - 建立 FastAPI 實例，註冊 CORS 中介軟體（預設允許本機 Private Network），掛載 health 路由。
- **測試**：`tests/test_api_health.py` 透過 `TestClient` 驗證 `GET /health` 回應 200，且欄位齊全。

---

### TASK-02：自然語言查詢端點封裝 (`handle_query` 整合)

#### 1. 查詢請求與回應模型 (`src/api/models/query.py`)
```python
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="自然語言查詢問題")
    clinic_id: Optional[str] = Field(None, description="台灣健保特約醫事機構代碼（10碼），如 3503190424")
    limit: int = Field(10, ge=1, le=50, description="最大檢索筆數")

class SearchHitField(BaseModel):
    id: Any
    score: float
    match_type: str
    fields: Dict[str, Any]

class ClinicHoursItem(BaseModel):
    day_of_week: str
    morning_start: Optional[str] = None
    morning_end: Optional[str] = None
    afternoon_start: Optional[str] = None
    afternoon_end: Optional[str] = None
    evening_start: Optional[str] = None
    evening_end: Optional[str] = None
    is_open: bool = True

class QueryResponseModel(BaseModel):
    query: str
    route: str = Field(..., description="'special' (特化療程/診所資訊) 或 'general' (健保通用藥品/服務項目)")
    reasoning: str
    clinic_info: Optional[Dict[str, Any]] = None
    clinic_hours: List[ClinicHoursItem] = Field(default_factory=list)
    page_index_hits: List[SearchHitField] = Field(default_factory=list)
    drug_hits: List[SearchHitField] = Field(default_factory=list)
    service_item_hits: List[SearchHitField] = Field(default_factory=list)
    clinic_custom_notes: Dict[str, str] = Field(default_factory=dict)
    faq_hits: List[SearchHitField] = Field(default_factory=list)
```

#### 2. 查詢路由設計 (`src/api/routes/query.py`)
- **端點 1**：`POST /api/v1/query`
  - 優先順序取得 `clinic_id`：Request Body `clinic_id` > Header `X-Clinic-ID` > `config.default_clinic_id`（若請求為空且路由為 special，可 fallback 或報錯）。
  - 核心邏輯：
    ```python
    try:
        response = handle_query(conn, request.query, clinic_id=effective_clinic_id, limit=request.limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ```
  - **二次價格防禦**：回傳前遞迴檢查所有字串欄位是否已完全遮蔽金額數值（`mask_prices`），杜絕漏網之魚。
- **端點 2**：`POST /api/v1/clinics/{clinic_id}/query`
  - 將 URL Path 中的 `clinic_id` 直接綁定帶入，強化多診所路徑隔離語意。
- **端點 3**：`GET /api/v1/query`
  - 支援 `?q=...&clinic_id=...&limit=...`，便於快速 GET 驗證。

#### 3. 測試規格 (`tests/test_api_query.py`)
- 測試案例 1：音波拉提查詢（`special` 路由），驗證命中 `page_index_hits` 或 `faq_hits`，且含有診所資訊。
- 測試案例 2：普拿疼/乙醯胺酚查詢（`general` 路由），驗證命中 `drug_hits`，且診所資訊嚴格為空。
- 測試案例 3：未提供 `clinic_id` 且查詢為 `special` 關鍵字（如「營業時間」），驗證回傳 HTTP 400 錯誤。
- 測試案例 4：價格遮蔽斷言——掃描整個 JSON 回應，斷言無 `[0-9]+元`、`NT\$` 存在。

---

### TASK-03：doctor-toolbox.com 雙向資料同步契約實作

#### 1. 資料庫結構升級 (`src/db/clinic_schema.sql`)
增補同步審計紀錄表：
```sql
CREATE TABLE IF NOT EXISTS sync_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id TEXT REFERENCES clinic_info(clinic_id),
    sync_type TEXT NOT NULL,         -- 'export' | 'import'
    direction TEXT NOT NULL,         -- 'push' | 'pull'
    status TEXT NOT NULL,            -- 'success' | 'failed' | 'partial'
    record_count INTEGER DEFAULT 0,
    payload_summary TEXT,            -- 簡要摘要（嚴禁記錄病患個資與具體價格）
    error_message TEXT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sync_logs_clinic_id ON sync_logs(clinic_id);
CREATE INDEX IF NOT EXISTS idx_sync_logs_started_at ON sync_logs(started_at);
```

#### 2. 同步資料模型 (`src/api/models/sync.py`)
- `SyncExportRequest`:
  - `clinic_id`: str (例如 `'3503190424'`)
  - `since_version`: Optional[int] = 0 (用於增量匯出)
  - `entities`: List[str] = `["trees", "faqs", "notes", "hours"]`
- `SyncExportResponse`:
  - `clinic_id`: str
  - `exported_at`: str (ISO 8601)
  - `counts`: Dict[str, int]
  - `data`: Dict[str, Any]
- `SyncImportRequest`:
  - `clinic_id`: str
  - `data`: Dict[str, Any] (包含欲更新的 notes, faqs, trees_physician_notes, hours)
- `SyncImportResponse`:
  - `success`: bool
  - `sync_id`: int
  - `summary`: Dict[str, int]
  - `message`: str

#### 3. 匯出邏輯實作 (`POST /api/v1/sync/export`)
- 讀取符合 `clinic_id` 與 `content_version >= since_version` 的 `page_index_trees` 與 `faq_cache`。
- 讀取 `clinic_custom_notes` 與 `clinic_hours`。
- **匯出安全規則**：對匯出的所有衛教與問答欄位統一執行 `mask_prices()`，確保即使本地有未遮蔽的草稿，匯出至雲端時也絕對安全。
- 記錄至 `sync_logs`（`sync_type='export', direction='pull', status='success'`）。

#### 4. 匯入邏輯實作 (`POST /api/v1/sync/import`)
- 驗證金鑰（`verify_admin_key`）。
- **資料合規清洗與驗證**：
  1. 繁中轉換：若傳入簡體中文內容，自動經由 `opencc` (`s2twp`) 轉為台灣繁體，或驗證繁體字。
  2. 價格防禦：若在非價格欄位發現具體促銷金額，直接拒絕或清洗。
  3. 保證療效詞語檢查（禁止「保證根除」、「百分之百有效」）。
- **呼叫唯一權威寫入函式**：
  - 臨床推理樹更新：呼叫 `src/pageindex/db_writer.py:upsert_trees(conn, trees, source_type='clinic_upload')`。
  - FAQ 更新：呼叫 `src/pageindex/faq_writer.py:upsert_faqs(conn, faqs, source_type='clinic_upload')`。
  - 診所備註更新：呼叫 `src/clinic/custom_notes.py:upsert_clinic_note(conn, clinic_id, section, note)`。
  - 門診時間更新：在同一個 transaction 中比對更新。
- 記錄至 `sync_logs`，並回傳異動結果。

#### 5. 測試規格 (`tests/test_api_sync.py`)
- 測試 Export：驗證 `since_version` 增量過濾、資料欄位齊全度。
- 測試 Import：驗證寫入後 `content_version` 正常遞增、冪等寫入第二次不重複增加。
- 測試 Import 安全攔截：傳入違法保證療效詞語時，預期拋出適當錯誤或過濾。

---

### TASK-04：端到端整合驗證與服務啟動器

#### 1. 啟動入口腳本 (`scripts/run_api_server.py`)
- 提供 CLI 參數（`--host`, `--port`, `--reload`），方便本機直接啟動：
  ```bash
  python3 scripts/run_api_server.py --port 8000
  ```

#### 2. Systemd 服務單元範本 (`clinicbrain-api.service`)
- 提供標準 systemd user service 配置，與現有 `llama-server.service` 同步管理。

#### 3. 測試總體驗收標準
- 執行 `pytest tests/`：所有新增 API 測試與既有 128 個測試全部 PASS（總數約 145+）。
- 驗證正式 `clinic.db` SHA-256：
  ```bash
  sha256sum clinic.db
  # 必須維持為 c51cc4d039379fe00f70d7864b29a952928233fa6caa6e72954900f4c28c65ad
  ```

---

## 3. 開發邊界與非目標 (Out of Scope)

1. **非目標：MITM 封包攔截**
   - 舊系統 `DrtoolboxLocalServer` 透過 mitmproxy 攔截瀏覽器對 `doctor-toolbox.com` 的請求，本 Phase 嚴格禁止使用此做法，一律採用標準 RESTful API。
2. **非目標：病患掛號或病歷隱私資料寫入本地**
   - 健保申報系統之完整病歷（EMR/HIS）不在 clinicbrain 知識庫管轄範圍內。clinicbrain 專注於「臨床推理樹、衛教 FAQ、門診時間、自訂備註與藥品給付」之同步。
3. **非目標：公網暴露（Public Internet Exposure）**
   - 預設一律綁定 `127.0.0.1`。若雲端需要推播同步，應透過安全通道（如 Cloudflare Tunnel、Tailscale 或診所反向代理）轉發，本 API 自身不開放外部未經保護之公網存取。
