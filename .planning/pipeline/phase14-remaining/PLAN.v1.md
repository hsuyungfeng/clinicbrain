# Phase 14 SOAP 剩餘項目改善執行計畫 (PLAN.md)

本文件依據 `.planning/pipeline/phase14-remaining/BRIEF.md` 指示，針對上一輪複審未覆蓋之三項核心問題制定具體改善計畫。全程遵循 `AGENTS.md` 規範（繁體中文、FTS5 trigram 鐵則、單一權威寫入路徑、正式庫寫入防禦）。

---

## 項目一：`scripts/migrate_soap_schema.py --dry-run` 執行失敗問題

### 1. 現況證據（實測驗證）
- **實測指令**：
  ```bash
  python3 scripts/migrate_soap_schema.py --dry-run
  ```
- **實測行為**：
  指令返回碼為 `2`，並於 `stderr` 輸出阻斷訊息：
  ```text
  🛑 拒絕操作正式資料庫！
  您嘗試對正式 clinic.db 執行 schema 遷移，但未提供 --confirm-prod-backup 旗標。
  請先手動備份正式庫，例如：
    cp clinic.db clinic.db.bak-$(date +%Y%m%d)
  備份完成後，請重新執行並附加確認旗標：
    python3 scripts/migrate_soap_schema.py --confirm-prod-backup
  ```
- **正式資料庫雜湊狀態**：
  ```bash
  sha256sum clinic.db
  # 輸出：ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e  clinic.db
  ```
  正式庫 SHA-256 前綴維持 `ad24426c`，未受影響。

### 2. 根因分析
- 在 `scripts/migrate_soap_schema.py` 第 106–116 行：
  腳本在解析參數後（預設 `--db` 指向正式庫 `clinic.db`），立即執行「檢查是否為正式庫且是否帶有 `--confirm-prod-backup`」的安全檢查。
- 檢查第 4 步的 `--dry-run` 預覽邏輯（第 127 行）位於上述安全檢查**之後**。
- 預覽操作（Dry-Run）本質為純唯讀檢視：僅讀取 `src/db/clinic_schema.sql`、動態解析 DDL 並輸出至標準輸出，完全不建立 SQLite 連線、不對目標檔案發起寫入。要求 Dry-Run 預覽亦必須帶備份確認旗標，阻礙了安全預演之核心目的。

### 3. 修法規劃
- 檔案：`scripts/migrate_soap_schema.py`
- 修改安全檢查條件，使 `--dry-run` 模式得以安全繞過寫入備份要求：
  ```python
  # 僅在非 dry-run 且目標為正式庫時，強制要求備份確認旗標
  if not args.dry_run and is_prod and not args.confirm_prod_backup:
      print(..., file=sys.stderr)
      return 2
  ```
- 保持防禦原則：Dry-Run 分支中嚴禁呼叫 `apply_soap_schema` 或任何 `sqlite3.connect`，印出 DDL 後即以 `return 0` 結束。
- 正式庫未帶備份旗標之實際遷移（`--dry-run` 為 False）依然維持嚴格阻斷（返回碼 2）。

### 4. 要新增的測試（先寫失敗測試清單）
檔案：`tests/test_soap_hardening.py`（或獨立遷移測試）：
1. `test_migrate_soap_schema_dry_run_prod_default_exits_zero`：
   執行 `scripts.migrate_soap_schema.main(["--dry-run"])`，斷言回傳值為 `0`，標準輸出包含 `CREATE TABLE IF NOT EXISTS soap_records` 與 `tokenize='trigram'`。
2. `test_migrate_soap_schema_real_run_prod_without_backup_rejected`：
   執行 `scripts.migrate_soap_schema.main([])`，斷言回傳值為 `2`，標準錯誤包含拒絕操作警示。
3. `test_migrate_soap_schema_dry_run_does_not_modify_file_content`：
   比對執行前後目標檔案之 SHA-256 雜湊值，確認完全一致。

### 5. 驗收指令與預期輸出
```bash
python3 scripts/migrate_soap_schema.py --dry-run
# 預期返回碼: 0
# 預期輸出包含:
# 🔍 [Dry-Run 模式] 將對目標資料庫執行的 DDL 如下：
# CREATE TABLE IF NOT EXISTS soap_records (
# tokenize='trigram'
# ✨ Dry-Run 完成，未對資料庫進行任何實質修改。

sha256sum clinic.db
# 預期輸出: 前綴依然為 ad24426c
```

---

## 項目二：`section_parser.parse_soap_text` 段落切分準確度改善

### 1. 現況證據（實測驗證）
透過 `src/soap/section_parser.py` 實測發現以下切分瑕疵：
1. **標記在行中（Inline Markers）嚴重漏切**：
   - 實測輸入：`"主訴：喉嚨痛 理學檢查：喉嚨紅 診斷：咽喉炎 處置：多喝水"`
   - 實測輸出：`{'subjective': '喉嚨痛 理學檢查：喉嚨紅 診斷：咽喉炎 處置：多喝水', 'objective': '', 'assessment': '', 'plan': ''}`
   - 現行程式碼以行首 `^` 逐行比對，語音逐字稿若無換行符號，整段文字全部跌入 `subjective`，後續三個區塊全空。
2. **英文單字與縮寫衝突（Indefinite Article Collision）**：
   - 實測輸入：`"A 35-year-old male presents with headache"`
   - 實測輸出：`{'subjective': '', 'objective': '', 'assessment': '35-year-old male presents with headache', 'plan': ''}`
   - 英文不定冠詞 "A " 因正則包含 `[:：\s-]`，空白被視為分隔符，被誤判為 Assessment 段落標記。
   - 同樣問題："Plan to observe..." 被誤判為 Plan 段落。
3. **中文括號與標籤樣式漏切**：
   - 臨床常見範本如 `【主訴】`、`[S]`、`（診斷）`，因包含括號且冒號非必填，現行正則 `^(?:[#*\s-]*)...` 無法匹配。
4. **否定語境在非標記位置之誤觸**：
   - 若行內切分正則未設防，文句中「病人主訴未做過任何檢查與評估」，「檢查」或「評估」會被誤當成新段落切點。
5. **無標記純文本退化**：
   - 目前全無標記時正確退化至 `subjective`，但若加入行內切分後，需確保無標記純文字仍百分之百安全退化，不產生碎裂片段。

### 2. 根因分析
- `_MARKER_PATTERNS` 採用行首錨定 `^`，並於 `for line in lines:` 迴圈中匹配，對無換行之行內標記缺乏切分能力。
- 單字母縮寫標記（S/O/A/P）的分隔符比對條件過於寬鬆（允許一般空白 `\s`），未嚴格要求結構化標點（如 `:`、`：`、`.` 或括號封裝）。
- 標記詞典中未將「單獨字詞（如『檢查』）」與「結構化標籤（如『【檢查】』、『檢查：』）」區隔。

### 3. 修法規劃
- 檔案：`src/soap/section_parser.py`
- **分隔符嚴格度分流（Delimiter Classification）**：
  1. **單字母英文縮寫（S, O, A, P）**：
     - 強制要求緊接冒號（`:`、`：`）、句點（`.`）、括號封裝（`[S]`, `(S)`, `【S】`）。
     - **嚴禁單獨以空白作為分隔符**，徹底杜絕 "A 35-year-old..." 與 "Plan to..." 等一般英文單字衝突。
  2. **多字母/英文全稱（Subjective, Objective, Assessment, Plan）**：
     - 允許冒號、連字號、或行首標籤樣式。
  3. **中文結構化標記**：
     - 支援常見前綴符號、括號（`【主訴】`、`[客觀檢查]`、`（診斷）`）以及全形/半形冒號（`主訴：`、`主訴:`）。
     - 單獨易混淆詞（如「檢查」、「評估」）必須帶有冒號或括號，防止「未做檢查」之否定敘述句中途觸發斷詞。
- **雙模切分管線（Dual-Mode Segmentation Pipeline）**：
  1. 先行正規化處理全形空白、連續標點與常見括號標籤。
  2. 掃描文字中所有符合「段落標記候選」之起始偏移量（Span Matching）。候選標記必須位於：
     - 行首，或
     - 標點符號後（如 `。`、`；`、`！`、`\n`），或
     - 具備成對標籤括號（如 `【`、`[`）。
  3. 依據標記出現之先後順序分割字串為區間片段，依標記類別累加至對應之 S/O/A/P 欄位。
  4. 若文字內未檢測到任何合格標記，嚴格保持向後相容：全文放入 `subjective`，其餘為空字串。

### 4. 要新增的測試（先寫失敗測試清單）
檔案：`tests/test_soap_deid_parser.py`：
1. `test_parse_soap_inline_chinese_markers`：
   輸入單行無換行字串 `"主訴：喉嚨痛 理學檢查：喉嚨紅 診斷：咽喉炎 處置：多喝水"`，驗證四段各自取得對應文字。
2. `test_parse_soap_bracketed_headers`：
   輸入 `"【主訴】發燒三天 【客觀】體溫38度 【診斷】流感 【處置】給予克流感"`，驗證正確解析。
3. `test_parse_soap_english_article_a_regression`：
   輸入 `"A 35-year-old male presents with headache"`，驗證 assessment 為空，全句安全歸入 subjective。
4. `test_parse_soap_single_letter_delimiter_strictness`：
   輸入 `"S: cough\nO: clear\nA: URI\nP: rest"` 正確分段；但 `"Plan to evaluate next Monday"` 不被誤切為 Plan 區塊。
5. `test_parse_soap_sentence_negation_not_triggering_marker`：
   輸入 `"病患主訴未做過任何身體檢查與評估，僅覺頭痛"`，驗證「檢查」與「評估」不觸發段落轉換，整句保留於 subjective。
6. `test_parse_soap_fullwidth_colon_and_spaces`：
   輸入 `"主訴　：喉嚨痛\n客觀檢查：體溫高"`，驗證正確處理全形空白與冒號。
7. `test_parse_soap_pure_audio_transcript_fallback`：
   輸入無任何標記之真實口語逐字稿，驗證乾淨 fallback 歸入 subjective，不發生例外。

### 5. 驗收指令與預期輸出
```bash
python3 -m pytest tests/test_soap_deid_parser.py -k "test_parse_soap"
# 預期：全部通過（包含既有與新增案例）
```

---

## 項目三：`extract_general_medical_insights` 特徵擷取與否定語境改善

### 1. 現況證據（實測驗證）
透過 `src/soap/section_parser.py` 實測發現以下特徵擷取瑕疵：
1. **否定語境嚴重偽陽性（Negation False Positives）**：
   - 實測輸入：
     ```python
     parsed = {
         "subjective": "無發燒、無咳嗽，否認腹瀉",
         "assessment": "排除流感，疑似普通感冒",
         "plan": "",
     }
     insights = extract_general_medical_insights(parsed)
     ```
   - 實測輸出：
     - `conditions`: `['感冒', '流感']`（「排除流感」被誤擷取為確診流感）
     - `symptoms`: `['發燒', '咳嗽', '腹瀉']`（明確否定之「無發燒、無咳嗽、否認腹瀉」全部被當成現存症狀）
     - `suggested_tags`: `['感冒', '流感', '發燒', '咳嗽', '腹瀉']`
   - 導致病歷中被排除之病症與不存在之症狀嚴重污染知識庫標籤。
2. **子字串冗餘匹配（Subsumed Substring Duplication）**：
   - 實測輸入：`assessment="急性咽喉炎"`
   - 實測輸出：`conditions=['急性咽喉炎', '咽喉炎']`
   - 父子詞同時出現，標籤未去冗餘。
3. **英文醫學縮寫漏判（Clinical Abbreviation Omissions）**：
   - 台灣臨床病歷極常使用英文診斷（如 `URI`、`AGE`、`GERD`、`Acute tonsillitis`），現行詞表僅支援 18 個中文詞彙，完全無法辨識。
4. **跨區段權重未分（Cross-Section Bleed）**：
   - 目前將 `f"{subjective} {assessment} {plan}"` 合併搜尋。若病患在主訴表示「同事得流感，擔心被傳染」，診斷實為「感冒」，「流感」依然被納入 `conditions`。

### 2. 根因分析
- `extract_general_medical_insights` 使用純字串包含判斷（`if cond in full_search_text`），缺乏語意範疇（Scope）與否定詞檢測機制。
- 疾病標籤與症狀標籤未依據 SOAP 的段落權威性做職責劃分（診斷應以 A 為權威、症狀應以 S/O 為主）。
- 未實作最長字串優先比對（Longest Match Subsumption）。

### 3. 修法規劃
- 檔案：`src/soap/section_parser.py`
- **否定語境防禦器（Clinical Negation Guard）**：
  1. 定義中文臨床前置否定詞：`無`、`未`、`沒有`、`未見`、`未有`、`不見`、`否認`、`非`、`排除`、`免除`、`無明顯`。
  2. 定義英文臨床前置否定詞：`r/o`、`rule out`、`negative for`、`no`、`denies`、`without`。
  3. 定義後置排除詞：`陰性`、`排除`（例如「流感快篩陰性」）。
  4. 實作否定視窗：於文字中定位關鍵字時，向前掃描 1–5 個字元（或同子句內，遇標點 `，`、`、`、`。`、`；` 中斷）；若發現否定前綴或後置陰性，判定為否定語境，不予納入正面特徵。
- **區段權威分流（Section Authority Scoping）**：
  1. `conditions`（診斷疾病）：
     - 優先以 `assessment` 為首要來源；若 `assessment` 為空，始降級檢索 `subjective`。
     - 徹底杜絕主訴中病患之擔憂或親友病史誤當成個人診斷。
  2. `symptoms`（臨床症狀）：
     - 僅從 `subjective` 與 `objective` 檢索，排除 `plan` 中的可能藥品適應症干擾。
- **最長匹配去重（Longest-Match Subsumption）**：
  - 關鍵字依長度降序匹配，若較長詞（如「急性咽喉炎」）已命中其字元區間，其涵蓋之子詞（如「咽喉炎」）自動跳過。
- **增補常見臨床對照（英文縮寫）**：
  - 在 `_GENERAL_CONDITION_KEYWORDS` 與同義對照中擴充台灣門診常見縮寫（如 `URI` -> `感冒`、`AGE` -> `急性腸胃炎`、`GERD` -> `胃食道逆流`）。

### 4. 要新增的測試（先寫失敗測試清單）
檔案：`tests/test_soap_deid_parser.py`：
1. `test_insights_negation_chinese_conditions`：
   輸入 `assessment="排除流感，診斷為普通感冒"`，斷言 `conditions` 包含 `"感冒"`，且**絕對不含** `"流感"`。
2. `test_insights_negation_chinese_symptoms`：
   輸入 `subjective="病患無發燒、無咳嗽，否認腹瀉，主訴喉嚨痛三天"`，斷言 `symptoms` 僅有 `["喉嚨痛"]`，排除發燒、咳嗽、腹瀉。
3. `test_insights_english_rule_out`：
   輸入 `assessment="R/O Influenza, Acute tonsillitis confirmed"`，斷言排除流感，命中急性扁桃腺炎。
4. `test_insights_rapid_test_negative_postposition`：
   輸入 `objective="流感快篩陰性，咽喉微紅"`，斷言 `conditions` 不含流感。
5. `test_insights_longest_match_subsumption`：
   輸入 `assessment="急性支氣管炎"`，斷言 `conditions` 僅包含 `["急性支氣管炎"]`，不重複出現 `["支氣管炎"]`。
6. `test_insights_subjective_worry_isolated`：
   輸入 `subjective="自述同事罹患流感，非常擔心"`，`assessment="過敏性鼻炎"`，斷言 `conditions` 僅有 `"過敏性鼻炎"`，不含 `"流感"`。

### 5. 驗收指令與預期輸出
```bash
python3 -m pytest tests/test_soap_deid_parser.py -k "test_insights"
# 預期：全部通過，且否定案例零偽陽性
```

---

## 範圍邊界與防護規範

1. **嚴格禁止跨 Phase 與偷跑功能**：
   - 僅限改善 Phase 14 所屬之 SOAP 接收、切分、特徵擷取與遷移腳本。
   - 嚴禁自行實作「SOAP 轉 FAQ」功能（屬後續 Phase 規劃）。
   - 嚴禁改動 `src/batch/`、`src/general/`、`src/query/`、`src/pageindex/` 等非 SOAP 模組。
2. **單一權威寫入與資料庫防禦**：
   - 正式庫 `clinic.db` 在規劃與測試期間不可有任何未授權寫入，雜湊前綴 `ad24426c` 必須恆常不變。
   - 所有測試一律使用 `tmp_path` 或 `isolated_db_path` 複本。
3. **無程式碼修改保證**：
   - 本規劃階段未修改 `src/`、`tests/`、`scripts/` 任何程式碼，無 git commit 與 push 操作。

---

## 需要使用者決策的點（醫療與產品規則）

以下涉及臨床語意與資料判斷，不得由工程端自行裁量，需請使用者確認：
1. **「疑似（Suspected / R/O）」之標籤處理決策**：
   - 臨床病歷常出現「疑似流感」或「R/O Appendicitis」。
   - **方案 A（保守安全，推薦）**：帶有「疑似」、「R/O」、「鑑別診斷」之疾病，一律視為未確診，不列入正面 `conditions` 與標籤，避免對民眾衛教或檢索造成誤導。
   - **方案 B（擴充標記）**：新增 `suspected_conditions` 欄位或標籤加註前綴（如 `疑似:流感`）。
2. **臨床英文縮寫詞庫之納入邊界**：
   - 是否同意初期僅納入台灣基層門診最常見之 5–10 個高頻縮寫（如 `URI`, `AGE`, `GERD`, `Acute pharyngitis`），避免過度擴張引入雜訊？
3. **純無標記逐字稿之處理底線**：
   - 是否維持「完全無標記時全數安全退化歸入主訴（subjective）」之確定性原則，不使用啟發式猜測任意切割？

---

## 風險與回滾計畫

1. **潛在風險**：
   - **切分邊界過鬆**：若行內標記正則邊界未妥善設防，可能將常規病注文句切割成碎語。
     - *防範措施*：英文字母縮寫（S/O/A/P）嚴格強制要求冒號/句點/括號；中文關鍵字必須緊鄰標點或標籤符號，並以既有 42 個測試進行無迴歸把關。
   - **否定視窗範圍過大**：若跨子句否定，可能誤把相鄰之真實症狀（如「無發燒，但有咳嗽」）也一同抹除。
     - *防範措施*：否定檢測作用範圍嚴格限制於逗點、句號或頓號前（子句內有效）。
2. **回滾程序**：
   - 若未來實作執行測試失敗或未符預期：
     - 使用 `git checkout` 復原變更檔案。
     - 正式庫 `clinic.db` 全程受到保護未被異動，無須回滾資料庫。
