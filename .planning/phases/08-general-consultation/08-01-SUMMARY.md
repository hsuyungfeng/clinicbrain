# Phase 08-01 總結報告：一般醫療諮詢基礎模組（固定文字與紅旗偵測器）

## 執行概述

本計畫為 Phase 08（一般醫療諮詢）之 Wave 1 任務，完成了 GENERAL-01（免責聲明與就醫提示固定文字）與 GENERAL-02（急重症紅旗偵測純函式）之實作。所有功能完全獨立於資料庫、API 與 LLM，落實隱私與醫療安全防護。

---

## 交付成果清單

### 1. 核心模組
- **一般諮詢套件入口 (`src/general/__init__.py`)**：宣告套件功能與設計定位。
- **免責聲明與就醫提示 (`src/general/disclaimer.py`)**：
  - `DISCLAIMER_TEXT`：一般諮詢之完整免責宣告（包含「非醫囑/不構成診斷或處方」與「建議儘速就醫」，強調無法取代醫師親自診察）。
  - `RED_FLAG_DISCLAIMER_TEXT`：紅旗就醫提示之精簡免責聲明。
  - `EMERGENCY_MESSAGE`：立即撥打 119 或前往急診之緊急指引（無其他專線）。
  - `URGENT_MESSAGE`：建議當日儘速就近就醫之指引。
  - `FILLER_OCCLUSION_ADDENDUM`：填充劑注射血管阻塞補充提示（建議同時聯絡施作診所並告知注射時間部位）。
  - `ANSWERED_MESSAGE`：衛教資訊前導句。
  - `NO_MATCH_MESSAGE`：查無資料時之誠實回應與就醫指引（絕不捏造醫療內容）。
  - `message_for_red_flag(level, rule_id)`：依據等級與規則識別碼組裝提示訊息（E08 自動附加填充劑補充提示）。
- **紅旗症狀偵測器 (`src/general/red_flags.py`)**：
  - `RedFlagRule` / `RedFlagMatch`：嚴格唯讀（frozen）資料結構，`RedFlagMatch` 僅含 `level`, `rule_id`, `label`，絕不包含問句原文或片段。
  - `RED_FLAG_RULES`：完整收錄經審閱之 13 條規則（E01~E08, U01~U05），涵蓋心臟胸痛、呼吸梗塞、意識抽搐、大量出血、休克水腫、中風、中毒過量、填充劑血管阻塞，以及劇痛、高燒、傷口感染、其他急症與急腹症。
  - 雙層正規化：`light_normalize`（保留小數點供體溫比對）與 `normalize_for_match`（去除標點與特殊字元）。
  - `detect_red_flag(text)`：純函式實作，無 logging、無 sqlite3 存取、無 LLM 呼叫。

### 2. 測試套件
- **固定文字單元測試 (`tests/test_general_disclaimer.py`)**：11 個測試全部通過。驗證繁中冪等性、無價格模式、無保證療效禁詞、電話僅限 119 等。
- **紅旗偵測器單元測試 (`tests/test_general_red_flags.py`)**：150 個測試全部通過。
  - 漏報導向正例（含補強之「喘不過來」、填充後視力喪失同句 E08、大量咳血等，全部命中預期規則與等級）。
  - 13 條規則覆蓋率 100%。
  - 否定語境（如「沒有胸痛」）仍保守觸發。
  - 格式變體（大小寫、弧形撇號、全形空白、標點插入等）。
  - 優先序測試（同時含發燒與呼吸困難優先回傳 emergency）。
  - 43 句誤觸發控制負例全部回傳 None。
  - 6 句已知並接受的過度觸發案例通過。
  - 純函式性保護（monkeypatch 驗證無 sqlite3 或 logging 呼叫）。

---

## 驗收結果

- `python3 -m pytest tests/test_general_disclaimer.py tests/test_general_red_flags.py -q`：**161 passed**
- 模組禁用詞彙與依賴檢查：無 `import logging`、無 `import sqlite3`、無 `llm_client`
- 正式庫零污染：未修改 `clinic.db`
