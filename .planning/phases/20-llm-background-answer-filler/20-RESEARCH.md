# Phase 20 Research: LLM 空閒時間衛教答案自動生成器

## 1. 現有架構資產盤點
在 Phase 19 後期，後端已初步建立背景作業核心：
- **核心模組 (`src/pageindex/batch_answer_job.py`)**：
  - 具備背景執行緒 `_worker`，逐題呼叫 `generate_answer_for_faq`。
  - 具備單例狀態保護 `_state_lock`、快照查詢 `snapshot()` 與取消標記 `_cancel`。
  - 與本機 LLM 呼叫共享 `_GENERATION_LOCK`，防範並發擠爆 GPU 顯存。
  - 每題獨立 SQLite 連線與獨立 commit，確保中斷或重啟時成果不遺失。
- **現有路由 (`src/api/routes/admin.py`)**：
  - `POST /api/v1/admin/review/batch-generate`（需手動傳入 `faq_ids: list[int]`，上限 100 筆）。
  - `GET /api/v1/admin/review/batch-generate/status`（查詢快照）。
  - `POST /api/v1/admin/review/batch-generate/cancel`（取消）。

## 2. 需補齊之關鍵斷點

### 2.1 後端功能缺口
1. **缺少「全自動偵測待補齊題目」端點**：
   - 當前 API 必須前端事先撈出所有 `faq_ids` 傳入，且受限於單次 100 筆上限。
   - 需要提供：`POST /api/v1/admin/review/autofill/all`（或傳入 `auto_all=True`），後端自動查詢所有 `review_status='pending'` 且 `needs_answer=1` 的項目，支援自動分批排入背景 Worker。
2. **夜間批次未自動串接**：
   - `src/batch/runner.py`（夜間離峰批次）目前只預生成種子 FAQ 與 PageIndex 推理樹，尚未自動掃描 Web 上傳留下的 `needs_answer=1` 待審題目。

### 2.2 前端 Web App 缺口
1. **介面未提供背景補齊觸發入口**：
   - 頂部工具列缺少【🚀 一鍵背景補齊全部答案】按鈕。
   - 底部浮動操作列缺少【🤖 批量生成所選答案】按鈕。
2. **缺少即時進度反饋介面**：
   - 缺少進度展示橫幅（Progress Banner）與輪詢邏輯：當背景正在執行時，前端每 2~3 秒輪詢一次狀態，動態展示百分比、目前處理之題目 ID、已成功數與跳過數，並提供【⏹️ 中止】按鈕。

---

## 3. 流水線與職責劃分（User Golden Rule）
- **實作 (Agy 3.6 Flash, `w5:p2`)**：後端自動端點擴充、夜間批次串接、前端 UI 按鈕與輪詢進度條元件。
- **加固 (Claude 5.5 Sonnet, `w5:p3`)**：對抗性審查（單例競爭、頻繁輪詢負載、斷網優雅降級、`AGENTS.md` 2.19 節更新）。
- **驗收 (Hermes Agent, `w5:p4`)**：跑全套回歸測試、確認正式庫 SHA-256 恆定。
