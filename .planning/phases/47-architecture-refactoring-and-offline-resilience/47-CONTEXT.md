# Phase 47: 架構重構、效能優化與離線韌性 (Architecture Refactoring, Performance & Offline Resilience)

> **所屬里程碑**：v1.6  
> **關聯依據**：`hydrogenimprovement.md`（P2 & P3 項目，接續 Phase 46 已完成的 P0/P1 止血與安全加固）  
> **核心目標**：在不改變任何對外 API 契約與醫療合規防線的前提下，解決 `hydrogenimprovement.md` 所列之 P2/P3 結構性問題：`LIKE` 萬用字元跳脫、本地 LLM 連線池與組態化、單體巨型檔案拆分（`admin.py` / `runner.py` / `autodraft.py`）、前端完全離線化、資料庫遷移統一化與 `AGENTS.md` 瘦身，並透過 `herdr` 調度獨立 Agent Hermes (`wA:p3`) 擔任 Tester 向 `agy` 回報驗收結果。

---

## 1. 範圍界定（承接 Phase 46 之後的剩餘項目）

Phase 46 已完成 P0 回歸修復、`sync_logs` 補建、CORS / `secrets.compare_digest`、`upload_admin_file` 非同步解鎖、影片渲染鎖與 `ffmpeg` 逾時、`pyproject.toml` 與 systemd 路徑修復。Phase 47 聚焦以下剩餘項目：

1. **搜尋安全與本地 LLM 連線優化（Wave 1）**：
   - `src/query/search.py` 與 `src/query/nhi_index.py` 統一套用 `escape_like()` + `ESCAPE '\\'`。
   - `src/pageindex/llm_client.py` 支援 `CLINICBRAIN_LLM_BASE_URL` 環境變數，改用 `httpx.Client` 連線池，移除每次呼叫前的 `/v1/models` 探測開銷。
   - `src/ingestion/medical_safety.py` 預編譯 `check_dosage_prescription` 正則熱點。
2. **高複雜度單體模組拆分（Wave 2）**：
   - `src/api/routes/admin.py`（1,888 行）拆分為 `src/api/routes/admin/` 子套件，維持路由路徑與相依性 100% 相容。
   - `src/batch/runner.py`（`run_batch` 認知複雜度 256）重構為 `BatchStage` 管線。
   - `src/visual/autodraft.py`（`parse_and_build_tree_ir` 認知複雜度 444）拆分為 per-scene 驗證／組裝策略函式。
3. **離線韌性、遷移統一、文件瘦身與 Hermes 獨立驗收（Wave 3）**：
   - `src/web/static/index.html` 移除外部 Tailwind CDN，本地化 CSS 並收緊 CSP `style-src 'self'`。
   - 收斂 9 支 `scripts/migrate_*.py` 為編號式遷移器（`scripts/migrate.py --status / --apply`）。
   - 修正 `.planning/STATE.md` 衝突狀態，精簡 `AGENTS.md`（將歷史 Phase 歸檔至 `docs/architecture/`）。
   - 透過 `herdr` 指派 `wA:p3` 的 Hermes 執行獨立測試與驗收並回報 `agy`。

## 2. 不可變約束（Non-Negotiable Constraints）
- 嚴禁在無使用者明確核准下直接修改正式 `clinic.db` 臨床資料或啟用 systemd。
- 所有醫療法規防線（繁體中文、`deep_mask_prices`、劑量／處方攔截、紅旗優先、`verify_admin_key`）不得放寬。
- `admin.py` 拆分後，所有既有 `/api/v1/admin/*` 端點路徑、HTTP 方法、狀態碼與測試 mock 路徑需保持相容或同步更新。
