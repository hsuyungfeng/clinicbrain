# Phase 14 SOAP 剩餘項目改善執行計畫 (PLAN.md - 修訂版)

> 本文件依據 `.planning/pipeline/phase14-remaining/REVIEW.md` 審查結論（REVISE）全面修訂，納入技術修正項 B1、B2、B3、W1、W2、W4、W5、W6，並將 B4、B5、W4 縮寫對照及空白英文標記等醫療/行為決策抽離至「待使用者決策」清單。
> 全程嚴格遵循 `AGENTS.md`（繁體中文、FTS5 trigram 鐵則、單一權威寫入路徑、正式庫寫入防禦）。

---

## 項目一：`scripts/migrate_soap_schema.py --dry-run` 執行失敗修復

### 1. 現況證據（實測驗證）
- **實測指令**：
  ```bash
  python3 scripts/migrate_soap_schema.py --dry-run
  ```
- **實測輸出（退出碼 2）**：
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
  正式庫 SHA-256 前綴維持 `ad24426c`，未受損。

### 2. 根因分析
- 在 `scripts/migrate_soap_schema.py` 第 106–116 行：
  腳本解析參數後（預設 `--db` 指向正式庫 `PROD_DB_PATH`），立即執行「檢查目標是否為正式庫且是否帶有 `--confirm-prod-backup`」的安全檢查。
- 檢查第 4 步的 `--dry-run` 預覽邏輯（第 127 行）位於上述安全檢查**之後**。
- 預覽操作（Dry-Run）為純唯讀檢視：僅讀取 `src/db/clinic_schema.sql`、動態解析 DDL 並輸出至標準輸出，完全不發起 SQLite 連線、不對目標檔案發起寫入。要求 Dry-Run 預覽亦必須帶備份確認旗標，阻礙了安全預演之核心目的。
- 目標檔案存在性檢查（第 96 行 `if not target_path.exists():` 退出碼 2）屬合理防禦（避免對不存在之路徑自動建檔），此行為應當保留。

### 3. 修法規格（含 W1、W2）
- 檔案：`scripts/migrate_soap_schema.py`
- 修改安全防禦條件：
  ```python
  # 僅在非 dry-run 且目標為正式庫時，強制要求備份確認旗標
  if not args.dry_run and is_prod and not args.confirm_prod_backup:
      print(..., file=sys.stderr)
      return 2
  ```
- **防禦保證**：
  1. Dry-Run 分支維持純記憶體 DDL 解析與標準輸出印出，嚴禁呼叫 `sqlite3.connect` 或 `apply_soap_schema`。
  2. 若 `--db` 指定不存在之檔案，維持退出碼 2（不自動建立空檔）。
  3. 正式庫非 dry-run 遷移若未帶 `--confirm-prod-backup`，依然由第 106 行阻斷並回傳退出碼 2。

### 4. 測試設計（強制 tmp_path 與 monkeypatch，W1）
- 測試檔案：`tests/test_soap_hardening.py`
- **安全隔離鐵則**：所有測試嚴禁直接對正式 `clinic.db` 操作。一律使用 `monkeypatch.setattr(scripts.migrate_soap_schema, "PROD_DB_PATH", tmp_path / "clinic.db")` 將「正式庫」改指向暫存路徑。
- 導入說明：`scripts.migrate_soap_schema` 沿用既有 `tests/conftest.py:62` 之 namespace package 匯入機制。

### 5. 驗收指令與預期輸出（W2 整合版）
```bash
# 整合驗收：確認 dry-run 輸出 DDL 且正式庫雜湊未變
python3 scripts/migrate_soap_schema.py --dry-run && sha256sum clinic.db
# 預期返回碼: 0
# 預期 stdout 包含:
# 🔍 [Dry-Run 模式] 將對目標資料庫執行的 DDL 如下：
# CREATE TABLE IF NOT EXISTS soap_records (
# tokenize='trigram'
# ✨ Dry-Run 完成，未對資料庫進行任何實質修改。
# ad24426cadd84db7521250631efbd0067fb3fb2f040ab257a915b73416022b9e  clinic.db
```

---

## 項目二：`section_parser.parse_soap_text` 段落切分準確度改善

### 1. 現況證據（實測驗證，含 I3）
透過 `src/soap/section_parser.py` 實測發現以下切分瑕疵：
1. **行內標記（Inline Markers）嚴重漏切（B1）**：
   - 實測輸入：`"主訴：喉嚨痛 理學檢查：喉嚨紅 診斷：咽喉炎 處置：多喝水"`
   - 實測輸出：`{'subjective': '喉嚨痛 理學檢查：喉嚨紅 診斷：咽喉炎 處置：多喝水', 'objective': '', 'assessment': '', 'plan': '', 'raw_text': '主訴：喉嚨痛 理學檢查：喉嚨紅 診斷：咽喉炎 處置：多喝水'}`
   - 逐行 `^` 比對無法切分無換行之行內標記，後續三個區塊全空。
2. **英文單字與縮寫衝突（B2）**：
   - 實測輸入：`"A 35-year-old male presents with headache"`
   - 實測輸出：`{'subjective': '', 'objective': '', 'assessment': '35-year-old male presents with headache', 'plan': '', 'raw_text': 'A 35-year-old male presents with headache'}`
   - 實測輸入：`"Plan to evaluate next Monday"`
   - 實測輸出：`{'subjective': '', 'objective': '', 'assessment': '', 'plan': 'to evaluate next Monday', 'raw_text': 'Plan to evaluate next Monday'}`
   - 英文不定冠詞 "A " 與名詞/動詞 "Plan " 因允許單純空白分隔，被誤判為段落標記。
3. **中文括號樣式漏切**：
   - 實測輸入：`"【主訴】發燒三天 【客觀】體溫38度 【診斷】流感 【處置】給予克流感"`
   - 實測輸出：全文字串歸入 subjective，無法識別成對括號標籤。
4. **全形空白前導冒號殘留（I3）**：
   - 實測輸入：`"主訴　：喉嚨痛"`
   - 實測輸出：`{'subjective': '：喉嚨痛', ...}`，全形空白觸發分隔後，冒號殘留在內容中。

### 2. 根因分析
- `_MARKER_PATTERNS` 依賴行首錨定 `^`，且以 `splitlines()` 逐行遍歷，無法處理行內連續標記。
- 標記前導邊界定義不清，若僅限制標點後，會與空白前導的行內標記互斥。
- 英文標記分隔符過於寬鬆（允許一般空白 `\s`），導致英文常規句子開頭碰撞。

### 3. 修法規格（含 B1、B2、I5、W6）
- 檔案：`src/soap/section_parser.py`
- **前置正規化（I5）**：
  - 將 Windows 換行（`\r\n`）、Tab（`\t`）及全形空白（`\u3000`）標準化。
- **標記前導合格邊界（B1 明確定義）**：
  一個段落標記候選（Token）的起始位置必須符合下列邊界條件之一：
  1. **行首或全文起點**（`^`、`\n`）。
  2. **空白字符之後**（包含半形空格、`\t`、`\u3000`）。
  3. **主要標點符號之後**（`。`、`；`、`！`、`？`、`，`、`、`）。
  4. **成對括號標籤起點**（`【`、`[`、`(`、`（`）。
- **標記後置分隔符嚴格度分流（B2）**：
  1. **英文單字母（S, O, A, P）**：
     - 強制要求緊接冒號（`:`、`：`）、句點（`.`）、或括號封裝（`[S]`、`(S)`、`【S】`）。
     - **技術實施：嚴格禁止單純空白 `\s` 作為單字母分隔符**（徹底解決 `A 35-year-old`）。
  2. **英文全稱（Subjective, Objective, Assessment, Plan）**：
     - 強制要求緊接冒號（`:`、`：`）、成對括號、或前後有空白之連字號（` - `）。
     - **技術實施：禁止單純空白分隔**（徹底解決 `Plan to evaluate` 誤切）。
  3. **中文複合標記（主訴、理學檢查、診斷、處置、治療計畫等）**：
     - 允許冒號（半形/全形）、括號標籤封裝。
     - 單獨易混淆詞（如「檢查」、「評估」）必須具備冒號或成對括號，防止「未做檢查」之非標記句子誤切。
- **區間切分與衝突防護（Span Segmentation & W6）**：
  - 掃描全文取得所有符合邊界之標記偏移區間 `(start, end, section_type)`。
  - **重複同類標記合併（W6）**：若出現連續同類標記（如 `主訴：頭痛 主訴：發燒`），自動接續累加至同一段落，不覆蓋。
  - **段內子標籤保護（W6）**：若 Plan 內部包含 `衛教事項：`，因同屬 Plan 類別，合併保留於 Plan 段落。
  - 若未檢測出任何合格標記，全文安全 fallback 歸入 `subjective`。

---

## 項目三：`extract_general_medical_insights` 特徵擷取與否定語境改善

### 1. 現況證據（實測驗證）
1. **否定語境偽陽性嚴重（B3）**：
   - 實測輸入：
     ```python
     extract_general_medical_insights({"assessment": "排除流感，確診普通感冒"})
     # 輸出: conditions: ['感冒', '流感'] （流感被排除卻被列為確診疾病！）
     
     extract_general_medical_insights({"subjective": "無發燒、無咳嗽，否認腹瀉"})
     # 輸出: symptoms: ['發燒', '咳嗽', '腹瀉'] （否定症狀全被誤抓為現存症狀！）
     ```
2. **頓號列舉否定全漏（B3）**：
   - 實測輸入：`subjective="無發燒、咳嗽"`
   - 實測輸出：`symptoms=['發燒', '咳嗽']`
3. **轉折詞未分流（B3）**：
   - 實測輸入：`subjective="無發燒，但有咳嗽"`
   - 實測輸出：`symptoms=['發燒', '咳嗽']`（未能保留轉折後的咳嗽）
4. **子字串冗餘匹配**：
   - 實測輸入：`assessment="急性咽喉炎"`
   - 實測輸出：`conditions=['急性咽喉炎', '咽喉炎']`
5. **非否定語境誤傷（B3 潛在風險）**：
   - 實測輸入：`"非常頭痛"` 目前輸出 `symptoms=['頭痛']`；`"未見好轉的咳嗽"` 目前輸出 `symptoms=['咳嗽']`。若粗暴以單字 `非` 或 `未見` 匹配，會將其誤殺。

### 2. 根因分析
- 現行程式使用簡單 `cond in full_search_text` 子字串比對，無上下文語境分析。
- 未建立精確否定片語白名單，未考慮列舉語法與轉折詞終止範圍。
- 疾病詞表未依字串長度進行覆蓋去重（Subsumption）。

### 3. 修法規格（含 B3、W3、W4、W6）
- 檔案：`src/soap/section_parser.py`
- **精確否定片語白名單（B3 杜絕誤傷）**：
  - 中文前置否定白名單：`無`、`未有`、`未出現`、`沒有`、`否認`、`排除`、`不見`、`非`（後接疾病詞，如 `非流感`）、`不是`。
  - **排除黑名單（嚴防誤殺）**：明確排除 `非常`、`無法`、`未見好轉`、`非但`、`無特殊`。
  - 中文後置否定白名單：`陰性`、`未檢出`（如 `流感快篩陰性`）。
  - **暫移出詞彙（B4）**：`r/o`、`rule out`、`疑似`、`鑑別診斷` 暫不列入否定詞表，移交使用者決策。
- **列舉延續與終止詞規則（B3）**：
  - **列舉延續**：在同一個子句內，若否定詞後接以頓號（`、`）或連接詞（`與`、`及`、`和`）連接之詞彙（如 `無發燒、咳嗽、腹瀉`），否定範圍延伸至該列舉序列之所有項目。
  - **終止詞（Scope Breaker）**：遇到轉折詞（`但`、`然而`、`不過`、`伴隨`、`出現`、`伴有`、`合併`）或句末標點（`。`、`；`、`！`、`？`），立即重置否定狀態（如 `無發燒，但有咳嗽`，發燒否定，咳嗽保留）。
- **英文邊界比對（W4 技術修正規範）**：
  - 若匹配英文字詞，一律強制使用 `\b` 單字邊界與大寫精確比對，避免 `uri` 誤中 `during`、`no` 誤中 `nose`。
- **最長匹配去重（Longest-Match Subsumption）**：
  - 關鍵字依長度降序掃描。若長詞（`急性咽喉炎`）已命中，則其覆蓋區間內之子詞（`咽喉炎`）不重複計入。
- **架構與路由層聲明（W3）**：
  - 路由層 `src/api/routes/soap.py` 原本已傳入 `objective`，**路由程式碼無需改動**。
  - 補強端到端 API 測試：驗證帶有否定句之推播，入庫時 `soap_records.tags` 不含否定標籤。

---

## 測試分類（Regression Guards vs Red TDD Tests）

> 依指示嚴格區分「現況已綠的守門測試」與「現況會紅的測試」，並列出當前環境真實實測輸出。

### 類別 A：現況已綠的守門測試（Regression Guards，防回歸）
此類測試在現行程式碼**已經通過**，修訂時必須確保維持綠燈：

1. **`test_guard_chinese_negation_in_narrative_stays_subjective`（原項目二測試 5）**
   - 語料：`"病患主訴未做過任何身體檢查與評估，僅覺頭痛"`
   - 現況實測輸出：`{'subjective': '病患主訴未做過任何身體檢查與評估，僅覺頭痛', 'objective': '', 'assessment': '', 'plan': '', ...}`
   - 守門目的：確保行內切分修訂後，句中出現「檢查」「評估」不會被意外截斷。
2. **`test_guard_pure_audio_transcript_fallback`（原項目二測試 7）**
   - 語料：`"病患昨晚開始頭暈眼花，胃部脹痛想吐，沒有腹瀉。"`
   - 現況實測輸出：全句正確保留於 `subjective`，無例外。
3. **`test_guard_non_negated_adverbs_preserved`（B3 反向守門）**
   - 語料：`subjective="非常頭痛，未見好轉的咳嗽"`
   - 現況實測輸出：`symptoms=['頭痛', '咳嗽']`
   - 守門目的：防止否定片語把「非常」「未見好轉」誤判為否定而吃掉症狀。
4. **既有 42 項 SOAP 測試全數守門**：
   - 現況實測：`python3 -m pytest tests/test_soap*` → `42 passed, 1 skipped`。

### 類別 B：現況會紅的測試（Red TDD Tests，需修復之目標）
此類測試在現行程式碼**必定失敗（會紅）**，作為修復目標：

1. **`test_red_parse_soap_inline_chinese_markers`（B1 主測資）**
   - 語料：`"主訴：喉嚨痛 理學檢查：喉嚨紅 診斷：咽喉炎 處置：多喝水"`
   - 現況實測輸出：`subjective='喉嚨痛 理學檢查：喉嚨紅 診斷：咽喉炎 處置：多喝水', objective='', assessment='', plan=''`
   - 預期修復後：`subjective='喉嚨痛', objective='喉嚨紅', assessment='咽喉炎', plan='多喝水'`。
2. **`test_red_parse_soap_bracketed_headers`**
   - 語料：`"【主訴】發燒三天 【客觀】體溫38度 【診斷】流感 【處置】給予克流感"`
   - 現況實測輸出：全文字串落在 `subjective`，其餘為空。
   - 預期修復後：正確切分四個區塊。
3. **`test_red_parse_soap_english_article_a_not_confused`（B2）**
   - 語料：`"A 35-year-old male presents with headache"`
   - 現況實測輸出：`assessment='35-year-old male presents with headache', subjective=''`（嚴重誤判）
   - 預期修復後：`subjective='A 35-year-old male presents with headache', assessment=''`。
4. **`test_red_parse_soap_plan_word_not_confused`（B2）**
   - 語料：`"Plan to evaluate next Monday"`
   - 現況實測輸出：`plan='to evaluate next Monday'`（嚴重誤判）
   - 預期修復後：`subjective='Plan to evaluate next Monday', plan=''`。
5. **`test_red_parse_soap_fullwidth_space_colon_clean`（I3）**
   - 語料：`"主訴　：喉嚨痛"`
   - 現況實測輸出：`subjective='：喉嚨痛'`（冒號殘留）
   - 預期修復後：`subjective='喉嚨痛'`。
6. **`test_red_insights_negation_conditions`（B3）**
   - 語料：`assessment="排除流感，確診普通感冒"`
   - 現況實測輸出：`conditions=['感冒', '流感']`
   - 預期修復後：`conditions=['感冒']`（排除流感）。
7. **`test_red_insights_negation_symptoms`（B3）**
   - 語料：`subjective="無發燒、無咳嗽，否認腹瀉"`
   - 現況實測輸出：`symptoms=['發燒', '咳嗽', '腹瀉']`
   - 預期修復後：`symptoms=[]`。
8. **`test_red_insights_enumeration_negation`（B3）**
   - 語料：`subjective="無發燒、咳嗽"`
   - 現況實測輸出：`symptoms=['發燒', '咳嗽']`
   - 預期修復後：`symptoms=[]`（兩者皆被否定）。
9. **`test_red_insights_conjunction_scope_breaker`（B3）**
   - 語料：`subjective="無發燒，但有咳嗽"`
   - 現況實測輸出：`symptoms=['發燒', '咳嗽']`
   - 預期修復後：`symptoms=['咳嗽']`（發燒被否定，咳嗽保留）。
10. **`test_red_insights_subsumption_dedup`**
    - 語料：`assessment="急性咽喉炎"`
    - 現況實測輸出：`conditions=['急性咽喉炎', '咽喉炎']`
    - 預期修復後：`conditions=['急性咽喉炎']`。
11. **`test_red_migrate_soap_schema_dry_run_exits_zero`（項目一）**
    - 呼叫：`scripts.migrate_soap_schema.main(["--dry-run"])`（monkeypatch PROD_DB_PATH）
    - 現況實測輸出：退出碼 2。
    - 預期修復後：退出碼 0。
12. **`test_red_migrate_soap_schema_dry_run_no_connect`（W1）**
    - 驗證：mock `sqlite3.connect`，執行 dry-run 斷言 connect 呼叫次數為 0。
    - 現況實測：被第 106 行提早阻斷，修訂後需驗證確實不連線。

---

## 待使用者決策清單（醫療與行為決策）

> 依使用者指示，B4、B5、W4 縮寫對照及空白英文標記等決策完全移出實作範圍，以下列出方案分析，**在使用者確認前對應測試標記 `@pytest.mark.xfail` 或暫不實作**。

### 決策一：臨床「疑似（Suspected）／R/O」語意處置（原 B4）
- **背景**：臨床病歷常記「疑似流感」或「R/O Appendicitis」。
- **方案 A（保守排除，建議）**：
  - 內容：凡帶有「疑似」、「鑑別診斷」、「R/O」、「rule out」之病症一律不列入正面 `conditions` 與標籤。
  - 影響：徹底杜絕未確診病症污染知識庫與對外諮詢；但疑似病例無法透過疾病標籤被直接檢索。
- **方案 B（標記保留）**：
  - 內容：保留並另增前綴（如 `疑似:流感`）或新增專用欄位。
  - 影響：需變更標籤欄位規範，對下游搜尋有相容性影響。
- **建議**：採方案 A（臨床寧缺勿濫）。
- **對應測試處置**：`test_insights_english_rule_out` 與 `test_insights_suspected_condition` 在決策前標記 `@pytest.mark.xfail`。

### 決策二：Assessment 為空時 Conditions 降級策略（原 B5）
- **背景**：若 SOAP 紀錄缺少 Assessment，是否向 Subjective 尋找診斷？
- **方案 A（保守留空，建議）**：
  - 內容：若 `assessment` 為空，`conditions` 一律保持為空清單 `[]`，只從 S/O 擷取 `symptoms`。
  - 影響：零污染（病患自述「同事得流感」絕不會變成病患確診）；但在完全無標記的純語音逐字稿情境下，`conditions` 將全數為空。
- **方案 B（降級檢索 Subjective）**：
  - 內容：`assessment` 為空時嘗試從 `subjective` 找疾病名稱。
  - 影響：兼顧無標記文本，但主訴中病患之擔憂、親友病史極易被誤判為診斷。
- **建議**：採方案 A。純語音逐字稿應鼓勵上游語音辨識或醫師口述標準標記切出 Assessment。
- **對應測試處置**：相關降級測試在決策前標記 `@pytest.mark.xfail`。

### 決策三：英文臨床縮寫之中文映射（原 W4）
- **背景**：醫師常寫 `URI`、`AGE`、`GERD`，是否由系統自動對照為中文？
- **方案 A（僅支援標準繁體中文，建議）**：
  - 內容：不擅自建立縮寫映射，僅依詞表中之繁體中文標準詞比對。
  - 影響：零醫學語意對照爭議（URI 嚴格來說是上呼吸道感染，不等同普通感冒）；但純英文縮寫病歷不會產生中文 tags。
- **方案 B（建立映射對照表）**：
  - 內容：建立 `URI → 感冒`、`AGE → 急性腸胃炎` 映射字典。
  - 影響：需醫師逐一簽核每一組對照，存在醫學定義誤差風險。
- **建議**：採方案 A。若需映射應待醫師團隊簽核標準對照表後再行納入。
- **對應測試處置**：英文縮寫映射測試在決策前暫不實作。

### 決策四：取消英文單字母空白分隔（如 `S cough`）（原 B2 / W4）
- **背景**：現行正則支援 `S cough`（以空白分隔），但這會導致英文常用單字（如 `A 35-year-old`、`Plan to observe`）嚴重衝突。
- **方案 A（嚴格要求標點，取消空白分隔，建議）**：
  - 內容：英文標記一律強制要求冒號、句點、括號或前後空白連字號（` - `），不再支援單純空白分隔（`S cough`）。
  - 影響：徹底根除英文句子開頭誤切問題；但若外部推播有傳送無標點的 `S cough`，該文本將退化為 subjective。
- **方案 B（保留單字母行首空白）**：
  - 內容：允許行首 `S cough`、`O clear`、`P rest`，但單獨排除 `A` 或維護英文開頭黑名單。
  - 影響：規則碎片化，難以窮舉所有常規英文句型碰撞。
- **建議**：採方案 A。推播規範要求提供標準標點。
- **對應測試處置**：`S cough` 舊格式切分測試在決策前標記 `@pytest.mark.xfail`。

---

## 範圍邊界與防護規範

1. **嚴禁偷跑與跨模組變更**：
   - 僅修改 `scripts/migrate_soap_schema.py` 與 `src/soap/section_parser.py`。
   - 嚴禁偷跑「SOAP 轉 FAQ」功能。
   - 嚴禁修改 `src/batch/`、`src/general/`、`src/query/`、`src/pageindex/`、`src/api/`（路由無需改動）。
2. **正式資料庫寫入絕對隔離（Rule 4）**：
   - 所有測試強制使用 `monkeypatch` 將 `PROD_DB_PATH` 指向 `tmp_path` 暫存檔，嚴禁對正式 `clinic.db` 發起連線或寫入。
   - 正式庫雜湊前綴 `ad24426c` 全程不變。
3. **無程式碼修改保證**：
   - 本計畫文件修訂期間，未修改 `src/`、`tests/`、`scripts/` 任何程式碼，無 git commit 與 push 操作。

---

## 風險與回滾計畫

1. **潛在風險與處置**：
   - **切分邊界鬆動風險**：引入空白前導後，藉由「單字母 S/O/A/P 強制標點」以及「易混淆中文詞（檢查）必須帶冒號/括號」雙重防線封堵。
   - **列舉否定過度延伸風險**：否定列舉延伸僅限同子句內，遇到句末標點或轉折連詞（`但`、`然而`、`不過`）立即終止。
2. **回滾程序**：
   - 若實施後迴歸測試未通過，直接透過版本控制復原檔案。正式資料庫全程唯讀受保，不需進行資料復原。
