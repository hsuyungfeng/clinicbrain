# Phase 21 Research: 臨床決策推理樹 (PageIndex Trees) 自動提煉、審核與檢索擴展

## 1. 既有架構與資料表分析

### 1.1 `page_index_trees` 現狀
目前 schema 欄位如下：
```sql
CREATE TABLE IF NOT EXISTS page_index_trees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT UNIQUE,              -- 療程 slug (如 botox-injection)
    clinic_id TEXT REFERENCES clinic_info(clinic_id),
    category TEXT NOT NULL,          -- 'special' or 'general'
    pre_op TEXT,                     -- 術前須知與評估
    pre_op_physician_notes TEXT,     -- 醫師權威指令 (LLM 禁動，醫師手填)
    procedure TEXT,                  -- 療程步驟與原理
    procedure_physician_notes TEXT,  -- 醫師權威指令
    post_op_short TEXT,              -- 術後立即照護
    post_op_short_physician_notes TEXT, -- 醫師權威指令
    maintenance TEXT,                -- 長期維持與保養
    maintenance_physician_notes TEXT, -- 醫師權威指令
    summary_text TEXT,               -- Combined summary for FTS
    version TEXT DEFAULT '2.0',
    source_type TEXT DEFAULT 'manual',
    content_version INTEGER NOT NULL DEFAULT 1,
    needs_regeneration BOOLEAN NOT NULL DEFAULT 0,
    indexed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```
**關鍵觀察**：
- 缺少 `review_status`（'pending', 'approved', 'rejected'），導致任何寫入若非人工手寫即可能直接對外暴露。
- 缺少 `title` 欄位：目前只有 `doc_id` slug（如 `fractional-laser`），在介面上對醫師不夠直覺友善（例如「飛梭雷射痘疤毛孔微創修復療程」）。
- 缺少 `reviewed_at` 與 `reviewed_by` 審計欄位。

### 1.2 權威寫入與觸發器機制
- 寫入函式：`src/pageindex/db_writer.py:upsert_trees()` 為唯一權威寫入函式，實作了增量比對、版號遞增（`content_version`）與清除 `needs_regeneration`。
- FTS5 觸發器：`page_index_ai` / `page_index_ad` / `page_index_au` 在 INSERT/UPDATE/DELETE 時自動同步維護 `page_index_fts(rowid, summary_text)`。
- **Fail-Closed 審核隔離需求**：
  在 `src/query/search.py:search_page_index_trees()` 中，需透過 `visible_tree_sql(conn)` 限制只有 `review_status = 'approved'`（或舊版無欄位時的 manual 紀錄）能被檢索出來。未核准之草稿即使存在於主表，亦不可由病患公開查詢讀取。

### 1.3 LLM 提煉與 Prompt 規範
- 既有 `src/pageindex/prompt_template.py` 具備完備的驗證邏輯：
  - `parse_and_validate()` 檢驗：JSON 格式、繁體中文無簡體字、無保證療效禁詞、無價格洩漏數字、欄位完整性。
  - 醫師指令（`*_physician_notes`）強制由 `to_upsert_row()` 置為 `None`。
- **推論長度優化**：
  Phase 20 的重大經驗指出，必須在 Prompt 開頭明確加入：
  `"思考過程請保持簡潔（不超過 100 字），直接輸出繁體中文 JSON 結果"`，避免 Qwen-27B 耗盡 6,144 token 導致截斷為空。

---

## 2. 模組職責劃分

| 模組 | 角色 | 具體任務 |
| :--- | :--- | :--- |
| `scripts/migrate_page_index_review.py` | 遷移腳本 | 冪等增加 `review_status`, `reviewed_at`, `reviewed_by`, `title` 欄位 |
| `src/pageindex/tree_review.py` | 審核邏輯庫 | 提煉審核核心：`list_trees`, `get_tree`, `update_tree`, `approve_tree`, `reject_tree`, `visible_tree_sql` |
| `src/pageindex/tree_distiller.py` | 提煉引擎 | 整合文件解析與本地 LLM，將長篇醫療內文提煉成四段式決策樹草稿 |
| `src/query/search.py` | 檢索過濾 | `search_page_index_trees` 加入審核可見性 SQL 過濾 |
| `src/api/routes/admin.py` | 後端管理 API | 提供決策樹查詢、提煉、編輯、簽核與駁回端點 |
| `src/web/static/` | Web 管理介面 | 新增「🌳 臨床決策樹簽核」分頁，支援四段卡片檢視、醫師醫囑填寫與簽核 |

---

## 3. 多 Agent 流水線執行計劃（User Golden Rule）

1. **Agy 3.6 Flash (`w5:p2`)**：
   - 執行 Plan 21-01：資料庫遷移、`tree_review.py`、`tree_distiller.py`、搜尋層隔離與後端 API 端點。
   - 執行 Plan 21-02：Web 前端介面（HTML/JS/CSS）擴充與整合。
2. **Claude 5.5 Sonnet (`w5:p3`)**：
   - 執行 Plan 21-03 審查與加固：
     - 檢查併發 GPU 鎖與交易隔離。
     - 檢查醫療合規（醫師指令留空、價格屏蔽）。
     - 撰寫對抗性加固測試 `tests/test_phase21_hardening.py`。
     - 更新規範文件 `AGENTS.md`。
3. **Hermes Agent (`w5:p4`)**：
   - 執行終端全套回歸測試。
   - 驗證正式庫 `clinic.db` SHA-256 恆定。
   - 產出 PASS 報告。
