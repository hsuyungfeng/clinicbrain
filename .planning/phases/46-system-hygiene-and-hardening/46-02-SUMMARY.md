---
phase: 46-system-hygiene-and-hardening
plan: 02
wave: 2
status: completed
completed_at: 2026-11-13T15:16:40+08:00
---

# 46-02-SUMMARY: P0/P1 API 安全防禦加固、非同步事件迴圈解鎖與背景渲染護欄

## 執行成果
1. **CORS 安全收緊與白名單機制 (`src/api/config.py` & `src/api/app.py`)**：
   - 杜絕 `allow_origins=["*"]` 與 `allow_credentials=True` 同時並存之反射憑證漏洞；僅在明確網域白名單時啟用 credentials。
   - `APIConfig` 支援環境變數 `CLINICBRAIN_CORS_ORIGINS`（逗號分隔），預設白名單收斂至本機 `http://127.0.0.1:8000`、`http://localhost:8000` 與 `http://127.0.0.1:8080`。
2. **常數時間 API 金鑰認證 (`src/api/dependencies.py`)**：
   - 全面落實 `AGENTS.md` 規劃之 AUTH-04：在 `verify_admin_key` 使用 Python 內建之 `secrets.compare_digest` 進行常數時間金鑰比對，阻斷時序側信道攻擊（Timing Attack）。
3. **解除檔案上傳事件迴圈阻塞 (`src/api/routes/admin.py`)**：
   - 將 `upload_admin_file` 中的同步 CPU 密集運算（MarkItDown / DOCX / OpenCC 繁簡轉換 / 去識別化與 SQLite 寫入）抽離為 `_process_admin_upload_sync`。
   - 透過 `starlette.concurrency.run_in_threadpool` 將其移至背景執行緒池執行，釋放主 asyncio 事件迴圈，保證高負載上傳期間 `/health` 與查詢端點低延遲響應。
4. **影片渲染防重入互斥鎖與 Subprocess 逾時 (`src/visual/video_queue.py`)**：
   - 實作行程內 `_rendering_topics: set[str]` 與執行緒鎖 `_rendering_lock`，阻斷同一主題/規格重複點擊造成的寫入衝突。
   - 為 `ffmpeg` 子行程加上 `timeout=180` 逾時防禦，並改採暫存檔 `.tmp.mp4` 成功後原子替換（`os.replace`），杜絕損毀影片落地。
