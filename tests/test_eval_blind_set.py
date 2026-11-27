"""
57-02 T6 測試：盲測集評估程式測試 (tests/test_eval_blind_set.py)。

測試項目：
1. evaluate_blind 指標計算：LLM-only 原始準確率、完整系統原始準確率、自動接受準確率。
2. 未接受列（system_accepted == False）不計入 C 指標的分子與分母。
3. 分母為 0 時精確率與召回率呈現 None / N/A。
4. 查表命中的 system_source == 'registry' 正確追蹤統計。
5. 退出碼測試：
   - 存在未標註列時回傳退出碼 1。
   - 缺必要欄位或檔案不存在時回傳退出碼 2。
"""

import csv
from pathlib import Path
import pytest
import openpyxl

from scripts.eval_blind_set import (
    SchemaError,
    UnlabeledError,
    evaluate_blind,
    load_blind_eval_data,
    main as eval_main,
    render_markdown_report,
)


def _create_mock_xlsx(path: Path, rows: list[dict[str, str]]) -> None:
    """建立臨時測試用 Excel 標註檔案。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "標註"
    headers = ["tree_id", "doc_id", "source_text", "physician_blueprint", "evidence_span"]
    ws.append(headers)
    for r in rows:
        ws.append([
            r.get("tree_id", ""),
            r.get("doc_id", ""),
            r.get("source_text", ""),
            r.get("physician_blueprint", ""),
            r.get("evidence_span", ""),
        ])
    wb.save(path)


def _create_mock_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """建立臨時測試用預測結果 CSV 檔案。"""
    headers = [
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
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def test_eval_metrics_calculation_and_accepted_filter(tmp_path: Path):
    """驗證各項指標計算，特別是未接受列（system_accepted=False）絕不計入 C 分子與分母。"""
    rows = [
        # 1. 查表命中，預測正確，接受
        {
            "tree_id": "T1",
            "doc_id": "doc1",
            "physician_blueprint": "laser_action",
            "llm_blueprint": "skin_energy",
            "system_blueprint": "laser_action",
            "system_source": "registry",
            "system_accepted": True,
            "llm_status": "ok",
        },
        # 2. LLM預測正確，通過閘門接受
        {
            "tree_id": "T2",
            "doc_id": "doc2",
            "physician_blueprint": "skin_energy",
            "llm_blueprint": "skin_energy",
            "system_blueprint": "skin_energy",
            "system_source": "llm",
            "system_accepted": True,
            "llm_status": "ok",
        },
        # 3. LLM預測錯誤，但通過閘門接受（拉低接受準確率）
        {
            "tree_id": "T3",
            "doc_id": "doc3",
            "physician_blueprint": "neuromuscular",
            "llm_blueprint": "dermal_support",
            "system_blueprint": "dermal_support",
            "system_source": "llm",
            "system_accepted": True,
            "llm_status": "ok",
        },
        # 4. LLM預測正確，但因未通過閘門而未接受（不應計入 C 的分子與分母）
        {
            "tree_id": "T4",
            "doc_id": "doc4",
            "physician_blueprint": "pathology_mechanism",
            "llm_blueprint": "pathology_mechanism",
            "system_blueprint": "pathology_mechanism",
            "system_source": "llm",
            "system_accepted": False,
            "llm_status": "invalid_evidence",
        },
    ]

    metrics = evaluate_blind(rows, threshold=0.85)

    assert metrics["total"] == 4
    # A. LLM 原始準確：T2, T4 正確 -> 2/4 = 0.50
    assert metrics["llm_correct"] == 2
    assert pytest.approx(metrics["llm_raw_accuracy"]) == 0.50

    # B. 完整系統原始準確：T1 (registry), T2 (llm), T4 (llm) 正確 -> 3/4 = 0.75
    assert metrics["system_correct"] == 3
    assert pytest.approx(metrics["system_raw_accuracy"]) == 0.75

    # C. 完整系統自動接受準確：接受集合為 T1, T2, T3（共3筆）
    # 其中正確為 T1, T2（共2筆）-> 2/3 = 0.6667
    assert metrics["system_accepted_count"] == 3
    assert metrics["system_accepted_correct"] == 2
    assert pytest.approx(metrics["system_accepted_accuracy"]) == 2 / 3
    assert pytest.approx(metrics["system_accept_rate"]) == 0.75

    # 查表命中：1 筆 (T1)，正確率 100%
    assert metrics["registry_hits"] == 1
    assert metrics["registry_correct"] == 1
    assert pytest.approx(metrics["registry_accuracy"]) == 1.0

    # invalid_evidence 統計
    assert metrics["invalid_evidence_count"] == 1


def test_zero_denominator_shows_na_and_handles_empty_class(tmp_path: Path):
    """驗證當某類別分母為 0 時，精確率、召回率與 F1 正確設定為 None，且 Markdown 顯示 N/A。"""
    rows = [
        {
            "tree_id": "T1",
            "doc_id": "doc1",
            "physician_blueprint": "cyst_excision",
            "llm_blueprint": "cyst_excision",
            "system_blueprint": "cyst_excision",
            "system_source": "llm",
            "system_accepted": True,
            "llm_status": "ok",
        }
    ]

    metrics = evaluate_blind(rows)
    # nail_matrix 完全無樣本且無預測
    nail_metric = next(m for m in metrics["class_metrics"] if m["blueprint"] == "nail_matrix")
    assert nail_metric["support"] == 0
    assert nail_metric["precision"] is None
    assert nail_metric["recall"] is None
    assert nail_metric["f1"] is None

    # 測試渲染出的 Markdown 包含 N/A
    report = render_markdown_report(metrics)
    assert "| `nail_matrix` | 0 | 0 | 0 | 0 | N/A | N/A | N/A |" in report


def test_unlabeled_rows_exit_code_1(tmp_path: Path):
    """驗證當標註表單存在未標註列時，拒絕評估並回傳 exit code 1。"""
    xlsx_file = tmp_path / "blind_incomplete.xlsx"
    csv_file = tmp_path / "blind_pred.csv"

    _create_mock_xlsx(xlsx_file, [
        {"tree_id": "B01", "doc_id": "d1", "physician_blueprint": "laser_action"},
        {"tree_id": "B02", "doc_id": "d2", "physician_blueprint": ""},  # 未標註
    ])
    _create_mock_csv(csv_file, [
        {
            "tree_id": "B01",
            "doc_id": "d1",
            "llm_blueprint": "laser_action",
            "llm_status": "ok",
            "system_blueprint": "laser_action",
            "system_source": "llm",
            "system_accepted": "True",
        },
        {
            "tree_id": "B02",
            "doc_id": "d2",
            "llm_blueprint": "laser_action",
            "llm_status": "ok",
            "system_blueprint": "laser_action",
            "system_source": "llm",
            "system_accepted": "True",
        },
    ])

    ret = eval_main([
        "--sheet", str(xlsx_file),
        "--predictions", str(csv_file),
        "--output", str(tmp_path / "report.md"),
    ])
    assert ret == 1, f"未標註列應回傳退出碼 1，得到 {ret}"


def test_schema_error_exit_code_2(tmp_path: Path):
    """驗證當缺少必要欄位或檔案不存在時，回傳 exit code 2。"""
    # 1. 檔案不存在
    ret1 = eval_main([
        "--sheet", str(tmp_path / "non_existent.xlsx"),
        "--predictions", str(tmp_path / "non_existent.csv"),
    ])
    assert ret1 == 2

    # 2. 欄位缺失
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("tree_id,doc_id\n1,x\n", encoding="utf-8")
    xlsx_file = tmp_path / "good.xlsx"
    _create_mock_xlsx(xlsx_file, [{"tree_id": "1", "doc_id": "x", "physician_blueprint": "other"}])

    ret2 = eval_main([
        "--sheet", str(xlsx_file),
        "--predictions", str(bad_csv),
    ])
    assert ret2 == 2
