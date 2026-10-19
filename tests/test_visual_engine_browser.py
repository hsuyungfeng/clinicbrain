"""
Phase 30 Plan 02 Task 3: 視覺場景引擎瀏覽器測試 (test_visual_engine_browser.py)。

驗證項目：
1. 契約測試：
   - Object.keys(ClinicVisual.blueprints) 與 Python BLUEPRINTS 鍵集合一致。
   - 各 blueprint 的 params 欄位名清單與 Python 一致。
   - ClinicVisual.PALETTE 鍵集合與 Python PALETTE_TOKENS 一致。
2. 向量測試：
   - 以 tests/fixtures/visual_merge_vectors.json 逐組驗證 resolveParams 合併結果。
3. 確定性測試：
   - 順序、逆序、隨機 seek 在相同進度 u 下產生的 outerHTML 100% 完全相同。
4. 邊界測試：
   - 排除 defs/clipPath/data-bg 背景/opacity 0 元素。
   - 所有元素落在 viewBox 邊界 [5, 795] x [5, 505] 內（容差 1 單位）。
   - 字幕安全區（y <= 410）只檢查 text 元素（y <= 411）。
5. 降級測試：
   - 未知 blueprint、缺 params、數值超範圍、未知調色盤代號皆不拋例外且安全渲染。
6. 零違規：
   - 載入與渲染過程 console 零 error，無任何非 file:// 網路請求。
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.visual.blueprints import BLUEPRINTS, PALETTE_TOKENS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENGINE_JS_PATH = PROJECT_ROOT / "src" / "web" / "static" / "visual_engine.js"
VECTORS_PATH = PROJECT_ROOT / "tests" / "fixtures" / "visual_merge_vectors.json"


def _create_test_html(tmp_path: Path) -> Path:
    """建立載入 visual_engine.js 的最小測試頁面。"""
    html_content = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="utf-8">
  <title>Visual Engine Test</title>
</head>
<body style="margin:0;padding:0;background:#000;">
  <svg id="testSvg" width="800" height="510" viewBox="0 0 800 510"></svg>
  <script src="{ENGINE_JS_PATH.as_uri()}"></script>
</body>
</html>
"""
    html_file = tmp_path / "engine_test.html"
    html_file.write_text(html_content, encoding="utf-8")
    return html_file


def _setup_page(playwright_page, tmp_path: Path):
    """導航至測試頁面並掛載監聽器。"""
    console_errors = []
    network_requests = []

    def on_console(msg):
        if msg.type == "error":
            console_errors.append(msg.text)

    def on_request(req):
        network_requests.append(req.url)

    playwright_page.on("console", on_console)
    playwright_page.on("request", on_request)

    test_html = _create_test_html(tmp_path)
    playwright_page.goto(test_html.as_uri())

    return console_errors, network_requests


def test_visual_engine_page_load_and_zero_violations(playwright_page, tmp_path):
    """驗證引擎載入正常、無 console 錯誤、無非 file:// 請求。"""
    console_errors, network_requests = _setup_page(playwright_page, tmp_path)

    # 檢查是否只請求本機 file:// 資源
    for req_url in network_requests:
        assert req_url.startswith("file://"), f"不允許的網路請求：{req_url}"

    assert console_errors == [], f"載入期間出現 console 錯誤：{console_errors}"

    is_defined = playwright_page.evaluate("typeof window.ClinicVisual === 'object'")
    assert is_defined is True, "window.ClinicVisual 必須為 object"


def test_visual_engine_contract(playwright_page, tmp_path):
    """驗證 JS 引擎與 Python BLUEPRINTS / PALETTE_TOKENS 契約完全一致。"""
    _setup_page(playwright_page, tmp_path)

    # 1. blueprint 名稱集合相等
    js_blueprints = set(playwright_page.evaluate("Object.keys(window.ClinicVisual.blueprints)"))
    py_blueprints = set(BLUEPRINTS.keys())
    assert js_blueprints == py_blueprints, f"Blueprint 註冊集合不一致: JS={js_blueprints}, PY={py_blueprints}"

    # 2. 各 blueprint 的 params 欄位清單相等
    for bp_name in py_blueprints:
        js_params = set(playwright_page.evaluate(f"window.ClinicVisual.blueprints['{bp_name}'].params"))
        py_params = set(BLUEPRINTS[bp_name]["params"].keys())
        assert js_params == py_params, f"Blueprint '{bp_name}' 的 params 欄位不符: JS={js_params}, PY={py_params}"

    # 3. PALETTE 鍵集合相等
    js_palette_keys = set(playwright_page.evaluate("Object.keys(window.ClinicVisual.PALETTE)"))
    py_palette_keys = set(PALETTE_TOKENS)
    assert js_palette_keys == py_palette_keys, f"PALETTE 鍵集合不一致: JS={js_palette_keys}, PY={py_palette_keys}"


def test_visual_engine_resolve_params_vectors(playwright_page, tmp_path):
    """以 visual_merge_vectors.json 逐組驗證 ClinicVisual.resolveParams。"""
    _setup_page(playwright_page, tmp_path)

    assert VECTORS_PATH.exists(), f"找不到向量檔：{VECTORS_PATH}"
    vectors = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))

    for vec in vectors:
        bp = vec["blueprint"]
        inp = vec["input_params"]
        expected = vec["expected"]

        actual = playwright_page.evaluate(
            "({bp, inp}) => window.ClinicVisual.resolveParams(bp, inp)",
            {"bp": bp, "inp": inp},
        )
        assert actual == expected, (
            f"向量驗證失敗 ({vec.get('description', bp)}):\n"
            f"Expected: {json.dumps(expected, ensure_ascii=False)}\n"
            f"Actual:   {json.dumps(actual, ensure_ascii=False)}"
        )


def test_visual_engine_determinism(playwright_page, tmp_path):
    """驗證三個 blueprint 在相同 u 下多次 seek、倒退 seek 產生的 outerHTML 絕對確定且一致。"""
    _setup_page(playwright_page, tmp_path)

    test_u_values = [0.0, 0.25, 0.5, 0.75, 1.0]

    for bp in ("process_diagram", "contrast", "timeline"):
        # 掛載測試場景
        playwright_page.evaluate(
            f"""(() => {{
            const svg = document.getElementById('testSvg');
            window.__mounted = window.ClinicVisual.mount(svg, [
              {{ blueprint: '{bp}', title: '測試確定性', params: null }}
            ]);
        }})()"""
        )

        total_dur = playwright_page.evaluate("window.__mounted.totalDuration")
        assert total_dur > 0

        # 正向順序渲染並紀錄 HTML
        forward_snapshots = {}
        for u in test_u_values:
            t = u * total_dur
            html = playwright_page.evaluate(f"window.__mounted.renderAt({t}); document.getElementById('testSvg').outerHTML")
            forward_snapshots[u] = html

        # 亂序與倒退渲染，驗證 outerHTML 絕對相等
        reverse_u_values = [1.0, 0.5, 0.25, 0.75, 0.0, 0.5]
        for u in reverse_u_values:
            t = u * total_dur
            html = playwright_page.evaluate(f"window.__mounted.renderAt({t}); document.getElementById('testSvg').outerHTML")
            assert html == forward_snapshots[u], f"Blueprint {bp} 在 u={u} 處倒退 seek 輸出不確定！"


def test_visual_engine_bounding_boxes_and_safe_zone(playwright_page, tmp_path):
    """以 getBoundingClientRect 換算座標，驗證所有繪圖元素落在邊界內且 text 落在安全區（y <= 410）。"""
    _setup_page(playwright_page, tmp_path)

    check_bounds_script = """(function() {
        const svgEl = document.getElementById('testSvg');
        const svgRect = svgEl.getBoundingClientRect();
        const scaleX = 800 / svgRect.width;
        const scaleY = 510 / svgRect.height;

        const elements = svgEl.querySelectorAll('*');
        const violations = [];

        for (const el of elements) {
            const tag = el.tagName.toLowerCase();
            if (tag === 'defs' || tag === 'clippath' || tag === 'g' || tag === 'svg') continue;
            if (el.closest('defs') || el.closest('clipPath')) continue;
            if (el.getAttribute('data-bg') === '1') continue;

            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            const op = parseFloat(style.opacity);
            if (Number.isFinite(op) && op <= 0.01) continue;
            const attrOp = parseFloat(el.getAttribute('opacity'));
            if (Number.isFinite(attrOp) && attrOp <= 0.01) continue;

            const rect = el.getBoundingClientRect();
            if (rect.width <= 0.1 || rect.height <= 0.1) continue;

            const vx1 = (rect.left - svgRect.left) * scaleX;
            const vy1 = (rect.top - svgRect.top) * scaleY;
            const vx2 = (rect.right - svgRect.left) * scaleX;
            const vy2 = (rect.bottom - svgRect.top) * scaleY;

            // 邊界檢查：[6, 794] x [6, 504]，容差 1 單位 -> [5, 795] x [5, 505]
            if (vx1 < 5 || vx2 > 795 || vy1 < 5 || vy2 > 505) {
                violations.push({ tag, text: el.textContent, vx1, vy1, vx2, vy2, type: 'out_of_bounds' });
            }

            // 字幕安全區（y <= 410）只檢查 text 元素，容差 1 單位 -> vy2 <= 411
            if (tag === 'text') {
                if (vy2 > 411) {
                    violations.push({ tag, text: el.textContent, vy1, vy2, type: 'subtitle_overlap' });
                }
            }
        }
        return violations;
    })()"""

    test_u_points = [0.0, 0.5, 1.0]

    for bp in ("process_diagram", "contrast", "timeline"):
        playwright_page.evaluate(
            f"""(() => {{
            const svg = document.getElementById('testSvg');
            window.__mounted = window.ClinicVisual.mount(svg, [
              {{ blueprint: '{bp}', title: '邊界量測', params: null }}
            ]);
        }})()"""
        )
        total_dur = playwright_page.evaluate("window.__mounted.totalDuration")

        for u in test_u_points:
            t = u * total_dur
            playwright_page.evaluate(f"window.__mounted.renderAt({t})")
            violations = playwright_page.evaluate(check_bounds_script)
            assert violations == [], f"Blueprint {bp} 在 u={u} 處發生邊界違規：{violations}"


def test_visual_engine_graceful_degradation(playwright_page, tmp_path):
    """驗證未知 blueprint、缺 params、超界數值與未知 palette 皆安全降級不拋錯。"""
    console_errors, _ = _setup_page(playwright_page, tmp_path)

    # 1. 未知 blueprint
    playwright_page.evaluate(
        """(() => {
        const svg = document.getElementById('testSvg');
        const m = window.ClinicVisual.mount(svg, [
            { blueprint: 'future_laser_treatment', title: '未來雷射降級畫面' }
        ]);
        m.renderAt(2);
    })()"""
    )
    assert console_errors == []

    # 2. 超界數值與未知 palette token
    playwright_page.evaluate(
        """(() => {
        const svg = document.getElementById('testSvg');
        const m = window.ClinicVisual.mount(svg, [
            {
                blueprint: 'process_diagram',
                title: '異常參數降級',
                params: {
                    particles: 9999,
                    source: { fill: 'super_neon_pink_not_exist' }
                }
            }
        ]);
        m.renderAt(4);
    })()"""
    )
    assert console_errors == []

    # 3. scene 缺 params (None)
    playwright_page.evaluate(
        """(() => {
        const svg = document.getElementById('testSvg');
        const m = window.ClinicVisual.mount(svg, [
            { blueprint: 'contrast', title: '無參數降級', params: null }
        ]);
        m.renderAt(3);
    })()"""
    )
    assert console_errors == []
