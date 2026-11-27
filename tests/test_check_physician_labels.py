import csv

import pytest

from scripts.check_physician_labels import check_rows, load_sheet, main
from src.visual.blueprint_classifier import CLASSIFIER_ALLOWED_BLUEPRINTS

SRC = "術前須知：過敏體質需告知醫師。療程步驟：皮秒雷射利用極短脈衝光束擊碎黑色素，過程約15-30分鐘。"


def _row(**kw):
    base = {
        "tree_id": "1",
        "doc_id": "laser-skin-resurfacing",
        "title": "皮秒雷射",
        "source_text": SRC,
        "physician_blueprint": "",
        "evidence_span": "",
        "physician_notes": "",
    }
    base.update(kw)
    return base


def test_valid_label_passes():
    rows = [_row(physician_blueprint="laser_action", evidence_span="皮秒雷射利用極短脈衝光束擊碎黑色素")]
    res = check_rows(rows)
    assert res["errors"] == []
    assert res["labeled"] == 1


def test_unlabeled_is_not_error_by_default():
    res = check_rows([_row()])
    assert res["errors"] == []
    assert res["unlabeled"] == 1


def test_unlabeled_is_error_with_require_complete():
    res = check_rows([_row()], require_complete=True)
    assert any("尚未標註" in e for e in res["errors"])


def test_invalid_blueprint_name_is_error():
    res = check_rows([_row(physician_blueprint="laser", evidence_span="皮秒雷射利用極短脈衝光束")])
    assert any("不合法的藍圖名稱" in e for e in res["errors"])


def test_blueprint_is_case_sensitive():
    res = check_rows([_row(physician_blueprint="Laser_Action", evidence_span="皮秒雷射利用極短脈衝光束")])
    assert any("不合法" in e for e in res["errors"])


def test_evidence_not_in_source_is_error():
    res = check_rows([_row(physician_blueprint="laser_action", evidence_span="這段文字不在原文中")])
    assert any("不是 source_text 的子字串" in e for e in res["errors"])


def test_missing_evidence_for_non_other_is_error():
    res = check_rows([_row(physician_blueprint="laser_action", evidence_span="")])
    assert any("未填寫 evidence_span" in e for e in res["errors"])


def test_other_without_evidence_passes():
    res = check_rows([_row(physician_blueprint="other")])
    assert res["errors"] == []
    assert res["warnings"] == []


def test_other_with_evidence_is_warning_not_error():
    res = check_rows([_row(physician_blueprint="other", evidence_span="皮秒雷射利用極短脈衝光束")])
    assert res["errors"] == []
    assert any("選 other" in w for w in res["warnings"])


def test_fullwidth_punctuation_difference_is_tolerated():
    # 原文為全形逗號與句號；證據以半形標點書寫，應依 D1 規範視為相符
    res = check_rows([_row(physician_blueprint="laser_action", evidence_span="術前須知:過敏體質需告知醫師")])
    assert res["errors"] == []


def test_evidence_length_outside_guideline_is_warning():
    res = check_rows([_row(physician_blueprint="laser_action", evidence_span="皮秒")])
    assert res["errors"] == []
    assert any("建議 10–40 字" in w for w in res["warnings"])


def test_duplicate_tree_and_doc_ids_are_errors():
    rows = [_row(), _row()]
    res = check_rows(rows)
    assert any("tree_id 重複" in e for e in res["errors"])
    assert any("doc_id 重複" in e for e in res["errors"])


def _write_sheet(path, rows):
    fields = ["tree_id", "doc_id", "title", "source_text", "physician_blueprint", "evidence_span", "physician_notes"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def test_cli_exit_0_when_clean(tmp_path):
    p = tmp_path / "sheet.csv"
    _write_sheet(p, [_row(physician_blueprint="laser_action", evidence_span="皮秒雷射利用極短脈衝光束擊碎黑色素")])
    assert main([str(p)]) == 0


def test_cli_exit_1_on_error(tmp_path):
    p = tmp_path / "sheet.csv"
    _write_sheet(p, [_row(physician_blueprint="laser_action", evidence_span="不存在的句子內容一二三")])
    assert main([str(p)]) == 1


def test_cli_exit_2_on_missing_column(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("tree_id,doc_id\n1,x\n", encoding="utf-8")
    assert main([str(p)]) == 2


def test_real_sheet_loads_and_reports_all_unlabeled():
    """目前實際表單尚未標註：預設模式應通過，且 50 列皆為未標註。"""
    from scripts.check_physician_labels import DEFAULT_SHEET

    rows = load_sheet(DEFAULT_SHEET)
    res = check_rows(rows)
    assert res["total"] == 50
    assert res["unlabeled"] == 50
    assert res["errors"] == []


def test_xlsx_build_has_blueprint_dropdown_and_loads(tmp_path):
    from openpyxl import load_workbook

    from scripts.build_physician_labeling_xlsx import BLUEPRINT_COLUMN, build
    from scripts.check_physician_labels import LABEL_SHEET_NAME

    p = tmp_path / "sheet.csv"
    _write_sheet(p, [_row(), _row(tree_id="2", doc_id="doc-2")])
    out = build(csv_path=p, xlsx_path=tmp_path / "sheet.xlsx")

    wb = load_workbook(out)
    ws = wb[LABEL_SHEET_NAME]
    headers = [c.value for c in ws[1]]
    col = headers.index(BLUEPRINT_COLUMN) + 1
    dvs = [dv for dv in ws.data_validations.dataValidation if dv.type == "list"]
    assert len(dvs) == 1
    dv = dvs[0]
    assert str(dv.sqref) == f"{ws.cell(row=2, column=col).column_letter}2:{ws.cell(row=3, column=col).column_letter}3"
    assert "藍圖選項" in dv.formula1
    assert wb["藍圖選項"].sheet_state == "hidden"
    opts = [wb["藍圖選項"].cell(row=r, column=1).value for r in range(2, 2 + len(CLASSIFIER_ALLOWED_BLUEPRINTS))]
    assert opts == list(CLASSIFIER_ALLOWED_BLUEPRINTS)


def test_xlsx_labels_are_checked(tmp_path):
    from openpyxl import load_workbook

    from scripts.build_physician_labeling_xlsx import BLUEPRINT_COLUMN, build
    from scripts.check_physician_labels import LABEL_SHEET_NAME, load_sheet

    p = tmp_path / "sheet.csv"
    _write_sheet(p, [_row()])
    out = build(csv_path=p, xlsx_path=tmp_path / "sheet.xlsx")

    wb = load_workbook(out)
    ws = wb[LABEL_SHEET_NAME]
    headers = [c.value for c in ws[1]]
    ws.cell(row=2, column=headers.index(BLUEPRINT_COLUMN) + 1, value="laser_action")
    ws.cell(row=2, column=headers.index("evidence_span") + 1, value="皮秒雷射利用極短脈衝光束擊碎黑色素")
    wb.save(out)

    rows = load_sheet(out)
    assert len(rows) == 1
    assert check_rows(rows)["errors"] == []


def test_xlsx_rejects_bad_evidence(tmp_path):
    from openpyxl import load_workbook

    from scripts.build_physician_labeling_xlsx import BLUEPRINT_COLUMN, build
    from scripts.check_physician_labels import LABEL_SHEET_NAME, load_sheet

    p = tmp_path / "sheet.csv"
    _write_sheet(p, [_row()])
    out = build(csv_path=p, xlsx_path=tmp_path / "sheet.xlsx")

    wb = load_workbook(out)
    ws = wb[LABEL_SHEET_NAME]
    headers = [c.value for c in ws[1]]
    ws.cell(row=2, column=headers.index(BLUEPRINT_COLUMN) + 1, value="laser_action")
    ws.cell(row=2, column=headers.index("evidence_span") + 1, value="原文中不存在的句子內容")
    wb.save(out)

    res = check_rows(load_sheet(out))
    assert any("不是 source_text 的子字串" in e for e in res["errors"])
