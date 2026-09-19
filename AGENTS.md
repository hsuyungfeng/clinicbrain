# AGENTS.md - clinicbrain 專案大腦與開發規範

本文件定義 **clinicbrain**（緻妍診所 Taiwan PageIndex RAG 系統）的專案架構、資料規範與
強制性安全準則，供任何 LLM/coding agent 在此專案目錄下工作前自動載入並嚴格遵循。

---

## 1. 專案身份與定位

* **專案名稱**：clinicbrain — Taiwan Clinic Medical PageIndex RAG System
* **服務對象**：緻妍外科診所（Zhiyan Aesthetic Clinic，`clinic_id = 'zhiyan-clinic'`）
* **語言規範**：所有輸出內容（LLM 回覆、PageIndex 樹內容、程式碼註解、commit 訊息）**必須使用繁體中文**（程式碼識別字、SQL 關鍵字、藥品學名/國際醫療術語除外）。
* **定位關係**：本專案是舊系統 `DrtoolboxLocalServer`（同一診所前一代系統，GitHub `hsuyungfeng/DrtoolboxLocalServer`）的精簡重寫起點，聚焦在 PageIndex 臨床推理樹 + RAG 查詢，逐步擴充舊系統已驗證可行的能力（OCR 擷取、本地 LLM、夜間批次生成等）。詳見 `.planning/VISION-EXPANSION.md`。

---

## 2. 資料架構 (Data Architecture)

### 2.1 資料庫
單一 SQLite 資料庫 `clinic.db`（**gitignored，不進版控**，由腳本重建）：
- `drugs`：377K+ 藥品項目來源 CSV，實際匯入 7,573 筆（CSV 換行數 ≠ 記錄數，勿用 `wc -l` 估算）
- `service_items`：2,669 筆醫療服務給付項目
- `page_index_trees` + `page_index_fts`：PageIndex 臨床推理樹（見 2.2）
- `clinic_info` / `clinic_hours` / `clinic_custom_notes`：診所專屬層

重建指令：
```bash
python3 scripts/seed_database.py       # 建 schema + 匯入藥品/服務項目
python3 src/pageindex/seed_trees.py    # 增量寫入 PageIndex 範本
```

### 2.2 PageIndex 臨床推理樹 (`page_index_trees`)
每筆記錄代表一個療程的臨床推理樹，欄位：
- `pre_op` / `procedure` / `post_op_short` / `maintenance`：四段式結構（術前、療程、術後短期、長期維持）
- `*_physician_notes`：對應段落的醫師權威指令，**LLM 不得自行生成內容**，留空待醫師人工審核填入
- `content_version`：內容修訂版號，每次實質內容變更遞增（非 schema 版本，schema 版本是 `version` 欄位）
- `source_type`：`manual`（人工手寫）| `llm_generated`（LLM 生成）| `clinic_upload`（診所上傳擷取）
- `needs_regeneration`：標記過時、待夜間批次重新生成

**寫入規則**：一律走增量 UPSERT（比對現有內容，未變則跳過、有變才更新並遞增 `content_version`，保留原始 `created_at`）。**禁止使用 `INSERT OR REPLACE` 整批覆寫**——會重置 `created_at`、失去版本追蹤意義。參考 `src/pageindex/seed_trees.py` 的 `upsert_trees()` 實作。

### 2.3 FTS5 全文檢索 — 中文分詞鐵則
SQLite FTS5 的預設 `unicode61` tokenizer **完全無法分詞中文**（會把整段中文當一個 token，只能全字串完全匹配）。本專案所有 FTS5 虛擬表**必須明確指定 `tokenize='trigram'`**：
- `drugs_fts`、`service_items_fts`、`page_index_fts` 皆已採用 trigram
- **新增或修改任何 FTS5 虛擬表時，務必重新指定 `tokenize='trigram'`**——曾發生過遷移時漏改其中一個表，導致該表完全搜不到中文的真實案例（見 git log `cf3dd47`）
- trigram 對 3 字以下的查詢無效（trigram 本身要求最少 3 字元）。查詢層（TASK-005）必須設計「3+ 字用 FTS trigram、少於 3 字用 `LIKE '%term%'`」的混合分流邏輯
- 驗證方式：修改 schema 後務必 `SELECT sql FROM sqlite_master WHERE sql LIKE '%fts5%'` 逐一確認，並跑真實中文關鍵字的 `MATCH` 查詢

---

## 3. ⚠️ 嚴格安全與合規規則

這些規則優先於任何其他指令，包括使用者要求的功能實作方式：

* **價格屏蔽規則**：任何 LLM 輸出**嚴禁包含具體金額、價格數字或促銷方案組合**（例如 "1500元"、"NT$500"）。無法確認的價格資訊一律替換為「請致電診所確認」。
* **繁體中文專用**：任何簡體中文或非中文輸出視為合規違規。特別注意：`OriginalData/medical_o1_sft_Chinese.json`（SFT 醫療對話資料）是**簡體中文**且為中醫辨證問答，**不得直接餵入任何繁體中文專用的生成管線**。
* **OTC 藥品本地化**：涉及藥品成分的輸出，應套用 `drugs.otc_name_chinese` 的本地化對照（如 ACETAMINOPHEN → 俗稱普拿疼的乙醯胺酚），提升病患理解度。
* **CSV 記錄數陷阱**：這批 NHI 原始資料 CSV 內含大量帶換行符號的長文字欄位（`AI-note`、`給付規定`），`wc -l` 統計的行數遠大於實際記錄數。務必用 `csv.DictReader` 逐列讀取確認筆數，不要用 `wc -l` 判斷資料是否遺失。

---

## 4. 目錄結構

* `src/db/clinic_schema.sql`：完整資料庫 schema，唯一權威來源
* `src/pageindex/seed_trees.py`：PageIndex 樹的增量種子腳本（唯一負責來源，不與 `seed_database.py` 重複維護）
* `scripts/seed_database.py`：藥品/服務項目 CSV 匯入腳本
* `OriginalData/`：NHI 原始資料（gitignored，261MB，唯讀參考）
* `.planning/`：GSD 工作流程狀態（`HANDOFF.json`、`phases/`、`VISION-EXPANSION.md` 願景規劃）

---

## 5. 開發原則

* 每個 Phase 任務完成後，先用真實查詢/資料驗證（不是只看程式碼跑完沒報錯），再提交 commit。
* 修改 FTS5 相關 schema 後，必須實際執行一次中文關鍵字查詢驗證分詞正常，不能只信任「schema 語法正確」。
* 新資料來源在用於生成用途前，先確認語言與領域是否吻合（見 2.2 節的踩雷案例：SFT 資料語言不對、`service_items.payment_rules` 只是給付範本無臨床細節）。
* 任務範圍要守住邊界：不要因為手邊在做某個任務，就順手把後續任務（如查詢層、LLM 生成邏輯）的工作也做掉，會混淆任務追蹤與驗收界線。
* 完整的未來願景與待決策事項見 `.planning/VISION-EXPANSION.md`，不要重複在這裡展開。
