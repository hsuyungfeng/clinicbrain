# Phase 32 CONTEXT：診所核准資產自動昇華一般醫學與語意動作繪圖引擎升級

## 來源與背景（使用者 2026-10-21）
1. **各診所審核後就准許進入一般醫學，不須再核准**：
   - 診所專科醫師在後台簽核 approved 之臨床推理樹與視覺解說卡，已具備高度專業性與醫療合規性。
   - 系統應在審核通過後，自動將該資產昇華（Auto-Promote）進入一般醫學知識池（`clinic_id IS NULL`），且直接標記為 `approved`，避免繁瑣的重複審核。
   - 一般醫學諮詢（`clinic_id is None`）查詢時，能自動跨診所調用所有已核准之優質衛教內容。
2. **場景 1、2、3 需要使用文字意義去寫 code 表現（徹底解決圖文不符）**：
   - 現有固定幾何藍圖（如 `process_diagram` 抽象圓點、`contrast` 大圓與網格、`timeline` 3 個空心圓）無法真實體現臨床文本所描繪的手術機轉（如「骨膜下剝離保護頦神經、下巴截骨滑移、純鈦板釘固定」）與術後歷程（加壓帶、冰敷、組織重組）。
   - 升級繪圖引擎 `visual_engine.js`，導入醫學語意動作指令集（Semantic Action DSL）與解剖圖元，讓動畫畫面 100% 呼應文本意義。

## 設計決策

### 1. 診所核准自動昇華機制 (Auto-Promotion)
- **單一寫入路徑聯動**：
  - 在 [`src/api/routes/admin.py`](file:///home/hsu/Desktop/clinicbrain/src/api/routes/admin.py) 之 `approve_admin_visual` 與 `approve_admin_tree`，以及 [`src/visual/review.py`](file:///home/hsu/Desktop/clinicbrain/src/visual/review.py) 之 `set_review_status` 中：
    - 當診所專屬資產（`clinic_id IS NOT NULL`）被設為 `approved` 時，後端自動以正規化 slug（去除診所代碼前綴，如 `tree-3503264627-mid-lower-smas-facelift` -> `tree-mid-lower-smas-facelift`）向 `clinic_id IS NULL` 的一般醫學共用池執行增量 UPSERT，狀態恆為 `approved`。
- **查詢層聯邦保底**：
  - [`src/visual/review.py`](file:///home/hsu/Desktop/clinicbrain/src/visual/review.py) `visible_assets(conn, clinic_id=None)`：若 `clinic_id is None`，查詢所有 `review_status = 'approved'` 之資產（`clinic_id IS NULL` 與所有已核准之診所資產）。
  - [`src/visual/match.py`](file:///home/hsu/Desktop/clinicbrain/src/visual/match.py) `find_visual(conn, query, clinic_id=None)`：若 `clinic_id is None`，不再過濾 `asset_clinic is not None`。
  - [`src/query/search.py`](file:///home/hsu/Desktop/clinicbrain/src/query/search.py) `search_page_index_trees(conn, query, clinic_id=None)`：若 `clinic_id is None`，條件由 `clinic_id IS NULL` 放寬為 `review_status = 'approved'`。
- **歷史資產昇華腳本**：
  - 提供 `scripts/promote_clinic_assets_to_general.py`，支援 `--clinic-id` 與 `--dry-run`，一鍵昇華現有已核准資產。

### 2. 場景 1/2/3 語意動作繪圖引擎 2.0 (Semantic Action Engine)
- **前端繪圖引擎升級 ([`src/web/static/visual_engine.js`](file:///home/hsu/Desktop/clinicbrain/src/web/static/visual_engine.js))**：
  - 嚴格遵守醫療前端安全政策：零 `eval`、零 `new Function`、零 `innerHTML`、純 Canvas 2D / SVG 函式直譯。
  - 擴充真實解剖動作圖元：
    - **Scene 1 (處置機轉)**：新增 `surgical_action` 藍圖，支援骨骼截骨滑移、神經血管路徑與保護高光、黏膜與皮下切口縫合、鈦板螺絲固定。
    - **Scene 2 (對比優勢)**：對照組支援粗糙切口張力與神經發紅警示；優勢組支援 3D 導板貼合、安全邊距與微創隱痕。
    - **Scene 3 (修復歷程)**：三階段支援急性期彈性加壓帶與冰敷雪花、水腫消退修復水紋、骨骼/膠原重組自然輪廓。
- **後端提示詞與參數整形升級 ([`src/visual/blueprints.py`](file:///home/hsu/Desktop/clinicbrain/src/visual/blueprints.py), [`src/visual/autodraft.py`](file:///home/hsu/Desktop/clinicbrain/src/visual/autodraft.py))**：
  - 擴充 `BLUEPRINTS` 規格，定義 `surgical_action` 及其參數。
  - 升級 `build_tree_visual_prompt`，引導本地 Qwen 模型根據文字意圖輸出結構化動作指令。
  - 升級 `parse_and_build_tree_ir`，自癒截斷與容錯回退。

## 多 Agent 協作執行架構 (Herdr Pipeline)
1. **Argon (Pane 1, agy)**：規劃 Phase 32 架構與子計畫（`32-01-PLAN.md`, `32-02-PLAN.md`）。
2. **Executor (Pane 6, claude)**：透過 `herdr agent prompt w6:p6` 派工執行實作。
3. **Tester (Pane 2, hermes)**：透過 `herdr agent prompt w6:p2` 派工執行測試驗收。
4. **Reviewer (Pane 1, agy)**：檢查、修正、Playwright 截圖審核並驗收提交。
