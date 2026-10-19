---
phase: 29-visual-explainer-cards
plan: 04
subsystem: consult-visual-ui
tags: [frontend, consult-html, svg, xss-safety, reduced-motion, visual-cards]
requires: ["29-03"]
provides:
  - "src/web/static/consult.html: renderVisual 與三種固定 SVG 場景模板（process_diagram / contrast / timeline）及匿名事件回報"
affects: ["src/web/static/consult.html"]
key-files:
  created:
    - tests/test_consult_visual_ui.py
  modified:
    - src/web/static/consult.html
decisions:
  - "嚴格遵守 XSS 與子字串禁令：全部動態文字以 textContent 賦值，SVG 以 document.createElementNS('http://www.w3.org/2000/svg', ...) 建立，完全不含 innerHTML、insertAdjacentHTML、document.write、eval（含任何包含 eval 之子字串）、localStorage、sessionStorage、document.cookie、setInterval。"
  - "解說卡僅在回應 status 為 answered 或 llm_general 且 visual.scenes 為 3～5 筆陣列時顯示，其餘狀態或每次重新送出時皆隱藏並清空。"
  - "免責文字『一般醫學知識說明，非個人化診斷；實際狀況須由醫師當面評估』定義於前端常數 VISUAL_FIXED_DISCLAIMER，不依賴伺服器資料。"
  - "首次顯示時回報 shown、首次切換至最後一幕時回報 completed（fetch POST /api/v1/general/visual/event, keepalive: true），錯誤全數靜默忽略。"
metrics:
  completed_date: "2026-10-19"
  tasks_completed: 1
  tests_added: 4
---

# Phase 29 Plan 04: 病人諮詢頁視覺解說卡渲染與事件回報摘要

## 核心成果

1. **Task 1：解說卡渲染與事件回報（`src/web/static/consult.html`, `tests/test_consult_visual_ui.py`）**
   - 在 `consult.html` 新增 `#visualCard` 容器、對應 CSS 樣式（含 `.tone-neutral`、`.tone-warning`、`.tone-optimal` 與 `@media (prefers-reduced-motion: reduce)` 無障礙降級）。
   - 實作 `renderVisual(data)` 並於 `renderResult(data)` 結尾呼叫；每次新查詢或新結果先清空舊卡片，僅當 `status` 為 `"answered"` 或 `"llm_general"` 且 `data.visual.scenes` 為 3～5 筆時渲染顯示。
   - 實作 `buildBlueprintSvg(scene)`，以 `document.createElementNS` 針對 `process_diagram`（圓形節點＋箭頭）、`contrast`（左右對照面板）、`timeline`（水平時間軸與節點）建立固定安全 SVG；未知 `blueprint` 自動退回純文字顯示不報錯。
   - 提供「上一步」「下一步」按鈕與進度圓點，無任何表單或輸入框；底部固定顯示前端常數免責文字「一般醫學知識說明，非個人化診斷；實際狀況須由醫師當面評估」。
   - 首次顯示回報 `shown`、首次抵達最後一幕回報 `completed`（`fetch('/api/v1/general/visual/event', {method: 'POST', keepalive: true})`），例外靜默吞除。
   - 通過 `tests/test_consult_visual_ui.py`、`tests/test_patient_consult_ui.py`、`tests/test_web_ui.py`、`tests/test_web_ui_v2.py`（共 18 passed）。

## Commit 紀錄

- `27a300a`: `feat(phase29): 於病人諮詢頁新增視覺解說卡渲染與匿名事件回報`

## 偏離計畫說明

無偏離計畫之處。既有輪詢、錯誤處理、紅旗顯示與預約連結邏輯完全未改動。
