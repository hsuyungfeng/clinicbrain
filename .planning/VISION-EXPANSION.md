# clinicbrain 願景擴充計畫

> 本文件回應使用者需求：「1. 一般醫療諮詢（使用者半夜自問健康問題）2. 診所專屬資料可上傳 PDF/JPEG/PNG，OCR 辨識、OTC 本地化，進 PageIndex」。
> 記錄目的：把新願景與現有 Phase 01（8-task 計畫）對齊，標出重疊、缺口與技術選型依據，交使用者審閱後才動工。

---

## 1. 現況盤點

### 1.1 clinicbrain 目前狀態（本 repo）
Phase 01「Taiwan PageIndex RAG」8 個任務中，已完成 TASK-001（SQLite schema + seed）、TASK-003（PageIndex 範本 6 筆，手寫）。剩餘：
- TASK-004 LLM prompt 設計
- TASK-005 查詢介面 + 路由
- TASK-006 OTC 本地化層
- TASK-007 診所資料庫整合
- TASK-008 評估測試套件

目前架構：單一 SQLite（`clinic.db`），FTS5 全文檢索用 `trigram` tokenizer（已修正中文分詞問題），無向量資料庫、無 OCR、無文件上傳介面。資料是靜態 seed script 灌入，不支援動態上傳。

### 1.2 舊專案 `DrtoolboxLocalServer`（同一家診所「緻妍」的前一代系統）
本機路徑：`~/Desktop/DrtoolBox/UpdateList/MedicalOderUpdate/` 下有相關 RAG 實驗；完整系統在 GitHub `hsuyungfeng/DrtoolboxLocalServer`。這是一個接近生產環境、功能遠超 clinicbrain 目前範圍的既有系統，**已經實作了使用者這次要的大部分東西**：

| 能力 | 舊系統實作位置 | 技術 |
|---|---|---|
| 一般 vs 診所專屬路由 | `src/agent/hermes_router.py`（AGENTS.md 記載） | 關鍵字意圖分類 → `special`/`general` |
| 文件擷取（PDF/DOCX/PPTX/CSV等） | `src/rag/ingest.py` (`DocumentIngestor`) | PyPDF2 / python-docx / python-pptx，純文字層擷取 |
| **圖片/掃描件 OCR** | `src/agent/hermes_core.py`, `src/data_loader.py`, `src/api/routes/dashboard.py`, `scripts/import_marketing_data.py`（4 處重複實作） | **pytesseract + `lang='chi_tra+eng'`**（Tesseract 繁中+英文語言包） |
| 通用文件轉換（.doc/.odt/.rtf 等冷門格式） | `src/services/anydoc_parser.py` | 包裝 Firecrawl `anydoc` Rust 執行檔，轉 GFM Markdown，100% 本地 |
| PageIndex 臨床推理樹 | `rag.db` 的 `page_index_trees` + `page_index_fts`（AGENTS.md） | SQLite FTS5，欄位與 clinicbrain 的 `page_index_trees` **幾乎完全一致**（pre_op/procedure/post_op_short/maintenance + `*_physician_notes`） |
| 向量檢索（語意相似） | `src/rag/ingest.py`, `src/rag/search.py` | ChromaDB + sentence-transformers (`all-MiniLM-L6-v2`) |
| 醫療知識圖譜 | `src/rag/graph_rag_engine.py` | SQLite 內建 8,800+ 疾病/症狀/藥物關聯 |
| 臨床實體辨識 (NER) | `src/rag/clinical_ner.py` | 純 CPU/ONNX，抽取 DISEASE/DRUG/DOSAGE/FREQUENCY/SYMPTOM |
| OTC 本地化 | `clinic.db` 的 `drugs.otc_name` | 與 clinicbrain 目前做法相同 |
| 本地 LLM 推理 | llama.cpp / Ornith-1.0-9B（雙 GPU 1060+3060），OpenAI 相容 API port 8080 | 完全離線，不依賴雲端 |
| 資料隔離 | `data/documents/special/` vs `data/documents/general/` | 目錄層級區分診所專屬 vs 通用醫學資料 |
| 個資去識別化 | `src/services/privacy_service.py` | 遮蔽身分證、電話、姓名、病歷號，HIPAA Safe Harbor 對標 |
| 紅旗症狀通知 | 員工 LINE 即時推送 | 偵測「流血、劇痛、發燒、呼吸困難」等字眼 |
| 價格防護 | AGENTS.md 明文規則 | 與 clinicbrain 的 CONSTRAINT 幾乎逐字相同 |

**結論：使用者這次提出的「OCR 擷取 + PageIndex」需求，本質上是把舊系統已驗證可行的能力，用更乾淨的架構在 clinicbrain 重新實作一遍**，而不是從零設計。

---

## 2. 落差分析：clinicbrain 現在 vs. 使用者新需求

| 需求 | clinicbrain 現況 | 落差 |
|---|---|---|
| 一般醫療諮詢（使用者半夜自問） | 無查詢介面（TASK-005 尚未開始）；無「使用者對系統」的入口，只有診所端資料 | 需要設計一個不涉及特定診所、不需登入的 general 問答入口；語氣/免責聲明需求（非醫囑，建議就醫）需明確定義 |
| 診所上傳 PDF | 無上傳機制 | 需新增上傳 API/介面 + PDF 文字擷取（可用 PyPDF2，比照舊系統） |
| 診所上傳 JPEG/PNG + OCR | 完全沒有 | 需引入 Tesseract + `chi_tra` 語言包（比照舊系統路徑），新建**單一共用** OCR 模組（避免重蹈舊系統 4 處重複貼碼的問題） |
| OTC 本地化 | 已有 14 種硬編碼成分（TASK-006 待完整化） | 舊系統做法相同（`drugs.otc_name` 硬編碼），可直接沿用現有 clinicbrain 設計，非新工作 |
| PageIndex 生成（超越手寫範本） | 6 筆手寫範本，TASK-004 待設計 LLM prompt | 舊系統沒有明確的「自動化生成」流程說明（AGENTS.md 只提到快取機制，樹本身怎麼生成的細節不明），仍需要 clinicbrain 自己設計 TASK-004 |
| 向量檢索 vs 純 FTS5 | 目前僅 SQLite FTS5（trigram），無向量庫 | 舊系統用 ChromaDB 混合向量 + FTS5。是否要引入向量庫是本計畫的**關鍵技術決策點**（見下節） |

---

## 3. 需要使用者決策的關鍵問題

### 3.1 OCR 引擎選型
舊系統統一用 **Tesseract + `chi_tra` 語言包**，這是最快能沿用的路徑（免額外訓練、有 4 處先例程式碼可參考）。但 Tesseract 對手寫字、低品質掃描件、複雜版面的中文辨識率偏弱。是否要：
- (a) 直接沿用 Tesseract（風險低、開發快，符合舊系統驗證過的路徑）
- (b) 改用更準確但更重的方案（如 PaddleOCR 中文模型，或雲端 OCR API——但雲端會牴觸「隱私優先、100% 本地」的既有原則）

### 3.2 向量檢索要不要引入
目前 clinicbrain 是刻意選擇「無向量庫、純 SQLite FTS5」的路線（這與 PageIndex 官方框架本身「Vectorless RAG」的哲學一致）。但舊系統額外疊加了 ChromaDB 向量檢索作為 fallback。新的「一般醫療諮詢」情境（使用者模糊症狀描述、非結構化提問）用純關鍵字 FTS5 可能召回率不足，向量語意檢索通常在這種場景表現更好。

### 3.3 本地 LLM vs 雲端 API — 已決策
**本地優先，雲端備援。** 預設走 local LLM（隱私優先、不依賴網路），僅當本地服務不可用時才 fallback 到雲端 API。與舊系統 AGENTS.md「所有核心推理必須使用本地運行模型，不依賴雲端 API（除非 local 服務完全不可用時的備援）」原則一致。

待確認：這台機器的 GPU 資源（舊系統用雙 GPU 1060+3060 跑 Ornith-1.0-9B）是否仍可用於 clinicbrain，或需要重新評估本地模型選型（模型大小 vs 現有硬體）。

### 3.4 使用者身份與資料隔離範圍
「一般醫療諮詢」是否完全匿名（不需登入、不留資料），還是也要記錄提問歷史？這會決定要不要做使用者系統、要不要比照舊系統的 `PrivacyService` 做去識別化。

### 3.5 夜間批次作業 — 已決策（兩者都要）
使用者確認夜間自動作業要同時做兩件事：
1. **常見問答預生成**：針對常見疾病/症狀問題，用 LLM 在夜間批次預先生成問答對，寫入資料庫（類似快取層）。使用者白天提問時，系統先查這份預生成庫，有命中就直接回覆，不必每次都即時呼叫 LLM 現場推理——降低回應延遲、節省推理資源。
2. **知識庫維護更新**：批次重建/更新 PageIndex 樹、重新索引新上傳文件，確保白天查詢時資料庫是最新的。

這代表系統需要：
- 一個常見問題/症狀清單的來源（需另外定義：從哪裡取得「常見」的定義——例如可從 general SFT 資料或診所歷史提問統計）
- 一個預生成問答對的儲存表（獨立於 `page_index_trees`，性質更像 FAQ 快取，需要新的 schema 設計）
- 排程機制（cron 或本機排程器）夜間觸發批次生成 + 索引更新
- 查詢時的「先查預生成快取 → 沒中才即時生成」的分流邏輯（這會是 TASK-005 查詢介面設計的一部分，或獨立於 Phase 03）

### 3.6 近期優先事項 — 可更新資料庫設計（降低 token 用量）
使用者明確要求：**在展開 Phase 02-05 之前，先設計一套「可更新」的資料庫架構，目標是減少未來查詢時的 LLM token 消耗**。

核心邏輯：查詢時先讀資料庫既有結構化內容，只有資料庫沒有覆蓋到的問題才需要即時呼叫 LLM——這與 3.5 節的夜間預生成是同一個方向，但優先順序提前，視為 Phase 01 收尾後、Phase 02 本地 LLM 層開工前的銜接工作，而非等到 Phase 04 才做。

具體要落實的設計點：
- `page_index_trees` 目前的更新方式（`seed_trees.py` 手寫 INSERT OR REPLACE）是否要改成支援**增量更新**（新增/修改單一療程樹，而非整批覆寫）
- 是否需要記錄「資料版本」或「最後更新時間」欄位，讓夜間批次知道哪些資料是舊的、需要重新生成
- 常見問答快取表（3.5 節提到的新表）的 schema 需要在這階段先定案，即使夜間生成邏輯本身留到 Phase 04 才做
- 目標效益：白天使用者查詢時，多數常見問題應該命中資料庫而非現場呼叫 LLM，直接降低正式上線後的 API/推理成本

---

## 4. 建議的任務排序（草案，待確認後才展開成正式 GSD phase/plan）

不建議把這些新增範圍硬塞進現有 Phase 01（會混淆任務邊界，且原 8 個任務本身還沒做完）。建議：

1. **先完成 Phase 01 剩餘任務**（TASK-004 ~ TASK-008），讓現有 PageIndex + 查詢路由基礎穩固。TASK-004（LLM prompt 設計）現在也是本地 LLM 推理層的第一個實際串接點，順序上更合理先做。
2. **新開 Phase 02：本地 LLM 推理層**
   - 評估本地模型選型與現有硬體資源（3.3 節待確認的 GPU 狀況）
   - 建立本地 LLM 服務介面（OpenAI 相容 API，比照舊系統 port 8080 模式）+ 雲端 API fallback 邏輯
   - 這是 Phase 03、04 都會依賴的共用基礎設施，須先於它們完成
3. **新開 Phase 03：文件擷取管線**
   - OCR 模組（Tesseract + chi_tra，單一共用模組，非舊系統的 4 處重複實作）
   - PDF/DOCX 文字擷取（可直接參考舊系統 `ingest.py` 的 `_parse_pdf`/`_parse_docx` 邏輯，精簡移植）
   - 上傳 API/介面（診所端操作）
   - 擷取結果 → PageIndex 生成管線串接（呼叫 Phase 02 的本地 LLM + TASK-004 的 prompt）
4. **新開 Phase 04：一般醫療諮詢入口 + 夜間批次生成**
   - 定義 general 路由的免責聲明與安全邊界（例如紅旗症狀偵測，比照舊系統）
   - 決定是否需要向量檢索補強 FTS5 的召回率（3.2 節的決策）
   - 常見問答預生成 schema 設計 + 夜間排程機制（3.5 節）
   - 查詢時「預生成快取優先、未命中才即時生成」的分流邏輯
   - 使用者介面（可能是簡單 Web 表單或 API）
5. **新開 Phase 05：doctor-toolbox.com 官方 API 整合**
   - 排在 clinicbrain 自身功能（Phase 01-04）完成之後
   - 範圍：呼叫官方 API 做資料**雙向匯入/匯出**（非 MITM 攔截方式——與舊系統 `DrtoolboxLocalServer` 的 mitmproxy 攔截手法不同，改用正式 API 合約）
   - 待釐清：官方 API 文件/認證方式、匯入/匯出的具體資料範疇（病歷？SOAP 記錄？預約？）需另外調查

---

## 5. 決策狀態

- [x] 3.3 本地 LLM vs 雲端 API — **本地優先，雲端備援**
- [x] 3.5 夜間批次作業範圍 — **常見問答預生成 + 知識庫維護更新，兩者都要**
- [x] 3.6 近期優先事項 — **先做可更新資料庫設計，目標降低未來 token 用量，順序提前到 Phase 01 收尾與 Phase 02 之間**
- [x] doctor-toolbox.com 整合方式 — **官方 API，雙向匯入/匯出，排在 Phase 05（clinicbrain 自身功能完成後）**
- [ ] 3.1 OCR 引擎選型 — 待確認（建議先沿用 Tesseract + chi_tra，有舊系統先例）
- [ ] 3.2 向量檢索要不要引入 — 待確認
- [ ] 3.4 使用者身份與資料隔離範圍 — 待確認
- [x] GPU/硬體資源確認 — **已盤點（2026-09-21）**：GTX 1060 6GB（閒置）+ RTX 2080 Ti 22GB（已被既有 `llama-server` 占用 17GB，跑 Qwen3.8-27B）。**機器上已有運行中的本地 LLM 服務**，不需重新部署，詳見 `.planning/phases/02-local-llm-layer/PLAN.md`。發現該模型對政治敏感問題會輸出中國官方立場內容，已決策：繼續用此服務，靠 prompt+驗證層防禦。
- [ ] doctor-toolbox.com 官方 API 文件、認證方式、匯入/匯出資料範疇 — 待調查

## 6. 下一步

這份文件是盤點與選項整理，尚未是可執行計畫。建議使用者針對第 5 節剩餘的 3 個問題給方向後，再由我（或 `/gsd-new-milestone`、`/gsd-phase` 等 GSD 指令）展開成正式的 phase 定義與 PLAN.md。
