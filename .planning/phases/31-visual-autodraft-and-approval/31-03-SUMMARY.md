# Phase 31 Plan 03: 管理端動畫資產審核、列表、修訂與自動生成 API 執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `31-03-PLAN.md` 規格，於 [`src/visual/review.py`](file:///home/hsu/Desktop/clinicbrain/src/visual/review.py) 與 [`src/api/routes/admin.py`](file:///home/hsu/Desktop/clinicbrain/src/api/routes/admin.py) 實作管理端視覺解說卡之列表、詳情、內聯修訂（改後自動回退 pending）、核准、駁回與由臨床決策推理樹觸發自動生成之 API 端點，所有端點皆受管理員金鑰認證保護：

1. **Task 1: src/visual/review.py 管理端查詢與修訂函式（P31-API）**：
   - 實作 `list_visual_assets(conn, *, status="pending", clinic_id=None, scope="all", limit=100, offset=0) -> tuple[list[dict], int]`：
     * 資料表不存在時安全回傳 `([], 0)`（Fail-Closed）。
     * 支援 `status` 過濾（`pending`、`approved`、`rejected`、`all`）。
     * 支援 `scope` 與 `clinic_id` 篩選：`scope="general"` 查 `clinic_id IS NULL`；`scope="clinic"` 查診所專屬；`scope="all"` 且傳入 `clinic_id` 時回傳 `(clinic_id = ? OR clinic_id IS NULL)`（兼顧本院專屬與一般共用動畫）。
     * 逐筆解析 `ir_json` 與 `keywords`，以 `validate_ir` 附加即時驗證結果 `"validation": {"ok": ok, "code": code}`，並將 `ir["scenes"]` 透過 `merge_defaults` 補齊 `params` 與預設 `duration_sec` 置於 `"scenes"` 欄位，方便前端 `ClinicVisual.mount` 直接播放。
   - 實作 `get_visual_asset_by_id(conn, asset_id: int) -> dict | None`：依主鍵 `id` 查詢單筆完整格式化後之視覺資產。
   - 實作 `update_visual_asset_by_id(conn, asset_id: int, *, title=None, keywords=None, scenes=None, commit=True) -> dict | None`：
     * 讀取既有列並合併傳入之 `title`、`keywords` 或 `scenes`（更新各場景之 `title`、`caption`、`labels`、`params`）。
     * 強制執行 `validate_ir(new_ir)` 及所有文字欄位（`title`, `caption`, `labels[].text`）零阿拉伯數字（`\d`）檢查；任一違規立即拋出 `ValueError(code)`（僅含固定英文錯誤碼，絕不洩漏違規原文）。
     * 比對實質變更：有變更時將 `review_status` 重置為 `'pending'`、`reviewed_at = NULL`、`content_version = content_version + 1`、`updated_at = CURRENT_TIMESTAMP`；無實質變更則不遞增版本亦不重置狀態。

2. **Task 2: src/api/routes/admin.py 動畫審核與自動生成端點（P31-API）**：
   - 定義 Pydantic 請求模型（皆嚴格設定 `ConfigDict(extra="forbid")`）：
     * `VisualSceneUpdateItem` (`title`, `caption`, `labels`)
     * `UpdateVisualAssetRequest` (`title`, `keywords`, `scenes`)
     * `AutodraftVisualRequest` (`tree_id: StrictInt`)
   - 實作 `_visual_llm_call(prompt: str) -> str`：使用 `VISUAL_SAMPLING` 取樣參數，支援測試時 monkeypatch 替換。
   - 新增管理端端點（皆在 `/api/v1/admin` 下，受 `Depends(verify_admin_key)` 保護）：
     * `GET /api/v1/admin/visuals`：分頁查詢動畫列表與總數。
     * `GET /api/v1/admin/visuals/{asset_id}`：單一動畫詳情（不存在回 404）。
     * `PATCH /api/v1/admin/visuals/{asset_id}`：修訂動畫文字，缺表回 503，不存在回 404，驗證未過回 422（`detail="動畫內容驗證未通過: {code}"`），成功回傳修訂後資產（狀態 `pending`）。
     * `POST /api/v1/admin/visuals/{asset_id}/approve`：呼叫 `set_review_status(conn, "", "approved", asset_id=asset_id)`；核准前強制重驗 `validate_ir`，不合格回 422，成功回 200。
     * `POST /api/v1/admin/visuals/{asset_id}/reject`：呼叫 `set_review_status(conn, "", "rejected", asset_id=asset_id)`，成功回 200。
     * `POST /api/v1/admin/visuals/autodraft`：呼叫 `autodraft_from_tree`；未核准樹回 400，不存在回 404，忙碌回 409，LLM 離線回 503，驗證失敗回 422（僅帶代碼），成功回傳生成之 pending 動畫資產。
   - 更新 `GET /api/v1/admin/review/summary`：安全加入 `visuals_pending_total` 與 `visuals_approved_total` 計數統計（缺表時安全為 0）。

---

## 2. 測試與驗收結果

- **Task 1 & Task 2 整合測試**：
  `uv run pytest -q -p no:cacheprovider tests/test_visual_admin_api.py`
  -> **8 passed, 2 warnings in 0.92s**。
- **計畫指定跨模組驗收**：
  `uv run pytest -q -p no:cacheprovider tests/test_visual_admin_api.py tests/test_tree_review_backend.py`
  -> **13 passed, 2 warnings in 1.08s**。
- **視覺模組全套迴歸測試**：
  `uv run pytest -q -p no:cacheprovider tests/test_visual_autodraft.py tests/test_visual_ir.py tests/test_visual_generator.py tests/test_visual_writer.py tests/test_visual_match.py tests/test_visual_serving.py tests/test_visual_blueprints.py`
  -> **84 passed, 1 warning in 1.76s**（零迴歸）。
- **正式資料庫保護**：
  `sha256sum clinic.db`: `2f66cd1b42fd927bca22a847b537c4cc43fb80c6a139aafb67669caaf25daf66`（完全未變更、未遷移）。

---

## 3. 改動檔案清單

- `src/visual/review.py`：新增 `list_visual_assets`、`get_visual_asset_by_id`、`update_visual_asset_by_id` 與 `_format_visual_asset_row`。
- `src/visual/autodraft.py`：`fetch_eligible_trees` 補強 `review_status = 'approved'` 欄位檢核，防止未核准樹被選取。
- `src/api/routes/admin.py`：新增 Pydantic 請求模型、`_visual_llm_call`、管理端視覺路由（`GET /visuals`, `GET /visuals/{id}`, `PATCH /visuals/{id}`, `POST /visuals/{id}/approve`, `POST /visuals/{id}/reject`, `POST /visuals/autodraft`）及 `summary` 統計欄位。
- `tests/test_visual_admin_api.py`：管理端 API 完整測試套件（8 個測試，涵蓋認證、查詢、過濾、修訂防護、核准駁回、自動生成與統計）。
- `.planning/phases/31-visual-autodraft-and-approval/31-03-SUMMARY.md`：本執行摘要。

---

## 4. 遵守規則聲明

1. 依序完成 31-02（已建 `31-02-SUMMARY.md`）與 31-03（本檔 `31-03-SUMMARY.md`）即停。
2. 嚴格遵守規定，未執行任何 `git reset`, `git checkout`, `git stash`, `git clean`, `git restore`。
3. 嚴禁修改或遷移正式庫 `clinic.db`，所有測試皆使用 `isolated_db_path` 隔離複本，不呼叫真實 LLM。
4. 依指示**未自行執行 git commit**，保留工作區改動等待 hermes 測試與 argon 審查。
