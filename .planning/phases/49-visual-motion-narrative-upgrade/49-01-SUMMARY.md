# 49-01-SUMMARY: `splitCaptionSegments()` 智能平衡分段升級完成

## 實作摘要
* **檔案**：`src/web/static/visual_engine.js`（`splitCaptionSegments`）
* **機制**：先依 `[。！？；]+` 切分基本句，若單句超過 28 字，再依 `[，、]+` 拆為子片語並貪婪平衡合併成 2～3 個自然短句（約 18～34 字/段），讓實庫 398 筆無須改動資料庫即可自動呈現多段時間軸同步字幕。

## 驗證結果
* `.venv/bin/pytest tests/test_phase49_visual_upgrade.py -q`：**6 passed**（含真實單句逗號長文 `test_single_period_comma_caption_auto_balances` 驗證 `1/3`、`2/3`、`3/3` 與零截斷）。
* `.venv/bin/pytest tests/test_visual_assets_real_ir.py -q`：**2 passed**（全庫 398 筆已核准真實 IR 渲染零錯誤、零 `NaN`/`undefined`/`null`）。
