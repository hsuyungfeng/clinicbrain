---
phase: 07-cache-first-query
status: passed
verified: 2026-09-30
verifier: Claude（與執行者 antigravity 分離的獨立驗證）
requirements: [CACHE-01, CACHE-02, CACHE-03, CACHE-04]
---

# Phase 7 驗證報告：快取優先查詢

## 成功標準對照

| 需求 | 結果 | 證據 |
|---|---|---|
| CACHE-01 高信心 FAQ 短路 | ✅ | 正式庫複本實測：40 筆 FAQ 以原文查詢，24 筆短路（`source=cache`），符合預期上限 24/40；另在真實服務上查「甲溝炎門診處理包含哪些內容？」回 `source: cache` |
| CACHE-02 source 欄位 | ✅ | 回應含 `source`（cache/pageindex）與 `cache_answer`；既有 `test_api_query.py` 未修改且全過 |
| CACHE-03 匿名統計 | ✅ | 在問句塞入 `PRIVATE-MARK-XYZ`、姓名、手機後查詢，`cache_stats` 整表 dump 無外洩；表內只有 outcome 與白名單關鍵字；營運問句不記 miss |
| CACHE-04 價格遮蔽 | ✅ | `tests/test_api_cache_first.py` 以含金額 FAQ 驗證輸出零價格數字 |

## 醫療安全實測（誤短路風險）
- 24 個對抗變形（術前／術後、可以／不可以、需要／不需要）：**零誤短路**。
- 測試先斷言「覆蓋率單獨就能通過門檻」，再斷言風險特徵檢查擋下，證明風險檢查有效。

## 其他驗證
- 全量 288 passed（獨立重跑）；正式庫在驗證當下無 `cache_stats` 表、筆數不變；後由使用者手動遷移並於 2026-10-01 重做一次。
- `tests/test_api_query.py`、`tests/test_router.py` 無修改（git diff 為空）。

## 已知缺口（技術債）
- 短路命中率上限約 60%：16/40 筆 FAQ 問句不含路由關鍵字，被分流為 general，不檢索 special FAQ（使用者決策接受）。
- 風險字集刻意寬鬆，釋義式問法多半不短路（保守設計取捨）。
- `GET /api/v1/query?q=` 仍會在 uvicorn access log 留下問句；統計寫入因公開端點可被灌數，僅供營運參考。
- 統計寫入每次請求最多多等 0.5 秒（資料庫被鎖時）。
