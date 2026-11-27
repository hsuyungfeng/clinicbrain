#!/usr/bin/env python3
"""盲測集第一幕藍圖預測程式（Phase 57 57-02 T6）。

功能：
- 唯讀讀取盲測表單 golden/blind_labeling_sheet.xlsx（不修改表單）。
- 對每筆資料平行或序列執行：
  1. LLM-only 預測：classify_scene1_blueprint(source_text, llm_call, title=doc_id)
  2. 完整系統預測：先執行 lookup_blueprint(title=doc_id)；若命中則以查表為準（source='registry', accepted=True）；
     未命中則採用 LLM 結果，並通過 is_auto_acceptable 放行閘門決定 system_accepted。
- 產出預測結果至 golden/blind_predictions.csv：
  欄位：tree_id, doc_id, llm_blueprint, llm_status, llm_confidence, llm_evidence, system_blueprint, system_source, system_accepted
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
from typing import Any, Callable, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.visual.blueprint_classifier import classify_scene1_blueprint
from src.visual.blueprint_registry import is_auto_acceptable, lookup_blueprint

_GOLDEN_DIR = (
    _PROJECT_ROOT
    / ".planning/phases/57-visual-blueprint-classification-narration-ab/golden"
)
DEFAULT_INPUT_SHEET = _GOLDEN_DIR / "blind_labeling_sheet.xlsx"
DEFAULT_OUTPUT_CSV = _GOLDEN_DIR / "blind_predictions.csv"
LABEL_SHEET_NAME = "標註"
REQUIRED_COLUMNS = ("tree_id", "doc_id", "source_text")


def load_blind_input(xlsx_path: Path) -> List[Dict[str, str]]:
    """唯讀讀取盲測 Excel 表單之輸入列。"""
    if not xlsx_path.exists():
        raise FileNotFoundError(f"找不到盲測表單檔案：{xlsx_path}")

    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    try:
        ws = wb[LABEL_SHEET_NAME] if LABEL_SHEET_NAME in wb.sheetnames else wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        header_row = next(it, None)
        if header_row is None:
            raise ValueError("工作表為空")
        fields = [str(h).strip() if h is not None else "" for h in header_row]

        missing = [c for c in REQUIRED_COLUMNS if c not in fields]
        if missing:
            raise ValueError(f"缺少必要欄位：{', '.join(missing)}")

        col_map = {f: idx for idx, f in enumerate(fields)}
        rows: List[Dict[str, str]] = []
        for values in it:
            tid = str(values[col_map["tree_id"]] or "").strip()
            doc_id = str(values[col_map["doc_id"]] or "").strip()
            source = str(values[col_map["source_text"]] or "").strip()
            if not tid and not doc_id:
                continue
            rows.append({
                "tree_id": tid,
                "doc_id": doc_id,
                "source_text": source,
            })
        return rows
    finally:
        wb.close()


def predict_rows(
    rows: List[Dict[str, str]],
    llm_call: Callable[[str], str],
    verbose: bool = True,
) -> List[Dict[str, Any]]:
    """對每列執行 LLM-only 與完整系統預測（純函式核心邏輯，支援傳入自訂 llm_call）。"""
    results: List[Dict[str, Any]] = []
    total = len(rows)

    for idx, r in enumerate(rows, start=1):
        tid = r["tree_id"]
        doc_id = r["doc_id"]
        source_text = r["source_text"]
        title = r.get("title") or doc_id

        if verbose:
            print(f"[{idx}/{total}] 處理中: tree_id={tid}, doc_id={doc_id} ...", flush=True)

        # 1. 完整系統先查表（使用真實中文標題）
        registry_bp = lookup_blueprint(title=title)

        # 2. 執行 LLM-only 預測
        llm_res = classify_scene1_blueprint(
            source_text=source_text,
            llm_call=llm_call,
            title=title,
        )

        llm_bp = str(llm_res.get("blueprint", "other")).strip()
        llm_status = str(llm_res.get("status", "needs_review")).strip()
        llm_conf = float(llm_res.get("confidence", 0.0))
        llm_ev = str(llm_res.get("evidence_span", "")).strip()

        # 3. 完整系統決策與放行閘門
        if registry_bp is not None:
            sys_bp = registry_bp
            sys_source = "registry"
            sys_accepted = True
        else:
            sys_bp = llm_bp
            sys_source = "llm"
            # 傳給 is_auto_acceptable 閘門驗證
            sys_accepted = is_auto_acceptable({
                "blueprint": sys_bp,
                "status": llm_status,
                "evidence_span": llm_ev,
                "source": "llm",
            })

        item = {
            "tree_id": tid,
            "doc_id": doc_id,
            "llm_blueprint": llm_bp,
            "llm_status": llm_status,
            "llm_confidence": f"{llm_conf:.2f}",
            "llm_evidence": llm_ev,
            "system_blueprint": sys_bp,
            "system_source": sys_source,
            "system_accepted": str(sys_accepted),
        }
        results.append(item)

        if verbose:
            print(
                f"    -> LLM: {llm_bp} ({llm_status}), "
                f"System: {sys_bp} (src={sys_source}, accepted={sys_accepted})",
                flush=True,
            )

    return results


def write_predictions_csv(predictions: List[Dict[str, Any]], out_path: Path) -> None:
    """將預測結果輸出為標準 CSV。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "tree_id",
        "doc_id",
        "llm_blueprint",
        "llm_status",
        "llm_confidence",
        "llm_evidence",
        "system_blueprint",
        "system_source",
        "system_accepted",
    ]
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in predictions:
            writer.writerow(p)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="盲測集第一幕藍圖預測程式")
    parser.add_argument(
        "--sheet",
        type=str,
        default=str(DEFAULT_INPUT_SHEET),
        help="盲測 Excel 檔案路徑",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT_CSV),
        help="輸出 CSV 檔案路徑",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="不印出逐列進度",
    )
    args = parser.parse_args(argv)

    sheet_path = Path(args.sheet)
    out_path = Path(args.output)

    try:
        rows = load_blind_input(sheet_path)
        # 修正：盲測表單的 title 欄為 doc_id（英文代碼），查表關鍵字為中文，必須改用真實標題。
        # 標題由 clinic.db.page_index_trees.title 以 doc_id 唯讀查得；不修改盲測表單。
        import sqlite3 as _sqlite3
        _con = _sqlite3.connect('file:' + str(Path(__file__).resolve().parent.parent / 'clinic.db') + '?mode=ro', uri=True)
        _titles = {d: t for d, t in _con.execute('SELECT doc_id, title FROM page_index_trees')}
        _con.close()
        for _r in rows:
            _r['title'] = _titles.get(_r['doc_id']) or _r.get('title') or _r['doc_id']

    except Exception as e:
        print(f"[讀取失敗] {e}", file=sys.stderr)
        return 2

    print(f"成功讀入 {len(rows)} 筆盲測資料，開始進行預測...")

    # 本地 LLM 呼叫建構（依 57-02 T6 計畫規格）
    from src.pageindex.llm_client import local_llm_call

    llm_call = lambda p: local_llm_call(
        p,
        timeout=420,
        sampling={"chat_template_kwargs": {"enable_thinking": False}},
    )

    try:
        predictions = predict_rows(rows, llm_call=llm_call, verbose=not args.quiet)
        write_predictions_csv(predictions, out_path)
        print(f"預測完成！已寫入：{out_path}")
        return 0
    except Exception as e:
        print(f"[預測過程失敗] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
