# 審查簡報：Phase 14 剩餘項目計畫（階段 2，Claude 審查）

你是獨立審查者，與計畫作者不同模型。**不得修改 src/、tests/、scripts/、AGENTS.md 任何檔案，不得 git commit／push，不得寫入 clinic.db。** 唯一允許寫入：`.planning/pipeline/phase14-remaining/REVIEW.md`。全程繁體中文。

## 審查對象
`.planning/pipeline/phase14-remaining/PLAN.md`，任務範圍見 `BRIEF.md`（三項：migrate --dry-run 失敗、section_parser 切分準確度、extract_general_medical_insights 誤判）。

## 審查方式（必須實測，不可只讀）
1. 計畫引用的每個「現況證據」都要親自重現（可跑唯讀指令與在 /tmp 或 scratchpad 內的實驗腳本；不可動專案檔）。計畫宣稱的行號、輸出、行為與實際不符者列為發現。
2. 用你自己設計的獨立語料測 `parse_soap_text` 與 `extract_general_medical_insights`，驗證計畫列出的案例是否真實、是否漏掉更嚴重的案例。
3. 對照 `AGENTS.md`（特別是第 3 節安全規則、2.13、「單一權威寫入路徑」、FTS5 trigram 鐵則）檢查計畫有無違規或遺漏。
4. 檢查：測試先失敗再修（TDD）是否可行、驗收指令是否真的會驗證到問題、是否越界（SOAP 轉 FAQ、改 Phase 14 以外模組）、需使用者決策的醫療判斷是否被計畫擅自決定。
5. 特別檢查項目一的修法是否在 dry-run 路徑上真的沒有任何寫入或連線副作用，並確認正式 clinic.db 的 sha256（前綴 ad24426c）不變。

## 輸出格式（寫入 REVIEW.md）
- 結論：通過／需修正
- BLOCKER／WARNING／INFO 分級列表，每項附證據（指令與輸出）
- 對計畫的具體修改建議
- 最後一行單獨寫：`VERDICT: PASS` 或 `VERDICT: REVISE`
