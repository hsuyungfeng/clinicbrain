# Phase 31 Plan 05: AGENTS.md 2.28 文件與 ROADMAP.md 更新執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `31-05-PLAN.md`（Wave 4：P31-DOC）規格，完善專案核心架構規範 `AGENTS.md` 與專案路線圖 `.planning/ROADMAP.md`，忠實記錄 Phase 31 導入之視覺解說卡多診所支援、PageIndex 推理樹自動草稿生成、管理審核 API 與審核介面分頁：

1. **Task 1: 新增 AGENTS.md 2.28 節與更新 ROADMAP.md（P31-DOC）**：
   - [`AGENTS.md`](file:///home/hsu/Desktop/clinicbrain/AGENTS.md)：
     * **2.26 節歷程註解更新**：更新原本「`visual_assets` 不設 `clinic_id`」之描述，註記自 Phase 31 起已擴充 `clinic_id` 欄位，支援診所專屬與跨診所共用資產並存。
     * **新增 2.28 節**：`### 2.28 由 PageIndex 自動生成動畫草稿、待簽核動畫分頁與診所優先（Phase 31 新增）`，完整闡述五大核心機制：
       1. **資料庫擴充與唯一鍵重建遷移**：`visual_assets.clinic_id` 欄位擴充、`UNIQUE(topic_slug, clinic_id)` 重建、`IS` 語意相容與冪等遷移保障。
       2. **診所優先比對規則**：帶診所時專屬優先於共用、未帶診所時僅限共用資產，防範跨院洩漏。
       3. **PageIndex 推理樹自動草稿生成**：僅讀取已核准推理樹、純本地無幻覺映射、零預設範本文字污染、永不自動核准（Human-in-the-Loop 恆為 `pending`）。
       4. **管理端動畫審核 API**：列表分頁（`GET /visuals`）、單筆詳情（`GET /visuals/{id}`）、微調編輯（`PATCH /visuals/{id}` 退回待審）、簽核核准（`POST /approve`）、駁回（`POST /reject`）與樹一鍵生草稿（`POST /autodraft`）。
       5. **管理審核介面「🎬 待簽核動畫」分頁**：第 7 分頁導覽、儀表板統計、純函式 SVG 動畫播放器、進度條拖曳 seek、場景切換、即時文字修訂與一鍵審核，維持前端嚴格 XSS 零禁語安全。
     * **第 4 節目錄結構補齊**：
       - `src/visual/autodraft.py`：由已核准臨床推理樹自動生成受約束視覺解說卡草稿模組
       - `scripts/autodraft_visual_from_trees.py`：由已核准推理樹批次生成視覺動畫草稿 CLI 腳本
       - `tests/test_visual_autodraft.py`、`tests/test_visual_admin_api.py`、`tests/test_visual_review_ui.py`：Phase 31 專屬單元、API 與瀏覽器測試套件
   - [`.planning/ROADMAP.md`](file:///home/hsu/Desktop/clinicbrain/.planning/ROADMAP.md)：
     * 於 Progress 進度表格補登 Phase 30（6/6 Complete 2026-10-20）與 Phase 31（5/5 Complete 2026-10-20）。
     * 將 Phase 30 狀態標記為 Complete、勾選全部 6 份計畫 `[x]`。
     * 將 Phase 31 狀態更新為 Complete、勾選全部 5 份計畫 `[x]`（31-01 至 31-05）。

---

## 2. 測試與驗收結果

- **Phase 31 核心與回歸測試套件**：
  `uv run pytest -q -p no:cacheprovider tests/test_migrate_visual_assets.py tests/test_visual_writer.py tests/test_visual_match.py tests/test_visual_serving.py tests/test_visual_autodraft.py tests/test_visual_admin_api.py tests/test_visual_review_ui.py`
  -> **59 passed, 2 warnings in 5.77s**。
- **正式資料庫保護**：
  `sha256sum clinic.db`: `2f66cd1b42fd927bca22a847b537c4cc43fb80c6a139aafb67669caaf25daf66`（維持一致、完全未被修改或遷移）。

---

## 3. 改動檔案清單

- `AGENTS.md`：新增 2.28 節、更新 2.26 節註記、於第 4 節目錄結構補入 Phase 31 模組、CLI 與測試清單。
- `.planning/ROADMAP.md`：更新進度總表與 Phase 30 / Phase 31 詳細狀態與核可方塊。
- `.planning/phases/31-visual-autodraft-and-approval/31-05-SUMMARY.md`：本執行摘要。

---

## 4. 遵守規則聲明

1. 完成 31-05 並建立 `31-05-SUMMARY.md`。
2. 嚴格遵守規定，未執行任何 `git reset`, `git checkout`, `git stash`, `git clean`, `git restore`。
3. 嚴禁修改或遷移正式庫 `clinic.db`，所有測試皆使用隔離複本，不呼叫真實 LLM。
4. 依指示**未自行執行 git commit**，保留工作區改動等待 hermes 測試與 argon 審查。
