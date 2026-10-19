---
phase: 29-visual-explainer-cards
plan: 03
subsystem: visual-serving-and-stats
tags: [visual, match, serving, stats, privacy, fail-closed]
requires: ["29-01"]
provides:
  - "src/visual/match.py: find_visual(conn, query) 純 SELECT 關鍵字比對與對外輸出整形"
  - "src/general/patient_consult.py & consult_jobs.py: answered / llm_general 回應附帶已核准解說卡"
  - "src/visual/stats.py & POST /api/v1/general/visual/event: 匿名日聚合計數（shown / completed）"
affects: ["src/general/patient_consult.py", "src/general/consult_jobs.py", "src/api/routes/general.py", "src/api/models/general.py"]
key-files:
  created:
    - src/visual/match.py
    - src/visual/stats.py
    - tests/test_visual_match.py
    - tests/test_visual_serving.py
    - tests/test_visual_stats.py
  modified:
    - src/general/patient_consult.py
    - src/general/consult_jobs.py
    - src/api/routes/general.py
    - src/api/models/general.py
decisions:
  - "關鍵字比對統一使用 NFKC 正規化（轉小寫）計算問句中子字串命中的關鍵字數，多筆命中取命中數最高者，同分取字典序較小之 topic_key 確保確定性。"
  - "對外輸出整形嚴格僅保留 topic_key、title、scenes（含 blueprint、title、caption、labels），排除資料庫 id、ir_json 原文、審核欄位、metadata 與 keywords。"
  - "僅在 patient_consult 的 answered（組稿與退回 found.message 兩處）與 llm_general（同題重用與新生成兩處）附加 find_visual 結果；red_flag、no_match、busy 一律為 None。"
  - "匿名事件計數端點 /api/v1/general/visual/event 掛載於 AnonymousRoute 下，以 VisualEventRequest(extra='forbid') 攔截非法輸入並回傳固定 422「請求格式不正確」；合法格式無論主題是否核准或資料庫是否遷移皆回固定 200 {\"ok\": true}。"
metrics:
  completed_date: "2026-10-19"
  tasks_completed: 3
  tests_added: 19
---

# Phase 29 Plan 03: 關鍵字比對、諮詢回應帶出動畫與匿名事件計數摘要

## 核心成果

1. **Task 1：關鍵字比對與對外輸出整形（`src/visual/match.py`）**
   - 實作 `find_visual(conn, query) -> dict | None`，僅呼叫 `visible_assets(conn)` 取得已核准且通過 `validate_ir` 再驗證之視覺資產。
   - 對問句與各資產關鍵字做 `NFKC` 正規化並轉小寫，計算子字串命中數；命中 0 回傳 `None`，多筆取命中數高者（同分取較小 `topic_key`）。
   - 對外輸出結構嚴格整形為 `{"topic_key", "title", "scenes": [{"blueprint", "title", "caption", "labels": [{"text", "tone"}]}]}`；缺表或任何資料庫錯誤皆回傳 `None`（Fail-Closed）。
   - 通過 `tests/test_visual_match.py`（8 項測試，含 AST 靜態掃描確認無寫入 SQL、無 logging、無 print）。

2. **Task 2：諮詢回應與非同步作業結果帶出動畫（`src/general/patient_consult.py`, `src/general/consult_jobs.py`, `src/api/routes/general.py`）**
   - `PatientConsultResult` 新增欄位 `visual: dict | None = None`。
   - `patient_consult` 僅在 `status` 為 `"answered"` 或 `"llm_general"` 的 4 個回傳點附加 `_safe_find_visual(conn, query)` 結果；`red_flag`、`no_match`、`busy` 一律維持 `None`。
   - `/api/v1/general/consult` 與 `consult_jobs._worker` 完成結果同步包含 `"visual"` 鍵並經 `deep_mask_prices()` 清洗；`GET /consult/jobs/{id}` 維持純記憶體讀取零資料庫連線。
   - 通過 `tests/test_visual_serving.py`（6 項測試）及既有 `test_patient_consult.py`、`test_consult_jobs.py`、`test_general_privacy.py`、`test_patient_clinic_scope.py`（共 58 passed，既有斷言零刪改）。

3. **Task 3：匿名事件計數與端點（`src/visual/stats.py`, `src/api/models/general.py`, `src/api/routes/general.py`）**
   - 實作 `record_event(db_path, topic_key, event) -> bool`，僅接受 `event in ("shown", "completed")` 且 `topic_key` 存在於 `visible_assets(conn)` 已核准主題，以獨立連線對 `visual_stats` 執行日聚合 `count + 1` UPSERT；所有例外全吞回傳 `False`。
   - 新增 `VisualEventRequest(extra="forbid")` 與 `POST /api/v1/general/visual/event`，驗證錯誤回傳固定 422 `{"detail": "請求格式不正確"}`，其餘情況一律回傳 200 `{"ok": True}`；路徑受 `/api/v1/general` 存取日誌過濾器保護。
   - 通過 `tests/test_visual_stats.py`（5 項測試）。

## Commit 紀錄

- `591aef7`: `feat(phase29): 實作視覺解說卡關鍵字比對與對外輸出整形模組`
- `ed247a1`: `feat(phase29): 讓病人諮詢回應與非同步作業結果帶出已核准視覺解說卡`
- `32e7d77`: `feat(phase29): 實作視覺解說卡匿名事件計數與 API 端點`

## 偏離計畫說明

無偏離計畫之處。所有既有測試斷言零刪改，`tests/test_general_privacy.py` 原封不動通過。
