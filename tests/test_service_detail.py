"""服務詳細頁說明擷取測試（離線合成 HTML，不連網）。"""

from src.scraper.service_detail import extract_service_detail

SAMPLE = """
<div class="contentBuilder template_text_002"><div class="mt-3 mb-3">
<h2 class="h2Title"><span>海菲秀(水飛梭)</span></h2>
<p>海菲秀是一種非侵入式的活膚煥膚美容療程，只需要三十分鐘左右即可完成。</p>
<p><img src="x.png" alt="x"></p>
<p>&nbsp;</p>
</div></div>
<div class="contentBuilder template_text_002"><div class="mt-3 mb-3">
<h2 class="h2Title"><span>海菲秀(水飛梭)原理為何</span></h2>
<p>採用專利渦漩注入技術，溫和地清除臉上堆積的髒污與老廢角質。</p>
</div></div>
"""


def test_extracts_name_and_paragraphs():
    d = extract_service_detail(SAMPLE)
    assert d is not None
    assert d.name == "海菲秀(水飛梭)"
    assert "非侵入式" in d.description
    assert "渦漩注入" in d.description


def test_images_and_empty_paragraphs_excluded():
    d = extract_service_detail(SAMPLE)
    assert "<" not in d.description
    assert "&nbsp;" not in d.description
    assert d.description.count("\n") == 1  # 兩段有效說明


def test_later_headings_become_sections():
    d = extract_service_detail(SAMPLE)
    assert d.sections == ["海菲秀(水飛梭)原理為何"]


def test_returns_none_without_heading_or_text():
    assert extract_service_detail("<html><body><p>沒有標題</p></body></html>") is None
    assert extract_service_detail('<div class="contentBuilder"><h2 class="h2Title">只有標題</h2></div>') is None
