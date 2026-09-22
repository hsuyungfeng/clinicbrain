# clinicbrain 專案計畫

> 給下次接手的 LLM/開發者：這是專案的單一入口計畫文件。先讀這份，再讀 `AGENTS.md`（規範）、
> 再讀 `.planning/HANDOFF.json` 或 `.planning/phases/01-taiwan-pageindex-rag/.continue-here.md`
> （目前確切進度），需要更完整背景再讀 `.planning/VISION-EXPANSION.md`。

---

## 1. 這是什麼

台灣診所醫療 PageIndex RAG 系統，服務對象是緻妍外科診所（醫美診所）。核心能力：
1. 把台灣 NHI（全民健保）藥品、服務給付項目資料結構化進 SQLite，支援中文全文檢索
2. 用 PageIndex 框架的「臨床推理樹」概念（術前/療程/術後短期/長期維持四段式）組織療程衛教內容
3. OTC 藥品成分自動本地化（如 ACETAMINOPHEN → 普拿疼）
4. 嚴格的台灣醫療合規：繁體中文專用、絕對禁止價格資訊外洩

技術棧：Python 3.12、SQLite 3.45（FTS5 + trigram tokenizer 做中文全文檢索）、無外部框架依賴。

---

## 2. Phase 01：Taiwan PageIndex RAG（✅ 已完成）

8 個任務全數完成：

| # | 任務 | 狀態 | 備註 |
|---|---|---|---|
| TASK-001 | SQLite schema + seed from OriginalData | ✅ (`0ac396d`) | 7,573 藥品 + 2,669 服務項目；FTS5 改用 trigram |
| TASK-003 | PageIndex schema + tree generation | ✅ (`cf3dd47`) | 6 筆手寫繁中範本；修復 `page_index_fts` 遺漏的 trigram |
| — | page_index_trees 增量更新設計 | ✅ (`f59af48`) | `content_version`/`source_type`/`needs_regeneration` |
| TASK-004 | LLM prompt 設計（生成臨床推理樹） | ✅ (`a55ed63`) | `src/pageindex/prompt_template.py`；未接真實 LLM 測試 |
| TASK-005 | 查詢介面 + special/general 路由 | ✅ (`1d5bb52`) | `src/query/`；修復 FTS5 完整句子查詢失敗問題 |
| TASK-006 | OTC 本地化層完整化 | ✅ (`24ab889`) | 68 種成分，覆蓋率 6.02%→32.8%；首次交予 Antigravity 執行 |
| TASK-007 | 診所資料庫整合 | ✅ (`b7c7fa5`) | `src/clinic/custom_notes.py`；`clinic_custom_notes` 查詢/寫入路徑 |
| TASK-008 | 評估測試套件 | ✅ (`a09e829`) | `tests/`，91 個 pytest 案例，專案首份正式測試套件 |

TASK-006/007/008 皆由外部工具 Antigravity 依 Claude 撰寫的規格執行，Claude 逐項親自驗證後才提交——每次都實測重跑而非採信交付報告，過程中抓到數次報告論述不準確或誤讀程式碼的情況，詳見 `.planning/HANDOFF.json` 各任務的 notes 欄位。

**確切執行狀態與完整驗證紀錄**請讀 `.planning/HANDOFF.json`——這份文件才是即時真相來源。

---

## 3. Phase 02：本地 LLM 推理層（✅ 已完成）

4 個任務全數完成（單一 commit `ff04197`，由 Antigravity 依 `.planning/phases/02-local-llm-layer/TASK-PLAN.md` 執行，Claude 逐項親自驗證後提交）：

| # | 任務 | 狀態 | 備註 |
|---|---|---|---|
| TASK-01 | `llm_client.py` adapter | ✅ | 純標準庫 `urllib` 串接既有 `llama-server`（127.0.0.1:8080，Qwen3.8-27B），健康檢查 + 明確逾時/連線例外 |
| TASK-02 | Prompt 立場中立規範 | ✅ | `prompt_template.py` 新增第 7 條規則，既有 1-6 條未動 |
| TASK-03 | 輸出驗證層立場檢測 | ✅ | `_POLITICAL_STANCE_PHRASES` 比照既有 `_FORBIDDEN_PHRASES` 機制 |
| TASK-04 | 端到端驗證 | ✅ | 3 筆真實生成（淨膚雷射/水飛梭/自體脂肪補臉），通過驗證，寫入隔離測試複本 |

驗收：pytest 100/100 通過（91 舊 + 9 新），`clinic.db` 測試前後 SHA-256 一致（零污染正式資料庫）。
背景：實測發現本機既有 Qwen 模型對政治敏感問題會輸出中國官方立場內容，使用者決定不換模型、
不重新部署，改用 prompt + 驗證雙層防禦（詳見 `.planning/HANDOFF.json` 決策紀錄）。
雲端 API 備援**未實作**，僅確認介面可留待未來串接。

**完整驗證紀錄**請讀 `.planning/HANDOFF.json`。

---

## 4. Phase 02 之後：願景擴充（Phase 03/04 已有草案，尚未展開為可執行任務）

使用者確認的方向（完整討論見 `.planning/VISION-EXPANSION.md`）：

- **Phase 03（草案已就緒，schema 已定案）：文件擷取管線** — `.planning/phases/03-document-ingestion/PLAN.md` 已完成真實資料盤點（`OriginalData/一般醫學/` 2.0G、`OriginalData/緻妍外科診所/` 782M）與使用者決策（診所文件先轉 Q&A 再入庫、需簡繁轉換、`健保相關/` 與 Phase 01 資料同源已確認）。2026-09-22 追加確認：新增獨立 `faq_cache` 表（不與 `page_index_trees` 共用同一張表，欄位模式比照），FTS5 一樣用 trigram。尚未展開為 TASK-PLAN.md，尚未動工。
- **Phase 04（TASK-PLAN.md 已展開，尚未動工）：多診所支援** — `.planning/phases/04-multi-clinic-support/PLAN.md` 已有使用者決策（單一資料庫邏輯隔離、`clinic_id` 改用健保特約醫事機構代碼、識別方式留給 Phase 05 部署層處理）。2026-09-22 追加確認：盤點發現 `page_index_trees` 目前完全沒有 `clinic_id` 欄位（診所身份只靠 `doc_id` 字串前綴 + 硬編碼比對辨識，是技術債），已定案新增真正的 `clinic_id` 欄位、`doc_id` 改為純療程 slug。同日已將 TASK-00（補欄位+doc_id 去前綴+`search_page_index_trees()` 補 clinic 過濾）與 TASK-01（clinic_id 值遷移為健保代碼+補齊 `clinic_info` 缺失的種子腳本）展開成完整可執行規格 `.planning/phases/04-multi-clinic-support/TASK-PLAN.md`（比照 Phase 02 模式，可直接交給 Antigravity 執行）。TASK-02（函式預設值是否移除）與 TASK-03（依賴 Phase 05）維持草案，不在本次展開範圍。尚未實際動工執行。
- **Phase 05（建議）：doctor-toolbox.com 官方 API 整合** — 雙向資料匯入/匯出，走正式 API（非舊系統的 MITM 攔截方式），排在 clinicbrain 自身功能完成之後。

**尚待決策**（見 VISION-EXPANSION.md 第 5 節）：OCR 引擎最終選型、要不要引入向量檢索補強 FTS5 召回率、使用者身份與資料隔離範圍（匿名 vs 留歷史）、doctor-toolbox.com API 文件與認證方式。

---

## 5. 重要背景與教訓（避免重蹈覆轍）

1. **舊系統 `DrtoolboxLocalServer` 已經做過類似的事**，不是從零開始設計。同一台機器本機路徑
   `~/Desktop/DrtoolBox/UpdateList/MedicalOderUpdate/` 也有相關 RAG 實驗。動工新 Phase 前，
   先去看舊系統對應模組怎麼做的（`src/rag/`、`src/services/anydoc_parser.py`、
   `src/agent/hermes_core.py` 的 OCR 呼叫方式等），能省下大量重新踩雷的時間。
2. **CSV 記錄數陷阱**：NHI 原始資料的 `wc -l` 行數遠大於實際記錄數（換行符號在長文字欄位內）。
   TASK-001 一度誤以為資料匯入短少了 98%，後來證實 7,573 筆才是正確值。
3. **FTS5 中文分詞陷阱**：`unicode61` tokenizer 完全無法處理中文，必須用 `trigram`。TASK-003
   時發現 `page_index_fts` 在遷移時被漏改，新增資料完全搜不到。修改 FTS5 schema 後務必逐表驗證。
4. **SFT 訓練資料的語言/領域陷阱**：`OriginalData/medical_o1_sft_Chinese.json` 是簡體中文的
   中醫辨證問答，不能直接用於繁體中文醫美診所的 PageIndex 生成。
5. **任務邊界要守住**：做 TASK-001 時不要順手把 TASK-005 的查詢邏輯也寫掉；做 schema 改動時
   若發現需要新功能（如查詢層 fallback），記錄成備註留給對應任務，不要當場展開。

---

## 6. 如何恢復工作

```
/gsd-resume-work
```
會自動讀取 `.planning/HANDOFF.json` 與對應 phase 的 `.continue-here.md`，還原完整上下文、
待辦事項、已知 blocker。這份 Plan.md 是靜態總覽，不會即時更新每個 session 的進度細節。

**⚠️ 已知踩雷紀錄**：2026-09-22 這次 session 發現 Phase 02 早已完成並 commit（`ff04197`），
但 `HANDOFF.json`／本文件都還停留在「Phase 02 尚未開始」的舊快照，直到這次比對 `git log`
才抓到落差並修正。**下次 session 開頭務必用 `git log --oneline -10` 或
`git log <上次HANDOFF記錄的commit>..HEAD` 跟這兩份文件的敘述做交叉比對**，不要只信任
文件裡寫的進度。
