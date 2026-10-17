# Phase 28 驗證對照與來源稽核

## 執行分工（使用者指示）
agy 執行計畫 -> hermes 測試 -> Claude 最後檢查。三方依序，不得自我核准。28-07 的實機探測需使用者明確核准（autonomous: false）。

## 波次
| Wave | 計畫 |
|------|------|
| 1 | 28-01（延遲與截斷偵測、共用鎖）、28-02（組稿純函式、句界截斷） |
| 2 | 28-03（組稿接入病人路由）、28-05（24 小時新鮮度規劃）、28-07（實機探測，非自主） |
| 3 | 28-04（job 加輪詢加 UI）、28-06（階段 8 預生成、CLI） |
| 4 | 28-09（伺服器固定單一診所設定：診所範圍檢索） |
| 5 | 28-08（AGENTS.md 2.25 與 2.6／2.9 例外文件,最後撰寫） |

## Nyquist 對照
| 需求 | 行為 | 自動化驗證 | 計畫 |
|------|------|------------|------|
| P28-LAT | 最多 1 次呼叫、不重試、鎖共用 | tests/test_patient_consult_latency.py、tests/test_llm_client.py | 01 |
| P28-LAT | 關思考欄位實效與速率 | 28-PROBE.md（實機，需核准） | 07 |
| P28-TRUNC | finish_reason=length 失敗 | tests/test_llm_client.py | 01 |
| P28-TRUNC | 句界截斷、警訊保留 | tests/test_answer_compose.py、tests/test_rag_ask_enhancement.py | 02 |
| P28-TPL | 價值＋單一追問＋邀請、驗證 | tests/test_answer_compose.py、tests/test_patient_compose.py、tests/test_patient_consult.py | 02、03 |
| P28-ASYNC | job、TTL、隱私、輪詢 | tests/test_consult_jobs.py、tests/test_patient_consult_ui.py | 04 |
| P28-CLINIC | 設定／無效／隔離／忽略夾帶／營運關鍵字／風險檢查／special 預生成 e2e | tests/test_patient_clinic_scope.py、tests/test_patient_prefill_special_e2e.py | 09 |
| P28-PRE | 預生成 pending、隔離、預算、skipped_budget | tests/test_patient_prefill_plan.py、tests/test_patient_prefill_batch.py | 05、06 |
| P28-FRESH | 24 小時、簽章、積壓（假時鐘） | tests/test_patient_prefill_plan.py、tests/test_patient_prefill_e2e.py | 05、06 |

## 來源稽核
| 來源 | 項目 | 計畫 |
|------|------|------|
| GOAL | 價值回答＋追問＋邀請 | 02、03 |
| GOAL | 夜間預生成待審 | 05、06 |
| GOAL | 修復約 960 秒耗時 | 01、07 |
| GOAL | 修復截斷、警訊不遺失 | 01、02 |
| GOAL | 不收集個資、留資為階段二 | 03、04（不實作留資） |
| CONTEXT | 三層架構 | 03（1、2、3 層）、06（預生成） |
| CONTEXT | 960 秒先查根因再決定 job | 01、07、04 |
| CONTEXT | FAITHFUL_SAMPLING、長度上限 | 01 |
| CONTEXT | 24 小時預生成、topic_key 追蹤、永不自動核准 | 05、06 |
| CONTEXT | 病人詢問優先命中預生成、少量組稿 | 03、06 |
| CONTEXT | 分工 agy／hermes／Claude | 全部計畫 frontmatter |
| RESEARCH | job_id token_urlsafe、TTL、無問句保留 | 04 |
| RESEARCH | 共用生成鎖與夜間鎖 | 01 |
| RESEARCH | 速率文件修正 | 07 |
| CONTEXT | 病人問答主題 → 相似 QA | 由 Phase 9 熱門未命中關鍵字(`miss_keyword`)種子機制承接(夜間批次既有 FAQ 階段);28-05 刻意不讀 `miss_keyword` 作額外題目來源,理由:該表只有白名單路由關鍵字、沒有主題內容或參考資料,階段 8 的題目必須有已核准 PageIndex／FAQ 作依據才可生成,不憑空擬題 |
| 延後 | 留資表單、limit_req、18 失敗測試 | 不納入 |

## 待使用者確認的假設
1. （已決定,見待決事項 BLOCKER-1,由 28-09 實作。）原假設「不檢索 special」作廢。注意：CONTEXT 的「診所專屬資料即時組稿」需要診所識別；special 預生成問答目前只能經 /api/v1/query（帶 clinic_id）使用。若要讓匿名諮詢使用診所資料，需另行決定診所識別方式（例如伺服器固定設定）。**此項建議在執行 28-03 前確認。**
2. 已核准資料組稿的回答不加「未經醫師審核」標示；2.24 未審說明保留標示。
3. 實機探測為 28-07 獨立任務，僅副本庫、不重啟、不改設定，需使用者核准。
4. 病人、管理端、背景補齊共用一把鎖；病人端有已核准資料時忙碌降級為確定性回答，無資料時回 busy。
5. 速率文字修正（/home/hsu/AGENTS.md 的約 90 tok/s）於探測確認後進行。
6. 預生成受保護列（approved／rejected／人工編修）：僅參考內容簽章改變時才重新生成（回 pending）；時間過期但簽章未變不排入、不佔名額。pending 列每 24 小時會被重新生成（GPU 成本，醫師未審期間會持續更新）。
7. 新鮮度判定採 24 小時減 2 小時寬限，避免每晚 02:30 批次因 23.9 小時而跳過導致實際 48 小時一輪。
8. 每晚處理的主題數受 --max-faq-topics 限制；主題多時積壓跨晚，24 小時為目標而非硬保證，摘要回報 prefill_backlog。

## 待決事項(阻斷性)
- **BLOCKER-1(已決定,2026-10-17,使用者採「伺服器固定單一診所設定」)**:新增顯式設定 `patient_clinic_id`(無預設值;須存在於 clinic_info,否則視為未設定,Fail-Closed)。設定後匿名 /consult 只可用該診所已核准的 special FAQ 與樹來源預生成內容;請求的 clinic_id 與 X-Clinic-ID 一律忽略;風險檢查與營運關鍵字規則照舊。由 28-09 實作(28-03 維持一般資料;special 範圍 e2e 因需要 28-06 與 28-09 同時存在,放在 28-09),文件由 28-08 補 AGENTS 2.6／2.9 例外。

## 第 1 輪修訂摘要(依規劃檢查員回報)
- B2:受保護列(approved/rejected/人工編修)簽章未變時不排入(28-05/06)。
- B3:`now_fn` 與 `clock` 分離(28-06)。
- B4:28-01 先用保守 3000 token,收緊只在 28-07 探測通過後(28-07 Task 3)。
- B5:文件拆為 28-08(Wave 4);P28 需求條目提前到 28-01 Task 3。
- W6:/home/hsu/AGENTS.md 修改獨立 blocking checkpoint(28-07 Task 4、5)。
- W7:28-03 直答套用 AGENTS 2.8 雙門檻、風險對稱、歧義邊界。
- W8:人工編修列受保護(28-05)。
- W9:見上方來源稽核。
- W10:ROADMAP 補 Requirements 行。
- W11:urlopen 層測試防護(28-01)、consult_jobs 測試 db 守門與並行限制調整(28-04)、`prefill_skipped_budget`(28-06)。

- B1 決定後新增:28-09 與 P28-CLINIC;28-08 移至 Wave 5。

## 第 3 輪修訂摘要與真實資料假設
- 預生成題目標題來源(28-05/06):正式庫 6 棵診所樹 doc_id 為英文 slug(laser-skin-resurfacing、botox-injection、electrowave-facelift、hyaluronic-acid-filler、fractional-laser、hifu-lifting),種子僅 2 個主題帶 tree_doc_id 且 title 為「…常見問題」。標題優先順序:`page_index_trees.title` → 種子 title 去掉「常見問題」→ 無可讀中文標題者不列入(日誌以 doc_id 記錄),絕不以 doc_id 拼題。**假設:正式庫 page_index_trees 具 title 欄位且為中文(執行者以 PRAGMA 確認;不具備則第一級跳過,多數樹將因無標題而不預生成,需使用者補 title 或種子)。**
- 28-09:config 用 `field(default_factory=...)`、conftest 重設、無資料不得 answered(W1、W5);28-03 驗收移除 PREFILL_HIT_COVERAGE(W3);28-06 Test 4 夾具為 general NULL 樹(W4);28-08 文件矛盾與 2.24 待辦指向(W2)。
- 已知實況:正式庫樹全為診所專屬,未設定 `patient_clinic_id` 時這些預生成內容匿名端點看不到。
