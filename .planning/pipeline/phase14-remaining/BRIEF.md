# 任務簡報：Phase 14 SOAP 剩餘項目（規劃階段）

你是規劃者。**只寫計畫，不修改 src/、tests/、scripts/ 任何檔案，不 git commit、不 git push。**
唯一允許寫入的檔案：`.planning/pipeline/phase14-remaining/PLAN.md`。全程使用繁體中文。

## 必讀
- `AGENTS.md`（尤其 2.13 SOAP、第 3 節安全規則、2.3 FTS5 trigram 鐵則）
- `src/soap/section_parser.py`、`src/soap/soap_writer.py`、`src/soap/deid.py`
- `src/api/routes/soap.py`、`scripts/migrate_soap_schema.py`、`src/db/clinic_schema.sql`（soap 區段）
- `tests/test_soap_*.py`

## 要規劃的三件事（上一輪複審沒檢查到的部分）
1. `python3 scripts/migrate_soap_schema.py --dry-run` 目前會失敗，找出根因並規劃修法（不可對正式 clinic.db 寫入；正式庫 sha256 前綴 ad24426c 必須不變）。
2. `section_parser.parse_soap_text` 的段落切分準確度：用「真實風格」中文逐字稿與帶標記文字設計獨立測試語料（含：標記在行中、全形冒號、英文縮寫 S/O/A/P 與一般英文單字衝突、否定語境「排除流感」、無標記退化），列出會誤切或漏切的案例與修法。
3. `extract_general_medical_insights` 的特徵擷取：評估誤判（否定語境被當成診斷）與漏判，規劃修法。

## 計畫格式要求
- 每項：現況證據（指出檔案與行為，需實測過而非推測）、根因、修法、要新增的測試（先寫失敗測試的清單）、驗收指令與預期輸出。
- 明列範圍邊界：不要順手做 SOAP 轉 FAQ、不要改 Phase 14 以外的模組。
- 列出需要使用者決策的點（醫療判斷類不得自行決定）。
- 結尾附「風險與回滾」。
