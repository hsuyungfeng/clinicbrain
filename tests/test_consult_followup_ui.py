"""病患諮詢頁：追問膠囊（後端 followup_chips、只在有動畫時顯示）與複製並前往預約的靜態安全檢查。"""

from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "src" / "web" / "static"
FORBIDDEN = ["innerHTML", "insertAdjacentHTML", "document.write", "eval", "localStorage", "sessionStorage", "document.cookie"]


def _js() -> str:
    return (STATIC / "consult.js").read_text(encoding="utf-8")


def test_chips_come_from_backend_and_only_show_with_visual():
    js = _js()
    assert "data.followup_chips" in js
    assert "deriveQuickFollowups" not in js  # 不再使用前端寫死的關鍵字推導
    assert "hasVis" in js and "backendChips" in js


def test_copy_button_copies_then_opens_fixed_booking_url():
    js = _js()
    assert 'var BOOKING_URL = "https://doctor-toolbox.com/";' in js
    assert 'window.open(BOOKING_URL, "_blank", "noopener,noreferrer");' in js
    # 預約網址不採用伺服器回傳值
    assert "data.booking_url" not in js.split("var BOOKING_URL")[1].split("btnCopySummary")[0]


def test_chip_and_copy_code_uses_textcontent_only():
    js = _js()
    for token in FORBIDDEN:
        assert token not in js, f"consult.js 不得包含 {token}"
    assert "btn.textContent = chipText;" in js


def test_consult_html_has_no_inline_script():
    html = (STATIC / "consult.html").read_text(encoding="utf-8")
    assert "<script>" not in html
    assert "<script src=" in html
