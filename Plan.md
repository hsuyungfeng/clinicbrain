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

## 4. Phase 04：多診所支援（TASK-00 ~ TASK-03 ✅ 全數完成）

TASK-00/TASK-01（commit `f487763`）、TASK-02（commit `625593d`）與 TASK-03 皆由 Antigravity 依
`.planning/phases/04-multi-clinic-support/PLAN.md`／`TASK-PLAN.md`／`TASK-03-PLAN.md` 執行，
逐項親自重新驗證（測試、腳本驗證行為、隔離安全）：

| # | 任務 | 狀態 | 備註 |
|---|---|---|---|
| TASK-00 | `page_index_trees` 補 `clinic_id` 欄位 + `doc_id` 去前綴 | ✅ | 順道修掉 `search_page_index_trees()` 完全沒有診所過濾的既有 bug |
| TASK-01 | `clinic_id` 值遷移為健保代碼 `3503190424` | ✅ | 四張表（`clinic_info`/`clinic_hours`/`clinic_custom_notes`/`page_index_trees`）同步遷移 |
| TASK-02 | 移除 5 個函式過期的 `clinic_id="zhiyan-clinic"` 預設值 | ✅ | 4 個函式改必填；`handle_query()` 單獨保留 `str \| None = None`，special 路由缺 `clinic_id` 時明確拋 `ValueError` |
| TASK-03 | FAQ 快取查詢整合與多診所檢索分流 | ✅ | `search_faq_cache()` 實作、`QueryResponse.faq_hits`、價格遮蔽與診所/路由嚴格隔離，新增 6 個測試全數通過 |

TASK-00/TASK-01 驗收：pytest 104/104 通過，`PRAGMA foreign_key_check` 零違規，正式 `clinic.db`
遷移前後非相關資料筆數一致。

TASK-02 驗收：pytest 123/123 通過，`handle_query()` 內部呼叫 `search_page_index_trees()` 未傳 `clinic_id` 的關聯問題已一併修正。

TASK-03 驗收：pytest 128/128 通過，新增 `tests/test_faq_search.py` 6 個測試涵蓋 FTS5 trigram MATCH、LIKE fallback、診所隔離、價格遮蔽；正式 `clinic.db` SHA-256 全程未變。

**完整驗證紀錄**請讀 `.planning/HANDOFF.json`。

---

## 5. Phase 03：文件擷取管線 Stage 1（✅ 已完成，TASK-00~TASK-03）

Stage 1（文字型文件擷取 + `faq_cache` 建表 + LLM 轉 Q&A）四個任務全數完成（單一 commit
`625593d`，與 Phase 04 TASK-02 合併在同一批交付，由 Antigravity 依
`.planning/phases/03-document-ingestion/TASK-PLAN.md` 執行，Claude 逐項親自驗證後提交）：

| # | 任務 | 狀態 | 備註 |
|---|---|---|---|
| TASK-00 | `faq_cache`/`faq_cache_fts`（trigram）+ 觸發器 + `faq_writer.py` 唯一寫入路徑 | ✅ | dedup 用 `clinic_id IS ?`，正確處理 general 類 `clinic_id=NULL` 的去重語意 |
| TASK-01 | docx/xlsx 文字擷取（`src/ingestion/extract_text.py`） | ✅ | docx 同時擷取段落與表格；xlsx 忠實轉成列字典，不預設欄位語意 |
| TASK-02 | 簡繁轉換（`src/ingestion/convert_chinese.py`，opencc `s2twp`） | ✅ | 含台灣慣用詞轉換（軟件→軟體等） |
| TASK-03 | LLM 轉 Q&A + 四層驗證 + 寫入（`src/ingestion/generate_faq.py`） | ✅ | 價格/簡體字/政治立場/保證療效禁詞，單筆過濾不影響同批其他合格項目 |

驗收：pytest 123/123 通過（107 舊 + 16 新），正式 `clinic.db` SHA-256 全程一致。三份優先檔案
（`緻妍自費門診手術內容.docx`、`緻妍可自費門診手術...docx`、`客服回覆話術.xlsx`）實際跑過端到端
流程，產出 **40 筆真實 FAQ**（`outpatient-surgery-procedures` 15、`insurance-diagnosis-certificates`
9、`customer-service-faq` 16），寫入隔離測試複本 `clinic_test.db`，Claude 逐筆掃過確認零價格
洩漏、零簡體字殘留。

**後續收尾（2026-09-22 已完成）**：Stage 1 交付時正式 `clinic.db` 還沒有 `faq_cache` schema，
已於同日補做：對正式 `clinic.db` 套用 `faq_cache`/`faq_cache_fts`/三個觸發器（先在隔離複本
演練一次確認安全，再對正式庫執行，執行前後非相關資料表筆數一致），並透過
`faq_writer.upsert_faqs()`（唯一權威寫入路徑）把已驗證的 40 筆真實 FAQ
（`source_type='clinic_upload'`）寫入正式資料庫，逐筆重新掃過確認零價格洩漏、零簡體字。
套用後重跑 pytest 發現 2 個既有測試（`test_faq_cache_fts_cjk_match`／
`test_faq_cache_triggers_sync`）因為測試選字（「甲溝炎」「矽膠貼」）剛好命中正式資料庫裡
真實存在的其他 FAQ 內容而失敗——已修正為用測試專屬 `topic_key` 過濾，不受既有資料影響
（commit `35a71a5`），連續重跑三次穩定 123/123 通過。

**Stage 2（圖片 OCR）與 `一般醫學/美容醫學/` 皆已於 2026-09-23 人工抽查結案，判定
不值得展開**——Stage 2 抽查 47 張圖片中 6 張跨類別樣本，多數是行銷圖/無實質文字
照片，唯一有實質內容的 `儀器/` 參數表也因文字混雜圖表、內容偏醫師參考而非病患
衛教，建議未來若真的需要改用人工謄寫而非 OCR。`美容醫學/` 原本盤點時只看檔名，
假設是繁體中文病患衛教 PDF，實際打開後發現是整本簡體中文醫學教科書等級的掃描檔
（`肉毒桿菌毒素美容.pdf`、`微創美容外科學.pdf` 等，動輒百餘頁到 555 頁，`pdftotext`
完全抽不到文字、需整本書 OCR），性質與規模都跟原假設完全不同，投資報酬率比
Stage 2 圖片更差，同樣不展開。完整判斷紀錄見
`.planning/phases/03-document-ingestion/PLAN.md`。**Phase 03 至此沒有已知的、
值得展開的剩餘擴充方向**；Stage 3（影片/複雜 PDF）尚未評估但優先度最低，且大機率
是同樣的低投資報酬率情況。

**完整驗證紀錄**請讀 `.planning/HANDOFF.json`。

---

## 6. Phase 05：doctor-toolbox.com 官方 API 整合與 HTTP 服務層架構（✅ 已完成）

4 個任務全數完工，由 Antigravity 依 `.planning/phases/05-api-integration/PLAN.md` 與 `TASK-PLAN.md` 執行，測試套件擴充至 155 個測試 100% 通過，正式 `clinic.db` SHA-256 全程未變：

| # | 任務 | 狀態 | 備註 |
|---|---|---|---|
| TASK-01 | FastAPI 基礎骨架、Pydantic Schema 與健康檢查 (`GET /health`) | ✅ (`3bf1436`) | 建立 `src/api/`，實作 `get_read_db`（`PRAGMA query_only=ON`）、`verify_admin_key` 與 `/health` 監控端點 |
| TASK-02 | 自然語言查詢端點封裝 (`POST /api/v1/query`) | ✅ (`816e3c2`) | 封裝 `handle_query()`、多診所動態路由（URL Path/Body/Header 三重解析）、遞迴字串二次價格遮蔽防禦 |
| TASK-03 | doctor-toolbox.com 雙向資料同步契約與審計日誌 | ✅ (`5c4f96c`) | `sync_logs` 表結構、`POST /api/v1/sync/export` 增量匯出、`POST /api/v1/sync/import` 權威寫入與醫療法規合規多層攔截（保證療效、政治立場正簡台臺異體字、價格清洗） |
| TASK-04 | 服務啟動器、Systemd 單元範本與全系統驗收 | ✅ (`bb12589`) | `scripts/run_api_server.py` CLI 參數解析與 Banner 診斷、`clinicbrain-api.service` 配置範本、全系統端到端測試通過 |

驗收：pytest 155/155 全數通過（128 舊 + 27 新），正式 `clinic.db` SHA-256 (`c51cc4d039379fe00f70d7864b29a952928233fa6caa6e72954900f4c28c65ad`) 全程未變（零污染正式資料庫）。獨立 Git 倉庫已建立並完整同步至 GitHub 遠端 `https://github.com/hsuyungfeng/clinicbrain`。

---

## 7. 重要背景與教訓（避免重蹈覆轍）

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
6. **盤點「這筆資料是哪裡寫入的」時，grep 範圍不能只查 `.py`**：Phase 04 規劃 TASK-PLAN.md
   時判斷「`clinic_info` 找不到任何種子腳本」，但漏查了 `.sql` 檔案——`clinic_schema.sql`
   本身就有一份內嵌的 `INSERT OR IGNORE`。這導致 Antigravity 依規格新增了一個重複的
   `seed_clinic_info.py`，驗收時才發現。之後要確認「某張表的資料從哪裡來」，`grep` 至少要
   涵蓋 `.py` 與 `.sql` 兩種副檔名，不要假設種子資料只會出現在 Python 腳本裡。
7. **Schema 改動（`clinic_schema.sql`）與正式資料庫（`clinic.db`）是兩件事，不會自動同步**：
   Phase 03 Stage 1 新增 `faq_cache` 表後，`clinic_schema.sql`（DDL 來源）已更新，但正式
   `clinic.db` 本身**沒有**這張表——因為任務隔離 CONSTRAINT 只要求驗證在隔離複本上完成，
   不要求同步遷移正式庫。這不是 bug，但下次要真正使用 `faq_cache` 功能前，必須記得先對
   正式 `clinic.db` 補跑一次 schema 更新，不能假設「schema.sql 改了 = 正式資料庫也有了」。
   （已於 2026-09-22 補做完成，見上方「後續收尾」。）
8. **測試 fixture 複製正式 `clinic.db` 後，一旦正式庫有了真實資料，測試選字不能再隨便挑**：
   `faq_cache` 套用到正式 `clinic.db` 並寫入 40 筆真實 FAQ 後，兩個既有 FTS 測試
   （用「甲溝炎」「矽膠貼」這類看似安全的醫療常見詞當 `MATCH` 關鍵字）突然失敗——不是
   程式碼壞了，是測試選的詞剛好命中資料庫裡真實存在的其他 FAQ 內容。`isolated_conn` 這類
   fixture 複製的是正式 `clinic.db`，不是空白資料庫，資料庫內容越豐富、隨便選字撞到既有
   資料的機率越高。修正方式是比照 `test_multi_clinic.py` 已有的慣例：用測試專屬的唯一
   識別碼（如 `topic_key='test-xxx-unique-marker'`）過濾查詢結果，只驗證本測試自己寫入的
   那一列，不要只信任裸的 `MATCH`/查詢命中數。
9. **FastAPI 的 Sync 路由執行在 Worker 執行緒池**：
   FastAPI 的同步端點（`def` handler）由 AnyIO 在執行緒池中並發執行。SQLite 連線必須指定
   `check_same_thread=False`，且測試注入時應 monkeypatch `config.db_path` 讓執行緒各自
   建立安全連線，禁止跨執行緒直接共用同一連線物件。
10. **繁簡轉換（OpenCC s2twp）自動將「台」轉換為「臺」**：
   在執行政治立場與敏感詞檢測時（如「中國台灣」、「台灣地區」），若文字先經過 `to_traditional()`
   處理，會被轉為「中國臺灣」、「臺灣地區」。過濾清單必須完整包含正簡繁與台/臺異體字，
   並於轉換前後執行雙重檢核，杜絕字元變體繞過風險。

---

## 8. 如何恢復工作

```
/gsd-resume-work
```
會自動讀取 `.planning/HANDOFF.json` 與對應 phase 的 `.continue-here.md`，還原完整上下文、
待辦事項、已知 blocker。這份 Plan.md 是靜態總覽，不會即時更新每個 session 的進度細節。

**⚠️ 已知踩雷紀錄**：
1. 2026-09-22 這次 session 一開始發現 Phase 02 早已完成並 commit（`ff04197`），但
   `HANDOFF.json`／本文件都還停留在「Phase 02 尚未開始」的舊快照，直到比對 `git log`
   才抓到落差並修正。
2. 同一個 session 稍後又發現第二次落差：Phase 04 的 TASK-00 已經被**實際執行**（正式
   `clinic.db` 跑過遷移、5 個 `src/` 檔案有改動），但這次連 commit 都沒有——純粹是
   working tree 裡的未追蹤/未提交狀態，連 `git log` 都看不出來，只有跑 `git status` +
   實際連進 `clinic.db` 查 schema 才發現。

**下次 session 開頭務必做兩件事**：
1. `git log --oneline -10` 或 `git log <上次HANDOFF記錄的commit>..HEAD` 跟文件敘述的
   進度做交叉比對（抓已 commit 但文件未同步的落差）
2. `git status --short` 檢查有沒有未 commit 的改動（抓已執行但連 commit 都沒有的落差，
   這種比第一種更危險，因為沒有任何 commit 訊息可以說明「這是什麼」「為什麼存在」）

不要只信任文件裡寫的進度，也不要只信任 `git log`——兩者都要查。
