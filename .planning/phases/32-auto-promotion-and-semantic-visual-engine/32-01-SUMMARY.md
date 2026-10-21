# 32-01 SUMMARY：診所核准即昇華一般醫學（已全部完成）

## 狀態
已全部完成。Task 1、Task 2、Task 3 均已實作，Python 層 `visible_assets` 與 `match.py:find_visual` 聯邦檢索守衛已由 Antigravity 完成放寬與隔離性驗證。

## 已完成
- `src/visual/review.py`
  - 新增 `visual_general_topic_key`、`promote_visual_row`。
  - `set_review_status` 在診所資產核准時自動昇華為 `clinic_id IS NULL` 的 approved 列，同一交易。
  - `visible_assets(None)` SQL 與 Python 守衛放寬：允許聯邦模式讀取已核准的診所資產，而指定診所模式（`clinic_id is not None`）仍嚴格隔離。
- `src/pageindex/tree_review.py`
  - 新增 `tree_general_doc_id`、`promote_tree`。
  - `approve_tree` 在診所推理樹核准時自動昇華為 `general-<slug>`。
- `src/visual/match.py`
  - `find_visual(conn, query, clinic_id=None)` 支援聯邦一般醫學查詢，於無一般專屬資產時安全回退至已核准的診所資產。
- `src/query/search.py`：`clinic_id=None` 時限定 `review_status='approved'`。
- `scripts/promote_clinic_assets_to_general.py`：一鍵昇華 CLI，支援 `--db`、`--clinic-id`、`--dry-run`、`--allow-prod-db`，單一交易、失敗整批回滾。
- `tests/test_auto_promotion.py`：15 項測試全數通過，全部使用隔離副本。

## 決策與設計對齊
- **推理樹 doc_id**：採 `general-<slug>`（符合 DB `UNIQUE(doc_id)` 約束）。
- **占位規則**：一般醫學列已存在且非同一診所昇華來源時冪等略過，絕不覆寫。
- **視覺 source_type**：沿用來源列之有效值（`manual` 或 `llm_generated`），符合 DB `CHECK` 約束。

## 驗證
- `tests/test_auto_promotion.py`：15 passed。
- `tests/test_visual_writer.py`、`tests/test_visual_match.py`：全數 passed。
- 零寫入正式庫保證：dry-run 測試於隔離副本執行，正式庫 sha256 恆定。
