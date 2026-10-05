# Phase 12 Plan 06: 端到端整合驗收與文件 總結 (GC-01, GC-02, GC-03, GC-04, DEBT-03)

## 執行概述

- **執行日期**：2026-10-05
- **目標需求**：GC-01（疾病種子清單擴充）、GC-02（用藥劑量與處方攔截層）、GC-03（就醫警訊檢驗、免責宣告欄位、sync 前置檢核）、GC-04（醫師審核工具主題檢視、驗證報告與相近診所 FAQ）、DEBT-03（被駁回題目人工標記重生成生命週期）
- **狀態**：完成 (PASSED)
- **測試通過情況**：全量 858 passed, 0 failed, 1 warning (21.81s)（基線 669，淨增 189 個測試）
- **正式資料庫完整性**：`clinic.db` SHA-256 全程維持 `ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e`，零寫入污染（`sha256sum -c prod.sha256` 成功）

---

## 五大需求端到端驗收成果

1. **GC-01: 疾病種子清單擴充與簽核門檻**
   - 擴充 `data/batch/faq_seeds.json`，納入感冒、流感、急性腸胃炎、過敏性鼻炎 4 大常見疾病，共 17 題繁體中文標準問題。
   - 支援 `question_tags` 標籤分組（`what`、`symptoms`、`when_to_see_doctor`、`home_care`）。
   - 實施硬性簽核門檻（Hard Gate），程式碼絕不參考暫存檔，端到端測試驗證 4 主題與 17 題完整加載。

2. **GC-02: 用藥劑量與處方建議攔截層**
   - 獨立醫療安全模組 `src/ingestion/medical_safety.py`，定義 DX-1~DX-5 規則，攔截具體劑量與處方建議。
   - 語料實測數據：劑量正例 47/47 攔截、負例 50/50 放行；正式庫既有 40 筆診所 FAQ 回掃 0 誤拒（包含診所 FAQ id 6 之「給予抗生素」描述性敘述）。
   - 批次生成管線全面串接，違規項分類為 `dosage_prescription` 拒絕代碼。

3. **GC-03: 就醫警訊檢驗、免責宣告欄位與同步前置檢核**
   - General 問答之 answer 強制要求具體症狀或數值條件之就醫警訊收尾句，實測正例 15/15 通過、負例 17/17 攔截；單純「若症狀加重請回診」單獨出現判定為不合規；雙層整合案例 4/4 通過。
   - 自然語言查詢結構純加法擴充 `disclaimer: Optional[str] = None`；當 `data_level == 'general'` 時自動附帶法定醫療免責宣告文字，診所層級為 `null`；匿名諮詢端點與自然語言查詢端點在命中 general 題目時皆附帶免責聲明。
   - 雙向資料同步匯入（`/api/v1/sync/import`）對 general FAQ 實施前置合規檢核，劑量違規或缺警訊者以 HTTP 400 整批原子性阻斷；special 類別維持豁免。

4. **GC-04: 醫師審核工具增強與衝突比對**
   - 提供共用覆蓋率純函式 `faq_shortcut.faq_coverage`，與快取短路同一套標準化與覆蓋率定義。
   - 相近診所問答衝突檢索 `find_similar_clinic_faqs`，門檻引用 `CLINIC_RELATED_FLOOR = 0.4`，嚴格隔離未核准之 LLM 生成診所問答，支援 `mode=ro` 唯讀連線。
   - 審核工具 `review_faq.py list` 支援 `--topic` 主題篩選與來源/驗證結果顯示；`show` 顯示生成來源、驗證結果與相近診所問答；`approve` 強制檢驗 general 警訊。
   - 詞彙守衛局限性揭示：17 題一般疾病種子對院所既有 40 筆醫美外科 FAQ 最高詞彙覆蓋率皆 $\le 0.30$（$< 0.4$），衝突清單為空不代表臨床無指示衝突，審核工具 `show` 一律附帶醒目警語提示醫師自行比對。

5. **DEBT-03: 被駁回題目手動標記重生成生命週期**
   - 唯一標記函式 `mark_for_regeneration` 僅允許標記 `rejected` 狀態之 `llm_generated` 項目。
   - 批次生成 `existing_questions` 支援 `exclude_regen_marked=True`，優先處理被標記之主題。
   - CLI `mark-regen` 子命令提供醫師標記入口，未帶 `--allow-prod-db` 於連線前以 code 2 阻斷正式庫操作。
   - 端到端重生成生命週期驗證：標記重生成後新答案以 `pending` 入庫且版號遞增；若模型回傳相同答案則清除重生成旗標並維持 `rejected`（計入 `faq_regen_unchanged`），避免無限推論。

---

## 測試數據與檔案變更

- **基線測試數**：669
- **最終測試數**：858（淨增 189 個測試，0 failed，1 warning）
- **新增/修改檔案清單**：
  - `src/ingestion/medical_safety.py`（新增：DX-1~5 劑量與處方攔截、就醫警訊收尾句檢驗）
  - `src/pageindex/faq_conflicts.py`（新增：相近診所 FAQ 檢索與覆蓋率比對）
  - `data/batch/faq_seeds.json`（擴充：4 個 general 疾病主題、17 題標準問題、question_tags）
  - `src/batch/topic_sources.py`（支援 `QUESTION_TAGS` 與種子清單標籤校驗）
  - `src/batch/faq_generator.py`（多層合規過濾、標記重生成排除、regen 計數器）
  - `src/batch/runner.py`（優先處理重生成標記主題、BatchSummary 統計欄位）
  - `src/pageindex/faq_review.py`（`mark_for_regeneration`、`clear_regeneration_flag`、`list_faqs` 主題篩選、`validation_report`）
  - `scripts/review_faq.py`（`list --topic`、`show` 衝突檢視、`approve` 警訊檢核、`mark-regen` 子命令）
  - `src/query/faq_shortcut.py`（公開純函式 `faq_coverage`）
  - `src/query/router.py`（`QueryResponse.disclaimer`、`STOPWORD_SPLIT_PATTERN`）
  - `src/api/models/query.py`（`QueryResponseModel.disclaimer`）
  - `src/api/routes/query.py`（查詢回應填入 `disclaimer`）
  - `src/api/routes/sync.py`（`/sync/import` general 前置合規驗證）
  - `tests/test_medical_safety.py`（新增 120 tests）
  - `tests/test_disease_seeds.py`（新增 11 tests）
  - `tests/test_faq_regen.py`（新增 8 tests）
  - `tests/test_query_disclaimer_field.py`（新增 6 tests）
  - `tests/test_sync_general_validation.py`（新增 5 tests）
  - `tests/test_faq_conflicts.py`（新增 6 tests）
  - `tests/test_review_faq_cli.py`（追加 5 tests，0 刪除行）
  - `tests/test_phase12_acceptance.py`（新增 5 tests 端到端驗收）
  - `AGENTS.md`（更新 2.10 已知限制 5、新增 2.12 一般疾病內容生成與審核、更新第 4 節目錄結構）
  - `docs/nightly-batch.md`（新增被駁回題目重新生成小節）

---

## 驗收確認清單

- [x] `tests/test_phase12_acceptance.py` 5 個端到端測試全數通過
- [x] 全量回歸測試 858 passed, 0 failed, 1 warning (21.81s)
- [x] 正式庫 SHA-256 前後即時量測完全一致（`ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e`）
- [x] `.planning/ROADMAP.md`、`src/general/*`、`src/api/routes/general.py` 零修改
- [x] `AGENTS.md` 2.12 包含 20 項可收集之真實測試名稱引用，6 項已知限制完整記錄
- [x] `docs/nightly-batch.md` 包含 `mark-regen` 指令與營運說明
