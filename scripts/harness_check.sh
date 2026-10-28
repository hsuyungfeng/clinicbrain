#!/usr/bin/env bash
# ClinicBrain Native Harness² 標準驗證馬具（Phase 36）
# 以固定短參數執行全部驗證，避免本地模型在超長 pytest 路徑下觸發 DRY 懲罰截斷。
set -euo pipefail

cd "$(dirname "$0")/.."

python3 -m pytest \
  tests/test_visual_engine_static.py \
  tests/test_visual_engine_browser.py \
  tests/test_icd10_primary_care.py \
  tests/test_visual_autodraft.py \
  tests/test_harness_optimizer.py \
  -q
