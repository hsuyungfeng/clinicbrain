# Phase 28 驗證對照與來源稽核

## 執行分工（使用者指示）
agy 執行計畫 -> hermes 測試 -> Claude 最後檢查。三方依序，不得自我核准。28-07 的實機探測需使用者明確核准（autonomous: false）。

## 波次
| Wave | 計畫 |
|------|------|
| 1 | 28-01（延遲與截斷偵測、共用鎖）、28-02（組稿純函式、句界截斷） |
| 2 | 28-03（組稿接入病人路由）、28-05（24 小時新鮮度規劃）、28-07（實機探測，非自主） |
| 3 | 28-04（job 加輪詢加 UI）、28-06（階段 8 預生成、CLI、文件） |

## Nyquist 對照
| 需求 | 行為 | 自動化驗證 | 計畫 |
|------|------|------------|------|
| P28-LAT | 最多 1 次呼叫、不重試、鎖共用 | tests/test_patient_consult_latency.py、tests/test_llm_client.py | 01 |
| P28-LAT | 關思考欄位實效與速率 | 28-PROBE.md（實機，需核准） | 07 |
| P28-TRUNC | finish_reason=length 失敗 | tests/test_llm_client.py | 01 |
| P28-TRUNC | 句界截斷、警訊保留 | tests/test_answer_compose.py、tests/test_rag_ask_enhancement.py | 02 |
| P28-TPL | 價值＋單一追問＋邀請、驗證 | tests/test_answer_compose.py、tests/test_patient_compose.py、tests/test_patient_consult.py | 02、03 |
| P28-ASYNC | job、TTL、隱私、輪詢 | tests/test_consult_jobs.py、tests/test_patient_consult_ui.py | 04 |
| P28-PRE | 預生成 pending、隔離、預算 | tests/test_patient_prefill_plan.py、tests/test_patient_prefill_batch.py | 05、06 |
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
| 延後 | 留資表單、limit_req、18 失敗測試 | 不納入 |

## 待使用者確認的假設
1. 匿名 /consult 本期不檢索診所專屬 special FAQ。注意：CONTEXT 的「診所專屬資料即時組稿」需要診所識別；special 預生成問答目前只能經 /api/v1/query（帶 clinic_id）使用。若要讓匿名諮詢使用診所資料，需另行決定診所識別方式（例如伺服器固定設定）。**此項建議在執行 28-03 前確認。**
2. 已核准資料組稿的回答不加「未經醫師審核」標示；2.24 未審說明保留標示。
3. 實機探測為 28-07 獨立任務，僅副本庫、不重啟、不改設定，需使用者核准。
4. 病人、管理端、背景補齊共用一把鎖；病人端有已核准資料時忙碌降級為確定性回答，無資料時回 busy。
5. 速率文字修正（/home/hsu/AGENTS.md 的約 90 tok/s）於探測確認後進行。
6. 預生成 approved 列：僅參考內容簽章改變時覆寫（回 pending）；僅時間過期而內容有變時不覆寫並計數，交醫師處理（避免公開內容每日消失）。
7. 新鮮度判定採 24 小時減 2 小時寬限，避免每晚 02:30 批次因 23.9 小時而跳過導致實際 48 小時一輪。
8. 每晚處理的主題數受 --max-faq-topics 限制；主題多時積壓跨晚，24 小時為目標而非硬保證，摘要回報 prefill_backlog。
