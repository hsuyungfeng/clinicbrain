# Phase 11 Plan 01 Summary: 跨層級（Tiered）高信心短路判定實作

## 執行成果概述
本計畫（11-01）以 TDD 模式完成跨層級短路判定核心（純函式層），成功鎖定設計題 B（跨層級競爭規則）與設計題 D（對抗性變形回歸），並消除 Blocker 回歸風險：
1. **RED 階段驗證**：
   - 建立 `tests/test_faq_shortcut_tiered.py`，前置編譯通過、`git diff` 保證未更動 `src/query/faq_shortcut.py`。
   - 執行 `pytest` 於 collection 階段如預期拋出 `ImportError: cannot import name 'CLINIC_RELATED_FLOOR' from 'src.query.faq_shortcut'`，pytest 結束碼恰為 2。
2. **GREEN 階段實作 (`src/query/faq_shortcut.py`)**：
   - 新增常數 `CLINIC_RELATED_FLOOR = 0.4`（僅 tiered 使用，Phase 7 既有常數完全未動）。
   - 新增資料結構 `TieredShortcutDecision`，包含 `hit`、`level`（`clinic` / `general` / `None`）、`reason`、`clinic_reason`、`general_reason`。
   - 實作純函式 `select_confident_faq_tiered`：
     - 空白/無效 `clinic_id` 直接回傳 `no_clinic`（兩階段皆 `skipped`）。
     - 診所階段優先比對（`route='special'`），高信心時勝出（`level='clinic'`），不讓 general 候選混排競爭。
     - 診所階段若為 `risk_mismatch`、`ambiguous` 或 `query_too_short`，視為相近但不可確認，為防一般衛教通則取代診所專屬指示，整體阻絕短路且不退回 general。
     - 診所階段若為 `low_coverage` 且 `query_coverage >= CLINIC_RELATED_FLOOR (0.4)`，阻絕退回 general（`reason='clinic_related_low_coverage'`）。
     - 僅在診所階段為 `no_eligible` 或 `low_coverage` 且 `query_coverage < 0.4` 時，才退回評估 general 層（`route='general'`）。
3. **CLINIC_RELATED_FLOOR 之取捨說明**：
   - 針對診所問句「縫合後的傷口可以碰水洗澡嗎？」（診所規定不可碰水），查詢問法略短（如「縫合後傷口可以洗澡嗎」覆蓋率約 0.83）若無 floor 防線將誤退回一般衛教「包覆防水敷料可淋浴」，造成醫療指示顛倒。引入 0.4 floor 成功阻絕誤退。
   - 已知取捨：query_coverage < 0.4 之鬆散釋義（如診所傷口問句對查詢「縫合後飲食注意」qc=0.33）仍會放行退回 general；此為基於 Bigram 覆蓋率之詞彙守衛取捨，已在測試 `test_t5b_known_tradeoff_boundary_floor` 完整記錄。

## 測試覆蓋與驗證
- `tests/test_faq_shortcut_tiered.py`：共 19 個測試項目（含 13 個獨立測試與多重參數化案例），全數 PASS：
  - T1: 診所高信心勝出（覆蓋率門檻通過）。
  - T2: 診所內部歧義不退 general。
  - T3: 診所風險特徵不符（數字單位、時序、否定詞）不退 general。
  - T3b: Blocker 回歸鎖定（三個短句變形皆阻絕退回 general，正向對照命中診所）。
  - T4: 診所無合格候選才退回 general。
  - T5: 診所完全無關（發燒 vs 縫合，qc=0.0）才退回 general。
  - T5b: 0.4 floor 邊界取捨驗證（飲食注意退 general、傷口照顧阻絕）。
  - T6: 兩層皆未命中。
  - T7: 層級隔離（跨診所與錯誤 category 排除）。
  - T8: 無效診所代碼防禦。
  - T9: general 層安全檢查（原句、不需要、第3天、之前、歧義）。
  - T10: 診所層對抗性變形（6 個變形皆被安全擋下）。
  - T11: 最小查詢長度。
  - T12: 常數鎖定。
- `tests/test_faq_shortcut.py`：52 個既有短路測試未改動一行代碼，全數 PASS。
- 組合驗證指令 `python3 -m pytest tests/test_faq_shortcut_tiered.py tests/test_faq_shortcut.py -q`：共 71 passed in 0.31s。
- `clinic.db` SHA-256 驗證完全不變。
