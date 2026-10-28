"""服務詳細頁多模板解析（離線合成 HTML）：textEditor、表格、圖文模板與醫師姓名遮罩。"""

from src.scraper.service_detail import extract_service_detail, redact_staff

TEXT_EDITOR_PAGE = """<html><head><title>雙眼皮手術-凡登診所</title></head><body>
<div class="tabContentItem" id="intro"><div class="block textEditor">
<h2 class="h2_title h2Title"><span>雙眼皮手術是什麼？</span></h2>
<p>雙眼皮手術可讓眼皮形成摺痕，恢復期依術式而異。</p>
</div></div></body></html>"""

TABLE_PAGE = """<html><head><title>抽脂手術-凡登診所</title></head><body>
<div class="tabContentItem"><div class="contentBuilder template_table_002"><div class="table-responsive">
<table><thead><tr><th>&nbsp;</th><th><p>傳統抽脂</p></th><th>水刀抽脂</th></tr></thead>
<tbody><tr><td>恢復期</td><td>2週</td><td>1週</td></tr></tbody></table>
</div></div></div></body></html>"""

IMAGE_TEXT_PAGE = """<html><head><title>中上臉拉皮-凡登診所</title></head><body>
<div class="tabContentItem"><div class="contentBuilder template_imageText_015"><div class="mt-3 mb-3">
<div class="Txt"><div class="h2Title mb-2"><span>顴骨脂肪下垂</span></div>
<p>顴骨脂肪墊下移會造成蘋果肌消失。</p></div>
</div></div></div></body></html>"""


def test_text_editor_template_is_extracted():
    d = extract_service_detail(TEXT_EDITOR_PAGE)
    assert d is not None
    assert d.name == "雙眼皮手術"
    assert "恢復期依術式而異" in d.description


def test_table_rows_are_joined_per_row_and_header_paragraph_kept():
    d = extract_service_detail(TABLE_PAGE)
    assert d is not None
    lines = d.description.split("\n")
    assert "恢復期 | 2週 | 1週" in lines
    assert "傳統抽脂 | 水刀抽脂" in lines  # <th><p> 內的標題不重複成段落


def test_image_text_template_uses_div_headings():
    d = extract_service_detail(IMAGE_TEXT_PAGE)
    assert d is not None
    assert d.name == "中上臉拉皮"
    assert "顴骨脂肪墊下移" in d.description


def test_page_without_any_content_returns_none():
    assert extract_service_detail("<html><head><title>X-凡登診所</title></head><body></body></html>") is None


def test_doctor_name_before_title_is_redacted():
    text = "依馮中和院長對抽脂手術的見解，術後需回診。"
    out = redact_staff(text)
    assert "馮中和" not in out
    assert "院長對抽脂手術的見解" in out


def test_dr_prefix_is_redacted():
    assert "Dr. Chen" not in redact_staff("由 Dr. Chen 評估")
