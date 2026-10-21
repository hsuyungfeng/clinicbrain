# 32-02 SUMMARY：場景 1/2/3 語意動作繪圖引擎 2.0

## 狀態
已完成（含一項需使用者知悉的判斷，見「設計決定」）。

## 已完成
- `src/web/static/visual_engine.js`
  - 13 個 blueprint 與 `src/visual/blueprints.py` 的 `BLUEPRINTS` 鍵完全一致。
  - `drawSurgicalAction`：骨骼基底、切口牽引、神經保護光暈、截骨滑移、純鈦板釘固定、步驟膠囊。
  - `drawContrast` 新增：
    - 左側 `wide_incision`：張開切口、皮瓣牽開、神經壓迫紅暈與標籤（標籤來自 `core_label`）。
    - 左側 `thermal_spread`：同心熱暈擴散。
    - 右側 `minimal_incision`：隱密切口、導板虛線邊界、安全邊距圈。
    - 右側 `targeted_energy`：多層光圈向單一焦點收斂。
  - `drawTimeline` 新增：
    - `wound_healing`：急性期彈性加壓帶與冰敷雪花，隨進度淡出。
    - `collagen_remodeling`：膠原纖維由波浪狀逐步拉直。
  - 修正 `resolveParams` 的列舉白名單：原本只接受舊值，新模式會被靜默退回預設（截圖實測發現）。現與 Python 列舉一致。
  - 靜態安全：無 `eval`、`new Function`、`innerHTML`、`setTimeout`、`Date.now`、`Math.random`。
- `src/visual/autodraft.py`
  - 新增外科推斷分支（在通用處置之前）：
    - 下顎／正顎／下巴截骨 → `mandible`。
    - 削骨／顴骨 → `malar_bone`。
    - 隆鼻／眼袋 → `general_surgery`。
  - 產出 `surgical_action` 參數範本，並通過 `validate_params`。
  - 提示詞新增第 7 條：外科場景須依序描述切口進入、神經保護、骨段處置、穩定固定。
- 測試
  - `tests/test_visual_autodraft.py`：`test_surgical_procedures_infer_surgical_action_blueprint`。
  - `tests/test_visual_engine_browser.py`：`test_plan_32_02_new_modes_render_without_errors`、`test_wide_incision_shows_nerve_label_at_full_progress`、`test_plan_32_02_enum_values_survive_sanitizer`（回歸）。

## 驗證
- 計畫指定的四組測試：48 passed（修改後）。
- 加上相關視覺與諮詢測試：118 passed，1 skipped。
  - 略過項：`tests/test_visual_video.py:123`，Playwright/Chromium 在該測試環境不可用，屬既有限制。
- 無頭瀏覽器截圖：7 組（6 個新模式 × 多個進度點 + 下顎手術案例）已逐一目視檢查，見 scratchpad 的 `montage2.png`。

## 設計決定（需使用者知悉）
- **削骨標題同時含顴骨與下顎骨角**：依規則先命中 `mandible`。單一場景只能呈現一個解剖目標，這是取捨而非錯誤；測試已明確記錄此預期。
- **Plan 文字與既有規格的差異**：`surgical_action` 的參數名稱採用既有 Python 規格（例如 `bone_shift_mm`、`nerve_status`、`incision_label`），未照計畫字面改名，以維持與既有測試與資料一致。

## 未完成或待驗證
- 下顎手術案例已截圖目視，但尚未以真實本地 LLM 生成的推理樹跑完整 autodraft 端到端（需要真實模型與 GPU，本次未執行）。
- 醫學正確性與圖文呼應程度仍需醫師審核，非自動測試可證明。
