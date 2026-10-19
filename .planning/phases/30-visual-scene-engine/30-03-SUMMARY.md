# Phase 30 Plan 03: 視覺 Bundle 匯出、通用播放器與 MP4 影片匯出泛化執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `30-03-PLAN.md` 規格，建立與主題無關的通用視覺解說匯出、播放與 MP4 錄製工具鏈，由 `visual_engine.js` 統一驅動：

1. **視覺 Bundle 匯出工具（Task 1, P30-BUNDLE）**：
   - 實作 [`scripts/export_visual_bundle.py`](file:///home/hsu/Desktop/clinicbrain/scripts/export_visual_bundle.py)：
     - 以 SQLite URI `mode=ro` 嚴格唯讀開啟資料庫，拒絕任何寫入行為。
     - 預設僅匯出狀態為 `approved` 之資產；支援 `--allow-pending`，但若 `--db` 解析為專案正式資料庫 `clinic.db` 時，於連線前立即以結束碼 `2` 拒絕。
     - 匯出前嚴格透過 `validate_ir` 進行四層醫療法規合規與結構驗證。
     - 輸出格式對齊公開資產形狀（`{"topic_key", "title", "scenes"}`），透過 `src/visual/blueprints.py:merge_defaults` 補齊所有場景之預設 `params`，並於未設定時填入 blueprint 預設 `duration_sec`。
     - 輸出檔案預設不覆蓋既有檔案（需顯式指定 `--force`），以 UTF-8 格式寫出。
     - 資料庫未套用遷移（缺表）時結束碼 `2`，找不到主題時結束碼 `1`。
   - 建立 [`tests/test_visual_bundle.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_visual_bundle.py)（8 個測試案例，全數通過）。
   - **Commit**: `23f3310` `feat(visual): 實作 export_visual_bundle.py 匯出腳本與安全檢查 (Task 1)`

2. **通用播放器 player.html／player.js（Task 2, P30-PLAYER）**：
   - 建立 [`demo/visual/player.html`](file:///home/hsu/Desktop/clinicbrain/demo/visual/player.html) 與 [`demo/visual/player.js`](file:///home/hsu/Desktop/clinicbrain/demo/visual/player.js)：
     - 純外部檔案架構，HTML 內**無任何內嵌腳本**，僅引入 `visual_engine.js` 與 `player.js`。
     - 嚴格靜態安全合規：絕無禁止子字串（`innerHTML`、`eval`、`localStorage`、`setInterval`、`setTimeout` 等，含註解與任何大小寫組合）。
     - 安全參數解析：嚴格檢核 `?bundle=` 參數符合 `^[A-Za-z0-9][A-Za-z0-9._/-]*\.json$`，嚴格禁止 `..`、`//`、`:`、`\`、空白與協定注入，並限定為同源路徑（`fetch("/" + bundleParam)`）。
     - 完全由 bundle 動態渲染：章節按鈕、總時長計算、字幕切換、進度條 seek 控制，並於播放結尾顯示外連 `doctor-toolbox.com` 之預約諮詢卡。
     - 對外暴露標準介面 `window.__player = {seek(t), total, ready}`，提供自動化測試與逐格截圖錄影使用。
   - 建立 [`tests/test_visual_player.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_visual_player.py)（7 個測試案例，含靜態安全掃描、負例路徑拒絕與 Playwright 瀏覽器互動測試，全數通過）。
   - **Commit**: `77871e6` `feat(visual): 實作通用影片式解說播放器 player.html 與 player.js (Task 2)`

3. **render_video.py 泛化支援 --bundle（Task 3, P30-VIDEO）**：
   - 更新 [`demo/visual/render_video.py`](file:///home/hsu/Desktop/clinicbrain/demo/visual/render_video.py)：
     - 新增 `--bundle PATH` 參數（必填，相對 repo 根的 `.json` 檔案），並套用與播放器完全相同的路徑安全檢驗。
     - 於本機背景執行緒啟動 repo 根為目錄的臨時埠 HTTP 伺服器，於無頭 Chromium 載入 `player.html?bundle=...`。
     - 等待 `window.__player.ready`，透過 `__player.total` 決定總影格數，逐格呼叫 `__player.seek(i / fps)` 並對 `.stage` 截圖。
     - 結尾預約畫面停留 `--hold` 秒，最後呼叫 ffmpeg 合成 H.264/yuv420p MP4 影片。
     - 失敗時保證清理臨時目錄，缺少 ffmpeg 或 Chromium 時輸出明確錯誤並以結束碼 `2` 結束。
   - 建立 [`tests/test_visual_video.py`](file:///home/hsu/Desktop/clinicbrain/tests/test_visual_video.py)（4 個測試案例，含缺少工具、非法路徑攻擊、檔案遺失與最小 bundle 端到端錄製測試，透過 ffprobe 驗證編碼、像素格式與 4.5s 時長，全數通過）。
   - **Commit**: `2f14bf1` `feat(visual): render_video.py 支援 --bundle 泛化匯出 (Task 3)`

---

## 2. 測試與驗收結果

- **測試執行結果**：
  執行 `uv run pytest -q -p no:cacheprovider tests/test_visual_video.py tests/test_visual_player.py tests/test_visual_bundle.py`：
  - 共 15 項測試全數通過（`15 passed in 4.62s`）。
  - 靜態安全檢核 `test_visual_engine_static.py` 4 項測試全數通過（`4 passed in 0.42s`）。
- **Playwright 執行確認**：
  Playwright 與無頭 Chromium 成功啟動並實際執行完成，未被 skip。
- **既有展示檔保護**：
  `demo/visual/full.html` 與 `demo/visual/lite.html` 零改動（保持 Phase 29 原樣）。
- **正式資料庫保護**：
  `clinic.db` SHA-256 維持為 `e28dc0089b01d59a03456bcced7974254c7986697d12dc0fb50da1e4a17ba6e1`，未遭任何存取或更動。

---

## 3. 改動檔案清單

- `scripts/export_visual_bundle.py`：新增 bundle 唯讀匯出腳本。
- `tests/test_visual_bundle.py`：新增 bundle 匯出測試套件。
- `demo/visual/player.html`：新增通用解說播放器頁面。
- `demo/visual/player.js`：新增通用解說播放器控制邏輯。
- `tests/test_visual_player.py`：新增通用播放器安全與瀏覽器測試套件。
- `demo/visual/render_video.py`：重構支援 `--bundle` 泛化匯出與臨時伺服器截圖。
- `tests/test_visual_video.py`：新增影片匯出端到端與邊界安全測試套件。
