# clinicbrain — Taiwan Clinic Medical PageIndex RAG System
> 緻妍外科診所（健保特約代碼：`3503190424`）Taiwan PageIndex 臨床決策樹、衛教問答與健保醫療知識庫系統。

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141+-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/SQLite-FTS5%20trigram-003B57.svg)](https://sqlite.org/)
[![License](https://img.shields.io/badge/License-Proprietary-red.svg)]()
[![Tests](https://img.shields.io/badge/Tests-132%20passed-brightgreen.svg)]()

---

## 📖 專案簡介 (Overview)

`clinicbrain` 是專為台灣基層診所設計的高精準度、低延遲、隱私優先（純本地推理）臨床衛教與健保給付檢索系統。

有別於傳統將整份長文切塊（Chunking）後做向量相似度搜尋的傳統 RAG 痛點，本系統採用 **PageIndex 臨床推理樹** 架構，將各療程拆解為標準「四段式結構」，並融合台灣健保 7,573 筆藥品與 2,669 筆醫療服務項目。同時提供現代化的 **FastAPI 服務層** 與對接 `doctor-toolbox.com`（或院所 HIS/EHR）之官方雙向同步契約。

---

## 🌟 核心特色 (Core Features)

1. **四段式 PageIndex 臨床決策樹 (`page_index_trees`)**
   - 將各項微創手術與美容醫學療程標準化為：`術前評估 (pre_op)`、`療程步驟 (procedure)`、`術後短期照護 (post_op_short)` 與 `長期維持追蹤 (maintenance)`。
   - 每段落保留醫師權威指令（`physician_notes`），未經醫師審定前 LLM 不得擅自生成。
   - 採增量 UPSERT 機制與實質修訂版號（`content_version`）。

2. **台灣健保局開放資料整合 (NHI Open Data)**
   - 完整收錄 7,573 筆藥品（含健保支付價、給付規定、成分規格）與 2,669 筆醫療服務給付項目點數。
   - **OTC 常用學名在地化對照**：收錄 68 種常見成分（如將 ACETAMINOPHEN 本地化顯示為俗稱普拿疼的乙醯胺酚），大幅提升醫病衛教溝通理解度。

3. **中文 FTS5 Trigram 全文檢索與混合分流**
   - 徹底解決 SQLite FTS5 預設 `unicode61` 無法分詞中文之問題，全虛擬表統一採用 `tokenize='trigram'`。
   - 查詢層實作長度分流：3 字以上走 FTS5 倒排索引，少於 3 字走 `LIKE '%term%'` 容錯，兼顧速度與召回率。

4. **文件自動擷取與 FAQ 快取 (`faq_cache`)**
   - 支援診所 `.docx`、`.xlsx` 營運衛教文件批次解析與 opencc (`s2twp`) 繁簡轉換。
   - 由本地 LLM 提煉標準問答對（40 筆已審定之門診手術與保險理賠真實 FAQ），提供即時問答快取服務。

5. **多診所健保機構代碼架構 (Multi-Clinic Support)**
   - 全面以台灣衛福部「健保特約醫事機構代碼」（緻妍外科診所 `3503190424`）進行多診所隔離。
   - 查詢入口自動根據語意分流：
     - `special`（診所特定療程/門診資訊/自訂備註）：強制驗證診所權限。
     - `general`（通用健保藥品/給付點數查詢）：完全公開無洩漏風險。

6. **FastAPI HTTP 服務層與 doctor-toolbox.com 雙向同步契約**
   - 徹底捨棄舊系統 mitmproxy 攔截手法，採用標準強型別 RESTful API（Pydantic v2 + OpenAPI 3.1）。
   - 查詢連線強制 `PRAGMA query_only = ON;`，杜絕任何查詢注入或修改風險。
   - 官方雙向同步契約：支援 `since_version` 增量匯出，匯入時經嚴格單一權威路徑寫入並記錄 `sync_logs`。

7. **嚴格醫療法規防禦**
   - **絕對價格遮蔽 (Price Masking)**：所有對外輸出一律執行 `mask_prices()`，自動替換具體金額促銷數字為「`[請致電診所確認]`」，防止觸犯醫療廣告法規。
   - **全繁體中文原則**：杜絕非繁體中文輸出。
   - **中立立場雙層過濾**：本地 LLM Prompt 與驗證器雙重防禦過濾政治敏感立場言論。

---

## 🏗️ 系統架構 (Architecture)

```text
clinicbrain/
├── src/
│   ├── api/                  # FastAPI 服務層 (app, config, routes, models)
│   ├── clinic/               # 診所專屬層 (custom_notes)
│   ├── db/                   # 資料庫 Schema (clinic_schema.sql, otc_mappings.json)
│   ├── ingestion/            # 文件擷取與 FAQ 生成管線
│   ├── pageindex/            # PageIndex 推理樹、LLM 客戶端、db_writer, faq_writer
│   └── query/                # 查詢路由 (router.py: handle_query, search.py)
├── scripts/                  # 建庫種子、遷移腳本與服務啟動器
├── tests/                    # 完整自動化測試套件 (132+ tests, 100% 通過)
├── .planning/                # GSD 專案規劃追蹤 (PROJECT.md, ROADMAP.md, STATE.md)
├── AGENTS.md                 # 專案大腦開發規範與安全鐵則
└── clinic.db                 # SQLite 主資料庫 (gitignored, 依腳本重建)
```

---

## 🚀 快速開始 (Quick Start)

### 1. 環境安裝
```bash
# 需求：Python 3.12+
pip install fastapi uvicorn pydantic httpx pytest opencc python-docx openpyxl
```

### 2. 資料庫建庫與種子匯入
```bash
# 1. 建立 schema + 匯入藥品/服務項目 + 診所資訊與自訂備註
python3 scripts/seed_database.py

# 2. 增量寫入 6 筆 PageIndex 臨床推理樹範本
python3 src/pageindex/seed_trees.py
```

### 3. 執行測試套件
本專案堅持測試資料庫 **100% 隔離原則**（測試過程使用記憶體/暫存複本，保證正式 `clinic.db` SHA-256 零污染）：
```bash
pytest -k "not test_check_llm_health_live"
# 132 passed
```

### 4. 啟動 API 伺服器
```bash
python3 -c "import uvicorn; from src.api.app import app; uvicorn.run(app, host='127.0.0.1', port=8000)"
```
啟動後可開啟瀏覽器檢視 Interactive API Docs：
- Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- 健康檢查端點: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

---

## 📡 API 介面範例

### 統一自然語言查詢 (`POST /api/v1/query`)

```bash
curl -X POST http://127.0.0.1:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "請問音波拉提術後要怎麼照顧？",
    "clinic_id": "3503190424",
    "limit": 5
  }'
```

---

## 🔒 授權與宣告 (License & Compliance)
本專案為緻妍外科診所內部醫療決策支援與知識庫系統。醫療資訊依據台灣衛生福利部與中央健康保險署公開法規標準，輸出皆已遮蔽價格並符合醫療法規範。
