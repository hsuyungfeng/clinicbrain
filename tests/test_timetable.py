"""Phase 25 門診表解析器單元測試：src/scraper/timetable.py（純函式，不觸及資料庫）。

覆蓋範圍：
1. 合規門診表（月、週 × 星期）解析與開/休診判定。
2. 格式不符之表格（缺星期列、標題無月份、週次標籤無法辨識）須略過、不猜測。
3. 真實頁面 fixture（凡登台中 location-detail 之 9/10 月門診表，離線使用）。
4. 輸出僅含開/休診狀態，不含醫師姓名（個資不進文字管線）。
"""

from __future__ import annotations

from pathlib import Path

from src.scraper.timetable import WEEKDAYS, TimetableEntry, parse_timetables

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scraper"


def _table_html(title: str, week_labels: list[str], cells_by_week: list[list[str]], header: list[str] | None = None) -> str:
    """組出一個帶 .h2Title 標題的門診表 HTML。"""
    header = header if header is not None else ["週"] + list(WEEKDAYS)
    rows = ["<tr>" + "".join(f"<th>{c}</th>" for c in header) + "</tr>"]
    for label, cells in zip(week_labels, cells_by_week):
        rows.append("<tr><td>{}</td>{}".format(label, "".join(f"<td>{c}</td>" for c in cells)) + "</tr>")
    return (
        f'<div class="h2Title">{title}</div>'
        "<table>" + "".join(rows) + "</table>"
    )


def test_valid_table_parses_month_week_weekday():
    """Test 1: 合規表格解析出（月、週、星期）開診狀態，週次含中文數字。"""
    html = _table_html(
        "台中整形外科9月門診表",
        ["第一週", "第2週"],
        [["李", "", "-", "休診", "休", "張", ""], ["", "王", "", "", "", "", ""]],
    )
    entries = parse_timetables(html)
    assert len(entries) == 14
    assert all(e.month == 9 for e in entries)
    assert {e.week for e in entries} == {1, 2}
    # 第一週：MON、SAT 開診（有醫師名）；TUE 空白、WED「-」、THU「休診」、FRI「休」、SUN 空白 → 休診
    week1 = {e.weekday: e.open for e in entries if e.week == 1}
    assert week1 == {"MON": True, "TUE": False, "WED": False, "THU": False, "FRI": False, "SAT": True, "SUN": False}
    # 第二週：僅 TUE 開診
    week2 = {e.weekday: e.open for e in entries if e.week == 2}
    assert week2["TUE"] is True
    assert all(not week2[d] for d in WEEKDAYS if d != "TUE")


def test_cells_with_text_are_open():
    """Test 2: 儲存格有文字（醫師名或特約標記）即為開診。"""
    html = _table_html("10月門診表", ["第一週"], [["特約門診"] * 7])
    entries = parse_timetables(html)
    assert len(entries) == 7
    assert all(e.open for e in entries)


def test_missing_weekday_header_skips_table():
    """Test 3: 首列非星期列之表格略過，不猜測對應。"""
    html = _table_html(
        "9月門診表",
        ["第一週"],
        [["a", "b", "c", "d", "e", "f", "g"]],
        header=["項目", "一", "二", "三", "四", "五", "六", "日"],
    )
    assert parse_timetables(html) == []


def test_title_without_month_skips_table():
    """Test 4: 標題無「N月門診表」之表格略過。"""
    html = _table_html("門診安排", ["第一週"], [["李"] * 7])
    assert parse_timetables(html) == []


def test_unrecognized_week_label_row_skipped():
    """Test 5: 無法辨識之週次標籤列略過；其餘合規列仍解析。"""
    html = _table_html(
        "11月門診表",
        ["第一週", "隔週", "第三週"],
        [["李", "", "", "", "", "", ""], [""] * 7, ["", "", "", "", "", "", "張"]],
    )
    entries = parse_timetables(html)
    assert {e.week for e in entries} == {1, 3}
    assert len(entries) == 14
    assert next(e for e in entries if e.week == 1 and e.weekday == "MON").open
    assert next(e for e in entries if e.week == 3 and e.weekday == "SUN").open


def test_malformed_row_width_skipped():
    """Test 6: 欄數不足 7 列之列略過。"""
    html = (
        '<div class="h2Title">9月門診表</div><table>'
        "<tr><th>週</th><th>MON</th><th>TUE</th><th>WED</th><th>THU</th><th>FRI</th><th>SAT</th><th>SUN</th></tr>"
        "<tr><td>第一週</td><td>李</td><td></td></tr>"
        "</table>"
    )
    assert parse_timetables(html) == []


def test_no_doctor_names_in_output():
    """Test 7: 輸出結構僅含月/週/星期/開診狀態，不帶任何儲存格文字（醫師姓名不外洩）。"""
    html = _table_html("9月門診表", ["第一週"], [["王小明", "李美玲", "", "張大華", "", "陳小華", ""]])
    entries = parse_timetables(html)
    assert all(isinstance(e, TimetableEntry) for e in entries)
    for e in entries:
        assert set(e.__dict__) == {"month", "week", "weekday", "open"}
        assert e.weekday in WEEKDAYS


def test_real_vendome_fixture_offline():
    """Test 8: 真實頁面 fixture（離線）：9 月與 10 月各 5 週、共 70 筆，週一全月皆有門診。"""
    html = (FIXTURES_DIR / "timetable_vendome.html").read_text(encoding="utf-8")
    entries = parse_timetables(html)
    assert len(entries) == 70
    assert {e.month for e in entries} == {9, 10}
    for month in (9, 10):
        weeks = {e.week for e in entries if e.month == month}
        assert weeks == {1, 2, 3, 4, 5}
        assert sum(1 for e in entries if e.month == month) == 35
    # 週一（MON）該診所固定開診
    mondays = [e for e in entries if e.weekday == "MON"]
    assert all(e.open for e in mondays)
