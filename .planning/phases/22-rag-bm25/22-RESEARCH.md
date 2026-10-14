# Phase 22 Research: RAG 提問檢索優化、BM25 排序與結構化衛教生成

## 1. 現狀診斷與根因分析

### 1.1 檢索召回視野與排擠問題
- **問題**：`src/pageindex/rag_ask.py` 的 `retrieve_evidence` 將 FAQ 召回筆數固定為 `MAX_FAQ = 4`。
- **根因**：當知識庫內有上百筆相關主題問答時（例如目前甲溝炎相關 FAQ 有 123 筆），前 4 筆幾乎全為早期匯入的「門診處置（清創、指甲移除縫合）」等主題，導致「居家照護」、「日常溫水浸泡」、「直邊修剪防嵌甲」等生活衛教問答（如 ID 497）根本無法擠進 Top 4 Context。
- **解法**：Qwen 3.8-27B 擁有 128k 上下文視窗，將 `MAX_FAQ` 由 4 筆放寬至 **8 筆**，整體 Prompt Token 僅增加約 1,000 tokens（合計約 1,800~2,200 tokens），顯存與推論速度完全充裕。

### 1.2 全文檢索缺乏 BM25 排序
- **問題**：`src/query/search.py` 中的 `search_text` 透過 `rowid IN (SELECT rowid FROM fts_table WHERE fts_table MATCH ?)` 查詢。
- **根因**：
  1. SQLite 在執行 `rowid IN (...)` 時不保證維持子查詢的排序，且原本子查詢並未加入 `ORDER BY rank`。
  2. 預設回傳排序會退回以主表的 rowid 升冪（或 B-Tree 物理順序），導致 ID 2、3、16、17 永遠排在最前面，無法體現語意詞頻（BM25）相關度。
- **解法**：
  升級為 subquery JOIN 模式：
  ```sql
  SELECT {table}.*
  FROM {table}
  JOIN (
      SELECT rowid, rank FROM {fts_table} WHERE {fts_table} MATCH ?
  ) AS _fts ON {table}.rowid = _fts.rowid
  {where_clause}
  ORDER BY _fts.rank ASC
  LIMIT ?
  ```
  實測證實：`_fts` 僅含 `rowid` 與 `rank`，既能精準按 BM25 評分排序，又完全不會與 `{table}` 的欄位產生命名衝突（無 ambiguous column 名稱錯誤）。

### 1.3 多關鍵字聚合（Multi-Term Aggregation）缺乏權重
- **問題**：自然語言問句「甲溝炎要怎麼照護？」經 `extract_search_terms` 拆出 `['甲溝炎要', '甲溝炎', '照護']`。
- **根因**：原本 `_search_terms_merged` 逐詞查詢，當搜尋 `甲溝炎` 湊滿 `limit` 後即提早結束迴圈，導致後續修飾詞 `照護`（屬 2 字詞，走 LIKE 檢索）完全未被納入考量。
- **解法**：
  優化 `_search_terms_merged`：
  - 每個 term 都擷取候選並計算 term frequency / hit count。
  - 同時命中多個候選詞（例如同時包含「甲溝炎」與「照護」之問答，如 ID 497、81、504）給予最高優先權提升至最前列。

### 1.4 提問 Prompt 字數與格式受限
- **問題**：`build_ask_prompt` 寫死「約 100～250 字」，導致 LLM 僅能極簡濃縮。
- **解法**：
  調整 Prompt 規則：
  1. 長度放寬至 `約 250～400 字`。
  2. 格式引導：`請按【門診處置】、【日常照護】、【就醫提醒】分段說明`。
  3. 保留嚴格接地與醫療合規：禁止出現具體藥品名稱與劑量、無保證療效、深層價格屏蔽、引用編號標註。

---

## 2. 實測驗證結論

透過本機 Qwen 3.8-27B 實機測試包含 ID 497（居家照護）之新 Prompt：
- **生成回答**：成功產出分段之【門診處置】、【日常照護】（含溫水浸泡、拍乾、透氣鞋襪、直邊修剪防嵌甲、不共用指甲刀）、【就醫提醒】（紅腫發炎、化膿流膿儘速就醫）。
- **合規檢驗**：送入 `validate_single_faq(..., check_dosage=True)` 檢驗結果為 `(True, None)`（100% 合規通過，零處方洩漏）。
- **推論時間**：耗時約 30～45 秒，顯存與系統負載平穩。
