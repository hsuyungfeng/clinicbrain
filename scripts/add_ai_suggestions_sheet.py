"""在醫師表單中加入「AI建議（僅供參考）」工作表（Phase 57 黃金標準集）。

- 對 physician_labeling_sheet.xlsx 每一列的 source_text，呼叫現有分類器
  （blueprint_classifier.classify_scene1_blueprint + 本地 LLM）取得建議藍圖與證據片段。
- 結果寫入獨立的「AI建議（僅供參考）」工作表，欄位名稱皆以 ai_ 開頭。
- 不修改「標註」工作表，不寫入 physician_blueprint / evidence_span；
  檢查程式只讀取「標註」工作表，因此 AI 建議不會被誤當成醫師標註。

用法（於 clinicbrain 目錄執行）：
    .venv/bin/python scripts/add_ai_suggestions_sheet.py            # 呼叫本地 LLM 產生建議
    .venv/bin/python scripts/add_ai_suggestions_sheet.py --dry-run  # 只檢查結構，不呼叫 LLM
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.visual.blueprint_classifier import classify_scene1_blueprint  # noqa: E402
from scripts.check_physician_labels import DEFAULT_SHEET, LABEL_SHEET_NAME, load_sheet  # noqa: E402

AI_SHEET_NAME = "AI建議（僅供參考）"
NOTICE = (
    "【注意】本工作表為系統 AI 建議，僅供參考，不是醫師標註。"
    "請逐列依原文自行判斷後，於「標註」工作表填寫 physician_blueprint 與 evidence_span；"
    "請勿直接複製本表內容作為標註。"
)
AI_HEADERS = ["tree_id", "doc_id", "ai_suggested_blueprint", "ai_confidence", "ai_evidence_span", "ai_status", "ai_reason"]
HEADER_ROW = 3  # 第 1 列為提示、第 2 列空白，表頭在第 3 列
DATA_START_ROW = HEADER_ROW + 1


def _ai_row(row: dict[str, str], llm_call) -> dict[str, str]:
    res = classify_scene1_blueprint(
        row.get("source_text", ""),
        llm_call,
        title=row.get("title", ""),
    )
    return {
        "tree_id": row.get("tree_id", ""),
        "doc_id": row.get("doc_id", ""),
        "ai_suggested_blueprint": str(res.get("blueprint", "")),
        "ai_confidence": f"{float(res.get('confidence', 0.0)):.2f}",
        "ai_evidence_span": str(res.get("evidence_span", "")),
        "ai_status": str(res.get("status", "")),
        "ai_reason": str(res.get("reason", "")),
    }


def build_ai_rows(rows: list[dict[str, str]], llm_call) -> list[dict[str, str]]:
    return [_ai_row(r, llm_call) for r in rows]


def write_ai_sheet(xlsx_path: Path, ai_rows: list[dict[str, str]]) -> None:
    wb = load_workbook(xlsx_path)
    if LABEL_SHEET_NAME not in wb.sheetnames:
        raise ValueError(f"找不到工作表：{LABEL_SHEET_NAME}")
    if AI_SHEET_NAME in wb.sheetnames:
        del wb[AI_SHEET_NAME]

    ws = wb.create_sheet(AI_SHEET_NAME, index=wb.sheetnames.index(LABEL_SHEET_NAME) + 1)
    ws["A1"] = NOTICE
    ws["A1"].font = Font(bold=True, color="9C0006")
    ws["A1"].fill = PatternFill("solid", fgColor="FFC7CE")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(AI_HEADERS))
    ws.row_dimensions[1].height = 36
    ws["A1"].alignment = Alignment(wrap_text=True, vertical="center")

    header_fill = PatternFill("solid", fgColor="F2F2F2")
    for idx, h in enumerate(AI_HEADERS, start=1):
        c = ws.cell(row=HEADER_ROW, column=idx, value=h)
        c.font = Font(bold=True)
        c.fill = header_fill

    for r_offset, rec in enumerate(ai_rows):
        for idx, h in enumerate(AI_HEADERS, start=1):
            c = ws.cell(row=DATA_START_ROW + r_offset, column=idx, value=rec.get(h, ""))
            c.alignment = Alignment(wrap_text=h in ("ai_evidence_span", "ai_reason"), vertical="top")

    widths = {"tree_id": 9, "doc_id": 28, "ai_suggested_blueprint": 24, "ai_confidence": 13,
              "ai_evidence_span": 44, "ai_status": 16, "ai_reason": 30}
    for idx, h in enumerate(AI_HEADERS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = widths[h]
    ws.freeze_panes = ws.cell(row=DATA_START_ROW, column=1)

    wb.save(xlsx_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="加入 AI 建議工作表（不寫入醫師欄位）")
    parser.add_argument("--sheet", default=str(DEFAULT_SHEET), help="醫師表單 .xlsx 路徑")
    parser.add_argument("--dry-run", action="store_true", help="不呼叫 LLM，只確認讀取與結構")
    args = parser.parse_args(argv)

    xlsx = Path(args.sheet)
    rows = load_sheet(xlsx)
    print(f"讀取 {len(rows)} 列")

    if args.dry_run:
        print("dry-run：不呼叫 LLM，未寫入任何檔案。")
        return 0

    from src.pageindex.llm_client import local_llm_call

    ai_rows = []
    for i, r in enumerate(rows, start=1):
        rec = _ai_row(r, local_llm_call)
        ai_rows.append(rec)
        print(f"[{i}/{len(rows)}] {rec['doc_id']} → {rec['ai_suggested_blueprint']} ({rec['ai_status']})")

    write_ai_sheet(xlsx, ai_rows)
    print(f"已寫入「{AI_SHEET_NAME}」工作表：{xlsx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
