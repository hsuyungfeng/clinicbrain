"""醫師標註表單檢查程式（Phase 57 黃金標準集）。

檢查 physician_labeling_sheet.csv 每一列：
- physician_blueprint 必須是合法選項（12 個藍圖 + other），拼字需完全一致。
- 非 other 的列必須有 evidence_span，且該片段必須是同列 source_text 的子字串
  （沿用 blueprint_classifier.is_evidence_in_source 的正規化比對，與正式流程一致）。
- other 的列應留空 evidence_span（超出時列為警告）。
- evidence_span 長度建議 10 至 40 字（超出時列為警告）。
- 空白的 physician_blueprint 視為「尚未標註」，預設不算錯誤；加上 --require-complete 則視為錯誤。
- tree_id 與 doc_id 不可重複。

退出碼：0 = 無錯誤；1 = 有錯誤；2 = 檔案讀取或格式問題。
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

# 直接以 `python scripts/check_physician_labels.py` 執行時，sys.path 不含專案根目錄，需補上才能 import src。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.visual.blueprint_classifier import (  # noqa: E402
    CLASSIFIER_ALLOWED_BLUEPRINTS,
    is_evidence_in_source,
)

_GOLDEN_DIR = (
    Path(__file__).resolve().parent.parent
    / ".planning/phases/57-visual-blueprint-classification-narration-ab/golden"
)
DEFAULT_SHEET = _GOLDEN_DIR / "physician_labeling_sheet.xlsx"  # 醫師填寫用（含下拉選單）
LABEL_SHEET_NAME = "標註"
REQUIRED_COLUMNS = ("tree_id", "doc_id", "source_text", "physician_blueprint", "evidence_span")
EVIDENCE_MIN_LEN = 10
EVIDENCE_MAX_LEN = 40


def check_rows(rows: list[dict[str, str]], require_complete: bool = False) -> dict[str, Any]:
    """純函式：檢查已讀入的列，回傳錯誤、警告與統計，不做任何 I/O。"""
    errors: list[str] = []
    warnings: list[str] = []
    seen_tree: set[str] = set()
    seen_doc: set[str] = set()
    labeled = 0
    unlabeled = 0

    for idx, row in enumerate(rows, start=2):  # 第 1 列為表頭
        tree_id = (row.get("tree_id") or "").strip()
        doc_id = (row.get("doc_id") or "").strip()
        tag = f"第{idx}列 tree_id={tree_id or '?'}"

        if tree_id in seen_tree:
            errors.append(f"{tag}：tree_id 重複")
        seen_tree.add(tree_id)
        if doc_id in seen_doc:
            errors.append(f"{tag}：doc_id 重複（{doc_id}）")
        seen_doc.add(doc_id)

        bp = (row.get("physician_blueprint") or "").strip()
        evidence = (row.get("evidence_span") or "").strip()
        source = row.get("source_text") or ""

        if not bp:
            unlabeled += 1
            if require_complete:
                errors.append(f"{tag}：尚未標註 physician_blueprint")
            continue

        labeled += 1
        if bp not in CLASSIFIER_ALLOWED_BLUEPRINTS:
            errors.append(f"{tag}：不合法的藍圖名稱「{bp}」")
            continue

        if bp == "other":
            if evidence:
                warnings.append(f"{tag}：選 other 但仍填寫 evidence_span（建議留空）")
            continue

        if not evidence:
            errors.append(f"{tag}：選 {bp} 但未填寫 evidence_span")
            continue

        if not is_evidence_in_source(source, evidence):
            errors.append(f"{tag}：evidence_span 不是 source_text 的子字串")

        if not (EVIDENCE_MIN_LEN <= len(evidence) <= EVIDENCE_MAX_LEN):
            warnings.append(
                f"{tag}：evidence_span 長度 {len(evidence)} 字，建議 {EVIDENCE_MIN_LEN}–{EVIDENCE_MAX_LEN} 字"
            )

    return {
        "total": len(rows),
        "labeled": labeled,
        "unlabeled": unlabeled,
        "errors": errors,
        "warnings": warnings,
    }


def _check_columns(fields: list[str]) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in fields]
    if missing:
        raise ValueError(f"缺少必要欄位：{', '.join(missing)}")


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        _check_columns(reader.fieldnames or [])
        return list(reader)


def _load_xlsx(path: Path) -> list[dict[str, str]]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[LABEL_SHEET_NAME] if LABEL_SHEET_NAME in wb.sheetnames else wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        header_row = next(it, None)
        if header_row is None:
            raise ValueError("工作表為空")
        fields = [str(h).strip() if h is not None else "" for h in header_row]
        _check_columns(fields)
        rows: list[dict[str, str]] = []
        for values in it:
            row = {
                fields[i]: ("" if v is None else str(v).strip())
                for i, v in enumerate(values)
                if i < len(fields) and fields[i]
            }
            # 跳過整列空白（Excel 常見的尾端空列）
            if any(row.get(c) for c in ("tree_id", "doc_id", "physician_blueprint", "evidence_span")):
                rows.append(row)
        return rows
    finally:
        wb.close()


def load_sheet(path: Path) -> list[dict[str, str]]:
    """依副檔名讀取表單：.xlsx（醫師填寫用）或 .csv。"""
    if path.suffix.lower() == ".xlsx":
        return _load_xlsx(path)
    return _load_csv(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="檢查醫師標註表單")
    parser.add_argument("sheet", nargs="?", default=str(DEFAULT_SHEET), help="表單 CSV 路徑")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="所有列都必須已標註，否則視為錯誤（用於正式評估前）",
    )
    args = parser.parse_args(argv)

    try:
        rows = load_sheet(Path(args.sheet))
    except (OSError, ValueError, csv.Error) as e:
        print(f"[讀取失敗] {e}", file=sys.stderr)
        return 2

    result = check_rows(rows, require_complete=args.require_complete)
    print(f"總列數：{result['total']}　已標註：{result['labeled']}　未標註：{result['unlabeled']}")
    for msg in result["errors"]:
        print(f"[錯誤] {msg}")
    for msg in result["warnings"]:
        print(f"[警告] {msg}")
    if not result["errors"]:
        print("結果：通過（無錯誤）")
        return 0
    print(f"結果：失敗（{len(result['errors'])} 個錯誤）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
