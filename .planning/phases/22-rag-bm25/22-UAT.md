---
status: testing
phase: 22-rag-bm25
source:
  - .planning/phases/22-rag-bm25/22-01-SUMMARY.md
  - .planning/phases/22-rag-bm25/22-02-SUMMARY.md
  - .planning/phases/22-rag-bm25/22-03-SUMMARY.md
started: "2026-10-14T13:20:00+08:00"
updated: "2026-10-14T13:25:00+08:00"
---

## Current Test

number: 2
name: FTS5 BM25 相關度排序與多詞交集加權
expected: |
  在 Web 管理介面（http://127.0.0.1:8000/admin/）「💬 向 LLM 提問」分頁：
  1. 輸入複合詞問句：「甲溝炎居家護理」或「甲溝炎微創手術」，點選「💬 送出提問」。
  2. 觀察下方「模型可見的資料來源」：
     - 若問「甲溝炎居家護理」：排在最前列（[F1]、[F2]）應精準為居家護理、家庭治療相關問答（如 ID 497 等），而非無關的手術問答。
     - 若問「甲溝炎微創手術」：排在最前列應精準為門診處置、手術治療相關問答。
  3. 驗證多關鍵字命中交集加權生效，修飾詞意圖未被截斷。
awaiting: user response

## Tests

### 1. Web 介面甲溝炎照護提問與居家護理來源召回
expected: |
  提問「甲溝炎要怎麼照護？」能召回包含 ID 497 之 8 筆 Context，輸出【門診處置】、【日常照護】與【就醫提醒】之結構化衛教，通過合規檢核。
result: pass

### 2. FTS5 BM25 相關度排序與多詞交集加權
expected: |
  查詢複合意圖詞彙（例如「甲溝炎居家護理」或「甲溝炎微創手術」）能精準將同時命中兩詞之問答排在最前列（[F1]、[F2]），修飾詞未遭截斷。
result: pending

### 3. 對抗性特殊符號與 SQL 邊界輸入防護
expected: |
  輸入帶未閉合引號、冒號或特殊標點（例如 `甲溝炎："照護"`、`雷射:手術` 或純空白）不拋出 500 錯誤或 SQLite syntax error，安全優雅退回 LIKE fallback 或回傳無資料。
result: pending

## Summary

total: 3
passed: 1
issues: 0
pending: 2
