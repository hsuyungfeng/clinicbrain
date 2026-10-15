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


class _ServiceDetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_content = 0  # contentBuilder 巢狀深度
        self._div_stack: list[bool] = []  # 每層 div 是否為 contentBuilder
        self._h2: list[str] | None = None
        self._p: list[str] | None = None
        self._title: list[str] | None = None
        self.title = ""
        self.headings: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        classes = (attr.get("class") or "").lower().split()
        if tag == "div":
            is_content = "contentbuilder" in classes
            self._div_stack.append(is_content)
            if is_content:
                self._in_content += 1
        elif tag == "title" and not self.title:
            self._title = []
        elif tag == "h2" and self._in_content and "h2title" in classes:
            self._h2 = []
        elif tag == "p" and self._in_content:
            self._p = []

    def handle_endtag(self, tag):
        if tag == "div" and self._div_stack:
            if self._div_stack.pop():
                self._in_content -= 1
        elif tag == "title" and self._title is not None:
            self.title = _clean("".join(self._title))
            self._title = None
        elif tag == "h2" and self._h2 is not None:
            text = _clean("".join(self._h2))
            if text:
                self.headings.append(text)
            self._h2 = None
        elif tag == "p" and self._p is not None:
            text = _clean("".join(self._p))
            if len(text) >= _MIN_PARAGRAPH_CHARS:
                self.paragraphs.append(text)
            self._p = None

    def handle_data(self, data):
        if self._title is not None:
            self._title.append(data)
        if self._h2 is not None:
            self._h2.append(data)
        if self._p is not None:
            self._p.append(data)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def extract_service_detail(html: str) -> ServiceDetail | None:
    """從服務詳細頁抽取服務名稱與說明。無法辨識名稱或沒有說明段落時回傳 None。"""
    parser = _ServiceDetailParser()
    parser.feed(html)
    if not parser.headings or not parser.paragraphs:
        return None
    name = _name_from_title(parser.title) or parser.headings[0]
    description = "\n".join(parser.paragraphs)
    return ServiceDetail(name=name, description=description, sections=parser.headings[1:])


_MAX_NAME_CHARS = 80
_TITLE_SEPARATOR = re.compile(r"\s*[｜|]\s*|\s+-\s+|\s*-\s*凡登")


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
