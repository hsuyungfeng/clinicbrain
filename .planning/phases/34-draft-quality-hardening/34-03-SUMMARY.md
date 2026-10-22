# 34-03 SUMMARY：template_override 覆寫欄位（程式完成，正式庫遷移待核准）
- `src/db/clinic_schema.sql`：visual_assets 新增 `template_override TEXT`。
- `scripts/migrate_visual_template_override.py`：冪等、交易性；正式庫需 `--confirm-prod-backup`。已在副本驗證（保留既有列、重跑無變更、dry-run 不寫入）。
- `src/visual/autodraft.py`：覆寫優先於關鍵字推斷；非法值回傳 `unknown_blueprint`，且在呼叫 LLM 之前拒絕。
- `tests/test_visual_template_override.py`：6 項通過。
- **未執行**：正式庫 `clinic.db` 的遷移（需使用者核准）。
