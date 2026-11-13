"""
Phase 44 Plan 03 Task 2: 次世代生動向量視覺引擎全景確定性與 2.5D 光影驗收測試 (test_nextgen_visual_engine.py)。

驗證項目：
1. Defs 擴充驗證：
   - 包含 2.5D 透光漸層 (grad-tissue-subsurface, grad-energy-core, grad-healing-glow, grad-mucosa-inflamed, grad-fascia-sheen, grad-energy-beam)。
   - 包含軟陰影濾鏡 (filter-drop-shadow-soft)。
2. 60fps Forward / Reverse Seek 確定性驗證：
   - 針對所有 14 大 Blueprints，驗證正向、反向、亂序 seek 至相同時間點時，產生的 outerHTML 100% 嚴格一致。
3. 代表性專科 Blueprint 渲染安全與零異常：
   - 抽查 process_diagram, skin_energy, laser_action, dermal_support, deep_plane_facelift, surgical_action, pathology_mechanism。
   - 驗證 outerHTML 絕對不含 'NaN', 'undefined', 'null' 屬性字樣。
   - 驗證瀏覽器 console 零 error。
4. Scene 2 (contrast) 與 Scene 3 (timeline) 次世代動效生成檢查：
   - contrast 渲染時具備翡翠綠屏障與顫動偏移。
   - timeline 節點在活躍狀態下生成金色微粒子 (Sparkle Dust)。
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.visual.blueprints import BLUEPRINTS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENGINE_JS_PATH = PROJECT_ROOT / "src" / "web" / "static" / "visual_engine.js"


def _create_test_html(tmp_path: Path) -> Path:
    html_content = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="utf-8">
  <title>NextGen Visual Engine Test</title>
</head>
<body style="margin:0;padding:0;background:#000;">
  <svg id="testSvg" width="800" height="510" viewBox="0 0 800 510"></svg>
  <script src="{ENGINE_JS_PATH.as_uri()}"></script>
</body>
</html>
"""
    html_file = tmp_path / "nextgen_engine_test.html"
    html_file.write_text(html_content, encoding="utf-8")
    return html_file


def _setup_page(playwright_page, tmp_path: Path):
    console_errors = []

    def on_console(msg):
        if msg.type == "error":
            console_errors.append(msg.text)

    playwright_page.on("console", on_console)
    test_html = _create_test_html(tmp_path)
    playwright_page.goto(test_html.as_uri())
    playwright_page.wait_for_function("typeof window.ClinicVisual !== 'undefined'")
    return console_errors


def test_nextgen_defs_and_motion_loaded(playwright_page, tmp_path):
    """驗證次世代 Defs 與 ClinicMotion 在瀏覽器中正確注入且無重複。"""
    _setup_page(playwright_page, tmp_path)

    res = playwright_page.evaluate("""() => {
        const svg = document.getElementById('testSvg');
        const inst = window.ClinicVisual.mount(svg, [
            { blueprint: 'process_diagram', title: '測試', params: null }
        ]);
        inst.renderAt(0);

        const defs = svg.querySelector('defs');
        const gradIds = Array.from(defs.querySelectorAll('radialGradient, linearGradient, filter')).map(el => el.id);
        const hasMotion = typeof window.ClinicVisual.motion === 'object' && typeof window.ClinicVisual.motion.springGentle === 'function';

        return {
            defsCount: svg.querySelectorAll('defs').length,
            gradIds: gradIds,
            hasMotion: hasMotion
        };
    }""")

    assert res["defsCount"] == 1, "全局 defs 必須恰好注入一次"
    assert res["hasMotion"], "ClinicVisual.motion 必須正確匯出"

    expected_ids = [
        "grad-tissue-subsurface",
        "grad-energy-core",
        "grad-healing-glow",
        "grad-mucosa-inflamed",
        "grad-fascia-sheen",
        "grad-fascia-highlight",
        "grad-energy-beam",
        "filter-drop-shadow-soft"
    ]
    for gid in expected_ids:
        assert gid in res["gradIds"], f"缺少次世代漸層/濾鏡: {gid}"


def test_nextgen_all_blueprints_seek_determinism(playwright_page, tmp_path):
    """驗證所有 Blueprint 在 forward / reverse seek 過程具備 100% outerHTML 確定性。"""
    _setup_page(playwright_page, tmp_path)

    test_u_points = [0.0, 0.25, 0.5, 0.75, 1.0]

    for bp in BLUEPRINTS:
        playwright_page.evaluate(f"""(() => {{
            const svg = document.getElementById('testSvg');
            window.__mounted = window.ClinicVisual.mount(svg, [
                {{ blueprint: '{bp}', title: '確定性測試', params: null }}
            ]);
        }})()""")

        dur = playwright_page.evaluate("window.__mounted.totalDuration")
        assert dur > 0

        # 正向快照
        forward_snaps = {}
        for u in test_u_points:
            t = u * dur
            html = playwright_page.evaluate(f"window.__mounted.renderAt({t}); document.getElementById('testSvg').outerHTML")
            forward_snaps[u] = html

        # 逆向與隨機快照核對
        check_sequence = [1.0, 0.75, 0.0, 0.5, 0.25, 0.5]
        for u in check_sequence:
            t = u * dur
            html = playwright_page.evaluate(f"window.__mounted.renderAt({t}); document.getElementById('testSvg').outerHTML")
            assert html == forward_snaps[u], f"Blueprint {bp} 在 u={u} 倒退 seek 時輸出不一致！"


def test_nextgen_no_nan_or_undefined_attributes(playwright_page, tmp_path):
    """抽查代表性專科藍圖，驗證在各影格渲染時絕對不含 NaN / undefined / null 屬性字串。"""
    errors = _setup_page(playwright_page, tmp_path)

    sample_blueprints = [
        "process_diagram",
        "contrast",
        "timeline",
        "skin_energy",
        "laser_action",
        "dermal_support",
        "deep_plane_facelift",
        "surgical_action",
        "pathology_mechanism"
    ]

    for bp in sample_blueprints:
        playwright_page.evaluate(f"""(() => {{
            const svg = document.getElementById('testSvg');
            window.__mounted = window.ClinicVisual.mount(svg, [
                {{ blueprint: '{bp}', title: '光影渲染檢查', params: null }}
            ]);
        }})()""")

        dur = playwright_page.evaluate("window.__mounted.totalDuration")
        for u in [0.0, 0.15, 0.45, 0.72, 1.0]:
            t = u * dur
            html = playwright_page.evaluate(f"window.__mounted.renderAt({t}); document.getElementById('testSvg').outerHTML")

            assert '="NaN"' not in html, f"{bp} 在 u={u} 包含 NaN 屬性"
            assert '="undefined"' not in html, f"{bp} 在 u={u} 包含 undefined 屬性"
            assert '="null"' not in html, f"{bp} 在 u={u} 包含 null 屬性"

    assert len(errors) == 0, f"控制台出現異常錯誤：{errors}"


def test_nextgen_scene2_and_scene3_dynamics(playwright_page, tmp_path):
    """驗證 Scene 2 (contrast) 翡翠綠屏障與 Scene 3 (timeline) 金色微粒子 (Sparkle Dust)。"""
    _setup_page(playwright_page, tmp_path)

    # 驗證 contrast 翡翠綠屏障
    playwright_page.evaluate("""(() => {
        const svg = document.getElementById('testSvg');
        const inst = window.ClinicVisual.mount(svg, [
            { blueprint: 'contrast', title: '對照場景', params: null }
        ]);
        inst.renderAt(4.0); // u = 0.5
    })()""")

    contrast_html = playwright_page.evaluate("document.getElementById('testSvg').outerHTML")
    assert 'stroke="#6ee7b7"' in contrast_html, "Scene 2 (contrast) 必須包含翡翠綠流光屏障"
    assert 'stroke="#ef4444"' in contrast_html, "Scene 2 (contrast) 對照組必須包含紅色警示震顫框"

    # 驗證 timeline Sparkle Dust 綻放
    playwright_page.evaluate("""(() => {
        const svg = document.getElementById('testSvg');
        const inst = window.ClinicVisual.mount(svg, [
            { blueprint: 'timeline', title: '時間軸場景', params: null }
        ]);
        inst.renderAt(1.5); // 節點一激活初期
    })()""")

    timeline_html = playwright_page.evaluate("document.getElementById('testSvg').outerHTML")
    assert 'fill="url(#grad-healing-glow)"' in timeline_html, "Scene 3 (timeline) 活躍節點必須包含金色癒合光圈"
    assert 'fill="#fef08a"' in timeline_html, "Scene 3 (timeline) 必須包含金色修復微粒子 (Sparkle Dust)"
