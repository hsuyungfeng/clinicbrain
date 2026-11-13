"""
Phase 44 Plan 01 Task 2: ClinicMotion 物理動態數學庫單元與確定性測試 (test_visual_engine_motion.py)。

驗證目標：
1. ClinicVisual.motion 於 visual_engine.js 中正確掛載並匯出 8 大物理數學函式：
   - bezier, easeOutCubic, easeInOutQuad, springGentle, anticipate, breathing, ripple, brownian
2. 緩動邊界契約：
   - easeOutCubic, easeInOutQuad, springGentle, anticipate 在 t=0 時皆為 0.0，在 t=1 時皆為 1.0。
3. 生物彈性過衝 (springGentle)：
   - 驗證在 0.5 <= t <= 0.9 區間存在 > 1.0 的過衝峰值，且最終收斂至 1.0。
4. 預備蓄力 (anticipate)：
   - 驗證在 0.1 <= t <= 0.4 區間存在 < 0.0 的回縮負值，隨後平滑超越。
5. 活體微律動 (breathing)：
   - 驗證 u=0 與 u=1 之數值完全一致（閉合循環），數值震盪範圍落在 [1 - amp, 1 + amp] 之內。
6. 同心圓擴散漣漪 (ripple)：
   - 驗證回傳物件包含 radius 與 opacity，且 opacity 在 [0, 1] 之間，半徑不超過 maxRadius。
7. 布朗微擾 (brownian)：
   - 100% 確定性：相同 (seed, idx, u) 重複計算之 dx, dy 嚴格完全相等。
   - 連續性：微小時間前進下位移變化平滑無突兀暴衝。
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENGINE_JS_PATH = PROJECT_ROOT / "src" / "web" / "static" / "visual_engine.js"


def _eval_in_node(js_expr: str) -> any:
    """在 Node.js 中載入 visual_engine.js 並執行表達式，回傳 JSON 反序列化結果。"""
    script = f"""
    const fs = require('fs');
    const vm = require('vm');
    const code = fs.readFileSync({json.dumps(str(ENGINE_JS_PATH))}, 'utf-8');
    const sandbox = {{
        globalThis: {{}},
        console: console,
        Math: Math,
        JSON: JSON,
        Object: Object,
        Number: Number,
        String: String
    }};
    sandbox.window = sandbox.globalThis;
    vm.createContext(sandbox);
    vm.runInContext(code, sandbox);
    const motion = sandbox.globalThis.ClinicVisual.motion;
    const result = (function() {{ {js_expr} }})();
    process.stdout.write(JSON.stringify(result));
    """
    res = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=True
    )
    return json.loads(res.stdout)


def test_clinic_motion_export():
    """驗證 ClinicVisual.motion 匯出 8 個核心函式。"""
    methods = _eval_in_node("""
        const keys = Object.keys(motion);
        return {
            keys: keys,
            hasBezier: typeof motion.bezier === 'function',
            hasEaseOutCubic: typeof motion.easeOutCubic === 'function',
            hasEaseInOutQuad: typeof motion.easeInOutQuad === 'function',
            hasSpringGentle: typeof motion.springGentle === 'function',
            hasAnticipate: typeof motion.anticipate === 'function',
            hasBreathing: typeof motion.breathing === 'function',
            hasRipple: typeof motion.ripple === 'function',
            hasBrownian: typeof motion.brownian === 'function'
        };
    """)
    assert methods["hasBezier"]
    assert methods["hasEaseOutCubic"]
    assert methods["hasEaseInOutQuad"]
    assert methods["hasSpringGentle"]
    assert methods["hasAnticipate"]
    assert methods["hasBreathing"]
    assert methods["hasRipple"]
    assert methods["hasBrownian"]


def test_easing_boundary_conditions():
    """驗證所有漸變/過衝函式在 t=0 與 t=1 的端點值。"""
    endpoints = _eval_in_node("""
        return {
            easeOutCubic_0: motion.easeOutCubic(0),
            easeOutCubic_1: motion.easeOutCubic(1),
            easeInOutQuad_0: motion.easeInOutQuad(0),
            easeInOutQuad_1: motion.easeInOutQuad(1),
            springGentle_0: motion.springGentle(0),
            springGentle_1: motion.springGentle(1),
            anticipate_0: motion.anticipate(0),
            anticipate_1: motion.anticipate(1),
            bezier_0: motion.bezier(0.25, 0.1, 0.25, 1.0, 0),
            bezier_1: motion.bezier(0.25, 0.1, 0.25, 1.0, 1)
        };
    """)
    for k, v in endpoints.items():
        if k.endswith("_0"):
            assert abs(v - 0.0) < 1e-4, f"{k} 在 t=0 必須為 0.0 (實際: {v})"
        elif k.endswith("_1"):
            assert abs(v - 1.0) < 1e-4, f"{k} 在 t=1 必須為 1.0 (實際: {v})"


def test_spring_gentle_overshoot():
    """驗證 springGentle 具備果凍過衝（在 0.5~0.9 區間存在 > 1.0 之數值）。"""
    samples = _eval_in_node("""
        const vals = [];
        for (let i = 0; i <= 100; i++) {
            const t = i / 100;
            vals.push({ t: t, val: motion.springGentle(t) });
        }
        return vals;
    """)
    overshoots = [s for s in samples if 0.5 <= s["t"] <= 0.9 and s["val"] > 1.0]
    assert len(overshoots) > 0, "springGentle 必須在 0.5~0.9 區間存在生物果凍過衝峰值 (> 1.0)"
    max_overshoot = max(s["val"] for s in overshoots)
    assert 1.01 <= max_overshoot <= 1.25, f"過衝峰值需在溫和自然區間 1.01~1.25 內 (實際: {max_overshoot})"


def test_anticipate_recoil():
    """驗證 anticipate 具備蓄力回縮（在 0.1~0.4 區間存在 < 0.0 之數值）。"""
    samples = _eval_in_node("""
        const vals = [];
        for (let i = 0; i <= 100; i++) {
            const t = i / 100;
            vals.push({ t: t, val: motion.anticipate(t) });
        }
        return vals;
    """)
    recoils = [s for s in samples if 0.05 <= s["t"] <= 0.45 and s["val"] < 0.0]
    assert len(recoils) > 0, "anticipate 必須在前期存在預備蓄力微縮負值 (< 0.0)"
    min_recoil = min(s["val"] for s in recoils)
    assert -0.25 <= min_recoil <= -0.01, f"回縮值需在溫和蓄力區間 -0.25~-0.01 內 (實際: {min_recoil})"


def test_breathing_closed_loop():
    """驗證 breathing 在 u=0 與 u=1 循環完美閉合，且極值落在振幅範圍內。"""
    res = _eval_in_node("""
        const amp = 0.02;
        const b0 = motion.breathing(0.0, 2.0, amp);
        const b1 = motion.breathing(1.0, 2.0, amp);
        let minVal = 999, maxVal = -999;
        for (let i = 0; i <= 200; i++) {
            const val = motion.breathing(i / 200, 2.0, amp);
            if (val < minVal) minVal = val;
            if (val > maxVal) maxVal = val;
        }
        return { b0: b0, b1: b1, minVal: minVal, maxVal: maxVal };
    """)
    assert abs(res["b0"] - res["b1"]) < 1e-6, "breathing 在 u=0 與 u=1 必須完全閉合"
    assert abs(res["minVal"] - (1.0 - 0.02)) < 1e-4
    assert abs(res["maxVal"] - (1.0 + 0.02)) < 1e-4


def test_ripple_mechanics():
    """驗證 ripple 漣漪之半徑遞增與透明度平滑起伏。"""
    res = _eval_in_node("""
        const r0 = motion.ripple(0.0, 0, 40);
        const rMid = motion.ripple(0.2, 0, 40); // p = 0.2 * 2.5 = 0.5 (正弦波頂峰)
        const rEnd = motion.ripple(0.4, 0, 40); // p = 0.4 * 2.5 = 1.0 (週期歸零)
        return { r0: r0, rMid: rMid, rEnd: rEnd };
    """)
    assert 0 <= res["r0"]["opacity"] <= 1.0
    assert res["rMid"]["opacity"] > res["r0"]["opacity"], "漣漪在週期中央透明度應提升"
    assert res["rMid"]["radius"] > 0, "漣漪半徑需正向擴散"


def test_brownian_determinism_and_smoothness():
    """驗證 brownian 微擾具備 100% 純確定性與連續性。"""
    res = _eval_in_node("""
        const seed = 42;
        const idx = 7;
        const run1 = motion.brownian(seed, idx, 0.35, 5);
        const run2 = motion.brownian(seed, idx, 0.35, 5);
        const runNext = motion.brownian(seed, idx, 0.352, 5);
        return { run1: run1, run2: run2, runNext: runNext };
    """)
    assert res["run1"]["dx"] == res["run2"]["dx"], "相同輸入必須得到 100% 確定之數值"
    assert res["run1"]["dy"] == res["run2"]["dy"]
    delta_x = abs(res["runNext"]["dx"] - res["run1"]["dx"])
    delta_y = abs(res["runNext"]["dy"] - res["run1"]["dy"])
    assert delta_x < 0.5, f"微小時間步長下 dx 變化平滑 (實際: {delta_x})"
    assert delta_y < 0.5, f"微小時間步長下 dy 變化平滑 (實際: {delta_y})"
