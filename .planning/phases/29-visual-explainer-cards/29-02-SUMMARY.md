# Phase 29 Plan 02: 視覺解說卡本地 LLM 預生成與醫師審核 CLI 執行摘要

## 1. 任務目標與完成範圍

本計畫依據 `29-02-PLAN.md` 規格，建立視覺解說卡的骨架檔、本地 LLM 說明文字生成器，以及預生成與醫師審核 CLI：
1. **骨架檔與生成器（Task 1, P29-GEN）**：
   - 建立人工撰寫之首個主題骨架檔 `data/visual/skeletons/autologous-fat-grafting.json`（自體脂肪移植原理，含 3 個場景：`process_diagram`、`contrast`、`timeline`，以及 5 條一般概念要點 `reference`）。
   - 於 `src/pageindex/llm_client.py` 新增 `VISUAL_SAMPLING`（忠實取樣、`enable_thinking: False`、`max_tokens: 600`、無 `reasoning_effort`），未改動既有取樣常數。
   - 建立 `src/visual/generator.py`：
     - `load_skeleton`：載入並驗證骨架全文（無禁詞、無數字、無 HTML 與價格）。
     - `build_prompt`：提示詞禁用詞表直接由 `ir.VISUAL_EXTRA_FORBIDDEN` 同步組出，要求只輸出固定「場景K：」行，並提供替代語指引。
     - `parse_output`：清理 `<think>` 標籤並擷取各場景說明。
     - `generate_ir`：模型僅填 `caption`，結構欄位（`blueprint`、`title`、`labels`、`keywords`、`topic_key`）100% 由骨架決定；經 `validate_ir` 檢驗通過才回傳，最多嘗試 2 次；整合 `GENERATION_LOCK` 與 `nightly_batch_running` 排程互斥。
2. **預生成 CLI 與醫師審核 CLI（Task 2, P29-GEN, P29-REVIEW）**：
   - 建立 `scripts/generate_visual_assets.py`：支援 `--db`、`--topic`、`--dry-run`（不連庫、不呼叫 LLM）、`--allow-prod-db`（正式庫未帶旗標於連線前結束碼 2）；未遷移庫以結束碼 2 退出；產出一律寫入 `pending`，失敗只印代碼不洩漏原文。
   - 建立 `scripts/review_visual.py`：支援 `list`、`show`（唯讀連線 `mode=ro`，且固定附「請逐句確認醫學敘述與用詞後再核准」警語）、`approve`、`reject`（正式庫寫入需 `--allow-prod-db`，核准前重跑 `validate_ir`）。

---

## 2. 改動檔案

- `data/visual/skeletons/autologous-fat-grafting.json`：自體脂肪移植骨架檔。
- `src/pageindex/llm_client.py`：新增 `VISUAL_SAMPLING` 常數。
- `src/visual/generator.py`：骨架載入、提示詞組裝、輸出解析與生成驗證。
- `scripts/generate_visual_assets.py`：預生成 CLI 工具。
- `scripts/review_visual.py`：醫師審核 CLI 工具。
- `tests/test_visual_generator.py`：骨架載入、提示詞禁詞同步、生成與鎖單元測試。
- `tests/test_visual_cli.py`：生成與審核 CLI 生命週期與安全守門單元測試。
- `.planning/phases/29-visual-explainer-cards/29-02-SUMMARY.md`：本執行摘要。

---

## 3. 驗收指令執行結果

1. **Task 1 驗收測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_visual_generator.py tests/test_visual_ir.py tests/test_llm_client.py`
   -> **27 passed in 0.55s**。
2. **Task 2 驗收測試**：
   `uv run pytest -q -p no:cacheprovider tests/test_visual_cli.py tests/test_visual_generator.py tests/test_visual_writer.py`
   -> **21 passed in 0.83s**。
3. **正式資料庫雜湊不變守門**：
   `sha256sum clinic.db`
   -> `ae1a3763d17f212ec99dbc53264db6828df6897a3a62e964f348c1b02d545bc2  clinic.db`（完全未變）。

---

## 4. 偏離與特別說明

- 無任何偏離計畫之處。測試全程使用注入之 fake `llm_call` 與隔離資料庫複本，未呼叫真實 LLM、未碰觸正式資料庫。
