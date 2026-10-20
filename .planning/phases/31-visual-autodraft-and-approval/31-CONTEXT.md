# Phase 31 CONTEXT：由 PageIndex 自動生成動畫草稿、待簽核動畫分頁、診所優先

## 來源（使用者 2026-10-20）
1. 直接合成動畫播放（資料驅動，瀏覽器直接播放，不需先做成影片）。
2. 衛教性質只說明原理與手術過程，可自動生成：由 PageIndex 抓取主題 → LLM 生成；醫師審核頁面須設計成「待簽核動畫」。
3. 一般醫學（general）與診所服務並存，**診所有相關服務時優先調用**。
審核頁現有分頁：📊 總覽儀表板、📝 待審衛教草稿簽核、🌳 臨床推理樹簽核、📁 文件拖曳上傳中心、🩺 臨床 SOAP、💬 向 LLM 提問。本 phase 新增 **🎬 待簽核動畫**。

## 設計決策
- `visual_assets` 新增 `clinic_id`（NULL＝一般醫學共用；有值＝診所專屬）。唯一鍵改為 `(clinic_id, topic_key)`（以資料表重建遷移，須 `--confirm-prod-backup`；既有資產全部視為一般醫學 NULL）。
- **選取規則**（`find_visual(conn, query, clinic_id)`，診所由伺服器固定設定，請求夾帶一律忽略）：只考慮已核准；命中關鍵字的資產中，**診所專屬（clinic_id＝伺服器設定）優先於一般醫學（NULL）**；同層以命中數高者、再以 topic_key 字典序（確定性）；Python 層再次比對 `row.clinic_id` ∈ {設定診所, NULL}，絕不顯示其他診所的資產。
- **自動生成（草稿）**：輸入為已核准的 PageIndex 推理樹（`visible_tree_sql`；標題、summary_text、四段內容）。LLM 只產生**受約束的結構化輸出**（場景標題、標籤、參數列舉值、說明文字），全部經 `validate_ir`／`validate_params`／`validate_visual_text`；最多 2 次；失敗不寫入、不退回主題專屬預設（避免再現「寫死脂肪文字」的錯誤）。範圍限於**原理與手術過程**：不得出現用藥劑量、價格、療效保證、個人化建議。產出一律 `pending`、`source_type=llm_generated`、`clinic_id＝該樹的 clinic_id`（一般醫學樹為 NULL）、topic_key＝`tree-<doc_id>`。**永不自動核准。**
- **待簽核動畫分頁**：醫師直接看到會動的預覽（同一個 `visual_engine.js`），可播放／暫停／拖曳、改說明文字（編輯後回 pending）、核准、駁回；顯示來源、診所／一般標籤、驗證結果；核准前重新驗證。
- 不收個資；不新增對外（病人端）的寫入路徑；管理端全部掛 `verify_admin_key`。

## 硬性約束
- 沿用 Phase 29／30 全部約束：`/admin` CSP 禁內嵌腳本、動態文字 `textContent`、禁用子字串（含註解）、`src/general/` 隱私守門不得放寬、`validate_ir` 不得放寬。
- 不直接寫正式庫；遷移與生成須先備份並取得使用者核准；測試用隔離副本、不呼叫真實 LLM。
- **有視覺輸出的功能，最後檢查必須用真實瀏覽器逐項檢視**（Phase 30 的教訓）。
- 派工 prompt 必須寫明：只做指定計畫、完成即停；嚴禁 `git reset/checkout/stash/clean/restore`；`git add` 只加自己改的檔案、不加 clinic.db。

## 需求編號
P31-SCOPE（診所優先）、P31-MIGRATE、P31-AUTODRAFT、P31-API、P31-UI、P31-DOC
