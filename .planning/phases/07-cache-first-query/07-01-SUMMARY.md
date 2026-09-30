# 07-01-SUMMARY: FAQ 快取短路判定與路由整合 (CACHE-01, CACHE-04)

## 執行成果摘要

本階段已完成高信心 FAQ 快取短路判定邏輯與 `handle_query` 整合：

1. **高信心 FAQ 短路判定模組 (`src/query/faq_shortcut.py`)**：
   - 實作無 DB、無 LLM 之純函式判定邏輯。
   - 制定五項可測量且保守之規則門檻：
     - `MIN_QUERY_CHARS = 4`（查詢至少 4 字元）
     - `MIN_QUERY_COVERAGE = 0.9`（Bigram 查詢覆蓋率至少 90%）
     - `MIN_QUESTION_COVERAGE = 0.7`（Bigram FAQ 問句覆蓋率至少 70%）
     - `MIN_MARGIN = 0.1`（最佳與次佳候選差距至少 10%）
     - `SHORTCUT_CANDIDATE_LIMIT = 50`（獨立較大候選集，防止呼叫端 limit 截斷導致歧義漏判）
   - 實作五維度對稱「風險特徵殘餘檢查」（`extract_risk_features` / `risk_mismatch`）：
     - 數字帶單位（如 `3天` vs `3週`、`5mg` vs `5g`）
     - 中文數字加量詞（如 `三天`）
     - 擴充否定/禁忌單字（不、無、沒、別、勿、禁、未、非、免、避、忌、否、戒、停）
     - 時序/方位字（前、後、內、外）
     - 人群/體質限定詞（懷孕、孕、哺乳、嬰、兒、童、老、糖尿、男、女、過敏、高血壓、抗凝血、服藥、成人、長者）
     - 全程於去除語助詞前以原文規範化偵測，對稱比對，任一邊多或少特徵即拒絕短路。

2. **統一查詢入口整合 (`src/query/router.py`)**：
   - `QueryResponse` 新增向後相容欄位：
     - `source: Literal["cache", "pageindex", "llm"] = "pageindex"`
     - `cache_answer: Optional[str] = None`
     - `cache_eligible: bool = True`
   - `handle_query` 支援 `cache_shortcut: bool = True`。
   - 營運關鍵字問句強制不短路（結構化 clinic_info / clinic_hours 優先），且標記 `cache_eligible = False`。
   - 雙重二次價格遮蔽：所有短路答案強制經過 `mask_prices`。

3. **單元與整合測試套件**：
   - `tests/test_faq_shortcut.py`（43 個單元測試）：覆蓋規則常數、標準化、Bigram 計算、五類風險特徵、歧義合併、順序不變性與隔離/非隔離對抗性案例。
   - `tests/test_cache_first_router.py`（25 個整合測試）：覆蓋完整 `handle_query` 短路流程、大候選集防截斷、營運資訊保護、價格遮蔽強制性、8 組正向對照對抗案例與 24 筆真實庫自我比對回歸。

---

## 已知限制與取捨說明

1. **短路命中率上限約 60%（使用者決策 #2）**：
   正式庫 40 筆 FAQ 中，有 16 筆問句因不含現行路由關鍵字（如雷射、拉提、術後、藥等）被 `classify()` 歸類為 `general`。依據既有架構，`general` 路由不會檢索 `special` FAQ，因此這 16 筆問句無法被快取短路，將正常走 PageIndex 流程。本階段遵從使用者決策與架構邊界，不更動 `classify` 詞表與路由分流邏輯。
2. **刻意寬鬆的保守風險字集**：
   風險字集設計以「寧可少短路，絕不可誤短路給出相反醫療建議」為最高指導原則。例如「免」會擋下「免費」相關問句、「男/女/老」會比對字面。最壞情況僅為回退至完整檢索，此為醫療安全之必要取捨。

---

## 驗證結果

- `tests/test_faq_shortcut.py`: 43 passed (>= 34)
- `tests/test_cache_first_router.py`: 25 passed (>= 24)
- 相關測試總計：`123 passed in 3.04s`，無任何 failure。
- 零 LLM 相依、零 router 循環匯入。
