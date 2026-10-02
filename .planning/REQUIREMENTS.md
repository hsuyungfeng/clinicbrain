# Requirements — Milestone v1.2 診所資料優先與一般疾病簡易資訊

> 目標：診所自己提供的資料永遠優先被查；一般問題則有本地 LLM 生成、經醫師審核的疾病簡易資訊可答。
> 所有需求須遵守 AGENTS.md 第 3 節（價格屏蔽、繁體中文、單一權威寫入路徑）。
> 前一里程碑 v1.1 歸檔於 `.planning/milestones/`，其技術債見 `v1.1-MILESTONE-AUDIT.md`。

## v1.2 Requirements

### CLINIC-FIRST 診所資料優先
- [ ] **CF-01**：有 `clinic_id` 時，一律先檢索該診所自己的 special FAQ，不受 `classify` 的 special/general 關鍵字分流限制（解決 16/40 FAQ 被誤分流、短路命中率上限約 60%）
- [ ] **CF-02**：診所資料未命中時才退到「已審核」的 general 內容；回應標示資料層級（clinic / general），避免把一般衛教當成診所意見
- [ ] **CF-03**：保留既有安全檢查（風險特徵、歧義邊界、價格遮蔽、審核閘門）；營運資訊關鍵字仍走營運路由；既有測試不回歸

### GENERAL-CONTENT 一般疾病簡易資訊（本地 LLM 生成）
- [ ] **GC-01**：擴充疾病種子清單（這是什麼／常見症狀／何時就醫／日常照護），問題由人撰寫，載入時通過四層檢查，問題文字須經使用者審閱
- [ ] **GC-02**：提示詞禁止具體用藥劑量與處方建議；驗證器新增攔截層（v1.1 驗證器無此層）
- [ ] **GC-03**：每筆答案必含「何時該就醫」警訊段落，驗證器檢查；一律附免責聲明
- [ ] **GC-04**：改善審核工具 `review_faq`（依主題批次檢視、顯示生成來源與驗證結果）。生成結果一律 `pending`，經使用者核准才上線（沿用 v1.1 審核閘門）

### DEBT 技術債清理
- [ ] **DEBT-01**：`migrate_faq_review_status` 的 ALTER 改由 schema 擷取，不再與 `clinic_schema.sql` 雙寫
- [ ] **DEBT-02**：`config.default_clinic_id` 孤兒設定——接線成真正後備或移除，並對齊 AGENTS.md 2.6
- [ ] **DEBT-03**：駁回題目可由人明確觸發重新生成（預設仍不自動重生成，避免被駁回內容自行回流）
- [ ] **DEBT-04**：批次對真實 LLM 的完整實跑驗證，僅在資料庫複本上進行（不碰正式庫），需 `llama-server` 空閒

## Future Requirements（延後）
- 健保給付規定類問答（審查注意事項，需加註「以健保署公告為準」、記錄規則日期、走審核閘門）
- 紅旗詞表殘餘漏報增補（詞表增修須使用者審閱）
- CF-04：推理樹與診所備註也納入優先檢索
- AUTH-03（EnvironmentFile）、AUTH-04（常數時間比對）、應用層速率限制
- 2~3 字滑動窗改善 `extract_search_terms`

## Out of Scope
- 簡體 `OriginalData/medical_o1_sft_Chinese.json`（中醫辨證，不得餵入繁中管線）
- 英文 ICD-10 `.ods`（無中文疾病名與衛教內容）
- 「健保相關」目錄的審查注意事項不可直接當疾病衛教來源（內容為給付審查規則，面向院所）

## 設計注意
- CF-01 改的是檢索順序；Phase 7 的短路安全檢查（覆蓋率、風險特徵）原本針對診所自己的 FAQ 校準，納入更多候選後必須由 CF-03 守門並補回歸測試。
- GC-02 是新風險面：v1.1 四層驗證器（價格／簡體／政治／保證療效）不攔截用藥劑量與處方。
- 本里程碑不涉及正式庫 schema 變更之外的資料遷移；任何對正式庫的寫入仍由使用者手動執行。

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DEBT-01 | Phase 10 | Pending |
| DEBT-02 | Phase 10 | Pending |
| CF-01 | Phase 11 | Pending |
| CF-02 | Phase 11 | Pending |
| CF-03 | Phase 11 | Pending |
| GC-01 | Phase 12 | Pending |
| GC-02 | Phase 12 | Pending |
| GC-03 | Phase 12 | Pending |
| GC-04 | Phase 12 | Pending |
| DEBT-03 | Phase 12 | Pending |
| DEBT-04 | Phase 13 | Pending |

涵蓋：11/11（無孤立、無重複）
