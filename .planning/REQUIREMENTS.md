# Requirements — Milestone v1.1 上線就緒與成本優化

> 目標：把 v1.0 的 API 安全上線，並讓常見問題不必每次都呼叫 LLM。
> 所有需求須遵守 AGENTS.md 第 3 節（價格屏蔽、繁體中文、單一權威寫入路徑）。

## v1.1 Requirements

### AUTH 認證
- [ ] **AUTH-01**：未設定 `CLINICBRAIN_ADMIN_API_KEY` 時服務拒絕啟動（提供明確旗標供本機開發關閉，啟動時印出繁體中文警告）。同步端點已掛 `verify_admin_key`，強制金鑰後自動受保護。

### CACHE 快取優先
- [ ] **CACHE-01**：`handle_query` 已會檢索 `faq_cache`；改為高信心 FAQ 命中時短路回答（直接回 FAQ 原文，不再附帶大量樹狀資料）。查詢路徑維持純檢索，不引入 LLM 合成
- [ ] **CACHE-02**：回應標示來源欄位（`cache` / `pageindex` / `llm`）
- [ ] **CACHE-03**：記錄命中/未命中次數（不存問句全文與個資，僅聚合計數或 topic_key）
- [ ] **CACHE-04**：快取命中的回答一律經 `deep_mask_prices()`，不得因走捷徑而繞過

### BATCH 夜間批次
- [ ] **BATCH-01**：依常見問題清單預生成 FAQ，經 `upsert_faqs` 寫入（`source_type='llm_generated'`），且通過四層驗證器
- [ ] **BATCH-02**：重建 `needs_regeneration=1` 的樹，經 `generate_tree` 驗證，不動 `*_physician_notes` 欄位
- [ ] **BATCH-03**：systemd timer 排程，含 dry-run 模式、執行日誌、LLM 不可用時優雅跳過
- [ ] **BATCH-04**：常見問題來源 = CACHE-03 未命中統計 + 手動清單（不使用簡體 SFT 資料）

### GENERAL 一般諮詢
- [ ] **GENERAL-01**：general 回答一律附繁體中文免責聲明（非醫囑、建議就醫）
- [ ] **GENERAL-02**：紅旗症狀偵測，命中時不走 LLM，直接回固定就醫提示
- [ ] **GENERAL-03**：匿名，不記錄問句全文與個資、不留提問歷史
- [ ] **GENERAL-04**：不綁診所的獨立端點，不需 `clinic_id`，只查 general 類資料

## Future Requirements（延後）
- AUTH-02 寫入/同步端點金鑰驗證（已由既有 `verify_admin_key` 涵蓋）
- AUTH-03 systemd `EnvironmentFile` 帶金鑰（權限 600），避免金鑰明文寫入 unit 檔
- AUTH-04 金鑰比對改用 `secrets.compare_digest`

## Out of Scope
- 向量檢索（VISION 3.2 維持純 FTS5，PageIndex 的 Vectorless 哲學）
- 圖片 OCR（Phase 03 Stage 2 已結案）

## 設計注意
- 2026-09-30 發現：查詢路徑（`handle_query`）本來就不呼叫 LLM，v1.1 決定維持純檢索（零幻覺、零價格洩漏風險）。「降低 token」在此架構下不適用，CACHE 的價值是回答精準度與命中率量測，BATCH 預生成的價值是擴充可檢索內容。若未來要引入 LLM 合成回答，另開里程碑。
- CACHE-03 與 GENERAL-03 有張力：只可存聚合計數/topic_key，不可存問句原文。BATCH-04 的「未命中來源」需在規劃時設計成不含個資的形式。

- **已決策（2026-09-30）**：CACHE-03 未命中統計只累加 `handle_query` 已比對到的路由關鍵字（來自固定詞表）的計數，不存問句原文、不推測 topic_key。代價：只知主題熱度，不知具體問法。BATCH-04 的自動來源因此是「熱門關鍵字」，需搭配手動清單。
- **已決策（2026-10-01，Phase 9）**：
  - 夜間批次以 LLM 預生成的 FAQ **寫入但預設不啟用**：需新增審核狀態（如 `review_status`），`source_type='llm_generated'` 預設 pending，**查詢檢索與快取短路只使用已審核（或手寫/診所上傳）內容**，確保未經醫師審核的 LLM 內容不會被當成權威答案回覆。此點需小幅修改 Phase 7 已完成的 FAQ 檢索（`search_faq_cache` 與短路候選集）。
  - BATCH-02 的 `needs_regeneration` 目前只有清除、沒有任何設為 1 的程式：由**手動標記工具**觸發，批次只處理已標記的樹，不做自動時間判斷；重建一律不得動 `*_physician_notes`。
  - ROADMAP 成功標準 1 的「topic_key」依 Phase 7 決策應讀為「路由關鍵字」：需定義關鍵字到可生成主題的對應規則（搭配手動清單）。

## Traceability
| Requirement | Phase | Status |
|-------------|-------|--------|
| AUTH-01 | Phase 6 | Pending |
| CACHE-01 | Phase 7 | Pending |
| CACHE-02 | Phase 7 | Pending |
| CACHE-03 | Phase 7 | Pending |
| CACHE-04 | Phase 7 | Pending |
| GENERAL-01 | Phase 8 | Pending |
| GENERAL-02 | Phase 8 | Pending |
| GENERAL-03 | Phase 8 | Pending |
| GENERAL-04 | Phase 8 | Pending |
| BATCH-01 | Phase 9 | Pending |
| BATCH-02 | Phase 9 | Pending |
| BATCH-03 | Phase 9 | Pending |
| BATCH-04 | Phase 9 | Pending |

涵蓋：13/13 條 v1.1 需求皆已對應唯一 phase（Future Requirements 的 AUTH-02~04 不在本里程碑）。
