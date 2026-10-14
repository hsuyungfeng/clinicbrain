# Phase 22 Plan 01 Summary: FTS5 BM25 相關度排序與多詞交集評分

## 執行成果概述
本計畫（Plan 22-01）完成對 `src/query/search.py` 與 `src/query/router.py` 的全文檢索能力升級，徹底解決了原本 SQLite FTS5 在缺乏 BM25 相關度排序下只能按主表 rowid 順序回傳、以及多詞檢索因提早截斷導致修飾詞（如「照護」）被忽視的問題：

1. **升級 `src/query/search.py:search_text`**：
   - 當走 FTS5 分流（`_use_fts(query) is True`，查詢長度 $\ge 3$）時，將原 `rowid IN (SELECT rowid ...)` 升級為 subquery JOIN 語法：
     ```sql
     SELECT {table}.{c1}, {table}.{c2}, ...
     FROM {table}
     JOIN (
         SELECT rowid, rank FROM {fts_table} WHERE {fts_table} MATCH ?
     ) AS _fts ON {table}.rowid = _fts.rowid
     {where_clause}
     ORDER BY _fts.rank ASC
     LIMIT ?
     ```
   - 確保 `extra_where` 欄位過濾（如 `clinic_id = ?`、`category = ?`、`visible_faq_sql`、`visible_tree_sql` 等）在 JOIN 架構下依然無歧義解析並正確生效。
   - 保留少於 3 字之 LIKE fallback 查詢行為不變。
2. **優化 `src/query/router.py:_search_terms_merged`**：
   - 解決多詞迴圈提早截斷問題：收集所有詞彙之候選結果（各詞上限設為 `cand_limit = max(limit, 20)`）。
   - 引入多詞命中加權排序（Multi-Term Intersection Boost）：
     - 同時命中越多搜尋詞的問答（例如同時命中「甲溝炎」與「照護」之 FAQ），優先權最高。
     - 次之按各檢索器之原始相關度（依詞序及檢索排名）排序。
     - 最後截斷至請求之 `limit` 筆數回傳。
   - 對單詞檢索無縫相容，完整保留單詞之 BM25 排名。
3. **單元與整合測試驗證 (`tests/test_rag_bm25_retrieval.py`)**：
   - 測試 BM25 排序生效：高相關度（高詞頻）之問答排在早期建立的低相關度問答前面。
   - 測試多詞交集加權：在真實 `clinic.db` 唯讀測試下驗證「甲溝炎要怎麼照護？」能精準將包含居家照護的 FAQ（如 ID 497 等）排進 Top 5。
   - 驗證 `search_drugs`、`search_service_items`、`search_page_index_trees`、`search_faq_cache` 均相容通過。
   - 驗證空查詢、純空白與負數/零 limit 等邊界條件。

## 測試覆蓋與驗證
- `pytest tests/test_rag_bm25_retrieval.py`：6 項專屬測試 100% 通過。
- `pytest tests/test_search.py tests/test_router.py tests/test_faq_search.py tests/test_api_query.py`：全數 PASS（71 passed）。
- 正式庫 `clinic.db` SHA-256 驗證：`0089ca28795fd0f0f2a41e9fa6b16f840ae794bfaf4e5597576410e9f0cf23db`，零資料污染。
