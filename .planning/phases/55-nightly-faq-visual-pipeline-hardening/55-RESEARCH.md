# Phase 55 Research: 夜間 FAQ 自動生成與動畫管線強化 (Nightly FAQ & Visual Pipeline Hardening)

**Researched:** 2026-11-24
**Scope:** `scripts/run_nightly_batch.py`, `src/batch/runner.py`, `src/batch/patient_prefill.py`, `src/batch/faq_generator.py`, `src/visual/autodraft.py`, `src/refresh/sources.py`, `scripts/run_daily_knowledge_refresh.py`

## 1. 現況與實測數據（2026-11-24 `03:30` & `04:45` 夜間批次）

1. **`patient_prefill` 主題上限與 `generate_faq` 耦合**
   - `src/batch/patient_prefill.py:127` 直接讀取 `cfg.max_faq_topics`（crontab 設為 `--max-faq-topics 5`）。
   - 2026-11-24 實測：`run_nightly_batch.py` 僅耗時 **3 分 52 秒**（預算 3600 秒，閒置超過 56 分鐘），`prefill_topics_planned = 85`、`prefill_generated = 21`、**`prefill_backlog = 80`**。以每晚 5 主題的速度需約 16 晚才能消化完畢。
2. **FAQ 驗證失敗未重試與 `question_not_in_seed` 嚴格退件**
   - `src/batch/patient_prefill.py:285-296`：`validate_composed()` 失敗（如 `missing_warning`、`dosage_or_prescription`）直接累計 `rejected` 並丟棄。2026-11-23 剔除 6 筆、11-24 剔除 4 筆。
   - `src/batch/faq_generator.py:301-313`：當 `pending_questions` 多題或模型微調問題字句時，若 `norm_q` 不完全吻合 `norm_pending_map` 會直接標記 `question_not_in_seed` 退件；另外 `generate_topic_faqs` 亦未對合規失敗做帶錯誤原因的單次重試。
3. **夜間「動畫」僅渲染既有資產，缺乏自動草擬階段**
   - `src/batch/runner.py:582-609` 的 `_stage_video_render` 僅針對已 `approved` 的 `visual_assets` 呼叫 `batch_render_queue()` 輸出 MP4（2026-11-24：`rendered=1, skipped=397`）。
   - 夜間批次沒有自動呼叫 `src/visual/autodraft.py:autodraft_from_tree()` 為「已有 `approved` 推理樹但尚未建立 `visual_assets` 的主題」產出 `pending` 動畫草稿。
   - 注意：`autodraft_from_tree()` 內建 `nightly_batch_running(db_path)` 防護，因此若在 `run_nightly_batch.py` 內部呼叫時需傳入適當旗標或走內部 helper，避免因自己持有 `.nightly.lock` 而回傳 `busy`。
4. **`video_render` 缺少 CLI `--video-render-limit` 防護**
   - `BatchConfig`（`src/batch/runner.py:74`）已定義 `video_render_limit: Optional[int] = None` 與 `video_render_aspect: str = "landscape"`，但 `scripts/run_nightly_batch.py` 尚未暴露對應 CLI 參數。
   - 若更新 `visual_engine.js` 導致 398 部影片 SHA-256 全部失效重算，無上限保護可能造成夜間超時或佔用白天時間。
5. **`run_daily_knowledge_refresh.py` 的 `RSS=0` 根因**
   - 實機測試 `src/refresh/sources.py` 的 `OFFICIAL_RSS_FEEDS`：
     - `https://www.cdc.gov.tw/RSS/RssXml/Emerald/1` → **HTTP 404 Not Found**
     - `https://www.fda.gov.tw/RSS/RssXml/25` → **XML `ParseError: mismatched tag: line 13, column 2`**（回傳非標準 RSS XML / 錯誤頁）
   - 且 `fetch_official_feeds()` 以 `except Exception: continue` 靜默吞掉所有異常，導致日誌僅見 `RSS=0` 而無錯誤提示。
   - 衛福部食藥署實際可用 RSS 頻道包含 `https://www.fda.gov.tw/TC/rssLawMedical.ashx` 等；疾管署 RSS 導覽頁為 `https://www.cdc.gov.tw/Home/Info/105`。

## 2. 風險與約束

- **資料庫安全**：`faq_cache`、`visual_assets` 新增列一律維持 `review_status = 'pending'`，絕不自動核准。
- **不破壞既有 API / CLI 相容性**：新增參數皆提供向後相容預設值（`--max-prefill-topics`、`--video-render-limit`、`--video-render-aspect`、`--max-visual-autodraft` / `--skip-visual-autodraft`）。
- **Hermes 獨立驗收（Herdr）**：規劃完成後由 Herdr `wA:p3` Hermes 擔任 PlanChecker；實作完成後由 Hermes 擔任 Tester 執行測試驗證。
