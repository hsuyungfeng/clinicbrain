"""由 physician_labeling_sheet.csv 產生帶藍圖下拉選單的 Excel 表單（Phase 57 黃金標準集）。

CSV 格式無法保存資料驗證（下拉選單），因此另產 .xlsx 供醫師填寫：
- 「標註」工作表：內容與 CSV 相同，source_text 自動換行。
- physician_blueprint 欄：下拉選單，選項為 12 個藍圖 + other，拼錯會被 Excel 擋下。
- 「藍圖選項」隱藏工作表：下拉選單的選項來源，與 classifier 的藍圖清單同一來源。

用法（於 clinicbrain 目錄執行）：
    .venv/bin/python scripts/build_physician_labeling_xlsx.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.visual.blueprint_classifier import CLASSIFIER_ALLOWED_BLUEPRINTS  # noqa: E402

GOLDEN_DIR = _PROJECT_ROOT / ".planning/phases/57-visual-blueprint-classification-narration-ab/golden"
SRC_CSV = GOLDEN_DIR / "physician_labeling_sheet.csv"
OUT_XLSX = GOLDEN_DIR / "physician_labeling_sheet.xlsx"
LABEL_SHEET = "標註"
OPTIONS_SHEET = "藍圖選項"
BLUEPRINT_COLUMN = "physician_blueprint"
WRAP_COLUMNS = ("source_text", "physician_notes")


def build(csv_path: Path = SRC_CSV, xlsx_path: Path = OUT_XLSX) -> Path:
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        rows = list(reader)

    if BLUEPRINT_COLUMN not in headers:
        raise ValueError(f"CSV 缺少欄位：{BLUEPRINT_COLUMN}")

    wb = Workbook()
    ws = wb.active
    ws.title = LABEL_SHEET

    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="DDEBF7")
    ws.append(headers)
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill

    for row in rows:
        ws.append([row.get(h, "") for h in headers])

    widths = {"tree_id": 9, "doc_id": 28, "title": 16, "source_text": 70,
              BLUEPRINT_COLUMN: 24, "evidence_span": 40, "physician_notes": 30}
    for idx, h in enumerate(headers, start=1):
        letter = get_column_letter(idx)
        ws.column_dimensions[letter].width = widths.get(h, 18)
        if h in WRAP_COLUMNS:
            for r in range(2, len(rows) + 2):
                ws[f"{letter}{r}"].alignment = Alignment(wrap_text=True, vertical="top")
        else:
            for r in range(2, len(rows) + 2):
                ws[f"{letter}{r}"].alignment = Alignment(vertical="top")

    ws.freeze_panes = "A2"

    # 隱藏的選項工作表，作為下拉選單來源
    opts = wb.create_sheet(OPTIONS_SHEET)
    opts["A1"] = "藍圖代碼（下拉選單來源，請勿編輯）"
    opts["A1"].font = header_font
    for i, bp in enumerate(CLASSIFIER_ALLOWED_BLUEPRINTS, start=2):
        opts[f"A{i}"] = bp
    opts.column_dimensions["A"].width = 30
    opts.sheet_state = "hidden"
    last_opt_row = 1 + len(CLASSIFIER_ALLOWED_BLUEPRINTS)

    bp_letter = get_column_letter(headers.index(BLUEPRINT_COLUMN) + 1)
    dv = DataValidation(
        type="list",
        formula1=f"'{OPTIONS_SHEET}'!$A$2:$A${last_opt_row}",
        allow_blank=True,
        showDropDown=False,  # 注意：openpyxl 的 showDropDown=True 反而會隱藏下拉箭頭
        showErrorMessage=True,
        errorStyle="stop",
        errorTitle="藍圖代碼不合法",
        error="請從下拉選單選擇藍圖代碼（或 other）。",
        showInputMessage=True,
        promptTitle="藍圖選擇",
        prompt="請從下拉選單選擇；不確定時選 other。",
    )
    ws.add_data_validation(dv)
    dv.add(f"{bp_letter}2:{bp_letter}{len(rows) + 1}")

    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(xlsx_path)
    return xlsx_path


if __name__ == "__main__":
    out = build()
    print(f"已產生：{out}")
