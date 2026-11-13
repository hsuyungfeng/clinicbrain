---
phase: 43-automated-video-queue
plan: 01
wave: 1
status: completed
completed_at: 2026-11-12T10:08:30+08:00
---

# 43-01-SUMMARY: 影片佇列引擎實作、直接讀取資料庫 IR 渲染與雙尺寸支援

## 執行成果
1. **影片佇列渲染模組實裝 (`src/visual/video_queue.py`)**：
   - `compute_ir_sha256`：對 IR 結構進行標準化排序序列化，保證 SHA-256 確定性。
   - `get_asset_bundle_data`：直接自 SQLite `visual_assets` 查詢已核准之 `ir_json`，自動關聯 `clinic_info` 取得院所代表號與名稱，並強制注入繁體中文法定免責聲明。
   - `DynamicBundleHandler`：提供記憶體動態 Bundle HTTP 服務，完全擺脫磁碟靜態檔案依賴。
   - `render_asset_to_video`：以無頭 Chromium 逐格 seek 截圖，支援 16:9 橫屏 (`landscape`, 1920×1080) 與 9:16 豎屏 (`portrait`, 1080×1920) 雙尺寸規範，透過 ffmpeg 合成為 H.264 (yuv420p) 高畫質 MP4 影片與 sidecar metadata。
   - SHA-256 增量快取防重染：比對現存 MP4 與 metadata 中的 SHA-256，未變動時秒級跳過。
   - `batch_render_queue`：支援全庫或指定主題的批次排程與統計回報。
2. **單元與端到端測試覆蓋 (`tests/test_visual_video_queue.py`)**：
   - 4/4 測試全數通過（雜湊確定性、免責聲明組裝、增量快取跳過、ffprobe 實體驗收 1920×1080 與 1080×1920 雙尺寸 MP4）。
