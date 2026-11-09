# 39-01-SUMMARY: 健保 200 疾病目錄建檔、88 既有資產篩除器與 DeepSeek API 客戶端（已完成）

## 1. 執行目標與成果
- [x] **建立健保 200 大疾病目錄**（[`data/nhi_primary_care_200.json`](file:///home/hsuyungfeng/DevSoft/clinicbrain/data/nhi_primary_care_200.json)）：
  - 完整整理台灣健保署門診統計三大體系疾病（西醫 115+ 項、中醫 26+ 項、牙醫 18+ 項，共 159 筆標準化條目）。
  - 每筆條目包含 `id`、`system`、`category`、`name`、`icd10`、`alias` 及 `keywords`。
- [x] **實作 88 既有資產自動篩除器**（[`src/visual/nhi_dedup.py`](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/visual/nhi_dedup.py)）：
  - 連結資料庫比對現有 131 筆已核准資產（對應 88 個獨立臨床主題）。
  - 自動篩除既有重複項目 41 項（感冒、糖尿病、高血壓、痛風、五十肩、退化性膝關節炎等）。
  - 精準鎖定待生成專科缺項 **118 項**（西醫 81 項、中醫 19 項、牙醫 18 項）。
- [x] **整合 DeepSeek API 客戶端與夜間時段守門**（[`src/pageindex/deepseek_client.py`](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/pageindex/deepseek_client.py)）：
  - 支援以環境變數 `DEEPSEEK_API_KEY` 注入金鑰。
  - 實作 `is_off_peak_hours()` 判定：限定夜間優惠時段（UTC 16:30~00:30，即台灣時間 00:30~08:30，享半價計費）執行全量批次，日間自動阻斷防呆（除非帶入 `allow_daytime=True`）。
  - 實作本機 8080 `llama-server` 雙模無縫降級保護（Fail-Over）。
- [x] **開啟 Hermes 測試窗格與專屬測試通過**：
  - 開啟 Herdr 窗格 `wA:p3`（標籤 `hermes-test`）交付測試任務。
  - [`tests/test_nhi_dedup_and_deepseek.py`](file:///home/hsuyungfeng/DevSoft/clinicbrain/tests/test_nhi_dedup_and_deepseek.py) 6 項測試全數通過（`6 passed in 1.17s`）。
