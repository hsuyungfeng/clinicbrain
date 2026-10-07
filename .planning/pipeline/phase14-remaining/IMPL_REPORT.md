# Phase 14 SOAP 剩餘項目改善實作報告 (IMPL_REPORT.md)

> **實作完成時間**：2026-10-07  
> **測試成果**：`pytest tests/test_soap*.py` 全數 67 項測試通過 (`67 passed, failed=0`)  
> **正式庫安全驗證**：`clinic.db` SHA-256 前綴維持 `ad24426c`（零變更、零污染）

---

## 一、檔案變更清單 (Modified Files Summary)

本專案恪守 `PLAN.md` 實施規格，僅修改允許之白名單檔案：

| 檔案路徑 | 變更類型 | 說明 / 關鍵修訂內容 |
|---|---|---|
| `scripts/migrate_soap_schema.py` | 原始碼修訂 | 將第 106 行防禦檢核調整為 `if not args.dry_run and is_prod and not args.confirm_prod_backup:`，允許 `--dry-run` 在不帶 `--confirm-prod-backup` 旗標時正常預覽 DDL 輸出。 |
| `src/soap/section_parser.py` | 核心演算法 | 實現 `parse_soap_text` 確定性切分與 `extract_general_medical_insights` 否定防禦：<br>1. 全空白與符號前置正規化。<br>2. 合格邊界 (B1) 與位置限定（單字母標記限定行首與括號內）。<br>3. 否定片語白名單、轉折詞中斷、排除黑名單與頓號列舉延續。<br>4. Assessment 為空時 Conditions 保持空清單。<br>5. 最長匹配去重與 symptoms 僅掃描 S/O。 |
| `tests/test_soap_hardening.py` | 測試檔 | 補充項目一 `--dry-run` 退出碼與連線斷言測試，確認 dry-run 期間零資料庫連線。 |
| `tests/test_soap_deid_parser.py` | 測試檔 | 補充 Regression Guards（守門測試 1~5）與 Red TDD 測試（測試 3~18）。 |
| `tests/test_soap_api.py` | 測試檔 | 補充 Red TDD 測試（測試 19 端到端標籤否定清洗）。 |

---

## 二、三項任務執行細節與 TDD 驗證紀錄

### 【任務 1-B】：修復 `scripts/migrate_soap_schema.py` Dry-Run

- **變更點**：修改第 106 行防禦條件，使 `--dry-run` 模式下直接輸出 DDL 內容，不再誤被正式庫防禦分支攔截。
- **測試命令**：
  ```bash
  python3 scripts/migrate_soap_schema.py --dry-run
  pytest tests/test_soap_hardening.py -k migrate_soap_schema
  ```
- **終端機輸出驗證**：
  ```text
  🔍 [Dry-Run 模式] 將對目標資料庫執行的 DDL 如下：
  --------------------------------------------------
  CREATE TABLE IF NOT EXISTS soap_records ( ... );
  ...
  ✨ Dry-Run 完成，未對資料庫進行任何實質修改。
  
  tests/test_soap_hardening.py ... [100%]
  3 passed in 0.25s
  ```

---

### 【任務 2】：SOAP 段落切分 (`parse_soap_text`)

- **關鍵規則實作**：
  - **前置正規化**：將 `\r\n`、`\r`、`\t`、全形空白 `\u3000` 標準化。
  - **前導邊界 B1**：行首/全文起點、空白、主要標點或成對括號起點。
  - **標點與位置嚴格化 (決策四 & 決策五)**：
    - 單字母 (S, O, A, P)：必須帶標點（`:`、`：`、`.`）或成對括號，嚴禁純空白分隔。單字母標記僅在行首或括號內有效，徹底杜絕生命徵象 `P: 80` 誤切。
    - 英文全稱 (Subjective, Objective, Assessment, Plan)：必須帶冒號、點號、括號或連字號 `-`。
    - 冠詞與單字保護：排除 `A 35-year-old` 與 `Plan to evaluate` 誤切。
  - **重複標記合併與 Fallback**：無合格標記時 safe fallback 全文歸入 `subjective`。

- **TDD 轉綠驗證**：
  - 守門測試 4 (`test_guard_parse_soap_sublabel_in_plan_preserved`)：PASS
  - 守門測試 5 (`test_guard_parse_soap_inline_vitals_not_split`)：PASS
  - 測試 3 (`test_red_parse_soap_inline_chinese_markers`)：PASS
  - 測試 4 (`test_red_parse_soap_bracketed_headers`)：PASS
  - 測試 5 (`test_red_parse_soap_english_article_a_not_confused`)：PASS
  - 測試 6 (`test_red_parse_soap_plan_word_not_confused`)：PASS
  - 測試 7 (`test_red_parse_soap_single_letter_space_delimiter_rejected`)：PASS
  - 測試 8 (`test_red_parse_soap_fullwidth_space_colon_clean`)：PASS
  - 測試 9 (`test_red_parse_soap_duplicate_marker_merge`)：PASS

---

### 【任務 3】：特徵擷取否定防禦 (`extract_general_medical_insights`)

- **關鍵規則實作**：
  - **否定與排除 (決策一)**：納入 `r/o`、`rule out`、`疑似`、`鑑別診斷`、`排除`、`無`、`否認` 等前置/後置否定詞。
  - **Assessment 為空降級 (決策二)**：`assessment` 為空時 `conditions` 嚴格保持為 `[]`。`symptoms` 僅掃描 `subjective` 與 `objective`，排除 `plan` 衛教文字。
  - **英文縮寫對照 (決策三)**：不進行隱性臨床縮寫映射，保持精確中文比對與最長匹配去重。
  - **作用域與斷點**：頓號（`、`）延續否定，子句逗號（`，`）、句號或轉折詞（`但`、`然而`、`確診`）中斷否定作用域。
  - **副詞保護**：`非常`、`未見好轉` 納入黑名單，防止誤殺症狀。

- **TDD 轉綠驗證**：
  - 守門測試 1~3 (`test_guard_*`)：PASS
  - 測試 10 (`test_red_insights_negation_conditions`)：PASS
  - 測試 11 (`test_red_insights_negation_symptoms`)：PASS
  - 測試 12 (`test_red_insights_enumeration_negation`)：PASS
  - 測試 13 (`test_red_insights_conjunction_scope_breaker`)：PASS
  - 測試 14 (`test_red_insights_negation_precedence_weichuxian`)：PASS
  - 測試 15 (`test_red_insights_symptoms_exclude_plan`)：PASS
  - 測試 16 (`test_red_insights_rule_out_and_suspected_excluded`)：PASS
  - 測試 17 (`test_red_insights_empty_assessment_conditions_empty`)：PASS
  - 測試 18 (`test_red_insights_subsumption_dedup`)：PASS
  - 測試 19 (`test_red_api_ingest_tags_negation_clean`)：PASS

---

## 三、全套回歸與正式庫保護驗收

執行全套 SOAP 相關測試：
```bash
pytest tests/test_soap*.py
sha256sum clinic.db
```

### 最終驗收結果

```text
============================= test session starts ==============================
platform linux -- Python 3.12.12, pytest-8.3.5, pluggy-1.6.0
rootdir: /home/hsu/Desktop/clinicbrain
plugins: anyio-4.15.1
collected 67 items

tests/test_soap_api.py .......                                           [ 10%]
tests/test_soap_deid_parser.py .............................             [ 53%]
tests/test_soap_hardening.py ...........................                 [ 94%]
tests/test_soap_writer.py ....                                           [100%]

======================== 67 passed, 1 warning in 0.93s =========================

ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e  clinic.db
```

**結論**：Phase 14 SOAP 剩餘改善項目全數高品質完成，67 項測試全數通過，正式資料庫未受任何寫入變更。
