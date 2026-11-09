"""
Phase 40 Wave 4: 201-400 次專科動畫瀏覽器渲染與抽幀審計測試 (test_nhi400_browser_render.py)。

測試目標：
1. 在 Playwright 無頭 Chromium 環境中掛載 visual_engine.js。
2. 驗證 201-400 新增之 5 大解剖次專科、對照模式與時序連接之確定性渲染：
   - pathology_mechanism: ophthalmic_retina, ent_airway, uro_genital, dental_periodontal, tcm_special_acup
   - contrast: airway_laryngeal_edema vs airway_patency_restore 等
   - timeline: retinal_epithelium_repair, meridian_unblock_healing 等
3. 抽幀審計（u = 0.0, 0.35, 0.5, 0.8, 1.0）：
   - 瀏覽器 console 零 error。
   - 渲染產生之文字節點零半形阿拉伯數字殘留（0-9）。
   - 確定性 renderAt 檢驗：正向與逆向 renderAt 到同一進度 u，其 outerHTML 100% 完全相同。
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import pytest

from src.visual.blueprints import BLUEPRINTS, default_params

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENGINE_JS_PATH = PROJECT_ROOT / "src" / "web" / "static" / "visual_engine.js"


def _create_test_html(tmp_path: Path) -> Path:
    html_content = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="utf-8">
  <title>Phase 40 Visual Engine Render Test</title>
</head>
<body style="margin:0;padding:0;background:#000;">
  <svg id="testSvg" width="800" height="510" viewBox="0 0 800 510"></svg>
  <script src="{ENGINE_JS_PATH.as_uri()}"></script>
</body>
</html>
"""
    html_file = tmp_path / "nhi400_render_test.html"
    html_file.write_text(html_content, encoding="utf-8")
    return html_file


def _setup_browser_page(playwright_page, tmp_path: Path):
    console_errors = []

    def on_console(msg):
        if msg.type == "error":
            console_errors.append(msg.text)

    playwright_page.on("console", on_console)
    test_html = _create_test_html(tmp_path)
    playwright_page.goto(test_html.as_uri())
    return console_errors


def test_nhi400_specialty_blueprints_render(playwright_page, tmp_path):
    """驗證次專科圖元在瀏覽器中掛載與渲染時無任何 Console 錯誤。"""
    console_errors = _setup_browser_page(playwright_page, tmp_path)

    test_cases = [
        # 1. 眼科視網膜
        {
            "blueprint": "pathology_mechanism",
            "title": "視網膜病理機轉",
            "params": {
                **default_params("pathology_mechanism"),
                "organ_system": "ophthalmic_retina",
                "organ_label": "視網膜底",
                "lesion_label": "黃斑變性",
            },
        },
        # 2. 耳鼻喉氣道
        {
            "blueprint": "pathology_mechanism",
            "title": "喉氣道狹窄機轉",
            "params": {
                **default_params("pathology_mechanism"),
                "organ_system": "ent_airway",
                "organ_label": "喉氣道腔",
                "lesion_label": "水腫狹窄",
            },
        },
        # 3. 泌尿生殖
        {
            "blueprint": "pathology_mechanism",
            "title": "精索靜脈曲張機轉",
            "params": {
                **default_params("pathology_mechanism"),
                "organ_system": "uro_genital",
                "organ_label": "骨盆靜脈",
                "lesion_label": "叢狀怒張",
            },
        },
        # 4. 牙周骨再生
        {
            "blueprint": "pathology_mechanism",
            "title": "牙周骨吸收機轉",
            "params": {
                **default_params("pathology_mechanism"),
                "organ_system": "dental_periodontal",
                "organ_label": "齒槽骨壁",
                "lesion_label": "骨內袋坑",
            },
        },
        # 5. 中醫特種針法
        {
            "blueprint": "pathology_mechanism",
            "title": "督脈挑刺經絡機轉",
            "params": {
                **default_params("pathology_mechanism"),
                "organ_system": "tcm_special_acup",
                "organ_label": "督脈尾閭",
                "lesion_label": "筋結沾黏",
            },
        },
        # 6. 次專科 contrast
        {
            "blueprint": "contrast",
            "title": "氣道狹窄與通暢對照",
            "params": {
                "left": {
                    "title": "病理充血",
                    "note": "氣道狹窄",
                    "mode": "airway_laryngeal_edema",
                    "core_effect": "dim",
                    "core_label": "通氣阻抗",
                    "footnote": "未及時正規評估",
                    "unit_fill": "warn",
                },
                "right": {
                    "title": "通暢復原",
                    "note": "氣道恢復",
                    "mode": "airway_patency_restore",
                    "rows": 3,
                    "per_row": 5,
                    "footnote": "正規專科穩定照護",
                    "unit_fill": "ok",
                },
            },
        },
        # 7. 次專科 timeline
        {
            "blueprint": "timeline",
            "title": "視網膜修復歷程",
            "params": {
                "milestones": ["門診散瞳", "光學斷層", "定期追蹤"],
                "unit_effect": "glow_restored",
                "connectors": "retinal_epithelium_repair",
                "units": 3,
                "unit_fill": "accent",
            },
        },
    ]

    for tc in test_cases:
        bp = tc["blueprint"]
        params_json = json.dumps(tc["params"], ensure_ascii=False)
        title_json = json.dumps(tc.get("title", "專科解說"), ensure_ascii=False)

        # 掛載
        playwright_page.evaluate(f"""
            (() => {{
                const svg = document.getElementById('testSvg');
                window.__inst = window.ClinicVisual.mount(svg, [
                    {{ blueprint: '{bp}', title: {title_json}, params: {params_json} }}
                ]);
            }})()
        """)

        total_dur = playwright_page.evaluate("window.__inst.totalDuration")
        assert total_dur > 0

        # 抽檢 5 個關鍵影格
        for u in [0.0, 0.35, 0.5, 0.8, 1.0]:
            t = u * total_dur
            playwright_page.evaluate(f"window.__inst.renderAt({t})")

            # 抓取所有 text 節點內容，檢驗零半形阿拉伯數字
            text_nodes = playwright_page.evaluate("""
                Array.from(document.querySelectorAll('#testSvg text')).map(el => el.textContent)
            """)
            for txt in text_nodes:
                assert not re.search(r"\d", txt), f"專科渲染畫面文字含有阿拉伯數字: {txt}"

    assert len(console_errors) == 0, f"瀏覽器控制台回報錯誤: {console_errors}"


def test_nhi400_render_determinism(playwright_page, tmp_path):
    """驗證正向與逆向 renderAt 在進度 u = 0.5 時產出的 SVG 完全一致（100% 確定性）。"""
    _setup_browser_page(playwright_page, tmp_path)

    params = {
        "milestones": ["初期疏通", "經絡得氣", "氣血調和"],
        "unit_effect": "glow_restored",
        "connectors": "meridian_unblock_healing",
        "units": 3,
        "unit_fill": "accent",
    }
    params_json = json.dumps(params, ensure_ascii=False)

    playwright_page.evaluate(f"""
        (() => {{
            const svg = document.getElementById('testSvg');
            window.__inst = window.ClinicVisual.mount(svg, [
                {{ blueprint: 'timeline', title: '經絡疏通歷程', params: {params_json} }}
            ]);
        }})()
    """)

    total_dur = playwright_page.evaluate("window.__inst.totalDuration")
    assert total_dur > 0

    # 1. 正向 seek 到 0.5
    t_mid = 0.5 * total_dur
    playwright_page.evaluate(f"window.__inst.renderAt(0); window.__inst.renderAt({0.2 * total_dur}); window.__inst.renderAt({t_mid});")
    html_fwd = playwright_page.evaluate("document.getElementById('testSvg').outerHTML")

    # 2. 逆向 seek 到 0.5
    playwright_page.evaluate(f"window.__inst.renderAt({total_dur}); window.__inst.renderAt({0.8 * total_dur}); window.__inst.renderAt({t_mid});")
    html_rev = playwright_page.evaluate("document.getElementById('testSvg').outerHTML")

    assert html_fwd == html_rev, "正向與逆向 seek 產出 SVG 不具備確定性"
