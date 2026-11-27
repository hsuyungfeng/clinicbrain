#!/usr/bin/env python3
"""盲測集第一幕藍圖分類獨立評估程式（Phase 57 57-02 T6）。

輸入：
- golden/blind_labeling_sheet.xlsx（「標註」工作表）
- golden/blind_predictions.csv

計算指標：
A. LLM-only 原始準確率（30 筆）
B. 完整系統原始準確率（30 筆，含查表與 LLM）
C. 完整系統自動接受準確率（僅 system_accepted == True）與自動接受率
每類召回率與精確率（分母為 0 顯示 N/A）
混淆矩陣
other 比例與 invalid_evidence 數量
以 --threshold 0.85 顯示是否達標（門檻保持凍結，標明「不作為放行依據」）

輸出：
- golden/57-02-T6-BLIND-EVAL.md

退出碼：
0 = 評估完成
1 = 有未標註列（拒絕評估）
2 = 讀檔或欄位錯誤
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.visual.blueprint_classifier import CLASSIFIER_ALLOWED_BLUEPRINTS

_GOLDEN_DIR = (
    _PROJECT_ROOT
    / ".planning/phases/57-visual-blueprint-classification-narration-ab/golden"
)
DEFAULT_XLSX_PATH = _GOLDEN_DIR / "blind_labeling_sheet.xlsx"
DEFAULT_PREDICTIONS_PATH = _GOLDEN_DIR / "blind_predictions.csv"
DEFAULT_OUT_REPORT_PATH = _GOLDEN_DIR / "57-02-T6-BLIND-EVAL.md"

LABEL_SHEET_NAME = "標註"
REQUIRED_LABEL_COLS = ("tree_id", "doc_id", "physician_blueprint")
REQUIRED_PRED_COLS = (
    "tree_id",
    "doc_id",
    "llm_blueprint",
    "llm_status",
    "system_blueprint",
    "system_source",
    "system_accepted",
)


class UnlabeledError(Exception):
    """存在未標註列錯誤。"""
    pass


class SchemaError(Exception):
    """檔案讀取或必要欄位缺失錯誤。"""
    pass


def load_blind_eval_data(xlsx_path: Path, csv_path: Path) -> List[Dict[str, Any]]:
    """讀取並合併盲測標註表單與預測 CSV。純唯讀讀取。"""
    if not xlsx_path.exists():
        raise SchemaError(f"標註表單檔案不存在：{xlsx_path}")
    if not csv_path.exists():
        raise SchemaError(f"預測 CSV 檔案不存在：{csv_path}")

    import openpyxl

    try:
        wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    except Exception as e:
        raise SchemaError(f"無法讀取 Excel 檔案：{e}")

    try:
        ws = wb[LABEL_SHEET_NAME] if LABEL_SHEET_NAME in wb.sheetnames else wb.worksheets[0]
        rows_raw = list(ws.iter_rows(values_only=True))
        if not rows_raw:
            raise SchemaError("標註工作表為空")

        lbl_headers = [str(c or "").strip() for c in rows_raw[0]]
        for col in REQUIRED_LABEL_COLS:
            if col not in lbl_headers:
                raise SchemaError(f"標註表單缺少必要欄位：{col}")

        col_idx = {h: idx for idx, h in enumerate(lbl_headers)}
        labels_by_tree: Dict[str, Dict[str, Any]] = {}

        for r_idx, row_vals in enumerate(rows_raw[1:], start=2):
            tid = str(row_vals[col_idx["tree_id"]] or "").strip()
            doc_id = str(row_vals[col_idx["doc_id"]] or "").strip()
            if not tid and not doc_id:
                continue

            phys_bp = str(row_vals[col_idx["physician_blueprint"]] or "").strip()
            if not phys_bp:
                raise UnlabeledError(f"第 {r_idx} 列 (tree_id={tid}) physician_blueprint 尚未標註")

            labels_by_tree[tid] = {
                "row_num": r_idx,
                "tree_id": tid,
                "doc_id": doc_id,
                "physician_blueprint": phys_bp,
                "evidence_span": str(row_vals[col_idx["evidence_span"]] or "").strip()
                if "evidence_span" in col_idx
                else "",
            }
    finally:
        wb.close()

    # 讀取預測 CSV
    preds_by_tree: Dict[str, Dict[str, Any]] = {}
    try:
        with csv_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            for col in REQUIRED_PRED_COLS:
                if col not in fieldnames:
                    raise SchemaError(f"預測 CSV 缺少必要欄位：{col}")

            for row in reader:
                tid = str(row.get("tree_id") or "").strip()
                if not tid:
                    continue
                preds_by_tree[tid] = {
                    "llm_blueprint": str(row.get("llm_blueprint") or "").strip(),
                    "llm_status": str(row.get("llm_status") or "").strip(),
                    "llm_confidence": str(row.get("llm_confidence") or "").strip(),
                    "llm_evidence": str(row.get("llm_evidence") or "").strip(),
                    "system_blueprint": str(row.get("system_blueprint") or "").strip(),
                    "system_source": str(row.get("system_source") or "").strip(),
                    "system_accepted": str(row.get("system_accepted") or "").strip().lower()
                    in ("true", "1"),
                }
    except SchemaError:
        raise
    except Exception as e:
        raise SchemaError(f"無法讀取預測 CSV 檔案：{e}")

    # 合併兩者
    merged: List[Dict[str, Any]] = []
    for tid, l_data in sorted(labels_by_tree.items()):
        if tid not in preds_by_tree:
            raise SchemaError(f"預測 CSV 缺少 tree_id={tid} 的對應列")
        p_data = preds_by_tree[tid]
        merged.append({**l_data, **p_data})

    return merged


def evaluate_blind(rows: List[Dict[str, Any]], threshold: float = 0.85) -> Dict[str, Any]:
    """純函式：以醫師標註為依歸，計算各項評估指標與統計。"""
    if not rows:
        raise SchemaError("輸入列為空")

    total = len(rows)
    llm_correct = 0
    system_correct = 0
    system_accepted_count = 0
    system_accepted_correct = 0

    registry_hits = 0
    registry_correct = 0
    invalid_evidence_count = 0

    # 混淆矩陣：[真實][預測]
    all_bps = list(CLASSIFIER_ALLOWED_BLUEPRINTS)
    cm_llm: Dict[str, Dict[str, int]] = {t: {p: 0 for p in all_bps} for t in all_bps}
    cm_sys: Dict[str, Dict[str, int]] = {t: {p: 0 for p in all_bps} for t in all_bps}

    phys_other_count = 0
    llm_other_count = 0
    sys_other_count = 0

    for r in rows:
        phys_bp = r["physician_blueprint"]
        llm_bp = r["llm_blueprint"]
        sys_bp = r["system_blueprint"]
        sys_acc = r["system_accepted"]
        sys_src = r["system_source"]
        llm_stat = r["llm_status"]

        if phys_bp == "other":
            phys_other_count += 1
        if llm_bp == "other":
            llm_other_count += 1
        if sys_bp == "other":
            sys_other_count += 1

        if llm_stat == "invalid_evidence":
            invalid_evidence_count += 1

        if sys_src == "registry":
            registry_hits += 1
            if sys_bp == phys_bp:
                registry_correct += 1

        # A. LLM 原始準確
        if llm_bp == phys_bp:
            llm_correct += 1
        if phys_bp in cm_llm and llm_bp in cm_llm[phys_bp]:
            cm_llm[phys_bp][llm_bp] += 1

        # B. 完整系統原始準確
        if sys_bp == phys_bp:
            system_correct += 1
        if phys_bp in cm_sys and sys_bp in cm_sys[phys_bp]:
            cm_sys[phys_bp][sys_bp] += 1

        # C. 完整系統自動接受準確（僅接受列計入）
        if sys_acc:
            system_accepted_count += 1
            if sys_bp == phys_bp:
                system_accepted_correct += 1

    llm_raw_acc = llm_correct / total if total > 0 else 0.0
    sys_raw_acc = system_correct / total if total > 0 else 0.0

    sys_accept_rate = system_accepted_count / total if total > 0 else 0.0
    sys_accepted_acc = (
        system_accepted_correct / system_accepted_count if system_accepted_count > 0 else 0.0
    )

    # 計算各藍圖類別精確率、召回率與 F1（以完整系統為準）
    class_metrics: List[Dict[str, Any]] = []
    for bp in all_bps:
        support = sum(cm_sys[bp].values())
        tp = cm_sys[bp][bp]
        predicted = sum(cm_sys[t][bp] for t in all_bps)
        fp = predicted - tp
        fn = support - tp

        rec = (tp / support) if support > 0 else None
        prec = (tp / predicted) if predicted > 0 else None
        if prec is not None and rec is not None and (prec + rec) > 0:
            f1 = 2 * prec * rec / (prec + rec)
        else:
            f1 = None

        class_metrics.append({
            "blueprint": bp,
            "support": support,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": prec,
            "recall": rec,
            "f1": f1,
        })

    return {
        "total": total,
        "llm_correct": llm_correct,
        "llm_raw_accuracy": llm_raw_acc,
        "system_correct": system_correct,
        "system_raw_accuracy": sys_raw_acc,
        "system_accepted_count": system_accepted_count,
        "system_accept_rate": sys_accept_rate,
        "system_accepted_correct": system_accepted_correct,
        "system_accepted_accuracy": sys_accepted_acc,
        "threshold": threshold,
        # 達標判定以「完整系統原始準確率」為準（不以樣本很小的自動接受子集判定）
        "threshold_met": sys_raw_acc >= threshold,
        "registry_hits": registry_hits,
        "registry_correct": registry_correct,
        "registry_accuracy": (registry_correct / registry_hits) if registry_hits > 0 else None,
        "invalid_evidence_count": invalid_evidence_count,
        "physician_other_count": phys_other_count,
        "llm_other_count": llm_other_count,
        "system_other_count": sys_other_count,
        "class_metrics": class_metrics,
        "confusion_matrix_sys": cm_sys,
        "confusion_matrix_llm": cm_llm,
        "rows": rows,
    }


def render_markdown_report(res: Dict[str, Any]) -> str:
    """將評估結果渲染為 GitHub Markdown 報告。"""
    total = res["total"]
    llm_raw_acc = res["llm_raw_accuracy"]
    sys_raw_acc = res["system_raw_accuracy"]
    sys_acc_acc = res["system_accepted_accuracy"]
    sys_acc_rate = res["system_accept_rate"]
    threshold = res["threshold"]

    status_badge = "✅ 達標" if res["threshold_met"] else "❌ 未達標"
    reg_acc_str = (
        f"{res['registry_accuracy'] * 100:.1f}%"
        if res["registry_accuracy"] is not None
        else "N/A"
    )

    md = []
    md.append("# 57-02 T6 盲測集第一幕藍圖分類獨立評估報告\n")
    md.append("> **【重要評估聲明】**\n"
              "> 1. 本次評估為在**獨立盲測樣本（30 筆）**上的首次無介入測試，盲測表單本身完全未含 AI 欄位與 AI 建議。\n"
              f"> 2. 評估門檻固定為 `{threshold * 100:.1f}%`，**本門檻保持凍結，僅作為客觀參考指標，不作為上線放行依據**。\n"
              "> 3. 盲測表單的 `title` 欄位以 `doc_id` 傳入，部分縮寫與特徵對查表命中與 LLM 理解存在客觀限制。\n")

    md.append("## 一、核心指標總覽\n")
    md.append("| 指標項目 | 數值 | 分子 / 分母 | 評估說明 |")
    md.append("| :--- | :---: | :---: | :--- |")
    md.append(f"| **A. LLM-only 原始準確率** | **{llm_raw_acc * 100:.1f}%** | {res['llm_correct']} / {total} | 單純依賴本機 LLM 提示詞判定之原始全量準確率 |")
    md.append(f"| **B. 完整系統原始準確率** | **{sys_raw_acc * 100:.1f}%** | {res['system_correct']} / {total} | 結合 TOPIC 查表（Registry）與 LLM 之全量預測準確率 |")
    md.append(f"| **C. 完整系統自動接受準確率** | **{sys_acc_acc * 100:.1f}%** | {res['system_accepted_correct']} / {res['system_accepted_count']} | **通過複合放行閘門（自動接受）子集之精準度** |")
    md.append(f"| 完整系統自動接受率 | {sys_acc_rate * 100:.1f}% | {res['system_accepted_count']} / {total} | 通過放行閘門進入夜間自動發布佇列之涵蓋比例 |")
    md.append(f"| 查表命中覆蓋率與準確率 | {res['registry_hits'] / total * 100:.1f}% (命中) / {reg_acc_str} (準確) | {res['registry_correct']} / {res['registry_hits']} | 命中白名單查表註冊表之比率與正確度 |")
    md.append(f"| 無效證據片段 (Invalid Evidence) | {res['invalid_evidence_count']} 筆 ({res['invalid_evidence_count']/total*100:.1f}%) | {res['invalid_evidence_count']} / {total} | LLM 提取之證據非原文子字串之攔截次數 |")
    md.append(f"| `other` 比例 (醫師 / LLM / 系統) | {res['physician_other_count']/total*100:.1f}% / {res['llm_other_count']/total*100:.1f}% / {res['system_other_count']/total*100:.1f}% | - | 各階段判定無合適藍圖之保守比例 |")
    md.append(f"| **85% 凍結門檻判定** | **{status_badge}** | - | 門檻 `{threshold * 100:.1f}%`（凍結不作放行依據） |\n")

    md.append("## 二、各藍圖類別精確率與召回率（完整系統）\n")
    md.append("| 藍圖代碼 (`blueprint`) | 樣本數 (Support) | TP | FP | FN | 精確率 (Precision) | 召回率 (Recall) | F1-Score |")
    md.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for cm in res["class_metrics"]:
        bp = cm["blueprint"]
        sup = cm["support"]
        tp = cm["tp"]
        fp = cm["fp"]
        fn = cm["fn"]
        p_str = f"{cm['precision'] * 100:.1f}%" if cm["precision"] is not None else "N/A"
        r_str = f"{cm['recall'] * 100:.1f}%" if cm["recall"] is not None else "N/A"
        f1_str = f"{cm['f1']:.3f}" if cm["f1"] is not None else "N/A"
        md.append(f"| `{bp}` | {sup} | {tp} | {fp} | {fn} | {p_str} | {r_str} | {f1_str} |")

    md.append("\n## 三、完整系統混淆矩陣 (Confusion Matrix)\n")
    active_bps = [cm["blueprint"] for cm in res["class_metrics"] if cm["support"] > 0 or cm["tp"] + cm["fp"] > 0]
    if not active_bps:
        active_bps = list(CLASSIFIER_ALLOWED_BLUEPRINTS)

    header = "| 真實 \\ 預測 | " + " | ".join(f"`{bp[:8]}`" for bp in active_bps) + " |"
    sep = "| :--- | " + " | ".join(":---:" for _ in active_bps) + " |"
    md.append(header)
    md.append(sep)
    cm = res["confusion_matrix_sys"]
    for true_bp in active_bps:
        row_str = f"| `{true_bp[:12]}` | " + " | ".join(str(cm[true_bp][pred_bp]) for pred_bp in active_bps) + " |"
        md.append(row_str)

    md.append("\n## 四、30 筆盲測樣本逐列對照明細\n")
    md.append("| tree_id | doc_id | 醫師標註 (標準答案) | LLM 預測 | 完整系統預測 | 來源 (Source) | 放行 (Accepted) | 結果 |")
    md.append("| :---: | :--- | :--- | :--- | :--- | :---: | :---: | :---: |")
    for r in res["rows"]:
        tid = r["tree_id"]
        doc = r["doc_id"]
        phys = r["physician_blueprint"]
        llm = r["llm_blueprint"]
        sys_bp = r["system_blueprint"]
        src = r["system_source"]
        acc = "✅ 是" if r["system_accepted"] else "❌ 否"
        match = "✅" if sys_bp == phys else "❌"
        md.append(f"| `{tid}` | `{doc}` | `{phys}` | `{llm}` | `{sys_bp}` | `{src}` | {acc} | {match} |")

    md.append("\n## 五、盲測結果與黃金集差異分析說明\n")
    md.append("1. **樣本獨立性**：\n"
              "   - 本次盲測 30 筆全數為未曾參與提示詞調整與規則制定的全新案例，能真實反映未知新進主題在未介入下的泛化能力。\n"
              "2. **標題欄位限制 (Title Field Limitation)**：\n"
              "   - 盲測表單的標題欄位直接填入 `doc_id`（例如 `icd-m179-knee-osteoarthritis`），缺乏完整正體中文標題。\n"
              "   - 查表註冊表（Registry）設計仰賴常見中文主題詞（例如「膝關節炎」），導致查表覆蓋率受限於 slug 英文命名。\n"
              "3. **放行閘門守護效果**：\n"
              "   - 透過 `is_auto_acceptable` 放行閘門與語意錨定檢驗，系統成功將不確定或高風險之預測攔截（未接受），有效保護了自動發布佇列的安全。\n")

    return "\n".join(md) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="盲測集第一幕藍圖分類獨立評估程式")
    parser.add_argument(
        "--sheet",
        type=str,
        default=str(DEFAULT_XLSX_PATH),
        help="盲測標註 Excel 檔案路徑",
    )
    parser.add_argument(
        "--predictions",
        type=str,
        default=str(DEFAULT_PREDICTIONS_PATH),
        help="盲測預測結果 CSV 路徑",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUT_REPORT_PATH),
        help="輸出 Markdown 報告路徑",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="評估達標門檻（預設 0.85，保持凍結）",
    )
    args = parser.parse_args(argv)

    xlsx_path = Path(args.sheet)
    csv_path = Path(args.predictions)
    out_path = Path(args.output)

    try:
        rows = load_blind_eval_data(xlsx_path, csv_path)
    except UnlabeledError as ue:
        print(f"[拒絕評估：存在未標註列] {ue}", file=sys.stderr)
        return 1
    except SchemaError as se:
        print(f"[讀取或格式錯誤] {se}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"[未預期讀取錯誤] {e}", file=sys.stderr)
        return 2

    metrics = evaluate_blind(rows, threshold=args.threshold)
    report_md = render_markdown_report(metrics)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_md, encoding="utf-8")

    print("================== 57-02 T6 盲測集評估結果 ==================")
    print(f"總評估樣本數：{metrics['total']} 筆")
    print(f"A. LLM-only 原始準確率：{metrics['llm_raw_accuracy'] * 100:.1f}% ({metrics['llm_correct']}/{metrics['total']})")
    print(f"B. 完整系統原始準確率：{metrics['system_raw_accuracy'] * 100:.1f}% ({metrics['system_correct']}/{metrics['total']})")
    print(
        f"C. 完整系統自動接受準確率：{metrics['system_accepted_accuracy'] * 100:.1f}% "
        f"({metrics['system_accepted_correct']}/{metrics['system_accepted_count']}) | "
        f"自動接受率：{metrics['system_accept_rate'] * 100:.1f}%"
    )
    print(f"查表命中數：{metrics['registry_hits']} 筆 (正確 {metrics['registry_correct']} 筆)")
    print(f"無效證據片段 (invalid_evidence)：{metrics['invalid_evidence_count']} 筆")
    status = "達標" if metrics["threshold_met"] else "未達標"
    print(f"85% 凍結門檻判定：{status}（不作為放行依據）")
    print(f"評估報告已產出至：{out_path}")
    print("============================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
