# Phase 51 Research: NHI400 衛教圖解解剖器官精準映射與零錯配防線

**Date**: 2026-11-18
**Status**: Complete

## 1. 根因實證

對 `data/visual/nhi400_manifest.json`（200 筆）執行 `scripts/audit_manifest_anatomy.py` 後，檢出 **122 筆疑似解剖錯配**：

- `respiratory_mucosa`（68 筆中有 67 筆錯配）：[build_nhi400_manifest.py#L100-L107](file:///home/hsuyungfeng/DevSoft/clinicbrain/scripts/build_nhi400_manifest.py#L100-L107) 把所有未命中前 6 個窄條件的腸胃、心血管、內分泌、皮膚、關節疾病全部 fallback 到 `respiratory_mucosa`。
- `dental_periodontal`（30 筆中有 29 筆錯配）：[build_nhi400_manifest.py#L70-L78](file:///home/hsuyungfeng/DevSoft/clinicbrain/scripts/build_nhi400_manifest.py#L70-L78) 因 `system == "dental"` 一律配發 `dental_periodontal`（牙周骨組織缺損），導致 `D384` 口腔念珠菌症、`D385` 小唾液腺黏液囊腫、`D382` 口腔扁平苔蘚、`D383` 口腔白斑、`D395` 顳顎關節等全部套錯模板。
- `ophthalmic_retina`（22 筆中有 19 筆錯配）：[build_nhi400_manifest.py#L41](file:///home/hsuyungfeng/DevSoft/clinicbrain/scripts/build_nhi400_manifest.py#L41) 只要文字含「眼」就全配給視網膜／眼底模板（結膜、角膜、眼瞼、乾眼、青光眼、白內障皆誤配）。
- `ent_airway`（3 筆）、`uro_genital`（2 筆）、`joint_spine`（2 筆）：部分關鍵字順序優先權錯誤（如 `W210` 慢性咽喉反流症、`W228` 腹股溝疝氣）。

## 2. 現有前端繪圖器盤點

[visual_engine.js#L3570-L3585](file:///home/hsuyungfeng/DevSoft/clinicbrain/src/web/static/visual_engine.js#L3570-L3585) 的 `PATHO_DRAWERS` 其實**已經內建** 14 種器官繪圖器：
`respiratory_mucosa`, `vascular_metabolic`, `gi_tract`, `skin_barrier`, `joint_spine`, `uro_pelvic`, `dental_oral`, `tcm_meridian`, `endocrine_receptor`, `ophthalmic_retina`, `ent_airway`, `uro_genital`, `dental_periodontal`, `tcm_special_acup`。

僅因 `build_nhi400_manifest.py` 未對接這些既有機關繪圖器（且缺乏口腔黏膜與前眼段細分），才導致大批錯配。

## 3. 修復與驗收策略

1. 重構 `build_nhi400_manifest.py` 的 `map_nhi400_archetype()`，依解剖部位與 ICD-10 精準映射到對應器官（並為口腔黏膜／唾液腺／前眼段補充專屬繪圖支援）。
2. 重建 `data/visual/nhi400_manifest.json` 並將 `audit_manifest_anatomy.py --strict` 納入建置後置閘門與 pytest。
3. 指派 **Hermes** 擔任獨立 Tester & Checker，驗證全量 200 筆零解剖錯配及 `D384`/`D385` 前端渲染。
