"""服務詳細頁（/service-detail/<代號>/）說明文字擷取（純函式，不寫入資料庫）。

結構（已由 HotFacial 實頁確認）：
  div.contentBuilder > div.mt-3.mb-3 > h2.h2Title（服務名稱或段落標題）+ 多個 <p>（說明文字）
僅抽取文字段落；圖片、空白段落與聯絡／身分資訊不進入輸出。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

_MIN_PARAGRAPH_CHARS = 2


@dataclass
class ServiceDetail:
    name: str
    description: str
    sections: list[str] = field(default_factory=list)


# 內容區：contentBuilder（表格、圖文模板）、textEditor（文字區塊）與 tabContentItem（分頁內容）。
_CONTENT_CLASSES = ("contentbuilder", "texteditor", "tabcontentitem")
# 醫師身分：「姓名＋院長」與 Dr. 稱謂不得進入文字管線（專案規則）
_STAFF_NAME_BEFORE_TITLE = re.compile(r"[\u4e00-\u9fff]{2,3}(?=院長)")
_STAFF_DR_PREFIX = re.compile(r"\bDr\.?\s*[A-Za-z]+", re.IGNORECASE)


def redact_staff(text: str) -> str:
    """遮掉醫師姓名（「姓名＋院長」、Dr. 稱謂），保留醫療內容本身。"""
    text = _STAFF_NAME_BEFORE_TITLE.sub("", text)
    text = _STAFF_DR_PREFIX.sub("醫師", text)
    return text


class _ServiceDetailParser(HTMLParser):
    """抽取內容區中的標題、段落與表格列（三種模板共用，順序與原文一致）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[tuple[str, bool, str]] = []  # (tag, 是否開啟內容區, 擷取類別)
        self._content_depth = 0  # 內容區巢狀深度
        self._table_depth = 0
        self._capture: list[str] | None = None
        self._capture_kind = ""
        self._row: list[str] | None = None
        self._title: list[str] | None = None
        self.title = ""
        self.headings: list[str] = []
        self.blocks: list[tuple[str, str]] = []  # ("p", 段落) 或 ("row", 表格列)

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._stack.append((tag, False, ""))
            return
        attr = dict(attrs)
        classes = (attr.get("class") or "").lower().split()
        if tag == "title" and not self.title and self._capture is None:
            self._title = []
            self._stack.append((tag, False, ""))
            return

        opens_content = tag in ("div", "section") and any(c in _CONTENT_CLASSES for c in classes)
        if opens_content:
            self._content_depth += 1
        if tag == "table":
            self._table_depth += 1
        if tag == "tr" and self._content_depth:
            self._row = []

        kind = ""
        if self._content_depth and self._capture is None:
            if tag in ("h2", "h3", "h4") or "h2title" in classes or "h3title" in classes:
                kind = "heading"
            elif tag == "p" and not self._table_depth:
                kind = "p"
            elif tag in ("td", "th") and self._row is not None:
                kind = "cell"
        if kind:
            self._capture = []
            self._capture_kind = kind
        self._stack.append((tag, opens_content, kind))

    def handle_endtag(self, tag):
        # 回溯到對應開始標籤（容忍不成對的標籤）
        while self._stack:
            open_tag, opened_content, kind = self._stack.pop()
            if open_tag == "title" and tag == "title":
                self.title = _clean("".join(self._title or []))
                self._title = None
                return
            if open_tag in ("script", "style"):
                if tag in ("script", "style"):
                    return
                continue
            if open_tag != tag:
                continue
            if opened_content:
                self._content_depth -= 1
            if tag == "table":
                self._table_depth = max(0, self._table_depth - 1)
            if self._capture is not None and kind == self._capture_kind:
                text = redact_staff(_clean("".join(self._capture)))
                if kind == "heading" and text:
                    self.headings.append(text)
                elif kind == "p" and len(text) >= _MIN_PARAGRAPH_CHARS:
                    self.blocks.append(("p", text))
                elif kind == "cell" and self._row is not None:
                    self._row.append(text)
                self._capture = None
                self._capture_kind = ""
            if tag == "tr" and self._row is not None:
                cells = [c for c in self._row if c]
                if cells:
                    self.blocks.append(("row", " | ".join(cells)))
                self._row = None
            return

    def handle_data(self, data):
        if self._title is not None:
            self._title.append(data)
        if self._capture is not None:
            self._capture.append(data)

    @property
    def paragraphs(self) -> list[str]:
        return [text for _, text in self.blocks]


def extract_service_detail(html: str) -> ServiceDetail | None:
    """從服務詳細頁抽取服務名稱與說明。缺少名稱或沒有任何說明內容時回傳 None。"""
    parser = _ServiceDetailParser()
    parser.feed(html)
    if not parser.blocks:
        return None
    name = _name_from_title(parser.title) or (parser.headings[0] if parser.headings else "")
    if not name:
        return None
    description = "\n".join(parser.paragraphs)
    sections = parser.headings[1:]
    return ServiceDetail(name=redact_staff(name), description=description, sections=sections)


_MAX_NAME_CHARS = 80
_TITLE_SEPARATOR = re.compile(r"\s*[｜|]\s*|\s+-\s+|\s*-\s*凡登")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _name_from_title(title: str) -> str:
    """從 <title> 取服務名稱：取第一個分隔符（｜、|、 - 、-凡登）之前的部分，去除問號。

    SEO 標題如「削骨手術首選｜顴骨…｜凡登整形診所」取「削骨手術首選」。
    段落標題不會出現在 <title>。
    """
    head = _TITLE_SEPARATOR.split(title, maxsplit=1)[0]
    head = head.replace("？", "").replace("?", "").replace("、", "·").replace("，", "·")
    head = re.sub(r"\s+", " ", head).strip()
    if len(head) > _MAX_NAME_CHARS:
        cut = head.rfind("·", 0, _MAX_NAME_CHARS)
        head = head[:cut] if cut > 0 else head[:_MAX_NAME_CHARS]
    return head
