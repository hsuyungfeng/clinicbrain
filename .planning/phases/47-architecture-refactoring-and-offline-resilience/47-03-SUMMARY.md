# Phase 47-03 Summary — Wave 3: 離線韌性、統一遷移器、文件瘦身與 Hermes 驗收

- **前端 Tailwind CSS 離線化與 CSP 收緊**：本地化 `src/web/static/tailwind.min.css`，更新 `src/web/static/index.html` 引用 `/admin/tailwind.min.css`，並於 `src/api/app.py` 移除 CSP `https://cdn.jsdelivr.net`。
- **統一資料庫遷移器**：新增 `scripts/migrate.py`（支援 `--status` 與 `--apply`），以 `schema_migrations` 統一追蹤 9 支遷移腳本。
- **文件瘦身**：將 `AGENTS.md` §2.9 起歷史 Phase 規範歸檔至 `docs/architecture/phase-history.md`（`AGENTS.md` 由 181KB 精簡至 45KB），並同步更新 `.planning/STATE.md` 與 `.planning/ROADMAP.md`。
- **Hermes 獨立驗收**：透過 `herdr` 指派 `wA:p3` 執行 Phase 47 驗證套件並產出 `47-VERIFICATION.md`。
