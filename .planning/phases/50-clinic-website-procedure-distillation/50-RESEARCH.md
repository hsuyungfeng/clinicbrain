# Phase 50 Research: 診所官網療程原理與手術步驟提煉（去診所名稱化）

**Date**: 2026-11-18
**Status**: Complete

## 1. 現況盤點與問題實證

檢查 `clinic.db` 中 `run_web_research_batch.py` 首批寫入的 5 筆 `source_type='web_upload'` 推理樹後，發現三個關鍵問題：

1. **目錄站混入來源**：`kb.commonhealth.com.tw`（康健醫療機構目錄頁）僅含診所地址、看診科別與服務時間，無任何實際醫療療程原理或手術步驟。
2. **無療程內容仍硬寫入空殼樹**：`distill_tree_from_text()` 目前只要來源文字達 200 字就強制產出四段 JSON，導致模型寫出「本頁未提供任何實際醫療療程或手術操作之原理與步驟…」等無效內容並寫入 `page_index_trees`。
3. **個別診所名稱洩漏**：
   - `distill_pipeline.py` 的 `TREE_TITLE_TEMPLATE = "{clinic_name}核心療程{index}"` 直接將診所全名寫入 `page_index_trees.title`。
   - Prompt 傳入 `{clinic_name}`，導致 `summary_text`、`procedure`、`faq_cache` 也出現「慶瑞堂中醫診所」、「嘉義市東區公明路」、「聯新國際醫院桃園國際機場醫療中心」等個別院所資訊。

## 2. 相關模組與修改邊界

- [scripts/run_web_research_batch.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/scripts/run_web_research_batch.py)
  - `EXCLUDED_HOST_SUFFIXES` 需補充 `commonhealth.com.tw`（及常見醫療名錄網域）。
  - 抓取單一首頁常只拿到最新消息／聯絡方式，可整合站內子頁探索（優先挑選含「療程、手術、治療、衛教、適應症、原理、步驟」連結之頁面），以取得實質醫療流程內容。
- [src/scraper/distill_pipeline.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/scraper/distill_pipeline.py)
  - 針對 `category="general"`（外部診所公開衛教蒐集）：
    - 不再將 `{clinic_name}` 放入 `TREE_TITLE_TEMPLATE` 或 `FAQ_PROMPT_TEMPLATE`。
    - 先萃取「純疾病／療程名稱」（例如「微創甲溝炎矯正術」）與判斷是否具備實質療程原理或手術步驟；若無則跳過寫入。
- [src/pageindex/tree_distiller.py](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/pageindex/tree_distiller.py)
  - `TREE_DISTILL_PROMPT_TEMPLATE` 強化要求聚焦「疾病病理、治療原理、手術／操作步驟、適應症與術後照護」，並明確禁止輸出任何診所／醫院名稱、地址與分院資訊。
  - 支援傳入 `forbidden_clinic_names`（或通用診所名遮蔽／拒絕檢查）與「無實質療程內容拒絕寫入」機制。

## 3. 驗證策略

- 單元測試（隔離 SQLite / `/tmp`）：
  1. 僅含地址／門診表／無療程步驟之文字 → 必須跳過，寫入 0 棵推理樹。
  2. 含實質療程原理與手術步驟之文字（夾帶某診所名稱與地址）→ 寫入之 `title`、`summary_text`、`pre_op`、`procedure`、`post_op_short`、`maintenance` 與 `faq_cache` 皆不得含個別診所名稱。
  3. `commonhealth.com.tw` 等目錄站被 `_is_valid_clinic_url()` 過濾。
- 獨立 Tester：由 **Hermes** 透過 `hermes chat --oneshot` 於 `/tmp` 隔離環境執行測試與驗證回報。
