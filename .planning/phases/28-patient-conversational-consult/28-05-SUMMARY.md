# Phase 28 Plan 05：24 小時預先生成主體醫學資訊規劃層執行總結

## 1. 執行目標
- 建立「24 小時預先生成主體醫學資訊」之規劃層（P28-PRE、P28-FRESH），列舉已建檔且經醫師核准之主題、以假時鐘判定新鮮度、計算參考內容短雜湊簽章，並輸出本次應生成之意圖佇列。
- 純唯讀設計：全函式零寫入、零模型呼叫、時鐘強制由外部注入，絕不讀取或儲存病人問句原文。
- 受保護列防護：已核准 (approved)、已駁回 (rejected) 或人工編修 (manual_edit) 之列在簽章未變時永不排入，且不佔用 `max_topics` 名額餓死其他過期主題；只有當簽章改變時才排入重新生成（Fail-Closed 回 pending）。

## 2. 實作變更清單
1. `src/batch/patient_prefill_plan.py`（全新建立）：
   - 常數：`FRESHNESS_HOURS = 24`、`REFRESH_GRACE_HOURS = 2`、`PREFILL_TOPIC_PREFIX = "prefill-"`。
   - `INTENT_TEMPLATES`：定義 5 大意圖問句（what, suitable, risk, recovery, when_to_see_doctor），模組載入時立即自我檢驗四層合規（無數字、恰一個「？」、繁體中文、通過法規驗證器），失敗拋出 RuntimeError。
   - 資料類別：`PrefillTopic`（frozen dataclass）、`PrefillItem`、`PrefillTopicPlan`、`PrefillPlan`。
   - `compute_ref_signature(parts)`：12 字元確定性十六進位 SHA-256 簽章，順序無關。
   - `enumerate_prefill_topics(conn, seed_path)`：
     - 以 `visible_tree_sql(conn)` 限定已核准樹，標題優先順序為：樹 title 欄位 -> 種子主題 title 去除「常見問題」後綴 -> 缺中文標題者記錄略過（不拼湊 slug）。
     - 納入種子中 category 為 general 且無 tree 的主題，以 `visible_faq_sql(conn)` 限定已核准 FAQ 為參考，無已核准資料者不列入。
     - 參考內容全面經 `mask_prices()` 與 `clip_at_sentence(..., 1200)` 處理。
   - `plan_prefill(conn, topics, now, max_topics, regenerate_all)`：
     - 以外部注入之 `now` 與 `FRESHNESS_HOURS - REFRESH_GRACE_HOURS`（22 小時門檻）判定時間過期。
     - 檢查既有列之 `ref_signature` 與 metadata；容錯處理損毀之 metadata。
     - 受保護列（approved/rejected/manual_edit）簽章未變時一律略過並累計 `protected_skipped`。
     - 優先排序：`signature_changed` (0) > `missing_intents` (1) > `time_stale` (2)；同級依最舊生成時間優先。
     - 受 `max_topics` 截斷並精確回報 `backlog` 與 `stale_total`。
2. `tests/test_patient_prefill_plan.py`（全新建立）：
   - Task 1 單元測試：
     - `test_1_intent_templates_structure_and_compliance`：5 大意圖模板結構與四層合規。
     - `test_2_enumerate_prefill_topics_approved_tree_only`：僅列舉已核准決策樹，排除 pending 樹。
     - `test_2b_title_priority_order`：標題優先順序（樹 title -> 種子 title 去後綴 -> 略過無中文標題樹）。
     - `test_3_pending_or_rejected_faq_excluded_from_reference`：pending 或 rejected FAQ 內容絕不進入 reference。
     - `test_5_compute_ref_signature_deterministic`：簽章短雜湊確定性、順序無關與變更敏感性。
   - Task 2 單元測試：
     - `test_task2_1_missing_topic_all_intents_queued`：全新主題 5 意圖全數排入。
     - `test_task2_2_fresh_topic_not_queued`：新鮮主題（10 小時）不排入。
     - `test_task2_3_time_stale_boundary_21_5_vs_22_5_hours`：假時鐘邊界（21.5 小時不排入，22.5 小時排入）。
     - `test_task2_4_signature_changed_priority_over_time_stale`：簽章變更優先於時間過期。
     - `test_task2_5_missing_intents_partial`：部分缺題僅排入缺少的意圖。
     - `test_task2_6_max_topics_truncation_and_backlog`：上限截斷與 backlog 積壓計數。
     - `test_task2_7_rejected_row_protected_until_signature_changes`：rejected 列簽章未變不排入，簽章改變才排入。
     - `test_task2_8_approved_rows_do_not_starve_others`：approved 列簽章未變不排入且不佔名額，簽章改變才排入。
     - `test_task2_8b_manual_edit_protected`：manual_edit 列簽章未變不排入，簽章改變才排入。
     - `test_task2_9_corrupt_metadata_fallback_gracefully`：metadata 損毀容錯處理。
     - `test_task2_10_plan_prefill_is_strictly_read_only`：plan_prefill 嚴格保證唯讀（total_changes 不變）。

## 3. 驗收指令執行結果
- **常數檢查**：
  `grep -n "FRESHNESS_HOURS = 24\|REFRESH_GRACE_HOURS = 2\|PREFILL_TOPIC_PREFIX" src/batch/patient_prefill_plan.py` -> 3 個常數均在。
- **可見性隔離函式**：
  `grep -n "visible_tree_sql\|visible_faq_sql" src/batch/patient_prefill_plan.py` -> 兩者皆有調用。
- **寫入與模型禁詞防護**：
  `grep -v '^#' src/batch/patient_prefill_plan.py | grep -c "INSERT\|UPDATE\|local_llm_call"` -> 輸出 0。
- **時鐘注入規範**：
  `grep -n "def plan_prefill" src/batch/patient_prefill_plan.py` -> 簽章包含 `now: datetime`。
  `grep -v '^#' src/batch/patient_prefill_plan.py | grep -c "datetime.now\|time.time"` -> 輸出 0。
- **Task 1 驗證測試**：
  `uv run pytest tests/test_patient_prefill_plan.py -x -q -k "template or enumerate or signature or price or pending"` -> `6 passed, 10 deselected in 0.62s`。
- **Task 2 全體測試**：
  `uv run pytest tests/test_patient_prefill_plan.py -x -q` -> `16 passed in 0.90s`。
- **隱私守門測試**：
  `uv run pytest -q -p no:cacheprovider tests/test_general_privacy.py` -> `6 passed in 1.30s`。
- **Phase 28 相關迴歸測試**：
  `uv run pytest -q -p no:cacheprovider tests/test_patient_compose.py tests/test_patient_consult.py tests/test_patient_consult_ui.py tests/test_patient_consult_latency.py tests/test_answer_compose.py` -> `48 passed in 1.37s`。
- **正式資料庫保護**：
  `sha256sum clinic.db`：`0b9548af8601c32dd1b884b54e34b3bd6fbc82609b08372c3e9d5212b8626084`，維持不變。
