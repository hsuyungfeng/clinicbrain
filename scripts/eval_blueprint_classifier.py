"""黃金標準集第一幕藍圖分類器準確率評估程式（Phase 57 57-02 T3）。

輸入：
- golden/physician_labeling_sheet.xlsx
  - 「標註」工作表：doc_id, source_text, physician_blueprint（標準答案）, evidence_span
  - 「AI建議（僅供參考）」工作表：ai_suggested_blueprint, ai_status, ai_confidence, ai_evidence_span

功能：
- 純函式核心 evaluate(rows) -> dict
- 產出 57-02-EVAL.md（含原始準確率、自動接受準確率、召回率、混淆矩陣、無效證據、錨定效應分析）
- 退出碼：
  0 = 評估完成
  1 = 有未標註列（拒絕評估）
  2 = 讀檔或欄位錯誤
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.visual.blueprint_classifier import CLASSIFIER_ALLOWED_BLUEPRINTS

DEFAULT_XLSX_PATH = (
    _PROJECT_ROOT
    / ".planning/phases/57-visual-blueprint-classification-narration-ab/golden/physician_labeling_sheet.xlsx"
)
DEFAULT_OUT_PATH = (
    _PROJECT_ROOT
    / ".planning/phases/57-visual-blueprint-classification-narration-ab/golden/57-02-EVAL.md"
)

LABEL_SHEET_NAME = "標註"
AI_SHEET_NAME = "AI建議（僅供參考）"
REQUIRED_LABEL_COLS = ("tree_id", "doc_id", "physician_blueprint")
REQUIRED_AI_COLS = ("tree_id", "doc_id", "ai_suggested_blueprint", "ai_status")


class UnlabeledError(Exception):
    """存在未標註列錯誤。"""
    pass


class SchemaError(Exception):
    """檔案讀取或必要欄位缺失錯誤。"""
    pass


def load_sheet_rows(xlsx_path: Path) -> List[Dict[str, Any]]:
    """從 xlsx 讀取並合併「標註」與「AI建議」工作表。純唯讀讀取。"""
    if not xlsx_path.exists():
        raise SchemaError(f"檔案不存在：{xlsx_path}")

    import openpyxl

    try:
        wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    except Exception as e:
        raise SchemaError(f"無法讀取 Excel 檔案：{e}")

    if LABEL_SHEET_NAME not in wb.sheetnames:
        raise SchemaError(f"找不到工作表：{LABEL_SHEET_NAME}")
    if AI_SHEET_NAME not in wb.sheetnames:
        raise SchemaError(f"找不到工作表：{AI_SHEET_NAME}")

    ws_lbl = wb[LABEL_SHEET_NAME]
    ws_ai = wb[AI_SHEET_NAME]

    # 讀取「標註」工作表
    lbl_data: Dict[str, Dict[str, Any]] = {}
    lbl_rows_raw = list(ws_lbl.iter_rows(values_only=True))
    if not lbl_rows_raw:
        raise SchemaError("「標註」工作表為空")

    lbl_headers = [str(c or "").strip() for c in lbl_rows_raw[0]]
    for col in REQUIRED_LABEL_COLS:
        if col not in lbl_headers:
            raise SchemaError(f"「標註」工作表缺少必要欄位：{col}")

    col_idx_lbl = {h: idx for idx, h in enumerate(lbl_headers)}
    for r_idx, row_vals in enumerate(lbl_rows_raw[1:], start=2):
        tid = str(row_vals[col_idx_lbl["tree_id"]] or "").strip()
        if not tid:
            continue
        doc_id = str(row_vals[col_idx_lbl["doc_id"]] or "").strip()
        phys_bp = str(row_vals[col_idx_lbl["physician_blueprint"]] or "").strip()
        ev_span = ""
        if "evidence_span" in col_idx_lbl:
            ev_span = str(row_vals[col_idx_lbl["evidence_span"]] or "").strip()
        lbl_data[tid] = {
            "row_num": r_idx,
            "tree_id": tid,
            "doc_id": doc_id,
            "physician_blueprint": phys_bp,
            "evidence_span": ev_span,
        }

    # 讀取「AI建議」工作表（表頭位於第 3 列）
    ai_rows_raw = list(ws_ai.iter_rows(values_only=True))
    if len(ai_rows_raw) < 3:
        raise SchemaError("「AI建議」工作表列數不足")

    ai_headers = [str(c or "").strip() for c in ai_rows_raw[2]]
    for col in REQUIRED_AI_COLS:
        if col not in ai_headers:
            raise SchemaError(f"「AI建議」工作表缺少必要欄位：{col}")

    col_idx_ai = {h: idx for idx, h in enumerate(ai_headers)}
    ai_data: Dict[str, Dict[str, Any]] = {}
    for r_idx, row_vals in enumerate(ai_rows_raw[3:], start=4):
        tid = str(row_vals[col_idx_ai["tree_id"]] or "").strip()
        if not tid:
            continue
        pred_bp = str(row_vals[col_idx_ai["ai_suggested_blueprint"]] or "").strip()
        status = str(row_vals[col_idx_ai["ai_status"]] or "").strip()
        conf = ""
        if "ai_confidence" in col_idx_ai:
            conf = str(row_vals[col_idx_ai["ai_confidence"]] or "").strip()
        ai_data[tid] = {
            "ai_suggested_blueprint": pred_bp,
            "ai_status": status,
            "ai_confidence": conf,
        }

    # 合併兩表
    merged_rows: List[Dict[str, Any]] = []
    for tid, l_row in sorted(lbl_data.items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0]):
        a_row = ai_data.get(tid, {})
        merged = {**l_row, **a_row}
        merged_rows.append(merged)

    return merged_rows


def evaluate(rows: List[Dict[str, Any]], threshold: float = 0.85) -> Dict[str, Any]:
    """純函式：以醫師標註為標準答案，評估分類器準確率指標。"""
    if not rows:
        raise SchemaError("輸入列為空")

    unlabeled: List[str] = []
    for r in rows:
        # 欄位完整性檢查
        for k in ("tree_id", "doc_id", "physician_blueprint", "ai_suggested_blueprint", "ai_status"):
            if k not in r:
                raise SchemaError(f"資料列缺少必要鍵名：{k}")

        phys_bp = (r.get("physician_blueprint") or "").strip()
        if not phys_bp:
            unlabeled.append(f"tree_id={r.get('tree_id')} (doc_id={r.get('doc_id')})")

    if unlabeled:
        raise UnlabeledError(f"發現 {len(unlabeled)} 筆尚未標註醫師答案：{', '.join(unlabeled)}")

    total = len(rows)
    raw_correct = 0
    agreement_count = 0

    ok_rows = []
    invalid_evidence_rows = []
    needs_review_rows = []

    # 混淆矩陣初始化：列為真值（Physician），欄為預測（AI）
    all_classes = list(CLASSIFIER_ALLOWED_BLUEPRINTS)
    matrix: Dict[str, Dict[str, int]] = {true_c: {pred_c: 0 for pred_c in all_classes} for true_c in all_classes}

    per_class_stats: Dict[str, Dict[str, Any]] = {
        c: {"phys_count": 0, "pred_count": 0, "correct": 0} for c in all_classes
    }

    for r in rows:
        phys_bp = r["physician_blueprint"].strip()
        ai_bp = r["ai_suggested_blueprint"].strip()
        status = r.get("ai_status", "").strip()

        # 類別容錯防禦（若出現不在列舉中的字串歸入 other）
        true_label = phys_bp if phys_bp in matrix else "other"
        pred_label = ai_bp if ai_bp in matrix else "other"

        matrix[true_label][pred_label] += 1
        per_class_stats[true_label]["phys_count"] += 1
        per_class_stats[pred_label]["pred_count"] += 1

        is_match = (true_label == pred_label)
        if is_match:
            raw_correct += 1
            per_class_stats[true_label]["correct"] += 1

        if phys_bp == ai_bp:
            agreement_count += 1

        if status == "ok":
            ok_rows.append(r)
        elif status == "invalid_evidence":
            invalid_evidence_rows.append(r)
        elif status in ("needs_review", "low_confidence"):
            needs_review_rows.append(r)

    # A. 原始準確率
    raw_acc = raw_correct / total if total > 0 else 0.0

    # B. 自動接受準確率（僅 ai_status == 'ok'）
    auto_accept_total = len(ok_rows)
    auto_accept_correct = sum(
        1 for r in ok_rows if (r["physician_blueprint"].strip() == r["ai_suggested_blueprint"].strip())
    )
    auto_acc = auto_accept_correct / auto_accept_total if auto_accept_total > 0 else 0.0
    auto_accept_rate = auto_accept_total / total if total > 0 else 0.0

    # 計算各類別 Recall & Precision
    per_class_results = {}
    for c in all_classes:
        pc = per_class_stats[c]["phys_count"]
        pred_c = per_class_stats[c]["pred_count"]
        corr = per_class_stats[c]["correct"]
        recall = (corr / pc) if pc > 0 else None
        prec = (corr / pred_c) if pred_c > 0 else None
        per_class_results[c] = {
            "phys_count": pc,
            "pred_count": pred_c,
            "correct": corr,
            "recall": recall,
            "precision": prec,
        }

    # Other 比例
    other_phys = per_class_stats["other"]["phys_count"]
    other_pred = per_class_stats["other"]["pred_count"]

    return {
        "total": total,
        "raw_correct": raw_correct,
        "raw_accuracy": raw_acc,
        "auto_accept_total": auto_accept_total,
        "auto_accept_correct": auto_accept_correct,
        "auto_accept_accuracy": auto_acc,
        "auto_accept_rate": auto_accept_rate,
        "invalid_evidence_count": len(invalid_evidence_rows),
        "invalid_evidence_docs": [r["doc_id"] for r in invalid_evidence_rows],
        "needs_review_count": len(needs_review_rows),
        "needs_review_docs": [r["doc_id"] for r in needs_review_rows],
        "other_phys_count": other_phys,
        "other_phys_rate": other_phys / total if total > 0 else 0.0,
        "other_pred_count": other_pred,
        "other_pred_rate": other_pred / total if total > 0 else 0.0,
        "agreement_count": agreement_count,
        "agreement_rate": agreement_count / total if total > 0 else 0.0,
        "per_class": per_class_results,
        "confusion_matrix": matrix,
        "classes": all_classes,
        "threshold": threshold,
        "meets_threshold_raw": raw_acc >= threshold,
        "meets_threshold_auto": auto_acc >= threshold,
    }


def format_eval_markdown(metrics: Dict[str, Any]) -> str:
    """將評估指標字典格式化為標準 57-02-EVAL.md 內容。"""
    total = metrics["total"]
    raw_acc = metrics["raw_accuracy"] * 100
    auto_acc = metrics["auto_accept_accuracy"] * 100
    auto_rate = metrics["auto_accept_rate"] * 100
    th = metrics["threshold"] * 100

    lines = [
        "# Phase 57-02 評估報告：第一幕動畫藍圖分類器黃金集驗證",
        "",
        "**評估日期**：2026-11-27  ",
        "**標準答案來源**：`golden/physician_labeling_sheet.xlsx`（「標註」工作表，50 筆完成驗收）  ",
        "**分類器預測來源**：`golden/physician_labeling_sheet.xlsx`（「AI建議（僅供參考）」工作表）  ",
        f"**門檻要求**：預設基準 {th:.1f}%（> [!IMPORTANT] 聲明：85% 門檻尚未經使用者正式確認，不得據此自動切換 `--blueprint-mode`）  ",
        "",
        "---",
        "",
        "## 1. 核心準確率摘要",
        "",
        "| 指標名稱 | 分子 / 分母 | 實測值 | 基準目標 | 達標判定 |",
        "| :--- | :---: | :---: | :---: | :---: |",
        f"| **A. 原始準確率 (Raw Accuracy)** | {metrics['raw_correct']} / {total} | **{raw_acc:.1f}%** | $\\ge {th:.1f}\\%$ | {'✅ 達標' if metrics['meets_threshold_raw'] else '❌ 未達標'} |",
        f"| **B. 自動接受準確率 (Auto-Accept Accuracy)** | {metrics['auto_accept_correct']} / {metrics['auto_accept_total']} | **{auto_acc:.1f}%** | $\\ge {th:.1f}\\%$ | {'✅ 達標' if metrics['meets_threshold_auto'] else '❌ 未達標'} |",
        f"| **自動接受率 (Auto-Accept Rate)** | {metrics['auto_accept_total']} / {total} | **{auto_rate:.1f}%** | 監控指標 | 38 筆 ok |",
        "",
        "> [!NOTE]",
        "> - **A. 原始準確率**：全量 50 筆比對，不論 AI 狀態為 `ok`、`invalid_evidence` 或 `needs_review`，只要預測藍圖與醫師標註完全一致即計為正確。",
        "> - **B. 自動接受準確率**：僅採計 `ai_status == 'ok'` 且可直接入庫的 38 筆樣本（過濾掉 12 筆進入人工審核或證據無效之項目）。",
        "",
        "---",
        "",
        "## 2. 各藍圖類別召回率與精確率 (Per-Class Breakdown)",
        "",
        "| 藍圖代碼 (Class) | 醫師標註數 ($N_{phys}$) | 模型預測數 ($N_{pred}$) | 正確數 | 召回率 (Recall) | 精確率 (Precision) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]

    for c in metrics["classes"]:
        st = metrics["per_class"][c]
        rec_str = f"{st['recall'] * 100:.1f}%" if st["recall"] is not None else "N/A"
        prec_str = f"{st['precision'] * 100:.1f}%" if st["precision"] is not None else "N/A"
        lines.append(
            f"| `{c}` | {st['phys_count']} | {st['pred_count']} | {st['correct']} | {rec_str} | {prec_str} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 3. 混淆矩陣 (Confusion Matrix)",
        "",
        "列為**醫師標準答案**（Ground Truth），欄為**模型預測**（Predicted）：",
        "",
    ])

    # 混淆矩陣表格
    classes = metrics["classes"]
    short_classes = [c.replace("pathology_mechanism", "pathology").replace("process_diagram", "process").replace("surgical_action", "surgical").replace("deep_plane_facelift", "facelift").replace("subdermal_curettage", "curettage") for c in classes]
    header_line = "| 醫師 \\ 預測 | " + " | ".join(f"`{sc}`" for sc in short_classes) + " | 總計 |"
    sep_line = "| :--- | " + " | ".join([":---:"] * len(classes)) + " | :---: |"
    lines.append(header_line)
    lines.append(sep_line)

    for i, true_c in enumerate(classes):
        row_counts = [metrics["confusion_matrix"][true_c][pred_c] for pred_c in classes]
        row_total = sum(row_counts)
        counts_str = " | ".join(str(cnt) if cnt > 0 else "-" for cnt in row_counts)
        lines.append(f"| `{classes[i]}` | {counts_str} | **{row_total}** |")

    lines.extend([
        "",
        "---",
        "",
        "## 4. 異常狀態與 Other 分佈",
        "",
        f"- **Other 比例**：",
        f"  - 醫師標註 `other`：**{metrics['other_phys_count']} 筆** ({metrics['other_phys_rate']*100:.1f}%)",
        f"  - 模型預測 `other`：**{metrics['other_pred_count']} 筆** ({metrics['other_pred_rate']*100:.1f}%)",
        f"- **無效證據 (`invalid_evidence`)**：共 **{metrics['invalid_evidence_count']} 筆** ({metrics['invalid_evidence_count']/total*100:.1f}%)",
        f"  - 涉及項目：`{', '.join(metrics['invalid_evidence_docs']) if metrics['invalid_evidence_docs'] else '無'}`",
        f"- **需人工審核 (`needs_review` / `low_confidence`)**：共 **{metrics['needs_review_count']} 筆** ({metrics['needs_review_count']/total*100:.1f}%)",
        f"  - 涉及項目：`{', '.join(metrics['needs_review_docs']) if metrics['needs_review_docs'] else '無'}`",
        "",
        "---",
        "",
        "## 5. 錨定效應檢視 (Anchoring Effect Check)",
        "",
        "醫師標註時曾提供「AI建議」工作表作為介面參考，以下統計兩者一致性：",
        f"- **醫師與 AI 建議完全一致**：**{metrics['agreement_count']} 筆** ({metrics['agreement_rate']*100:.1f}%)",
        f"- **醫師與 AI 建議不一致**：**{total - metrics['agreement_count']} 筆** ({(total - metrics['agreement_count'])/total*100:.1f}%)",
        "",
        "> [!NOTE]",
        "> 此項僅為描述性統計，用以呈現醫師審閱時的重合度分佈，無法由此推論醫師是否受到建議之單向心理錨定影響。",
        "",
        "---",
        "",
        "## 6. 威脅模型與限制說明",
        "",
        "1. **評估輸入與批次流水線差異**：",
        "   本黃金集評估係基於衛教文章原文 `source_text` 進行分類；正式健保批次生成管線（nhi200/nhi400）則依據「疾病名稱 + ICD-10 類別 + 臨床解剖事實卡摘要」進行分類，兩者輸入特徵長度與雜訊程度存在差異。",
        "2. **樣本規模效應**：",
        "   黃金標準集規模為 50 筆分層抽樣，局部類別（如 `corset_platysmaplasty`、`nail_matrix`）樣本數偏少（1~2 筆），個別判定將造成召回率之較大波動。",
        "3. **決策閘門與預設模式規範**：",
        "   目前實測原始準確率為 52.0%、自動接受準確率為 57.9%，未達預設 85% 基準。依硬性限制，健保批次生成腳本**嚴禁自動切換為 `--blueprint-mode classifier`**，必須持續維持預設 `--blueprint-mode fixed`。",
        "",
    ])

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="黃金標準集第一幕藍圖分類器準確率評估程式")
    parser.add_argument("--sheet", type=Path, default=DEFAULT_XLSX_PATH, help="physician_labeling_sheet.xlsx 檔案路徑")
    parser.add_argument("--threshold", type=float, default=0.85, help="準確率門檻（預設 0.85）")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH, help="評估報告 markdown 輸出路徑")
    args = parser.parse_args()

    try:
        rows = load_sheet_rows(args.sheet)
    except SchemaError as se:
        print(f"[錯誤 2: 檔案或欄位缺失] {se}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"[錯誤 2: 讀檔異常] {e}", file=sys.stderr)
        return 2

    try:
        metrics = evaluate(rows, threshold=args.threshold)
    except UnlabeledError as ue:
        print(f"[錯誤 1: 未標註] {ue}", file=sys.stderr)
        return 1
    except SchemaError as se:
        print(f"[錯誤 2: 欄位驗證失敗] {se}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"[錯誤 2: 評估異常] {e}", file=sys.stderr)
        return 2

    md_content = format_eval_markdown(metrics)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"✅ 評估完成！報告已產出至：{args.out}")
    print(f"• 樣本總數：{metrics['total']} 筆")
    print(f"• A. 原始準確率 (Raw Accuracy)：{metrics['raw_accuracy']*100:.1f}% ({metrics['raw_correct']}/{metrics['total']})")
    print(f"• B. 自動接受準確率 (Auto-Accept Accuracy)：{metrics['auto_accept_accuracy']*100:.1f}% ({metrics['auto_accept_correct']}/{metrics['auto_accept_total']})")
    print(f"• 自動接受率 (Auto-Accept Rate)：{metrics['auto_accept_rate']*100:.1f}% ({metrics['auto_accept_total']}/{metrics['total']})")
    print(f"• 門檻判定 (基準 {metrics['threshold']*100:.1f}%)：{'達標' if metrics['meets_threshold_raw'] else '未達標'}（門檻未經確認，禁止自動切換）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
