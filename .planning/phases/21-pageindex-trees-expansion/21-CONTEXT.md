# Phase 21 Context: 臨床決策推理樹 (PageIndex Trees) 自動提煉、審核與檢索擴展

## 1. 業務背景與臨床痛點
目前系統在 Phase 01 建立了 6 筆手寫臨床推理樹範本（皮秒雷射、肉毒桿菌、電波拉皮、玻尿酸、飛梭雷射、音波拉提），並在 Phase 18–20 完善了 FAQ 知識庫的審核、批次提煉與 Web App 管理。

- **臨床現況與痛點**：
  1. **推理樹數量匱乏**：診所實務上擁有大量複雜手術與微創療程文件（如「微創旋轉切除刀在乳房腫瘤檢測和診斷中的應用價值」、「Endolift 光纖微雕溶脂」、「粉瘤與脂肪瘤微創切除術」等），目前上傳後僅能被動切分成零碎問答（FAQ），無法結構化提煉為四段式臨床推理樹（`pre_op`, `procedure`, `post_op_short`, `maintenance`）。
  2. **缺乏視覺化簽核與醫師指令填寫介面**：目前 Web App 僅有 FAQ 審核分頁，缺乏「臨床推理樹」的結構化預覽、編輯四段內容以及由醫師親自填寫「醫師權威醫囑 (`*_physician_notes`)」之專屬操作介面。
  3. **未建立 Fail-Closed 審核閘門**：`page_index_trees` 原 schema 未設有 `review_status`（pending/approved/rejected），任何新加入的推理樹若無審核隔離，恐有未經醫師簽核即被公開查詢引用之醫療風險。

- **核心價值與目標**：
  1. **文件自動提煉推理樹管線**：自上傳文件或療程內文自動萃取並透過本地 LLM 結構化提煉四段式臨床推理樹，預設狀態為 `pending`。
  2. **Web 臨床推理樹視覺化管理介面**：在管理介面中新增「🌳 臨床決策樹簽核」分頁，呈現四段式卡片，支援內聯編輯與醫師專屬權威指令（`*_physician_notes`）填寫。
  3. **Fail-Closed 審核隔離與檢索擴展**：未核准之推理樹對外嚴格保密，經醫師簽核核准後即時同步更新 FTS5 全文檢索索引，並擴展 RAG 推理檢索範圍。

---

## 2. 核心規範與多 Agent 流水線（User Golden Rule）
依據使用者明確指定的不可動搖鐵則：
- **實作端 (Executor)**：一律由 **Agy 3.6 Flash (`w5:p2`)** 負責編寫後端提煉管線、API 端點、Web 前端卡片元件與初始測試。
- **審查加固端 (Reviewer & Hardener)**：一律由 **Claude 5.5 Sonnet (`w5:p3`)** 進行深度對抗性代碼審查，重點防護：執行緒安全、GPU 鎖防重疊、資料庫遷移冪等性、醫療法規合規與 `AGENTS.md` 規範文檔同步。
- **終端驗收端 (Tester)**：一律由 **Hermes Agent (`w5:p4`)** 進行終端獨立全套回歸測試驗收與正式庫 SHA-256 防禦檢核。

---

## 3. 邊界與安全準則（Guardrails）
1. **醫師特約醫囑 (Physician Notes) 鐵則**：
   - LLM 生成之推理樹，`pre_op_physician_notes`、`procedure_physician_notes`、`post_op_short_physician_notes`、`maintenance_physician_notes` 必須**強制留空 (None / NULL)**，嚴禁 LLM 擅自生成醫師個人醫囑。
2. **Fail-Closed 審核隔離**：
   - 新提煉之推理樹狀態恆為 `review_status='pending'`。在醫師於介面核准前，`search_page_index_trees` 與公開 RAG 查詢端點**絕對不可檢索出**。
3. **GPU 顯存與推論保護**：
   - 沿用本地 LLM 鎖（`_GENERATION_LOCK`）與 Prompt `<think>` 思考長度限制（不超過 100 字），防止長篇推論耗盡 token 或超時。
4. **醫療合規與零價格洩漏**：
   - 產出之各段落均須通過正體中文檢核、無保證療效禁詞、`deep_mask_prices()` 價格清洗。
5. **正式資料庫絕對保護**：
   - 遷移腳本支援安全冪等升級；所有測試一律使用 `tmp_path`，正式庫 `clinic.db` SHA-256 恆定。
