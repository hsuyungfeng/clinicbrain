# Phase 47 Research — 實作前技術盤點

## 1. `LIKE` 萬用字元跳脫現況
- `src/api/routes/soap.py:60` 已實作 `ESCAPE '\\'` 跳脫 `%` 與 `_`。
- `src/query/search.py:99`（`where_clause = "(" + " OR ".join(f"{col} LIKE ?" for col in like_columns) + ")"`）與 `src/query/nhi_index.py:72`（`WHERE (c.name LIKE ? ...)`）未跳脫 `%` 與 `_`，輸入 `%` 會退化為全表掃描。
- **解法**：在 `src/query/search.py` 抽出 `escape_like(term: str) -> str`，統一供 `search.py` 與 `nhi_index.py` 使用並加上 `ESCAPE '\\'`。

## 2. `llm_client.py` 連線與組態
- `src/pageindex/llm_client.py` 目前將 `LLM_ENDPOINT` / `MODELS_ENDPOINT` 寫死 `http://127.0.0.1:8080`，且每次 `local_llm_call()` 皆先以 `urllib.request.urlopen` 請求 `/v1/models`。
- **解法**：改讀 `os.getenv("CLINICBRAIN_LLM_BASE_URL", "http://127.0.0.1:8080")`（保留模組常數向後相容），使用模組級 `httpx.Client` 連線池，將 `/v1/models` 探測改為快取 TTL（或僅失敗診斷）。

## 3. 單體檔案拆分對象
- `src/api/routes/admin.py`（1,888 行）：可拆為 `src/api/routes/admin/` 子套件，保留 `admin/__init__.py` 匯出同一個 `router` 給 `src/api/app.py`，對外零破壞。
- `src/batch/runner.py`（`run_batch` 503 行）：可定義 `BatchStage` dataclass / protocol，統一處理 `dry_run`、`time_budget` 與例外隔離。
- `src/visual/autodraft.py`（`parse_and_build_tree_ir` 577 行）：可按 Scene 1 / Scene 2 / Scene 3 拆出獨立純函式。

## 4. 離線化與遷移統一
- `src/web/static/index.html:8` 載入 `https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css`。可將該 CSS 下載或抽取出專案實際使用的樣式置於 `src/web/static/tailwind.min.css`，並更新 `src/api/app.py` CSP。
- `scripts/migrate_*.py` 共 9 支，各自檢查表／欄位存在性。可建立 `scripts/migrate.py`（支援 `--status` / `--apply`）與 `schema_migrations` 表，將既有 9 支包裝為具冪等性的遷移步驟。
