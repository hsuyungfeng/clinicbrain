# Phase 30 CONTEXT：資料驅動的視覺場景引擎

## 來源與動機
- Phase 29 的動畫展示（`demo/visual/lite.html`、`full.html`）是為「自體脂肪移植」手工設計的，**新主題要新畫面＝新程式碼**，本地 27B 無法獨立完成。
- 目標：把場景做成**參數化的 blueprint 元件**，新主題只需改骨架 JSON（參數＋說明文字），不改任何 JS；本地模型仍只填文字，不寫畫面程式碼。

## 設計決策（Claude 規劃，使用者 2026-10-19 要求「規劃資料驅動的場景引擎」）
1. **三個 blueprint 參數化**（沿用 Phase 29 的 `process_diagram`／`contrast`／`timeline`），參數全為列舉、小整數、短文字、調色盤代號；**不接受任意顏色、HTML、SVG、程式碼**。
2. **每個元件是進度 `u∈[0,1]` 的純函式**：`draw(ctx, params, u)`；不依賴實際時間與前一格狀態。因此可任意拖曳、重播、逐格錄影，結果確定一致（determinism 是驗收條件）。
3. **參數規格單一來源在 Python**（`src/visual/blueprints.py`：參數 schema、預設值、調色盤代號），`validate_ir` 呼叫它；JS 引擎只實作繪製，並以「契約測試」驗證 JS 註冊的 blueprint／參數名稱與 Python 一致。
4. **向後相容**：`params` 為選填；缺省時用預設值（等同 Phase 29 既有畫面）。已核准的資產不需遷移。
5. **證明引擎成立的標準**：新增第二個主題（玻尿酸填充）**只靠骨架 JSON**即可預生成、渲染、匯出 MP4，**零 JS 改動**。
6. 新 blueprint 仍需人工／Claude 設計（寫一個元件＋schema＋測試）；本 phase 提供「新增 blueprint 指南」讓這件事可重複、可驗證，但不宣稱可自動生成新畫面。

## 範圍
- 引擎 `src/web/static/visual_engine.js`（外部檔，CSP 相容）；通用播放器 `demo/visual/player.html`（讀 bundle JSON）；`scripts/export_visual_bundle.py`；`render_video.py` 支援 `--bundle`。
- 正式解說卡（`consult.js`）在有 `params` 時改用引擎動畫渲染，無 `params` 時沿用既有靜態圖（30-05）。**正式環境啟用另需使用者核准與醫師重審**（新參數使 IR 內容改變 → 版本遞增 → 回 pending）。

## 硬性約束
- 不放寬 `validate_ir` 既有規則；新增 params 驗證只會更嚴。
- 前端：`/admin` CSP `script-src 'self'`，**不得有內嵌 `<script>`**；動態文字 `textContent`；禁 `innerHTML／insertAdjacentHTML／document.write／eval／setInterval／localStorage／sessionStorage／document.cookie`（子字串，註解也不得出現）。
- 不收個資；CTA 只導向 doctor-toolbox.com。
- 不直接寫正式庫；測試用隔離副本、不呼叫真實 LLM；真實驗收用副本庫＋真實 llama-server＋真實瀏覽器。
- 瀏覽器相關測試用 Playwright（已裝 Chromium），不可用時 `pytest.skip`，不得讓套件失敗。

## 需求編號
P30-PARAMS、P30-ENGINE、P30-BUNDLE、P30-PLAYER、P30-VIDEO、P30-PROD、P30-PROOF、P30-DOC
