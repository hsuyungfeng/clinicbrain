# 47-HERMES-TESTER-REPORT（Phase 47 獨立 Tester 審查報告）

> Tester：Hermes (`wA:p3` 角色代號）
> 日期：2026-11-14 10:0x CST（CST, UTC+08:00）
> 基準 commit：`9c80015`（`hydrogenimprovement.md` 分析基準）
> 約束遵守：**未修改任何程式碼**、**未觸及正式 `clinic.db`**（全部為唯讀檢查 + pytest，未啟用的為未建表的遷移指令）。

---

## 一、基準測試結果（Benchmark）—— ✅ 全綠

執行指令（原样）：
```
.venv/bin/python -m pytest tests/test_admin_ask.py tests/test_batch_runner.py \
  tests/test_search.py tests/test_nhi_index.py tests/test_llm_client.py -q
```

| 測試檔案 | 結果 |
| :--- | :--- |
| tests/test_admin_ask.py | ✅ 8 passed |
| tests/test_batch_runner.py | ✅ 14 passed |
| tests/test_search.py | ✅ 22 passed |
| tests/test_nhi_index.py | ✅ 4 passed |
| tests/test_llm_client.py | ✅ 9 passed |
| **合計** | **✅ 57 passed / 0 failed**（9.06s）|

- 唯一警告為 Starlette TestClient 使用 httpx 的 deprecation（非阻断，與本次重構無關）。
- 結論：**基線健康**，這五個模組在重構前有乾淨的測試護城河。

---

## 二、Plan 檔案路徑與驗證指令可行性

| Wave | 列出的 source / test 路徑 | 可行性 |
| :--- | :--- | :--- |
| 01（Wave 1） | `src/query/search.py`、`nhi_index.py`、`src/pageindex/llm_client.py`、`src/ingestion/medical_safety.py`、對應 3 個 test | ✅ 全部存在 |
| 02（Wave 2） | `src/api/routes/admin.py`、`src/batch/runner.py`、`src/visual/autodraft.py`、`test_admin*.py`、`test_batch_runner.py`、`test_visual_autodraft.py` | ✅ 主要 source/test 存在（Wave 3 才需確認 `test_visual_autodraft.py`） |
| 03（Wave 3） | `src/web/static/index.html`、`src/api/app.py`、`scripts/migrate.py` | ⚠️ `index.html`/`app.py` 存在；**`scripts/migrate.py` 尚不存在**（它是 Wave 3 Task 2 的「產出物」，故其驗證指令 `.venv/bin/python scripts/migrate.py --status` 目前無法執行） |

⚠️ **Wave 3 驗證指令可行性提醒**：`47-03` 的 Task 2 verify 指令 `.venv/bin/python scripts/migrate.py --status` 依賴 Wave 3 才建立的 `migrate.py`。此為「未實作波次」的正常狀態，但應在 Wave 3 動筆前先建立該檔案，否則該 verify 指令今日必失敗。

---

## 三、P2/P3 涵蓋度核對（vs `hydrogenimprovement.md`）

### ✅ 已涵蓋的核心項目
| hydrogenimprovement.md | Plan 落點 | 狀態 |
| :--- | :--- | :--- |
| P2 3.1 admin.py 1,888 行拆分 | 47-02 Task 1 | ✅ |
| P2 3.1 autodraft.py (444) 拆分 | 47-02 Task 3 | ✅ |
| P2 3.1 runner.py (256) → BatchStage | 47-02 Task 2 | ✅ |
| P2 3.4 LIKE 跳脫 `%`/`_` + `escape_like` | 47-01 Task 1 | ✅ |
| P3 4.1 medical_safety 正則熱點預編譯 | 47-01 Task 3 | ✅ |
| P3 4.2 llm_client env var + httpx 連線池 | 47-01 Task 2 | ✅ |
| P3 4.3 移除外部 Tailwind CDN | 47-03 Task 1 | ✅ |
| P3 4.4 STATE.md / AGENTS.md 瘦身 | 47-03 Task 2 | ✅ |
| P2 3.3.1 9 支 migrate 統一為編號式 | 47-03 Task 2 | ✅ |

### ⚠️ 未涵蓋 / 部分涵蓋的剩餘項目（P2/P3 缺口）
1. **P2 3.2 前端 JS ES Modules 分割 —— 完全未涵蓋**
   `47-03` 只處理 CSS/CDN（`visual_engine.js` 3,919 行、`app.js` 2,916 行、`anatomy_viewer.js` 1,468 行、`three.js` 1.3MB 的 ES Modules 化、three.js 改 min、抽出安全 DOM builder / API client）。這是 P2 大項，Plan 只做了其中最輕的 CSS 段。
2. **P2 3.1 剩餘高複雜度函式 —— 未涵蓋**：`patient_prefill.py run_prefill_stage`(160)、`sync.py import_sync_data`(115)、`fetch.py fetch_page`(8 參數)。Plan 聚焦三大檔案，未提這三檔。
3. **P2 3.3.2 寫入連線缺 `busy_timeout`** —— 未涵蓋。`dependencies.py:get_write_db()` 未設 `PRAGMA busy_timeout`。
4. **P2 3.5 109 處 `except Exception` 靜默捕捉** —— 完全未涵蓋，三個 Wave 都無對應任務。
5. **P3 4.4 scripts/ 分層**（`ops/`、`migrations/`、`oneoff/`）—— 僅建 `migrate.py` + `schema_migrations` 表，未實際重整 `scripts/` 目錄。
6. **P3 4.1 其他 loop hotspots**（`review.py`、`drafts.py`）—— 僅 `medical_safety.py`。

> 綜合評語：Plans 完整涵蓋了 P2/P3 的「**骨幹大項**」（admin/autodraft/runner 拆分、LIKE 跳脫、llm pool、CDN、遷移統一、AGENTS 瘦身），架構分波合理（1→2→3 依賴清晰）。但**非 100% 涵蓋**——上述 6 項缺口（尤其 3.2 前端 JS ES Modules 與 3.5 靜默 except）需另行增列 Wave 4 或在後續里程碑補上，否则 P2 重構與 P3 整理會留下明顯尾巴。

---

## 四、獨立 Tester 關鍵發現：Phase 47 目前「尚未實作」

基準測試全綠是因為它跑在**未改動**的程式碼上。實際查證 `hydrogenimprovement.md` 所列 P2/P3 改變**全部尚未寫入程式**：

| 項目 | 實際狀態（grep 查證） |
| :--- | :--- |
| `escape_like`（search.py / nhi_index.py） | ❌ 不存在（grep 0 matches）；`test_search.py` 亦無 `%`/`_` 全表跳脫測試 |
| `llm_client.py` | ❌ 仍用 `urllib.request`，無 `httpx`、無 `CLINICBRAIN_LLM_BASE_URL` |
| `medical_safety.py` | ❌ regex 仍為函式內字串，無模組層級 `re.compile` 預編譯 |
| `admin.py` | ❌ 仍為單一檔案 **1,911 行**（未拆 `routes/admin/`） |
| `index.html` | ❌ 仍 `https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/...`（CDN 未移除） |
| `scripts/migrate.py` | ❌ 不存在；9 支 `migrate_*.py` 仍零散 |

> 含意：本次 benchmark（57/57）驗證的是「**重構前的健康基線**」，並非 Phase 47 交付的驗收。上述 Plan 的 verify 指令（如 `pytest test_search.py -q`）只有在 Wave 1 寫入 `escape_like` 並補上對應 `%`/`_` 跳脫測試後，才會真正驗收 P2 3.4。建議 **Wave 3 啟動前先建立 `scripts/migrate.py`**，以消除 Wave 3 首個 verify 指令的必失敗風險。

---

## 五、給 agy 的建議（Action Items）
1. **維持現基線**：57/57 通過，無需任何修復即可直接進入 Phase 47 實作。
2. **增列缺口任務**（優先序由大到小）：3.2 前端 JS ES Modules ＞ 3.5 靜默 except 结构化 ＞ 3.1 patient_prefill/sync/fetch ＞ 3.3.2 busy_timeout ＞ 4.4 scripts/分層。
3. **Wave 3 前置**：動筆前先建 `scripts/migrate.py`（`--status`/`--apply`），讓其 verify 指令可執行。
4. **驗收時再跑一次本命令**：待 Wave 1 完成後重跑 `pytest ... -q`，確認新補的 escape/llm 測試亦全綠。

— Tester 報告完 —
