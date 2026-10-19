---
phase: 29-visual-explainer-cards
plan: 05
subsystem: documentation
tags: [docs, agents-md, phase29, visual-explainer-cards]
requires: ["29-02", "29-03", "29-04"]
provides:
  - "AGENTS.md: 新增 2.26 一般醫學視覺解說卡（Phase 29 新增）與第 4 節目錄結構條目"
affects: ["AGENTS.md", "src/visual/ir.py"]
key-files:
  created: []
  modified:
    - AGENTS.md
    - src/visual/ir.py
decisions:
  - "AGENTS.md 嚴格採用純新增行方式（被刪行數為 0），完整反映 29-01 至 29-04 已實作並通過測試之行為。"
  - "真實本地 LLM 生成品質與解說卡對預約諮詢之轉換成效據實記載為『待驗證』。"
  - "修正 src/visual/ir.py 將 deep_mask_prices 改為於 validate_visual_text 內延遲匯入，消除單獨先載入 src.visual.ir 時與 src.api 產生的循環匯入。"
metrics:
  completed_date: "2026-10-19"
  tasks_completed: 1
  tests_added: 0
---

# Phase 29 Plan 05: AGENTS.md 2.26 與目錄結構補充摘要

## 核心成果

1. **Task 1：撰寫 `AGENTS.md` 2.26 節與第 4 節目錄補充**
   - 新增 `### 2.26 一般醫學視覺解說卡（Phase 29 新增）`，涵蓋：
     - 定位與使用者決策（純一般醫學說明、無診所代碼共用資產、零個資收集）。
     - Typed IR 規格與 `validate_ir` 唯一權威驗證（含 `VISUAL_EXTRA_FORBIDDEN`、零原文錯誤碼）。
     - 資料表（`visual_assets`、`visual_stats`）與單一來源遷移（`--confirm-prod-backup`、未遷移 Fail-Closed）。
     - 唯一寫入路徑（`upsert_assets`）、骨架與本地 LLM 預生成（`VISUAL_SAMPLING`、最多 2 次、鎖與夜間批次互斥、恆為 `pending`）、醫師審核 CLI 與雙重驗證。
     - 服務端確定性關鍵字比對（`find_visual`）、`answered`/`llm_general` 附帶規則、匿名事件計數（`record_event`、`/api/v1/general/visual/event`）與前端安全渲染（`textContent`、`createElementNS`、無自動輪播、固定免責常數）。
     - 已知限制（含真實模型生成品質與轉換成效**待驗證**）與完整測試清單。
   - 於第 4 節目錄結構新增 `src/visual/`、`data/visual/skeletons/autologous-fat-grafting.json`、3 支 CLI 腳本與 9 個測試檔條目。
   - 驗證 `git diff AGENTS.md | grep -c '^-[^-]'` 為 `0`（零刪行），且專案外 `/home/hsu/AGENTS.md` 完全未動。

2. **循環匯入微幅修正（`src/visual/ir.py`）**
   - 當單獨先載入 `src.visual.ir` 時，頂層 `from src.api.routes.query import deep_mask_prices` 會觸發 `src.api.__init__` → `general.py` → `patient_consult.py` → `src.visual.match` → `src.visual.review` → `src.visual.ir` 循環匯入。已將 `deep_mask_prices` 改為在 `validate_visual_text` 函式內延遲匯入，所有測試順序皆可穩定通過。

## Commit 紀錄

- `cfa906b`: `fix(phase29): 延遲匯入 deep_mask_prices 避免 src.visual.ir 與 src.api 循環匯入`
- `e9ecf4f`: `docs(phase29): 新增 AGENTS.md 2.26 一般醫學視覺解說卡規範與第 4 節目錄結構`
