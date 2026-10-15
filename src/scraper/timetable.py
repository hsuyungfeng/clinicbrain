"""門診表（週次 × 星期）HTML 表格解析（純函式，不寫入資料庫）。

輸出僅含「哪一天有門診／休診」，**不含醫師姓名**：醫師身分資訊依專案規則不得進入文字管線。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_CLOSED_MARKERS = {"", "-", "休診", "休"}
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


@dataclass
class TimetableEntry:
    month: int
    week: int
    weekday: str
    open: bool


@dataclass
class _Table:
    title: str = ""
    rows: list[list[str]] = field(default_factory=list)


class _TimetableHTMLParser(HTMLParser):
    """收集所有 <table> 的儲存格文字，並記錄其前方最近的 .h2Title 標題。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self._table: _Table | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._in_title = False
        self._title_text: list[str] = []
        self._last_title = ""

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == "div" and "h2title" in (attr.get("class") or "").lower():
            self._in_title = True
            self._title_text = []
        elif tag == "table":
            self._table = _Table(title=self._last_title)
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag == "div" and self._in_title:
            self._in_title = False
            self._last_title = "".join(self._title_text).strip()
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row:
                self._table.rows.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data):
        if self._in_title:
            self._title_text.append(data)
        if self._cell is not None:
            self._cell.append(data)


def parse_timetables(html: str) -> list[TimetableEntry]:
    """解析頁面中所有門診表，回傳每個（月、週、星期）的開診狀態。

    表格格式不符（缺星期列、標題無月份）的表格會被略過，不猜測對應。
    """
    parser = _TimetableHTMLParser()
    parser.feed(html)

    entries: list[TimetableEntry] = []
    for table in parser.tables:
        month_match = re.search(r"(\d{1,2})\s*月門診表", table.title)
        if not month_match or not table.rows:
            continue
        header = [c.upper() for c in table.rows[0][1:]]
        if tuple(header[:7]) != WEEKDAYS:
            continue
        month = int(month_match.group(1))
        for row in table.rows[1:]:
            week = _parse_week(row[0] if row else "")
            if week is None:
                continue
            cells = row[1:8]
            if len(cells) != 7:
                continue
            for weekday, cell in zip(WEEKDAYS, cells):
                entries.append(
                    TimetableEntry(
                        month=month,
                        week=week,
                        weekday=weekday,
                        open=_is_open(cell),
                    )
                )
    return entries


def _is_open(cell: str) -> bool:
    """儲存格有醫師名稱或特約門診標記即為開診；空白、「-」、「休診」為休診。"""
    text = cell.strip()
    return text not in _CLOSED_MARKERS


def _parse_week(label: str) -> int | None:
    """解析「第一週」「第2週」等週次標籤；無法辨識回傳 None。"""
    match = re.match(r"第\s*([一二三四五六七八九十]+|\d+)\s*週", label)
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        return int(token)
    return _CN_NUM.get(token)
