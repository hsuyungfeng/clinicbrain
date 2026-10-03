# Phase 11 Plan 04 Summary: 診所資料優先量測驗收與規範文件同步

## 執行成果概述
本計畫（11-04）建立獨立可重跑之量測驗收測試（設計題 G），並更新專案大腦與規範文件（`AGENTS.md`），完成 Phase 11 全套測試回歸：

1. **量測驗收測試 (`tests/test_clinic_first_acceptance.py`)**：
   - 支援環境變數 `CLINICBRAIN_ACCEPT_DB` 指向之獨立資料庫複本，全程以 `sqlite3.connect(f'file:{path}?mode=ro', uri=True)` 唯讀開啟。
   - 安全防護：解析後若等於專案正式庫 `clinic.db`（`PROD_DB_PATH.resolve()`），立即引發 `pytest.fail` 拒絕執行（實測引發 `Failed: 驗收測試拒絕直接量測正式庫 clinic.db，請使用複本`，結束碼 1）。
   - 以原生 SQL `WHERE clinic_id = '3503190424' AND ({visible_faq_sql})` 讀出可見診所 FAQ。
   - 逐筆以原文自查呼叫 `handle_query`，輸出對齊表格包含：ID、舊路由 (classify)、回應 source、data_level、短路決策 reason、問句。
   - 驗收前後比對 `faq_cache` 筆數，證明全程無任何寫入。

2. **正式庫 40 筆真實 FAQ 實測量測結果**：
   - **總筆數**：40 筆可見診所專屬 FAQ。
   - **舊流程基準**：被 `classify` 分流為 `general` 達 16 筆，舊流程可短路上限僅 24 / 40 (60.00%)。
   - **Phase 11 新流程實測**：短路命中數達 **38 / 40 (95.00%)**。
   - **原 16 筆 general 路由對照**：14 筆達成高信心短路、2 筆歧義保護。
   - **未短路集合**：恰為 `id: 4` 與 `id: 19` 兩筆，兩筆問句完全相同（「痣、疣或皮膚小贅生物可以如何處理？」）但答案不同，觸發 `clinic_reason == 'ambiguous'`（margin = 0 < 0.1 歧義邊界保護），未為湊數放寬任何門檻常數。
   - 所有短路回應之 `data_level` 皆為 `'clinic'`，且 `route` 欄位與 `classify` 保持一致。

3. **規範文件同步 (`AGENTS.md`)**：
   - **2.8 已知限制第 1 點解除**：載明帶 `clinic_id` 的查詢不再受 `classify` 分流限制，短路由 24/40 提升至 38/40，未短路 2 筆為歧義邊界生效。
   - **新增 2.11 診所資料優先檢索（Phase 11 新增）小節**：
     - (a) 兩階段跨層級（Tiered）檢索規則（診所優先，不混排，歧義/風險不符阻斷不退）。
     - (b) 回應新增純加法欄位 `data_level`（'clinic'|'general'|None；faq_hits 每筆帶自己的 data_level；非短路時表示最前端 FAQ 之層級，不代表回答內文與該 FAQ 相關）。
     - (c) 隔離宣告局部放寬（僅診所自己 special FAQ 可在 general 路由被檢索；其餘營運表與樹對 general 隔離完全不變；匿名 `/api/v1/general/query` 0 行修改維持隔離）。
     - (d) 安全檢查與審核閘門貫徹（Phase 07 常數與五維風險完全未動；未審核不外洩；不呼叫 LLM）。
     - (e) 統計語意：cache_eligible/hit/miss 規則不變，分母不變；命中率包含 general 層級。
     - (f) 無 clinic_id 時不列任何診所專屬 FAQ，其餘行為不變。
     - (g) 未涵蓋範圍：CF-04 診所推理樹與備註優先化。
     - (h) special 路由退 general 機制與相近內容（$\ge 0.4$）阻斷保護。
     - (i) 修正跨診所外洩：無 clinic_id 時排除所有診所專屬 FAQ。
     - (j) clinic_id 正規化與 API 行為差異（POST `/api/v1/clinics/{clinic_id}/query` 空白路徑參數回 400）。
     - (l) `CLINIC_RELATED_FLOOR = 0.4` 取捨與複審數據（24 組釋義 0.4 擋 11 組；0.3 以下相鄰主題誤擋約 40%）。
     - (m) 營運規則：general FAQ 入庫審核須比對診所 FAQ 避免指示衝突。
   - **目錄結構補列**：`tests/test_clinic_first_acceptance.py`。

4. **ROADMAP 成功標準差異與追蹤說明**：
   - **成功標準 1 字面差異**：
     - ROADMAP 字面為「原本因 classify 分流為 general 的 16 筆皆可短路命中（短路率 24/40 → 40/40）」。
     - 實測為 24/40 → 38/40 (+14)。16 筆 general 路由中扣除 id 4 與 id 19 兩筆歧義問句，其餘 14 筆全數達成短路。
     - **使用者待辦事項**：請醫師合併或區分 id 4 與 id 19 的問句文字（例如區分為手術切除與雷射/冷凍處置情境），去除歧義後即可自然達到 40/40。
   - **成功標準 4 測試基線差異**：
     - ROADMAP 字面寫「測試覆蓋維持 >= 578 passed」，此基線係 Phase 09 撰寫時之舊數字。
     - 本 Phase 執行前之實際基線為 588 passed + 1 skipped（共 589）。
     - 本 Phase 完成後全量回歸測試實測為 **662 passed, 0 failed, 1 warning (deprecation)**，全部通過。

5. **正式庫安全保證**：
   - 驗收前後正式庫 `clinic.db` SHA-256 雜湊值皆為：
     `ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e`
   - 全程 0 位元組異動。
   - 靜態守衛 `tests/test_faq_read_guard.py` 3 項測試全綠，無新增未經授權之 FAQ 讀取。
