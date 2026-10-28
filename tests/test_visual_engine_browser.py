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

from src.visual.blueprints import BLUEPRINTS, PALETTE_TOKENS, merge_defaults

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

    for bp in BLUEPRINTS:
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

    for bp in BLUEPRINTS:
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


def _texts_of_scene(playwright_page, blueprint: str, params_json: str, u: float) -> list:
    return playwright_page.evaluate(
        f"""(() => {{
        const svg = document.getElementById('testSvg');
        const m = window.ClinicVisual.mount(svg, [{{ blueprint: '{blueprint}', title: 't', params: {params_json} }}]);
        m.renderAt({u} * m.totalDuration);
        return Array.from(svg.querySelectorAll('text')).map(e => e.textContent);
    }})()"""
    )


def test_contrast_has_no_hardcoded_fat_graft_text(playwright_page, tmp_path):
    """回歸（2026-10-19）：玻尿酸驗證主題暴露對照場景寫死『中心缺血／不易獲取充足養分』。
    現在核心標籤與底註都來自 params；core_effect=none 時不得畫核心暗化與其標籤。"""
    _setup_page(playwright_page, tmp_path)
    gel = json.dumps({
        "left": {"title": "單點過量", "note": "較不自然", "mode": "mass", "core_effect": "none",
                 "core_label": "集中放置", "footnote": "集中放置：易顯得不自然", "unit_fill": "gel"},
        "right": {"title": "分點少量", "note": "更貼近自然", "mode": "layered", "rows": 2, "per_row": 5,
                  "footnote": "分散放置：貼近自然", "unit_fill": "gel"},
    }, ensure_ascii=False)
    for u in (0.5, 1.0):
        texts = _texts_of_scene(playwright_page, "contrast", gel, u)
        joined = "".join(texts)
        assert "缺血" not in joined and "養分" not in joined, f"不得出現脂肪移植專屬字樣：{texts}"
        assert "集中放置：易顯得不自然" in joined and "分散放置：貼近自然" in joined

    # 預設（脂肪移植）仍保留原畫面文字
    default_texts = "".join(_texts_of_scene(playwright_page, "contrast", "null", 1.0))
    assert "中心缺血" in default_texts and "不易獲取充足養分" in default_texts


def test_unit_fill_param_changes_unit_color(playwright_page, tmp_path):
    """unit_fill 以調色盤代號控制脂肪球／凝膠球顏色；fat 與 gel 渲染結果必須不同。"""
    _setup_page(playwright_page, tmp_path)

    def fills(bp, params_json):
        return playwright_page.evaluate(
            f"""(() => {{
            const svg = document.getElementById('testSvg');
            const m = window.ClinicVisual.mount(svg, [{{ blueprint: '{bp}', title: 't', params: {params_json} }}]);
            m.renderAt(m.totalDuration);
            return Array.from(svg.querySelectorAll('circle')).map(e => e.getAttribute('fill'));
        }})()"""
        )

    assert fills("timeline", '{"unit_fill":"fat"}') != fills("timeline", '{"unit_fill":"gel"}')
    right_fat = fills("contrast", '{"right":{"unit_fill":"fat"}}')
    right_gel = fills("contrast", '{"right":{"unit_fill":"gel"}}')
    assert right_fat != right_gel


_PLAN_32_02_NEW_MODES = [
    ("contrast", {"left": {"mode": "wide_incision", "core_label": "神經受壓"}}),
    ("contrast", {"left": {"mode": "thermal_spread"}}),
    ("contrast", {"right": {"mode": "minimal_incision"}}),
    ("contrast", {"right": {"mode": "targeted_energy"}}),
    ("timeline", {"connectors": "wound_healing"}),
    ("timeline", {"connectors": "collagen_remodeling"}),
    ("surgical_action", {}),
]


def test_plan_32_02_new_modes_render_without_errors(playwright_page, tmp_path):
    """Plan 32-02：contrast/timeline 新增模式與 surgical_action 於各進度皆可渲染，無 console 錯誤。"""
    import json as _json

    console_errors, _ = _setup_page(playwright_page, tmp_path)
    for bp, overrides in _PLAN_32_02_NEW_MODES:
        payload = _json.dumps(overrides, ensure_ascii=False)
        counts = playwright_page.evaluate(
            f"""(() => {{
            const svg = document.getElementById('testSvg');
            svg.innerHTML = '';
            const m = window.ClinicVisual.mount(svg, [{{ blueprint: '{bp}', title: 't', params: {payload} }}]);
            const out = [];
            for (const f of [0, 0.5, 1]) {{
                m.renderAt(f * m.totalDuration);
                out.push(svg.children.length);
            }}
            return out;
        }})()"""
        )
        assert all(c > 0 for c in counts), (bp, overrides, counts)

    assert console_errors == []


def test_wide_incision_shows_nerve_label_at_full_progress(playwright_page, tmp_path):
    """wide_incision 於完成時應顯示神經壓迫標籤（來自 params.core_label，非寫死文字）。"""
    _setup_page(playwright_page, tmp_path)
    texts = playwright_page.evaluate(
        """(() => {
        const svg = document.getElementById('testSvg');
        const m = window.ClinicVisual.mount(svg, [{ blueprint: 'contrast', title: 't',
            params: { left: { mode: 'wide_incision', core_label: '神經受壓' } } }]);
        m.renderAt(m.totalDuration);
        return Array.from(svg.querySelectorAll('text')).map(e => e.textContent);
    })()"""
    )
    assert "神經受壓" in texts


def test_plan_32_02_enum_values_survive_sanitizer(playwright_page, tmp_path):
    """回歸：JS 正規化白名單必須與 Python 列舉一致，否則新模式會被靜默退回預設（2026-10-21 實機發現）。"""
    _setup_page(playwright_page, tmp_path)
    pairs = [
        ("contrast", "left", "mode", "wide_incision"),
        ("contrast", "left", "mode", "thermal_spread"),
        ("contrast", "right", "mode", "minimal_incision"),
        ("contrast", "right", "mode", "targeted_energy"),
        ("timeline", None, "connectors", "wound_healing"),
        ("timeline", None, "connectors", "collagen_remodeling"),
    ]
    for bp, side, key, value in pairs:
        inp = {side: {key: value}} if side else {key: value}
        got = playwright_page.evaluate(
            "([bp, inp]) => window.ClinicVisual.resolveParams(bp, inp)",
            [bp, inp],
        )
        actual = got[side][key] if side else got[key]
        assert actual == value, (bp, side, key, value, actual)


_PHASE33_BOUNDS_SCRIPT = """(function() {
    const svgEl = document.getElementById('testSvg');
    const svgRect = svgEl.getBoundingClientRect();
    const scaleX = 800 / svgRect.width;
    const scaleY = 510 / svgRect.height;
    const violations = [];
    for (const el of svgEl.querySelectorAll('*')) {
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
        if (vx1 < 5 || vx2 > 795 || vy1 < 5 || vy2 > 505) {
            violations.push({ tag, text: el.textContent, vx1, vy1, vx2, vy2, type: 'out_of_bounds' });
        }
        if (tag === 'text' && vy2 > 411) {
            violations.push({ tag, text: el.textContent, vy2, type: 'subtitle_overlap' });
        }
    }
    return violations;
})()"""

# Phase 33：5 組 contrast 專科 + glow_restored + 5 組 timeline 修復歷程
_PHASE33_CASES = [
    ("contrast", {"left": {"mode": "tissue_trauma_torn_vessel"}, "right": {"mode": "ultrasonic_emulsification"}}),
    ("contrast", {"left": {"mode": "scar_contracture_ectropion"}, "right": {"mode": "transconjunctival_fat_reposition"}}),
    ("contrast", {"left": {"mode": "silicone_extrusion_erythema"}, "right": {"mode": "cartilage_triangular_strut"}}),
    ("contrast", {"left": {"mode": "capsular_contracture_ball"}, "right": {"mode": "dual_plane_natural_teardrop"}}),
    ("contrast", {"left": {"mode": "nodule_clumping"}, "right": {"mode": "micro_droplet_diffusion"}}),
    ("timeline", {"connectors": "bone_healing"}),
    ("timeline", {"connectors": "bruise_metabolism"}),
    ("timeline", {"connectors": "scar_maturation"}),
    ("timeline", {"connectors": "nerve_regeneration"}),
    ("timeline", {"connectors": "skin_retraction"}),
    ("timeline", {"connectors": "skin_retraction", "unit_effect": "glow_restored"}),
]


def _mount_phase33(page, bp, overrides):
    import json as _json
    payload = _json.dumps(overrides, ensure_ascii=False)
    page.evaluate(
        f"""(() => {{
        const svg = document.getElementById('testSvg');
        svg.innerHTML = '';
        window.__mounted = window.ClinicVisual.mount(svg, [{{ blueprint: '{bp}', title: 't', params: {payload} }}]);
    }})()"""
    )


def test_phase33_determinism_forward_and_reverse_seek(playwright_page, tmp_path):
    """Phase 33：每個新模式正向與倒退 seek 的 outerHTML 必須完全一致（確定性）。"""
    _setup_page(playwright_page, tmp_path)
    for bp, overrides in _PHASE33_CASES:
        _mount_phase33(playwright_page, bp, overrides)
        total = playwright_page.evaluate("window.__mounted.totalDuration")
        forward = {}
        for u in [0.0, 0.25, 0.5, 0.75, 1.0]:
            forward[u] = playwright_page.evaluate(
                f"window.__mounted.renderAt({u} * {total}); document.getElementById('testSvg').outerHTML"
            )
        for u in [1.0, 0.5, 0.0, 0.75, 0.25, 0.5]:
            html = playwright_page.evaluate(
                f"window.__mounted.renderAt({u} * {total}); document.getElementById('testSvg').outerHTML"
            )
            assert html == forward[u], (bp, overrides, u)


def test_phase33_bounds_and_subtitle_safe_zone(playwright_page, tmp_path):
    """Phase 33：每個新模式在 u=0/0.5/1 的所有圖元都在安全邊界內，文字 y<=411。"""
    _setup_page(playwright_page, tmp_path)
    for bp, overrides in _PHASE33_CASES:
        _mount_phase33(playwright_page, bp, overrides)
        total = playwright_page.evaluate("window.__mounted.totalDuration")
        for u in [0.0, 0.5, 1.0]:
            playwright_page.evaluate(f"window.__mounted.renderAt({u} * {total})")
            violations = playwright_page.evaluate(_PHASE33_BOUNDS_SCRIPT)
            assert violations == [], (bp, overrides, u, violations)


def test_phase33_enum_whitelist_matches_python_spec(playwright_page, tmp_path):
    """Phase 33：JS 白名單必須保留所有新列舉值（與 Python 規格一致，否則會被靜默退回預設）。"""
    _setup_page(playwright_page, tmp_path)
    for bp, overrides in _PHASE33_CASES:
        got = playwright_page.evaluate(
            "([bp, inp]) => window.ClinicVisual.resolveParams(bp, inp)", [bp, overrides]
        )
        for side in ("left", "right"):
            if side in overrides:
                assert got[side]["mode"] == overrides[side]["mode"], (bp, side, got[side]["mode"])
        if "connectors" in overrides:
            assert got["connectors"] == overrides["connectors"]
        if "unit_effect" in overrides:
            assert got["unit_effect"] == overrides["unit_effect"]


# ============================================================================
# 幾何審計與相鄰影格跳變檢查（Phase 35）
#
# 對每個 blueprint 的預設參數與每個列舉參數的每個值，沿時間軸密集取樣，
# 在瀏覽器內量測每個繪圖元素的實際位置：
# - 幾何審計：座標有限（無 NaN／Infinity／undefined）、所有元素落在
#   [5, 795] x [5, 505] 內、字幕安全區（text y <= 411）、文字與文字不得大面積重疊。
# - 跳變檢查：相鄰影格之間，同一元素的邊界不得瞬間位移超過 POP_JUMP_UNITS，
#   元素數量在影格之間不得突然增減（視覺 pop）。
# ============================================================================

# 取樣影格數與跳變門檻（viewBox 單位）。總時長 / 影格數 ≈ 0.05~0.1 秒/影格。
POP_SAMPLE_FRAMES = 160
POP_JUMP_UNITS = 25.0
TEXT_OVERLAP_RATIO = 0.3


# 引擎宣告的硬切換點：timeline（drawTimeline 的 stageIdx）、surgical_action
# （drawSurgicalAction）與 cyst_excision（drawCystExcision）皆在 u=0.35 與 u=0.70 切換階段。
# 這些瞬間變化是設計內容，僅允許落在這兩個 u 的那一影格上；其他位置一律視為 pop。
DECLARED_STAGE_CUTS = {
    "timeline": (0.35, 0.70),
    "surgical_action": (0.35, 0.70),
    "cyst_excision": (0.35, 0.70),
}


def _is_declared_cut(bp: str, frame: int, n: int) -> bool:
    cuts = DECLARED_STAGE_CUTS.get(bp, ())
    u = frame / n
    return any(abs(u - c) < 1.0 / n / 2 for c in cuts)


def _variants_for_sweep() -> list[tuple[str, dict | None]]:
    """每個 blueprint 的預設參數，加上每個列舉參數的每個值（一次只變一個參數）。"""
    out: list[tuple[str, dict | None]] = []
    for bp, spec in BLUEPRINTS.items():
        out.append((bp, None))
        for pname, pspec in spec["params"].items():
            if pspec.get("type") == "enum":
                for value in pspec["values"]:
                    out.append((bp, {pname: value}))
    return out


_SWEEP_JS = """(function (bp, params, N, jump, overlapRatio) {
    const MATCH_R = 60;
    const MIN_SIZE = 4;
    const svg = document.getElementById('testSvg');
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const mounted = window.ClinicVisual.mount(svg, [{ blueprint: bp, title: '審計', params: params }]);
    const total = mounted.totalDuration;
    const svgRect = svg.getBoundingClientRect();
    const sx = 800 / svgRect.width;
    const sy = 510 / svgRect.height;

    function snap() {
        const out = [];
        svg.querySelectorAll('*').forEach(function (el) {
            const tag = el.tagName.toLowerCase();
            if (tag === 'defs' || tag === 'clippath' || tag === 'svg' || tag === 'g') return;
            if (el.closest('defs') || el.closest('clipPath')) return;
            if (el.getAttribute('data-bg') === '1') return;
            const r = el.getBoundingClientRect();
            if (r.width <= 0.1 || r.height <= 0.1) return;
            const op = parseFloat(window.getComputedStyle(el).opacity);
            out.push({
                tag: tag,
                id: el.getAttribute('data-id') || '',
                text: tag === 'text' ? el.textContent : '',
                op: Number.isFinite(op) ? op : 1,
                x1: (r.left - svgRect.left) * sx,
                y1: (r.top - svgRect.top) * sy,
                x2: (r.right - svgRect.left) * sx,
                y2: (r.bottom - svgRect.top) * sy,
            });
        });
        return out;
    }

    function center(e) { return [(e.x1 + e.x2) / 2, (e.y1 + e.y2) / 2]; }

    // 以同標籤最近鄰做身分配對；回傳 {pairs, appeared, vanished}
    function match(prev, cur) {
        const used = new Array(prev.length).fill(false);
        const pairs = [];
        const appeared = [];
        // 第一輪：引擎提供 data-id 的元素以身分直接配對（如 neuromuscular 的 signal-0..4）
        const byId = {};
        prev.forEach(function (p, pi) { if (p.id) byId[p.id] = pi; });
        const idMatched = new Array(cur.length).fill(false);
        cur.forEach(function (c, ci) {
            if (c.id && byId[c.id] !== undefined && !used[byId[c.id]]) {
                used[byId[c.id]] = true;
                idMatched[ci] = true;
                pairs.push([byId[c.id], ci]);
            }
        });
        // 第二輪：其餘元素以同標籤最近鄰配對
        cur.forEach(function (c, ci) {
            if (idMatched[ci]) return;
            const [cx, cy] = center(c);
            let best = -1, bestD = Infinity;
            prev.forEach(function (p, pi) {
                if (used[pi] || p.tag !== c.tag) return;
                const pw = p.x2 - p.x1, ph = p.y2 - p.y1;
                const cw = c.x2 - c.x1, ch = c.y2 - c.y1;
                if (Math.abs(pw - cw) > 0.25 * Math.max(pw, cw, 1) || Math.abs(ph - ch) > 0.25 * Math.max(ph, ch, 1)) return;
                const [px, py] = center(p);
                const d = Math.hypot(px - cx, py - cy);
                if (d < bestD) { bestD = d; best = pi; }
            });
            if (best >= 0 && bestD <= MATCH_R) {
                used[best] = true;
                pairs.push([best, ci]);
            } else if (c.op >= 0.5 && Math.min(c.x2 - c.x1, c.y2 - c.y1) >= MIN_SIZE) {
                appeared.push(c);
            }
        });
        const vanished = prev.filter(function (p, pi) {
            return !used[pi] && p.op >= 0.5 && Math.min(p.x2 - p.x1, p.y2 - p.y1) >= MIN_SIZE;
        });
        return { pairs: pairs, appeared: appeared, vanished: vanished };
    }

    const audit = { bounds: [], subtitle: [], finite: [], labelOverlap: [] };
    const pops = { appear: [], vanish: [], jumps: [] };
    let maxJump = 0;
    let prev = null;

    for (let i = 0; i < N; i++) {
        const t = (i / N) * total;
        mounted.renderAt(t);
        if (/NaN|Infinity|undefined/.test(svg.outerHTML)) audit.finite.push({ frame: i });

        const cur = snap();
        cur.forEach(function (e) {
            if (e.x1 < 5 || e.x2 > 795 || e.y1 < 5 || e.y2 > 505) {
                audit.bounds.push({ frame: i, tag: e.tag, text: e.text, box: [e.x1, e.y1, e.x2, e.y2] });
            }
            if (e.tag === 'text' && e.y2 > 411) {
                audit.subtitle.push({ frame: i, text: e.text, y2: e.y2 });
            }
        });

        const texts = cur.filter(function (e) { return e.tag === 'text' && e.op > 0.05; });
        for (let a = 0; a < texts.length; a++) {
            for (let b = a + 1; b < texts.length; b++) {
                const A = texts[a], B = texts[b];
                const iw = Math.min(A.x2, B.x2) - Math.max(A.x1, B.x1);
                const ih = Math.min(A.y2, B.y2) - Math.max(A.y1, B.y1);
                if (iw <= 0 || ih <= 0) continue;
                const minArea = Math.min((A.x2 - A.x1) * (A.y2 - A.y1), (B.x2 - B.x1) * (B.y2 - B.y1));
                if (minArea > 0 && (iw * ih) / minArea > overlapRatio) {
                    audit.labelOverlap.push({ frame: i, a: A.text, b: B.text });
                }
            }
        }

        if (prev !== null) {
            const m = match(prev, cur);
            m.appeared.forEach(function (c) { pops.appear.push({ frame: i, tag: c.tag, text: c.text, op: c.op }); });
            m.vanished.forEach(function (p) { pops.vanish.push({ frame: i, tag: p.tag, text: p.text, op: p.op }); });
            m.pairs.forEach(function (pr) {
                const p = prev[pr[0]], c = cur[pr[1]];
                const d = Math.max(
                    Math.abs(c.x1 - p.x1), Math.abs(c.y1 - p.y1),
                    Math.abs(c.x2 - p.x2), Math.abs(c.y2 - p.y2)
                );
                if (d > maxJump) maxJump = d;
                // 兩影格皆不可見（透明度 < 0.05）的位移不構成視覺跳變
                if (d > jump && Math.max(p.op, c.op) >= 0.05) pops.jumps.push({ frame: i, tag: c.tag, text: c.text, delta: d });
            });
        }
        prev = cur;
    }
    return { total: total, maxJump: maxJump, audit: audit, pops: pops };
})"""


def test_visual_engine_geometry_audit_and_frame_pop_check(playwright_page, tmp_path):
    """幾何審計與相鄰影格跳變檢查：所有 blueprint 變體、所有影格。"""
    _setup_page(playwright_page, tmp_path)

    failures: list[str] = []
    summary: list[str] = []
    info_births: list[str] = []
    for bp, params in _variants_for_sweep():
        result = playwright_page.evaluate(
            "(args) => (" + _SWEEP_JS + ")(args.bp, args.params, args.n, args.jump, args.ratio)",
            {"bp": bp, "params": params, "n": POP_SAMPLE_FRAMES, "jump": POP_JUMP_UNITS, "ratio": TEXT_OVERLAP_RATIO},
        )
        label = f"{bp}{'' if params is None else ' ' + json.dumps(params, ensure_ascii=False)}"
        summary.append(f"{label}: 最大單幀位移 {result['maxJump']:.1f}")

        audit = result["audit"]
        for key, msg in (
            ("finite", "出現 NaN／Infinity／undefined"),
            ("bounds", "元素超出 [5,795]x[5,505]"),
            ("subtitle", "文字侵入字幕安全區（y>411）"),
            ("labelOverlap", "文字與文字大面積重疊"),
        ):
            items = audit[key]
            if items:
                failures.append(f"[{label}] {msg}：{len(items)} 處，例 {items[:2]}")

        pops = result["pops"]
        # 硬性檢查：連續元素的相鄰影格位移（已排除宣告的階段切換）
        jumps = [it for it in pops["jumps"] if not _is_declared_cut(bp, it["frame"], POP_SAMPLE_FRAMES)]
        if jumps:
            failures.append(f"[{label}] 相鄰影格跳變 > {POP_JUMP_UNITS}：{len(jumps)} 處，例 {jumps[:2]}")
        # 資訊性統計：粒子系統會在同一影格生成全不透明元素，幾何上無法與 pop 區分，
        # 待引擎提供元素身分後再升為硬性檢查。
        births = [it for it in pops["appear"] + pops["vanish"] if not _is_declared_cut(bp, it["frame"], POP_SAMPLE_FRAMES)]
        if births:
            info_births.append(f"{label}: {len(births)}")

    print("\n".join(summary))
    print("資訊性：可見元素瞬間出現／消失（粒子生成，未計入失敗）→ " + "; ".join(info_births))
    assert failures == [], "幾何審計／跳變檢查失敗：\n" + "\n".join(failures)


def test_visual_defs_injected_once_and_background_uses_gradient(playwright_page, tmp_path):
    """精緻畫風 2.5：<defs> 於 mount 時只注入一次（跨多次 renderAt 不重複），主背景使用漸層。"""
    _setup_page(playwright_page, tmp_path)
    result = playwright_page.evaluate(
        """(() => {
            const svg = document.getElementById('testSvg');
            const m = window.ClinicVisual.mount(svg, [{ blueprint: 'process_diagram', title: 'defs', params: null }]);
            for (let i = 0; i < 5; i++) m.renderAt(i * 0.2 * m.totalDuration);
            const defsCount = svg.querySelectorAll('defs').length;
            const bg = svg.querySelector('rect[data-bg="1"]');
            const hasGrad = !!svg.querySelector('#grad-canvas-bg');
            const hasShadow = !!svg.querySelector('#soft-shadow');
            return { defsCount, bgFill: bg ? bg.getAttribute('fill') : null, hasGrad, hasShadow };
        })()"""
    )
    assert result["defsCount"] == 1
    assert result["hasGrad"] is True
    assert result["hasShadow"] is True
    assert result["bgFill"] == "url(#grad-canvas-bg)"


# ============================================================================
# Phase 35-02：pathology_mechanism 嚴格安全區與 resolveParams 正確性
# - 所有繪圖元素（排除 data-bg 背景）落在 [15,785] x [15,495] 內（較測試框 [5,795]x[5,505] 更嚴）
# - 所有 <text> 底部 vy2 <= 405（字幕安全區更嚴格版本）
# - resolveParams 在 params 為 null 與物件時皆正確處理，且與 Python merge_defaults 結果一致
# ============================================================================

PATHO_ORGANS = ["respiratory_mucosa", "vascular_metabolic", "gi_tract", "skin_barrier", "joint_spine", "uro_pelvic"]
PATHO_SAMPLE_U = [0.0, 0.1, 0.25, 0.35, 0.5, 0.7, 0.85, 1.0]

_PATHO_STRICT_JS = """(args) => {
    const svg = document.getElementById('testSvg');
    const out = [];
    args.organs.forEach(function (org) {
        args.us.forEach(function (u) {
            while (svg.firstChild) svg.removeChild(svg.firstChild);
            const mounted = window.ClinicVisual.mount(svg, [{ blueprint: 'pathology_mechanism', title: '驗收', params: { organ_system: org } }]);
            mounted.renderAt(u * mounted.totalDuration);
            const svgRect = svg.getBoundingClientRect();
            const sx = 800 / svgRect.width;
            const sy = 510 / svgRect.height;
            svg.querySelectorAll('*').forEach(function (el) {
                const tag = el.tagName.toLowerCase();
                if (tag === 'defs' || tag === 'clippath' || tag === 'svg' || tag === 'g') return;
                if (el.closest('defs') || el.closest('clipPath')) return;
                if (el.getAttribute('data-bg') === '1') return;
                const r = el.getBoundingClientRect();
                if (r.width <= 0.1 || r.height <= 0.1) return;
                const x1 = (r.left - svgRect.left) * sx;
                const y1 = (r.top - svgRect.top) * sy;
                const x2 = (r.right - svgRect.left) * sx;
                const y2 = (r.bottom - svgRect.top) * sy;
                if (x1 < 15 || x2 > 785 || y1 < 15 || y2 > 495) {
                    out.push({ org: org, u: u, tag: tag, type: 'outside_safe_zone', box: [x1, y1, x2, y2] });
                }
                if (tag === 'text' && y2 > 405) {
                    out.push({ org: org, u: u, tag: tag, text: el.textContent, type: 'text_bottom', y2: y2 });
                }
            });
        });
    });
    return out;
}"""


def test_pathology_mechanism_strict_safe_zone(playwright_page, tmp_path):
    """六大專科器官病理機轉：所有元素在 [15,785]x[15,495]，文字底部 <= 405。"""
    _setup_page(playwright_page, tmp_path)
    violations = playwright_page.evaluate(
        "(args) => (" + _PATHO_STRICT_JS + ")(args)",
        {"organs": PATHO_ORGANS, "us": PATHO_SAMPLE_U},
    )
    assert violations == [], f"pathology_mechanism 安全區違規：{violations[:5]}（共 {len(violations)} 處）"


def test_pathology_mechanism_resolve_params_null_and_object(playwright_page, tmp_path):
    """resolveParams 對 pathology_mechanism：null 與物件皆正確，且 null 結果與 Python 預設一致。"""
    _setup_page(playwright_page, tmp_path)
    js_defaults = playwright_page.evaluate("window.ClinicVisual.resolveParams('pathology_mechanism', null)")
    py_defaults = merge_defaults("pathology_mechanism", None)
    assert js_defaults == py_defaults

    clipped = playwright_page.evaluate(
        "window.ClinicVisual.resolveParams('pathology_mechanism', "
        "{organ_system: 'gi_tract', severity_level: 9, organ_label: '一二三四五六七八九十', "
        "accent_fill: 'nope', step_labels: ['甲', '乙']})"
    )
    assert clipped["organ_system"] == "gi_tract"
    assert clipped["severity_level"] == 5
    assert clipped["organ_label"] == "一二三四五六七八"
    assert clipped["accent_fill"] == "warn"
    assert clipped["step_labels"] == py_defaults["step_labels"]

    bogus = playwright_page.evaluate(
        "window.ClinicVisual.resolveParams('pathology_mechanism', {organ_system: 'surgical_face'})"
    )
    assert bogus["organ_system"] == "respiratory_mucosa"


# ============================================================================
# Phase 35-03：基層病程與對照模式的渲染文字不得殘留外科隱痕／脂肪移植字樣
# ============================================================================

BASE_RENDER_FORBIDDEN = ("隱痕", "移植物", "術後", "注射", "套管", "脂肪移植")


def test_base_connectors_and_contrast_modes_render_no_surgical_text(playwright_page, tmp_path):
    _setup_page(playwright_page, tmp_path)
    cases = [
        ("timeline", {"connectors": c, "milestones": ["甲乙丙", "丁戊己", "庚辛壬"]})
        for c in ("mucosal_clearance", "homeostasis_control", "structural_rehab", "none")
    ] + [
        ("contrast", {"left": {"mode": m}}) for m in ("mucosal_irritant_surge", "metabolic_mechanical_overload")
    ] + [
        ("contrast", {"right": {"mode": m}}) for m in ("barrier_hydration_shield", "lifestyle_homeostasis_load")
    ]
    problems = []
    for bp, params in cases:
        for u in (0.0, 0.5, 0.9):
            texts = playwright_page.evaluate(
                """([bp, params, u]) => {
                    const svg = document.getElementById('testSvg');
                    while (svg.firstChild) svg.removeChild(svg.firstChild);
                    const m = window.ClinicVisual.mount(svg, [{ blueprint: bp, title: 'x', params: params }]);
                    m.renderAt(u * m.totalDuration);
                    return Array.prototype.map.call(svg.querySelectorAll('text'), function (t) { return t.textContent; });
                }""",
                [bp, params, u],
            )
            for text in texts:
                for word in BASE_RENDER_FORBIDDEN:
                    if word in text:
                        problems.append((bp, json.dumps(params, ensure_ascii=False), u, word, text))
    assert problems == [], problems[:5]
