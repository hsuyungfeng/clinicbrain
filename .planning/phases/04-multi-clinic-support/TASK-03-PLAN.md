# Phase 04 TASK-03 實作規格：FAQ 快取查詢整合與多診所檢索分流

> 給執行者（Hermes）：本文件是 Phase 04 TASK-03 的**完整可執行規格**。
> 請嚴格依照本規格實作，**完成後請勿自行 commit**，請將執行結果交回，由檢查者（Antigravity/Claude）執行獨立驗證（執行測試、檢查 SHA-256、檢驗合規約束）後再行提交。
> 開始前請務必先閱讀根目錄之 `AGENTS.md`、`Plan.md` 及 `.planning/phases/04-multi-clinic-support/PLAN.md`。

---

## 1. 背景與任務目標

### 1.1 現況盤點
- **資料庫已具備資料**：`clinic.db` 中已有 `faq_cache` 表及對應的 FTS5 trigram 虛擬表 `faq_cache_fts`，並已寫入 40 筆經嚴格合規驗證的真實 FAQ（`source_type = 'clinic_upload'`，主題涵蓋自費門診手術、保險診斷書、客服話術）。
- **查詢層尚未串接**：
  - `src/query/search.py` 具備 `search_drugs()`, `search_service_items()`, `search_page_index_trees()`，但**缺少 `search_faq_cache()`**。
  - `src/query/router.py` 的統一查詢入口 `handle_query()` 回傳的 `QueryResponse` 結構中**沒有 `faq_hits` 欄位**，亦未對 `faq_cache` 進行檢索。
  - 當病患提問常見衛教與客服問題（如「瘦瘦筆可以用多久？」、「甲溝炎門診處置？」、「粉瘤怎麼治療？」）時，系統無法利用已建置的 40 筆真實 FAQ 回覆。

### 1.2 任務目標
1. 在 `src/query/search.py` 新增 `search_faq_cache()` 函式，遵循統一的 FTS5 trigram (3+ 字) 與 LIKE (2 字) 混合分流邏輯，並支援 `clinic_id` 與 `category` 過濾。
2. 在 `src/query/router.py` 的 `QueryResponse` dataclass 新增 `faq_hits: list` 欄位，並於 `handle_query()` 中串接 `search_faq_cache` 檢索與合併。
3. 嚴格貫徹多診所與路由資料隔離：
   - `route == "general"` 時，絕對不可洩漏任何特定診所專屬之 FAQ（僅能回傳 `clinic_id IS NULL` 且 `category == 'general'` 之項目）。
   - `route == "special"` 時，可檢索該 `clinic_id` 之專屬 FAQ 與通用 FAQ（`clinic_id = ? OR clinic_id IS NULL`）。
4. 嚴格貫徹合規要求：
   - 回傳之 `faq_hits` 中所有文字欄位必須經過 `mask_prices()` 價格遮蔽防禦。
   - 全繁體中文，嚴禁簡體字。
5. 擴充測試套件（新增 `tests/test_faq_search.py`），確保既有 123 個測試與新增測試全部通過，且正式 `clinic.db` 保持隔離（零污染）。

---

## 2. 嚴格約束 (CONSTRAINTS)

1. **不可變動正式資料庫**：所有測試必須使用 `tests/conftest.py` 提供的 `isolated_conn` 或暫存資料庫複本，測試前後正式 `clinic.db` 的 SHA-256 雜湊值必須完全一致。
2. **單一寫入路徑不變**：本任務為查詢層擴充，嚴禁修改 `src/pageindex/faq_writer.py` 與 `src/pageindex/db_writer.py` 的寫入原則。
3. **價格遮蔽強制性**：任何要封裝進 `QueryResponse` 回傳給呼叫端的文字，一律套用 `mask_prices()`。
4. **FTS5 trigram 斷詞限制**：3 字元以上才可使用 FTS `MATCH`；未滿 3 字元（如「粉瘤」、「肉毒」等 2 字詞）必須由 `_use_fts()` 分流至 `LIKE` fallback。
5. **SQL OR 條件括號保護**：在組合 `WHERE` 條件時，若涉及 `(clinic_id = ? OR clinic_id IS NULL)`，必須加上括號，避免與 `AND category = ?` 結合時破壞運算優先順序。

---

## 3. 詳細修改規格

### 3.1 `src/query/search.py` 修改

新增 `search_faq_cache` 函式：

```python
def search_faq_cache(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 10,
    clinic_id: Optional[str] = None,
    category: Optional[str] = None,
) -> list[SearchHit]:
    """檢索 faq_cache 資料表。
    
    支援依查詢字串長度自動分流（3+字走 faq_cache_fts，<3字走 LIKE）。
    支援依 clinic_id 及 category 進行權限與範圍過濾。
    
    過濾語意：
    - 若 clinic_id 有值（如 '3503190424'）：
        篩選條件為 (clinic_id = ? OR clinic_id IS NULL)
        參數帶入 (clinic_id,)
    - 若 clinic_id 為 None 且 category == 'general'：
        篩選條件為 (clinic_id IS NULL)
        無 clinic 參數帶入
    - 若 clinic_id 為 None 且 category is None（或 special）：
        不加 clinic 條件（向後相容或由呼叫端明確控制）
    - 若指定 category（如 'special' 或 'general'）：
        額外 AND category = ?
    """
```

**實作要求**：
- 呼叫既有的 `search_text()` 輔助函式：
  - `table = "faq_cache"`
  - `fts_table = "faq_cache_fts"`
  - `select_columns = ("id", "clinic_id", "topic_key", "category", "question", "answer")`
  - `like_columns = ("question", "answer")`
- 正確組裝 `extra_where` 與 `extra_params`：
  - 條件範例：`extra_conditions = []`, `params = []`
  - 若 `clinic_id` 存在：`extra_conditions.append("(clinic_id = ? OR clinic_id IS NULL)")`, `params.append(clinic_id)`
  - 若 `clinic_id` 為 `None` 且 `category == "general"`：`extra_conditions.append("clinic_id IS NULL")`
  - 若 `category` 存在：`extra_conditions.append("category = ?")`, `params.append(category)`
  - 若 `extra_conditions` 非空，以 `" AND ".join(extra_conditions)` 組合成 `extra_where`。

---

### 3.2 `src/query/router.py` 修改

#### 1. Import 更新
確認 `src/query/search.py` 匯出的 `search_faq_cache` 正確匯入至 `router.py`：
```python
try:
    from .search import (
        search_drugs,
        search_service_items,
        search_page_index_trees,
        search_faq_cache,
    )
except ImportError:
    from search import (
        search_drugs,
        search_service_items,
        search_page_index_trees,
        search_faq_cache,
    )
```

#### 2. `QueryResponse` 新增欄位
在 `QueryResponse` dataclass 增加 `faq_hits: list = field(default_factory=list)`：
```python
@dataclass
class QueryResponse:
    route: Route
    matched_keywords: list
    clinic_info: dict | None
    clinic_hours: list
    page_index_hits: list
    drug_hits: list
    service_item_hits: list
    clinic_custom_notes: dict = field(default_factory=dict)
    faq_hits: list = field(default_factory=list)  # 新增 FAQ 命中列表
```

#### 3. `handle_query()` 檢索與過濾邏輯更新
在 `handle_query()` 內部：
1. 檢索 `faq_cache`：
   ```python
   # 使用 _search_terms_merged 合併不同切詞之命中結果
   faq_hits = _search_terms_merged(
       search_faq_cache,
       conn,
       search_terms,
       limit,
       clinic_id=clinic_id if route_result.route == "special" else None,
       category="general" if route_result.route == "general" else None,
   )
   ```
2. 價格遮蔽保護：
   在現有對 `page_index_hits`, `drug_hits`, `service_item_hits` 執行 `mask_prices()` 的迴圈中，**一併將 `faq_hits` 納入**：
   ```python
   for hit_list in (page_index_hits, drug_hits, service_item_hits, faq_hits):
       for hit in hit_list:
           for key, value in hit.fields.items():
               if isinstance(value, str):
                   hit.fields[key] = mask_prices(value)
   ```
3. 回傳實例化：
   將 `faq_hits=faq_hits` 傳入 `QueryResponse` 回傳。

---

### 3.3 新增測試檔案 `tests/test_faq_search.py`

新增獨立測試檔案 `tests/test_faq_search.py`，使用 `isolated_conn` fixture 執行：

需包含以下測試函式：
1. `test_search_faq_cache_fts_match(isolated_conn)`:
   - 驗證 3 字以上關鍵字（如「瘦瘦筆」、「甲溝炎」）能透過 FTS5 MATCH 正確檢索到 FAQ。
2. `test_search_faq_cache_like_fallback(isolated_conn)`:
   - 驗證少於 3 字之關鍵字（如 2 字「粉瘤」）能正確透過 LIKE fallback 命中 `[FAQ #20]`。
3. `test_search_faq_cache_clinic_isolation(isolated_conn)`:
   - 在測試庫寫入一筆帶有假診所代碼（如 `other-clinic-999`）的 FAQ，並確認以 `clinic_id='3503190424'` 查詢時絕不會命中該筆資料。
4. `test_handle_query_special_faq_integration(isolated_conn)`:
   - 測試 `handle_query(conn, "瘦瘦筆可以用多久？", clinic_id="3503190424")`：
   - 驗證回傳之 `resp.faq_hits` 至少有 1 筆命中，且題目包含「瘦瘦筆」。
5. `test_handle_query_general_faq_isolation(isolated_conn)`:
   - 測試 `handle_query(conn, "一般醫療常識問題")`（走 general 路由）：
   - 驗證絕對不會回傳任何 `category == 'special'` 或 `clinic_id != None` 的私有 FAQ。
6. `test_handle_query_faq_price_masked(isolated_conn)`:
   - 驗證 `resp.faq_hits` 中任何可能含有價格字樣的欄位均被替換為 `[請致電診所確認]`。

---

## 4. 驗收核對清單 (Acceptance Criteria)

- [ ] `src/query/search.py` 實作 `search_faq_cache`，支援 FTS/LIKE 分流與過濾條件。
- [ ] `src/query/router.py` 的 `QueryResponse` 包含 `faq_hits`，`handle_query()` 正確調用並整合結果。
- [ ] 所有 `faq_hits` 欄位均通過 `mask_prices()` 遮蔽。
- [ ] 執行 `pytest tests/`，原有的 123 個測試與新增的 `tests/test_faq_search.py` 測試全數通過（無任何 regression）。
- [ ] 正式資料庫 `clinic.db` SHA-256 於測試執行前後完全一致。
- [ ] 程式碼註解、測試說明均使用繁體中文。
- [ ] 保持工作區未提交狀態，等候獨立驗收。
