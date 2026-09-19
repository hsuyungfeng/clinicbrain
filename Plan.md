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

## 2. Phase 01：Taiwan PageIndex RAG（進行中）

8 個任務，目前進度：

| # | 任務 | 狀態 | 備註 |
|---|---|---|---|
| TASK-001 | SQLite schema + seed from OriginalData | ✅ 完成 (`0ac396d`) | 7,573 藥品 + 2,669 服務項目；FTS5 改用 trigram |
| TASK-003 | PageIndex schema + tree generation | ✅ 完成 (`cf3dd47`) | 6 筆手寫繁中範本；修復 `page_index_fts` 遺漏的 trigram |
| — | page_index_trees 增量更新設計 | ✅ 完成 (`f59af48`) | `content_version`/`source_type`/`needs_regeneration`，見 AGENTS.md 2.2 節 |
| TASK-004 | LLM prompt 設計（生成臨床推理樹） | ⬜ 未開始 | 用現有 6 筆範本作 few-shot 品質基準 |
| TASK-005 | 查詢介面 + special/general 路由 | ⬜ 未開始 | 需含 FTS trigram 的 3 字元以下 LIKE fallback |
| TASK-006 | OTC 本地化層完整化 | ⬜ 未開始 | 目前僅 14 種硬編碼成分，456/7,573 筆命中 |
| TASK-007 | 診所資料庫整合 | ⬜ 未開始 | |
| TASK-008 | 評估測試套件（50+ 查詢） | ⬜ 未開始 | |

**確切執行狀態**（哪個任務做到哪一步、當前 blocker）請讀 `.planning/HANDOFF.json`——這份文件才是即時真相來源，本表格只是概覽,可能落後於實際進度。

---

## 3. Phase 01 之後：願景擴充（已規劃，未展開為正式 phase）

使用者確認的方向（完整討論見 `.planning/VISION-EXPANSION.md`）：

- **Phase 02（建議）：本地 LLM 推理層** — 本地優先、雲端 API 備援。待確認機器 GPU 資源。
- **Phase 03（建議）：文件擷取管線** — 診所上傳 PDF/JPEG/PNG，OCR（建議沿用 Tesseract + `chi_tra`，舊系統 `DrtoolboxLocalServer` 已驗證此路徑）+ PDF/DOCX 文字擷取 → 餵入 PageIndex 生成管線。
- **Phase 04（建議）：一般醫療諮詢入口 + 夜間批次生成** — 使用者半夜自問健康問題的匿名/一般入口；夜間批次用 LLM 預生成常見問答存資料庫（降低白天即時 LLM 呼叫的 token 成本，是查詢時「先查資料庫、沒中才即時生成」的分流邏輯的前提）；同時批次維護/更新 PageIndex 索引。
- **Phase 05（建議）：doctor-toolbox.com 官方 API 整合** — 雙向資料匯入/匯出，走正式 API（非舊系統的 MITM 攔截方式），排在 clinicbrain 自身功能完成之後。

**尚待決策**（見 VISION-EXPANSION.md 第 5 節）：OCR 引擎最終選型、要不要引入向量檢索補強 FTS5 召回率、使用者身份與資料隔離範圍（匿名 vs 留歷史）、doctor-toolbox.com API 文件與認證方式。

---

## 4. 重要背景與教訓（避免重蹈覆轍）

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

## 5. 如何恢復工作

```
/gsd-resume-work
```
會自動讀取 `.planning/HANDOFF.json` 與對應 phase 的 `.continue-here.md`，還原完整上下文、
待辦事項、已知 blocker。這份 Plan.md 是靜態總覽，不會即時更新每個 session 的進度細節。
