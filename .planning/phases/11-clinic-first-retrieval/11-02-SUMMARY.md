# Phase 11 Plan 02 Summary: router.py 接線 clinic-first 檢索、短路與 data_level

## 執行成果概述
本計畫（11-02）完成 `src/query/router.py` 的診所資料優先檢索（Clinic-First）與跨層級短路接線，並修復無 `clinic_id` 時之跨診所 FAQ 外洩技術債：
1. **RED 階段驗證**：
   - 建立 `tests/test_clinic_first_router.py`，未實作前執行 `pytest -q -x` 如預期在 `test_r1_cf01_clinic_special_faq_retrieved_in_general_route` 斷言失敗（`assert 'pageindex' == 'cache'`），pytest 結束碼恰為 1。
2. **GREEN 階段實作 (`src/query/router.py`)**：
   - **clinic_id 入口正規化**：`None`、空字串 `""` 或純空白 `'   '` 一律正規化為 `None`。此行為變更使營運問句在傳入空白字串時一致拋出 `ValueError`（Fail-Loud），杜絕靜默回空資料的分歧。
   - **`QueryResponse.data_level`（純加法）**：新增 `Optional[Literal["clinic", "general"]] = None` 欄位。短路時採用決策層級；非短路時採用首筆 FAQ 之層級（`faq_hit_level(faq_hits[0])`），無 FAQ 命中時為 `None`。當 `clinic_id` 為 `None` 時，`data_level` 保證僅能為 `'general'` 或 `None`。
   - **單筆層級判斷函式 `faq_hit_level(hit)`**：公開函式，`fields['clinic_id']` 為真值即判定為 `"clinic"`，否則為 `"general"`。
   - **FAQ 檢索整合函式 `_gather_faq_hits`**：
     - **決策 1（外洩修復）**：`clinic_id` 為 `None` 時，檢索後強制以 `fields.get('clinic_id') is None` 過濾，僅保留通用衛教列，徹底杜絕無診所身分查詢時列出他院專屬 FAQ 之安全問題。
     - **診所 special 路由**：檢索後採穩定排序，診所專屬層級在前、general 在後。
     - **診所 general 路由（隔離宣告局部放寬）**：優先檢索該診所自己的 special FAQ（僅保留該診所 ID），再接續 general FAQ，依 `row_id` 去重並截斷至 `limit`。
     - **合規保證**：嚴禁任何原生 SQL，整檔無 `from faq_cache`，所有 FAQ 檢索均透過 `search_faq_cache`（內含 `visible_faq_sql` 審核閘門）。
   - **短路候選集與 Tiered 判定接線**：
     - 帶有效 `clinic_id` 時，分別檢索診所專屬候選（上限 50）與 general 候選（上限 50），價格遮蔽後調用 `select_confident_faq_tiered`。
     - 無 `clinic_id` 時，僅檢索 general 候選（上限 50）並過濾排除診所專屬列，走既有 `select_confident_faq` 路徑。
3. **正式庫 40 筆診所 FAQ 實測量測（設計題 G）**：
   - 40 筆診所 FAQ 原文自查短路數達 **38/40（95%）**。
   - 原本因關鍵字分類分流為 `general` 的 16 筆診所 FAQ 中，除 2 筆歧義問句外，其餘 **14 筆全數達成短路**，命中率突破既有 60% 上限。
   - 未短路之 2 筆問句嚴格鎖定於 id 4 與 id 19 相同問句不同答案之爭議題（「痣、疣或皮膚小贅生物可以如何處理？」），判定理由為 `clinic_ambiguous`，符合預期。

## 測試覆蓋與驗證
- `tests/test_clinic_first_router.py`：共 28 個測試全數 PASS：
  - R1: CF-01 診所 special FAQ 於 general 路由成功命中與短路。
  - R2: CF-02 診所無合格候選時安全退至 approved general FAQ。
  - R3: 診所優先——同問句兩層皆有時診所答案勝出。
  - R4: 診所歧義——同問句不同答案不退 general，排序診所優先。
  - R5: 隔離宣告——general 路由下 clinic_info/hours/notes 與 page_index 隔離完全不動。
  - R6: 審核閘門——pending 與 rejected 絕不外洩，核准後立即可見。
  - R7: 對抗性變形防禦——6 種變形皆被安全擋下。
  - R8: Blocker 回歸——縫合傷口碰水/洗澡衝突問句不退一般通則。
  - R9: 正式庫 40 筆量測——短路 38 筆，未短路僅限 id 4/19 歧義問句。
  - R10: 正式庫變形安全掃描。
  - R11: 快取答案二次價格遮蔽。
  - R12: `clinic_id` 正規化防禦（None, '', '   '）。
  - R13: 非短路排序與 `data_level`。
  - R14: `cache_eligible` 語意鎖定。
  - R15: 靜態程式碼檢查（無 `from faq_cache`）。
  - R16: 決策 1 跨診所外洩修復。
  - R17: 決策 2 special 路由退 general 機制。
- 組合驗證指令（包含 9 個測試檔共 177 個測試）全綠，既有測試零變動。
- 正式庫 `clinic.db` SHA-256 驗證完全不變。
