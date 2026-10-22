# 34-01 SUMMARY：黃金測試集（完成）
- `data/visual/golden/tree_blueprints_49.json`：49 筆，由唯讀匯出腳本產生（分布與報告一致）。
- `tests/test_visual_golden_49.py`：7 項通過；含能量儀器不得判為外科的回歸測試。
- 變異驗證：暫時以錯誤推斷取代，測試失敗並指出 doc_id（以 monkeypatch 完成，未改原始碼）。
- 發現：黃金檔只需 doc_id 與 title 即可完全重現推斷結果（0 筆不同）。
