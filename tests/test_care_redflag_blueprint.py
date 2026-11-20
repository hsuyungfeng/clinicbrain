"""Phase 53-01: `care_redflag` 藍圖驗證與 Playwright 瀏覽器渲染回歸測試。"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from src.visual.blueprints import BLUEPRINTS, default_params, validate_params
from src.visual.ir import VALID_BLUEPRINTS, validate_ir

VISUAL_ENGINE_PATH = Path(__file__).resolve().parent.parent / "src" / "web" / "static" / "visual_engine.js"


def test_care_redflag_registered_and_validates_ir() -> None:
    assert "care_redflag" in BLUEPRINTS
    assert "care_redflag" in VALID_BLUEPRINTS

    params = default_params("care_redflag")
    ok_p, err_p = validate_params("care_redflag", params)
    assert ok_p, f"default_params 應通過驗證，實際錯誤: {err_p}"

    sample_ir = {
        "topic_key": "nhi-w095-k57-9",
        "title": "大腸結腸憩室病衛教圖解",
        "keywords": ["大腸憩室病", "高纖飲食", "急診警訊"],
        "scenes": [
            {
                "blueprint": "pathology_mechanism",
                "title": "結腸壁囊袋形成機轉",
                "caption": "纖維攝取不足使腸腔壓力升高，黏膜從肌肉層縫隙向外膨出形成小囊袋。",
                "labels": [{"text": "腸腔壓力", "tone": "warning"}, {"text": "黏膜膨出", "tone": "neutral"}],
                "duration_sec": 8,
                "params": default_params("pathology_mechanism"),
            },
            {
                "blueprint": "contrast",
                "title": "憩室病與憩室炎對照",
                "caption": "單純憩室病多無明顯不適；若糞便卡住引發細菌感染，則演變為急性憩室炎。",
                "labels": [{"text": "飲食調整", "tone": "optimal"}, {"text": "感染評估", "tone": "warning"}],
                "duration_sec": 8,
                "params": default_params("contrast"),
            },
            {
                "blueprint": "care_redflag",
                "title": "日常預防與急診紅旗警訊",
                "caption": "日常維持高纖與飲水習慣有助降低發炎風險，若出現紅旗警訊應立即就醫評估。",
                "labels": [{"text": "預防保健", "tone": "optimal"}, {"text": "紅旗急診", "tone": "warning"}],
                "duration_sec": 8,
                "params": {
                    "care_items": ["高纖蔬果全穀", "每日足量飲水", "每週規律運動", "養成排便習慣"],
                    "red_flags": ["劇烈持續腹痛", "高燒或畏寒", "大量便血黑便"],
                    "myth_note": "堅果種子並不會增加憩室炎風險",
                    "takeaway": "多吃纖維多喝水，腹痛發燒快就醫。",
                    "urgency_level": 5,
                },
            },
        ],
    }
    ok, errs = validate_ir(sample_ir)
    assert ok, f"validate_ir 應通過，實際錯誤: {errs}"


def test_care_redflag_rejects_invalid_params() -> None:
    bad_params = {
        "care_items": ["只有兩項", "不夠三項"],
        "red_flags": ["僅一項"],
        "myth_note": "測試",
        "takeaway": "測試一句話",
        "urgency_level": 9,
    }
    ok, err = validate_params("care_redflag", bad_params)
    assert not ok and err


def test_care_redflag_playwright_render_no_overlap() -> None:
    js_code = VISUAL_ENGINE_PATH.read_text(encoding="utf-8")
    scene = {
        "blueprint": "care_redflag",
        "title": "日常預防與急診紅旗警訊",
        "caption": "日常維持高纖與飲水習慣有助降低發炎風險，若出現紅旗警訊應立即就醫評估。",
        "labels": [{"text": "預防保健", "tone": "optimal"}, {"text": "紅旗急診", "tone": "warning"}],
        "duration_sec": 8,
        "params": {
            "care_items": ["高纖蔬果全穀", "每日足量飲水", "每週規律運動", "養成排便習慣"],
            "red_flags": ["劇烈持續腹痛", "高燒或畏寒", "大量便血黑便"],
            "myth_note": "堅果種子並不會增加憩室炎風險",
            "takeaway": "多吃纖維多喝水，腹痛發燒快就醫。",
            "urgency_level": 5,
        },
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 800, "height": 600})
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.set_content(f"<!doctype html><html><body><svg id='stage' viewBox='0 0 800 510'></svg><script>{js_code}</script></body></html>")

        for frac in (0.2, 0.6, 0.9):
            result = page.evaluate(
                """([s, f]) => {
                    const svg = document.getElementById('stage');
                    const m = window.ClinicVisual.mount(svg, [s]);
                    m.renderAt(m.totalDuration * f);
                    const nonSubMaxY = Array.from(svg.querySelectorAll('rect'))
                        .filter(r => !r.hasAttribute('data-subtitle') && !r.hasAttribute('data-bg'))
                        .map(r => parseFloat(r.getAttribute('y') || '0') + parseFloat(r.getAttribute('height') || '0'))
                        .reduce((a, b) => Math.max(a, b), 0);
                    return { html: svg.outerHTML, nonSubMaxY };
                }""",
                [scene, frac],
            )
            assert "高纖蔬果全穀" in result["html"]
            assert "劇烈持續腹痛" in result["html"]
            assert "多吃纖維多喝水，腹痛發燒快就醫。" in result["html"]
            assert result["nonSubMaxY"] <= 402, f"care_redflag 元件底部 y={result['nonSubMaxY']} 不可侵犯 y=414 字幕區"

        browser.close()
    assert not errors, f"Playwright 出現 JS 錯誤: {errors}"
