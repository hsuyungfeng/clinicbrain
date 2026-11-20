# 49-02-SUMMARY: 3 代表療程 MP4 強制重渲染完成並交付 `hermes-test` 驗收

## 產出檔案（`data/videos/`）
1. `icd-k279-peptic-ulcer_landscape.mp4`（1.69 MB, 26.5s） / `_portrait.mp4`（0.94 MB, 26.5s）
2. `tree-3503264627-structural-autologous-rhinoplasty_landscape.mp4`（1.11 MB, 26.5s） / `_portrait.mp4`（0.62 MB, 26.5s）
3. `tree-ultraformer-mpt-hifu_landscape.mp4`（1.41 MB, 26.5s） / `_portrait.mp4`（0.80 MB, 26.5s）

## 驗收委派
已透過 `herdr` 委派 `hermes-test`（pane `wA:p3`）執行：
* `ffprobe` 檢查 6 支 MP4 解析度（1920x1080 / 1080x1920）、時長（26.5s）與串流完整性。
* 驗證 `splitCaptionSegments` 升級後 3 主題三幕字幕皆已自動切分為多段（`1/2`、`2/2` 或 `1/3`…，不再是 `1/1`）。
* 抽幀檢視 Scene 1（`t=0.6s, 4.0s`）、Scene 2（`t=12.0s`）、Scene 3（`t=20.0s`）構圖與字幕可讀性。
