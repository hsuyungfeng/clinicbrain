# Phase 52 Research: 全庫 398 筆衛教圖解深度稽核與渲染層錯配根治

**Date**: 2026-11-18
**Status**: Complete

## 1. 為何修復 nhi400_manifest 後仍有錯圖？（四層根因）

實機盤點 `clinic.db` 的 `visual_assets`（共 **398 筆**，涵蓋 `nhi200`、`nhi400` 與 `page_index` 專屬療程），發現只檢查 `nhi400_manifest.json` 仍有四個盲區：

1. **全庫盤點範圍不足**：`audit_manifest_anatomy.py` 只檢查 `nhi400_manifest.json`（200 筆），未檢查 `clinic.db` 內其餘 **198 筆**（`nhi200` 與既有專科資產，其中有 78 筆 Scene 0 `organ_system` 為 `N/A`）。
2. **單字關鍵字誤匹配（Cross-organ false hit）**：
   - `build_nhi400_manifest.py` 先檢查 `dental` 且包含寬鬆單字 `"牙"`，導致 **`nhi-w266-n48-1`（龜頭包皮炎伴包皮過長垢積）** 因內文出現該字而被誤配為 **`dental_oral`**！
   - **`nhi-w283-g50-0`（三叉神經痛）** 也被歸入 `dental_oral`。
3. **渲染層 `pmPickAnatomyDrawer()` 退化回單顆臼齒蛀牙**：
   - `generate_nhi400_visual_batch.py` 將 `organ_label` 截斷至前 6 字（`name[:6]`），例如 `"反覆性口瘡性"`、`"藥物性牙齦纖"`、`"懷孕期血管性"`、`"拔牙後乾槽症"`。
   - `visual_engine.js` 的 `pmPickAnatomyDrawer()` 沒命中這些截斷字串時，會統一落入 `if (p.organ_system === "dental_oral") return pmDentalCariesSection;`——也就是**全部畫成「一顆大臼齒上有黑洞蛀牙」**！
4. **MP4 渲染快取未連動 `visual_engine.js`**：
   - `video_queue.py` 只對 `ir_json` 算 SHA-256。當我們只修正 `visual_engine.js` 繪圖邏輯而 `ir_json` 未變時，舊的 `data/videos/*.mp4` 不會自動重渲。

## 2. 深度檢查與防呆設計

- **全庫稽核器 (`scripts/audit_db_visual_assets.py`)**：
  - 直接掃描 `clinic.db` 全部 398 筆 `visual_assets`，同時檢查：
    1. `title`／`keywords` 與 `organ_system` 是否跨科錯配；
    2. 模擬 `pmPickAnatomyDrawer()` 實際派發的繪圖函式名稱，禁止非齲齒／非牙髓病變（如口瘡、口炎、囊腫、牙齦瘤、三叉神經痛、多生牙、齒列矯正、龜頭包皮炎）落入 `pmDentalCariesSection`。
- **渲染快取鹽值 (`video_queue.py`)**：
  - 將 `visual_engine.js` 的檔案 SHA-256 前 12 碼混入渲染快取雜湊，確保每次升級前端繪圖器後，受影響的 MP4 自動重渲。
