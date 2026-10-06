#!/usr/bin/env python3
"""
手動 OCR 草稿小工具：對「單一」圖片產出 OCR 草稿，供人工參考。

用法：
    python3 scripts/ocr_draft.py 圖片路徑            # 草稿印到標準輸出
    python3 scripts/ocr_draft.py 圖片路徑 --out 草稿.txt [--force]

絕不寫入資料庫、不自動入庫；草稿未經驗證，須人工對照原圖。
結束碼：0 成功；2 輸入或環境錯誤。
"""

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.ocr_draft import OcrDraftError, make_draft  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="對單張圖片產生 OCR 草稿（僅供人工參考，不入庫）")
    parser.add_argument("image", help="圖片路徑")
    parser.add_argument("--out", help="將草稿寫入此檔案（預設印到標準輸出）")
    parser.add_argument("--force", action="store_true", help="允許覆蓋既有的 --out 檔案")
    args = parser.parse_args(argv)

    out_path = Path(args.out) if args.out else None
    if out_path and out_path.exists() and not args.force:
        print(f"❌ 輸出檔已存在，不覆蓋（可加 --force）: {out_path.name}", file=sys.stderr)
        return 2

    try:
        draft = make_draft(args.image)
    except OcrDraftError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2

    if out_path:
        out_path.write_text(draft, encoding="utf-8")
        print(f"✅ 草稿已寫入 {out_path}（僅供人工參考，未入庫）", file=sys.stderr)
    else:
        print(draft)
    return 0


if __name__ == "__main__":
    sys.exit(main())
