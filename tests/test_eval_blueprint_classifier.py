import hashlib
import subprocess
import sys
from pathlib import Path
import pytest

from scripts.eval_blueprint_classifier import (
    evaluate,
    load_sheet_rows,
    UnlabeledError,
    SchemaError,
    DEFAULT_XLSX_PATH,
)

def test_evaluate_all_correct():
    """驗證全部正確時準確率為 1.0"""
    rows = [
        {
            "tree_id": "1",
            "doc_id": "doc-1",
            "physician_blueprint": "laser_action",
            "ai_suggested_blueprint": "laser_action",
            "ai_status": "ok",
        },
        {
            "tree_id": "2",
            "doc_id": "doc-2",
            "physician_blueprint": "skin_energy",
            "ai_suggested_blueprint": "skin_energy",
            "ai_status": "ok",
        },
    ]
    res = evaluate(rows, threshold=0.85)
    assert res["raw_accuracy"] == 1.0
    assert res["auto_accept_accuracy"] == 1.0
    assert res["auto_accept_rate"] == 1.0
    assert res["meets_threshold_raw"] is True


def test_evaluate_all_wrong():
    """驗證全部錯誤時準確率為 0.0"""
    rows = [
        {
            "tree_id": "1",
            "doc_id": "doc-1",
            "physician_blueprint": "laser_action",
            "ai_suggested_blueprint": "skin_energy",
            "ai_status": "ok",
        },
        {
            "tree_id": "2",
            "doc_id": "doc-2",
            "physician_blueprint": "skin_energy",
            "ai_suggested_blueprint": "laser_action",
            "ai_status": "ok",
        },
    ]
    res = evaluate(rows, threshold=0.85)
    assert res["raw_accuracy"] == 0.0
    assert res["auto_accept_accuracy"] == 0.0
    assert res["meets_threshold_raw"] is False


def test_evaluate_non_ok_status_excluded_from_b():
    """驗證 invalid_evidence 與 needs_review 不計入 B 的分子與分母"""
    rows = [
        {
            "tree_id": "1",
            "doc_id": "doc-1",
            "physician_blueprint": "laser_action",
            "ai_suggested_blueprint": "laser_action",
            "ai_status": "ok",
        },
        {
            "tree_id": "2",
            "doc_id": "doc-2",
            "physician_blueprint": "skin_energy",
            "ai_suggested_blueprint": "skin_energy",
            "ai_status": "invalid_evidence",  # 雖然藍圖相符，但非 ok，不能算入 B 的分子
        },
        {
            "tree_id": "3",
            "doc_id": "doc-3",
            "physician_blueprint": "surgical_action",
            "ai_suggested_blueprint": "surgical_action",
            "ai_status": "needs_review",  # 雖然藍圖相符，但非 ok，不能算入 B 的分子
        },
        {
            "tree_id": "4",
            "doc_id": "doc-4",
            "physician_blueprint": "pathology_mechanism",
            "ai_suggested_blueprint": "process_diagram",
            "ai_status": "ok",
        },
    ]
    res = evaluate(rows, threshold=0.85)
    # A. 原始準確率採計全部 4 筆：1, 2, 3 相符 -> 3 / 4 = 0.75
    assert res["raw_correct"] == 3
    assert res["total"] == 4
    assert res["raw_accuracy"] == 0.75

    # B. 自動接受準確率只採計 ai_status == 'ok' 的 2 筆（doc-1 與 doc-4）
    # 其中只有 doc-1 相符 -> 1 / 2 = 0.5
    assert res["auto_accept_total"] == 2
    assert res["auto_accept_correct"] == 1
    assert res["auto_accept_accuracy"] == 0.5
    assert res["auto_accept_rate"] == 0.5


def test_evaluate_zero_denominator_recall_na():
    """驗證當某類別醫師無標註時（分母為 0），顯示 None / N/A 而非除以零"""
    rows = [
        {
            "tree_id": "1",
            "doc_id": "doc-1",
            "physician_blueprint": "laser_action",
            "ai_suggested_blueprint": "laser_action",
            "ai_status": "ok",
        }
    ]
    res = evaluate(rows)
    # 檢查未出現的類別（例如 nail_matrix）
    assert res["per_class"]["nail_matrix"]["phys_count"] == 0
    assert res["per_class"]["nail_matrix"]["recall"] is None
    assert res["per_class"]["laser_action"]["recall"] == 1.0


def test_evaluate_unlabeled_raises_error(tmp_path):
    """驗證未標註列引發 UnlabeledError，CLI 退出碼為 1"""
    rows = [
        {
            "tree_id": "1",
            "doc_id": "doc-1",
            "physician_blueprint": "",  # 未標註
            "ai_suggested_blueprint": "laser_action",
            "ai_status": "ok",
        }
    ]
    with pytest.raises(UnlabeledError):
        evaluate(rows)


def test_evaluate_missing_column_raises_error():
    """驗證缺少必要鍵名時引發 SchemaError，CLI 退出碼為 2"""
    rows = [
        {
            "tree_id": "1",
            "doc_id": "doc-1",
            # 缺少 physician_blueprint
            "ai_suggested_blueprint": "laser_action",
            "ai_status": "ok",
        }
    ]
    with pytest.raises(SchemaError):
        evaluate(rows)


def test_cli_exit_codes(tmp_path):
    """驗證 CLI 在各情境下的退出碼"""
    import openpyxl

    # 1. 正常 xlsx
    cmd = [sys.executable, "scripts/eval_blueprint_classifier.py", "--sheet", str(DEFAULT_XLSX_PATH), "--out", str(tmp_path / "eval.md")]
    ret = subprocess.run(cmd, capture_output=True, text=True)
    assert ret.returncode == 0
    assert (tmp_path / "eval.md").exists()

    # 2. 檔案不存在 -> code 2
    cmd_not_found = [sys.executable, "scripts/eval_blueprint_classifier.py", "--sheet", str(tmp_path / "non_existent.xlsx")]
    ret_nf = subprocess.run(cmd_not_found, capture_output=True, text=True)
    assert ret_nf.returncode == 2

    # 3. 含有未標註的 xlsx -> code 1
    unlabeled_xlsx = tmp_path / "unlabeled.xlsx"
    wb = openpyxl.load_workbook(DEFAULT_XLSX_PATH)
    ws = wb["標註"]
    ws.cell(2, 5).value = ""  # 清空第一列答案
    wb.save(unlabeled_xlsx)

    cmd_unlabeled = [sys.executable, "scripts/eval_blueprint_classifier.py", "--sheet", str(unlabeled_xlsx)]
    ret_un = subprocess.run(cmd_unlabeled, capture_output=True, text=True)
    assert ret_un.returncode == 1


def test_xlsx_immutability():
    """驗證評估腳本執行前後 physician_labeling_sheet.xlsx 的 sha256 保持完全一致（唯讀約束）"""
    assert DEFAULT_XLSX_PATH.exists()
    with open(DEFAULT_XLSX_PATH, "rb") as f:
        sha_before = hashlib.sha256(f.read()).hexdigest()

    # 執行評估
    cmd = [sys.executable, "scripts/eval_blueprint_classifier.py"]
    ret = subprocess.run(cmd, capture_output=True, text=True)
    assert ret.returncode == 0

    with open(DEFAULT_XLSX_PATH, "rb") as f:
        sha_after = hashlib.sha256(f.read()).hexdigest()

    assert sha_before == sha_after, "評估腳本違反唯讀原則，修改了 xlsx 檔案！"
