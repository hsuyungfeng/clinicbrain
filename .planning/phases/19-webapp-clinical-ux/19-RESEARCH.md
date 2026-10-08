# Phase 19 Research: Web 管理介面臨床體驗升級與 AI 輔助生成

## 1. 現有架構分析與對接方案

### 1.1 批次簽核與事務安全 (`src/api/routes/admin.py` & `src/pageindex/faq_review.py`)
- **現狀**：目前僅有單筆 `POST /api/v1/admin/review/faqs/{id}/approve` 與 `reject`。
- **後端擴充**：
  - 新增 `POST /api/v1/admin/review/batch`:
    - 請求體：`{"action": "approve" | "reject", "faq_ids": [1, 2, 3...]}`。
    - 限制單次批次上限（例如最大 100 筆），防範大量 ID 造成鎖定過久。
    - 在單一交易內執行，若有任何不存在之 ID 或失敗，安全處理並回傳 `{success_count, failed_count, failed_ids}`。
  - 新增 `PATCH /api/v1/admin/review/faqs/{id}`:
    - 允許更新 `question` 與 `answer`（經四層防護過濾），方便醫師在核准前微調文字。

### 1.2 本地 LLM 生成衛教解答 API
- **現有模組**：
  - 本地 llama-server (Qwen3.8-27B-UD-Q4_K_XL，監聽 127.0.0.1:8080)。
  - `src/batch/faq_generator.py` 中的 `FAQ_SEED_PROMPT_TEMPLATE` 與四層合規檢查。
- **後端端點設計**：
  - `POST /api/v1/admin/review/faqs/{id}/generate-answer`:
    - 讀取該題的 `question`、`clinic_id` 與 `category`。
    - 透過本地 LLM 生成 150~300 字專業繁體中文衛教指引。
    - 自動通過 `deep_mask_prices()` 價格清洗與就醫警訊檢查。
    - 更新至資料庫該列的 `answer`，狀態維持 `pending`，回傳生成之解答。

### 1.3 前端 UI 美化與互動升級
- **設計風格**：現代高質感醫學臨床風格（Modern Clinical Aesthetic）：
  - 沉穩深藍/靛藍導覽列 + 柔和淺灰背景。
  - 卡片式排版：邊框微陰影（`box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05)`）、層次分明的標籤徽章。
  - 待審卡片配備多功能工具列：
    - 題目左側提供大型 Checkbox。
    - 若答案為空或簡陋，顯示「⚠️ 尚未生成解答」警示，並附帶顯眼的「🤖 呼叫本地 LLM 生成解答」按鈕。
    - 答案區塊支援點擊「✏️ 編輯」或直接內聯編輯。
- **全選 / 反選 / 浮動工具列（Sticky Action Bar）**：
  - 頂部控制列：
    - ☑️ 全選 (Select All)
    - 🔄 反選 (Invert Selection)
    - ⏹️ 清除 (Clear)
  - 當勾選數量 > 0 時，底部彈出浮動操作列（Sticky Bottom Bar）：
    - 顯示「已選取 X 筆草稿」
    - 【✅ 批量核准】
    - 【❌ 批量駁回】
    - 【🤖 批量生成答案】

---

## 2. 審查加固要點（Claude 對抗性角色指引）
1. **輸入與 SQL 防護**：`batch` API 的 ID 列表必須校驗為整數陣列，防範非合法輸入或過量 ID 攻擊。
2. **XSS 防護**：生成的答案或內聯編輯的文字在前端渲染時，必須持續維持 `textContent` 或嚴格的 HTML 跳脫。
3. **LLM 呼叫超時與容錯**：本機 LLM 生成需設定適當 timeout（如 30 秒），避免連線卡死。
