# Plan 24-01 總結：上傳端點新增名稱欄位與抽出 _text_to_faq_drafts 共用管線

## 執行成果

- **完成日期**：2026-10-14
- **成果狀態**：全部測試通過（16/16 passed, 回歸測試 13/13 passed），零外部依賴、抽離共用管線，嚴格遵循正體中文規範與個資防線。
- **Commit**：`feat(admin): 上傳端點新增名稱欄位與抽出 _text_to_faq_drafts 共用管線 (Plan 24-01)`

## 產出與變更檔案

1. `tests/fixtures/upload_pipeline_golden.json` (Commit `903d2bd`)：
   - 包含改動前 `upload_admin_file(preview_only=True)` 對典型多段落 docx 的完整回傳結構作為 golden 基準。
2. `src/api/routes/admin.py`：
   - `validate_display_name(raw: Optional[str]) -> Optional[str]`：
     - NFKC 正規化與頭尾空白去除。
     - 長度限制 1–80 字元。
     - 正則白名單 `^[\u4e00-\u9fffA-Za-z0-9 \-_·（）\(\)\[\]]+$`。
     - 整合 `deidentify_text` 拒絕包含個資/電話的名稱。
     - 整合 `deep_mask_prices` 拒絕包含金額/價格的名稱。
     - 違規時統一拋出 HTTP 400，detail 為固定安全字串，絕不包含使用者輸入。
   - `_text_to_faq_drafts(raw_text: str, topic: str, clinic_id: str) -> tuple[list[dict[str, Any]], int, int]`：
     - 將純文字/Markdown/萃取內文清洗（簡轉繁、去識別化、價格數字遮蔽）、切分並轉換為 FAQ 草稿清單。
     - 超過 200 段拋 HTTP 400。
     - 保留 Q&A 辨識與非 Q&A 之 `【診所文件】{topic} - 指示 {idx+1}` 佔位題邏輯。
     - 執行四層驗證（簡體字／政治立場／保證療效／價格洩漏），違規單筆剔除。
   - `upload_admin_file`：
     - 新增 `name: Optional[str] = Form(None)` 參數。
     - 呼叫 `validate_display_name` 取得 `name_clean`。
     - `doc_topic = name_clean if name_clean else Path(filename).stem[:80]`，確保未填寫時維持既有檔名 slug 行為。
     - 呼叫 `_text_to_faq_drafts` 完成處理。
3. `tests/test_upload_name_field.py`：
   - 16 項單元與端到端測試，覆蓋 golden 基準比對、名稱驗證規則、同名/不同名覆寫邏輯、批量上傳獨立性。

## 驗證指標

- `python3 -m pytest tests/test_upload_name_field.py -v`：16 passed in 1.20s。
- `python3 -m pytest tests/test_admin_api.py tests/test_webapp_e2e.py -q`：13 passed in 1.24s。
- 正式庫 `clinic.db`：SHA-256 維持 `0089ca28795fd0f0f2a41e9fa6b16f840ae794bfaf4e5597576410e9f0cf23db`，零變更零污染。
