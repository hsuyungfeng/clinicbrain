# 33-01 SUMMARY：Contrast 與 Timeline 專科架構規格與 Autodraft 語意推斷升級（已完成）

## 狀態
已全部完成。Task 1 與 Task 2 均已由 Claude Haiku 5.5 實作完成，經測試與審查全數通過。

## 已完成
- `src/visual/blueprints.py`：
  - `contrast` 的 `left.mode` 擴充支援 5 大專科對照模式：`tissue_trauma_torn_vessel`（抽脂盲吸撕裂出血）、`scar_contracture_ectropion`（外切眼整攣縮外翻）、`silicone_extrusion_erythema`（矽膠鼻整壓迫穿出）、`capsular_contracture_ball`（假體隆乳厚莢膜緊縮）、`nodule_clumping`（微整針劑硬塊結節）。
  - `contrast` 的 `right.mode` 擴充支援 5 大微創優勢模式：`ultrasonic_emulsification`（威塑超音波乳化）、`transconjunctival_fat_reposition`（內開眶隔轉位平鋪）、`cartilage_triangular_strut`（軟骨三角海鷗線支架）、`dual_plane_natural_teardrop`（雙平面水滴垂墜）、`micro_droplet_diffusion`（微滴均勻散佈）。
  - `timeline` 的 `connectors` 擴充支援 5 大活體修復歷程：`bone_healing`（骨痂微網橋接）、`bruise_metabolism`（退瘀色譜歷程）、`scar_maturation`（疤痕褪紅隱痕）、`nerve_regeneration`（感覺神經軸突萌芽）、`skin_retraction`（組織緊緻回彈貼合）。
  - `timeline` 的 `unit_effect` 新增 `glow_restored`（修復完成微光）。
- `src/visual/autodraft.py`：
  - 實作 `infer_scene2_contrast(tree)`：依推理樹第 2 段臨床文字意圖自動匹配並輸出對稱的 `(left.mode, right.mode)`。
  - 實作 `infer_scene3_timeline(tree)`：依推理樹第 3/4 段術後照護文字意圖自動匹配並輸出專科修復歷程。
  - 升級提示詞第 8 條：明確引導本地模型使用推斷出的新列舉值。
  - 升級自癒整形器 `parse_and_build_tree_ir`：動態讀取 Blueprint 規格白名單，徹底解決硬編碼退回預設值的問題。
- `tests/test_visual_blueprints.py` 與 `tests/test_visual_autodraft.py`：
  - 新增 5 大專科與修復歷程之推斷驗證、白名單穿透與容錯降級測試。

## 驗證
- `uv run pytest -v tests/test_visual_blueprints.py tests/test_visual_autodraft.py`：**41 passed in 0.69s**（包含 5 項新增測試）。
- 正式資料庫零污染：`clinic.db` SHA-256 恆定未變（`ebb1cc79...`）。

## 下一步
進入 **Plan 33-02**：
1. 在 `src/web/static/visual_engine.js` 中實作上述 5 組對照模式與 5 組修復歷程的動態 SVG 向量渲染程式碼。
2. 同步 `resolveParams` 白名單。
3. 執行 Playwright 瀏覽器契約與安全邊界測試。
4. 截圖驗收與錄製 MP4 動畫。
