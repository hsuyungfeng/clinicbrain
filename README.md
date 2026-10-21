# clinicbrain — Taiwan Clinic Medical PageIndex RAG System
> 緻妍外科診所（健保特約代碼：`3503190424`）Taiwan PageIndex 臨床決策樹、衛教問答與健保醫療知識庫系統。

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141+-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/SQLite-FTS5%20trigram-003B57.svg)](https://sqlite.org/)
[![License](https://img.shields.io/badge/License-Proprietary-red.svg)]()
[![Tests](https://img.shields.io/badge/Tests-167%20passed-brightgreen.svg)]()

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

2. **專科解剖動作與病理修復動態動畫卡 2.0 (`visual_engine.js`, Phase 32 & 33)**
   - 徹底告別傳統靜態圖表與文字，100% 依據臨床文本意圖以純數學向量 Code 渲染 60fps 動態向量卡片。
   - **場景 1 外科動作 DSL (`surgical_action`)**：骨骼滑移重塑（0~15mm）、純鈦板釘剛性旋入固定、神經保護光暈、深層拉皮懸吊與馬甲縫合。
   - **場景 2 專科病理對照 (`contrast`)**：體雕超音波乳化 vs 粗鈍撕裂、無痕眼袋內切 vs 疤痕外翻、自體軟骨三角架 vs 矽膠壓迫穿出、雙平面水滴 vs 包膜攣縮球、微滴散佈 vs 結節硬塊。
   - **場景 3 活體修復歷程與動態看板 (`timeline`)**：三階段動態色彩徽章（`【階段一·初期防護】` ➔ `【階段二·修復重塑】` ➔ `【階段三·穩定隱痕】`）、即時專科動態解說文字切換、骨骼剛性癒合、退瘀色譜代謝、疤痕隱痕平整、神經軸突萌芽與組織回縮貼合。

3. **診所核准即自動昇華一般醫學機制 (`src/visual/auto_promotion.py`, Phase 32)**
   - 各診所醫師審核通過特定療程動畫資產後，系統自動去除診所私有特異資訊，無損昇華複製進入一般醫學庫（`clinic_id = NULL`）。全院跨診所與匿名病患諮詢立即可查，徹底免除人工二次核准負擔。

4. **Local LLM 批次生成與 Hermes 自治監控 (`clinic-visual-batch`)**
   - 驅動本地離線大模型（Qwen3.8-27B-FP8 @ localhost:8080）自 49 筆已核准推理樹自動提煉 3 幕受約束 Typed IR，由 Hermes Agent 全程守護、錯誤自癒重試與 Playwright 無頭渲染驗證。

5. **台灣健保局開放資料整合 (NHI Open Data)**
   - 完整收錄 7,573 筆藥品（含健保支付價、給付規定、成分規格）與 2,669 筆醫療服務給付項目點數。
   - **OTC 常用學名在地化對照**：收錄 68 種常見成分（如將 ACETAMINOPHEN 本地化顯示為俗稱普拿疼的乙醯胺酚），大幅提升醫病衛教溝通理解度。

6. **中文 FTS5 Trigram 全文檢索與混合分流**
   - 徹底解決 SQLite FTS5 預設 `unicode61` 無法分詞中文之問題，全虛擬表統一採用 `tokenize='trigram'`。
   - 查詢層實作長度分流：3 字以上走 FTS5 倒排索引，少於 3 字走 `LIKE '%term%'` 容錯，兼顧速度與召回率。

7. **文件自動擷取與 FAQ 快取 (`faq_cache`)**
   - 支援診所 `.docx`、`.xlsx` 營運衛教文件批次解析與 opencc (`s2twp`) 繁簡轉換。
   - 由本地 LLM 提煉標準問答對（40 筆已審定之門診手術與保險理賠真實 FAQ），提供即時問答快取服務。

8. **多診所健保機構代碼架構 (Multi-Clinic Support)**
   - 全面以台灣衛福部「健保特約醫事機構代碼」（緻妍外科診所 `3503190424`）進行多診所隔離。
   - 查詢入口自動根據語意分流：
     - `special`（診所特定療程/門診資訊/自訂備註）：強制驗證診所權限。
     - `general`（通用健保藥品/給付點數查詢）：完全公開無洩漏風險。

9. **FastAPI HTTP 服務層與 doctor-toolbox.com 雙向同步契約**
   - 徹底捨棄舊系統 mitmproxy 攔截手法，採用標準強型別 RESTful API（Pydantic v2 + OpenAPI 3.1）。
   - 查詢連線強制 `PRAGMA query_only = ON;`，杜絕任何查詢注入或修改風險。
   - 官方雙向同步契約：支援 `since_version` 增量匯出，匯入時經嚴格單一權威路徑寫入並記錄 `sync_logs`。

10. **嚴格醫療法規防禦**
    - **絕對價格遮蔽 (Price Masking)**：所有對外輸出一律執行 `mask_prices()`，自動替換具體金額促銷數字為「`[請致電診所確認]`」，防止觸犯醫療廣告法規。
    - **全繁體中文原則**：杜絕非繁體中文輸出。
    - **中立立場雙層過濾**：本地 LLM Prompt 與驗證器雙重防禦過濾政治敏感立場言論。

11. **臨床 Web App 管理中心與待簽核動畫分頁**
    - 支援拖曳上傳診所 `.docx`、`.xlsx`、`.pdf` 文件，自動解析並去識別化轉化為待審衛教草稿。
    - 視覺化醫師簽核儀表板：支援全選／反選、批量核准／駁回、單題內聯編輯、臨床推理樹簽核，以及專屬「🎬 待簽核動畫」即時預覽與簽核發布。

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
│   ├── visual/               # 視覺解說卡核心 (auto_promotion, blueprints, autodraft, ir, writer)
│   └── query/                # 查詢路由 (router.py: handle_query, search.py)
├── scripts/                  # 建庫種子、遷移腳本、批次生成與服務啟動器
├── tests/                    # 完整自動化測試套件 (167+ tests, 100% 通過)
├── demo/visual/              # 視覺解說卡播放器 (player.html)、Bundle 匯出與 MP4 影片
├── plan33_gallery.html       # Phase 33 專科對照與修復歷程成果展示藝廊
├── .agents/skills/           # Hermes Agent 技能手冊 (clinic-visual-batch)
├── .planning/                # GSD 專案規劃追蹤 (PROJECT.md, ROADMAP.md, STATE.md)
├── clinicbrain-api.service   # Systemd user service 單元範本
├── Plan.md                   # 專案總計畫與歷程紀錄
├── AGENTS.md                 # 專案大腦開發規範與安全鐵則
└── clinic.db                 # SQLite 主資料庫 (納入版控，增量維護)
```

---

## 🚀 快速開始 (Quick Start)

### 1. 環境安裝
```bash
# 需求：Python 3.12+
pip install fastapi uvicorn pydantic httpx pytest opencc python-docx openpyxl playwright
```

### 2. 檢視專科解說動畫展示藝廊
```bash
# 開啟 Phase 33 專科解剖對照與修復歷程成果展示藝廊（內嵌 H.264 MP4 影片與 15 格演進拼圖）
xdg-open plan33_gallery.html
```

### 3. Local LLM 專科動畫全自動批次生成
```bash
# 驅動本地 Qwen3.8-27B-FP8 自治處理 49 筆已核准推理樹（輸出至 demo/visual/out/batch_49/）
python3 scripts/run_hermes_batch_49.py
```

### 4. 資料庫建庫與種子匯入
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
# 307 passed（2026-10-15，含網址解析、診所管理、審核頁籤篩選與門診表解析相關測試）
```

### 4. 啟動 API 伺服器

#### 方法 A：使用本機啟動腳本（支援 CLI 參數）
```bash
# 基本啟動 (預設 127.0.0.1:8000)
python3 scripts/run_api_server.py

# 開發模式：啟用自動熱重載
python3 scripts/run_api_server.py --port 8000 --reload

# 生產模式：自訂連接埠與 Worker 數量
python3 scripts/run_api_server.py --host 127.0.0.1 --port 8080 --workers 2
```

#### 方法 B：使用 Systemd User Service（開機自啟與背景常駐）
```bash
# 複製服務單元至使用者 systemd 目錄並重新載入
cp clinicbrain-api.service ~/.config/systemd/user/
systemctl --user daemon-reload

# 啟動服務與檢視狀態
systemctl --user start clinicbrain-api
systemctl --user status clinicbrain-api

# 設定開機自動啟動
systemctl --user enable clinicbrain-api
```

啟動後可開啟瀏覽器檢視 Interactive API Docs：
- Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- 健康檢查端點: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

---

## 📡 API 介面範例

### 0. 診所清單與新增（管理端，需 `X-API-Key`）

```bash
# 列出已建檔診所
curl http://127.0.0.1:8000/api/v1/admin/clinics -H "X-API-Key: your-admin-token"

# 新增診所（代碼重複回 409；格式錯誤回 422；官網須為 https）
curl -X POST http://127.0.0.1:8000/api/v1/admin/clinics \
  -H "Content-Type: application/json" -H "X-API-Key: your-admin-token" \
  -d '{"clinic_id": "3503264627", "name": "凡登整形外科診所", "clinic_type": "醫美診所"}'
```

### 0-1. 網址解析草稿（管理端，需 `X-API-Key`）

```bash
# 預覽（不寫入）；服務詳細頁請使用 /service-detail/ 網址
curl -X POST http://127.0.0.1:8000/api/v1/admin/upload-url \
  -H "X-API-Key: your-admin-token" \
  -F "url=https://www.nu-vendome.com/service-detail/HydraFacial-Treatment/" \
  -F "clinic_id=3503264627" -F "name=海菲秀(水飛梭)" -F "target=faq" -F "preview_only=true"
```

### 1. 統一自然語言查詢 (`POST /api/v1/query`)

```bash
curl -X POST http://127.0.0.1:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "請問音波拉提術後要怎麼照顧？",
    "clinic_id": "3503190424",
    "limit": 5
  }'
```

### 2. 雲端資料增量匯出 (`POST /api/v1/sync/export`)

```bash
curl -X POST http://127.0.0.1:8000/api/v1/sync/export \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-admin-token" \
  -d '{
    "clinic_id": "3503190424",
    "since_version": 0,
    "entities": ["trees", "faqs", "notes", "hours"]
  }'
```

### 3. 雲端資料推播匯入 (`POST /api/v1/sync/import`)

```bash
curl -X POST http://127.0.0.1:8000/api/v1/sync/import \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-admin-token" \
  -d '{
    "clinic_id": "3503190424",
    "data": {
      "notes": {
        "post_op_short": "【更新】術後一週內嚴格避免前往三溫暖與溫泉。"
      }
    }
  }'
```

---

## 🔒 授權與宣告 (License & Compliance)
本專案為緻妍外科診所內部醫療決策支援與知識庫系統。醫療資訊依據台灣衛生福利部與中央健康保險署公開法規標準，輸出皆已遮蔽價格並符合醫療法規範。
