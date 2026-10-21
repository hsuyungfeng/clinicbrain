#!/usr/bin/env python3
"""
Playwright 截圖驗收 Plan 32-02 語意動作繪圖引擎 2.0：
1. surgical_action: 骨骼基底、面/頦神經保護光暈、截骨位移、純鈦板釘固定
2. contrast: wide_incision vs minimal_incision (傳統廣泛切口 vs 3D導板微創)
3. timeline: wound_healing (彈性加壓帶與冰敷雪花 -> 消腫穩定)
"""

from __future__ import annotations

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT_DIR = Path("/home/hsu/.gemini/antigravity-cli/brain/c33449a9-2e9f-4993-ae32-6a016e23cf97")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENGINE_JS_PATH = PROJECT_ROOT / "src" / "web" / "static" / "visual_engine.js"


def capture_plan32_scenes():
    html_content = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="utf-8">
  <title>Plan 32-02 Semantic Visual Verification</title>
</head>
<body style="margin:0;padding:20px;background:#0b1120;display:flex;flex-direction:column;align-items:center;font-family:sans-serif;">
  <div style="background:#0f172a;border:1px solid #334155;border-radius:12px;padding:16px;box-shadow:0 10px 25px rgba(0,0,0,0.5);">
    <svg id="testSvg" width="800" height="510" viewBox="0 0 800 510"></svg>
  </div>
  <script src="{ENGINE_JS_PATH.as_uri()}"></script>
</body>
</html>
"""

    scenes = [
        # Scene 1: surgical_action (下顎骨截骨滑移與頦神經保護)
        {
            "blueprint": "surgical_action",
            "title": "截骨滑移與純鈦板釘固定",
            "params": {
                "anatomy_target": "mandible",
                "bone_label": "下顎骨端",
                "nerve_label": "頦神經",
                "nerve_status": "protected",
                "incision_label": "口內隱痕",
                "fixation_label": "純鈦板釘",
                "bone_shift_mm": 6,
                "protect_nerve": True,
                "step_labels": ["口內隱痕切開", "保護神經截骨", "純鈦板釘固定"],
            },
        },
        # Scene 2: contrast (wide_incision vs minimal_incision)
        {
            "blueprint": "contrast",
            "title": "切口創傷與神經保護對比",
            "params": {
                "left": {
                    "title": "傳統切口",
                    "note": "廣泛翻瓣壓迫",
                    "mode": "wide_incision",
                    "core_effect": "dim",
                    "core_label": "神經拉扯發紅",
                    "footnote": "切口較大且盲切易壓迫神經路徑",
                    "unit_fill": "warn",
                },
                "right": {
                    "title": "3D微創導板",
                    "note": "精準安全邊距",
                    "mode": "minimal_incision",
                    "rows": 3,
                    "per_row": 5,
                    "footnote": "在安全邊界內隱密切開，避開神經",
                    "unit_fill": "ok",
                },
            },
        },
        # Scene 3: timeline (wound_healing 加壓繃帶與冰敷雪花)
        {
            "blueprint": "timeline",
            "title": "術後加壓修復與消腫重塑歷程",
            "params": {
                "milestones": ["加壓冰敷", "水腫消退", "骨骼重塑"],
                "unit_effect": "mature",
                "connectors": "wound_healing",
                "units": 3,
                "unit_fill": "accent",
            },
        },
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 900, "height": 600})
        tmp_html = PROJECT_ROOT / "tests" / "fixtures" / "temp_render.html"
        tmp_html.write_text(html_content, encoding="utf-8")
        page.goto(tmp_html.as_uri())

        # 1. 截取 Scene 1 的三個動態階段 (u=0.20 切開牽引, u=0.55 截骨滑移, u=0.88 純鈦剛性固定)
        for u_val, label in [(0.20, "incision_retraction"), (0.55, "osteotomy_sliding"), (0.88, "titanium_rigid_fixation")]:
            scene_config = [scenes[0]]
            page.evaluate(
                f"""(() => {{
                    const svg = document.getElementById('testSvg');
                    window.__mounted = window.ClinicVisual.mount(svg, {json.dumps(scene_config, ensure_ascii=False)});
                    const totalDur = window.__mounted.totalDuration;
                    window.__mounted.renderAt({u_val} * totalDur);
                }})()"""
            )
            out_path = OUT_DIR / f"plan32_scene1_{label}.png"
            svg_element = page.query_selector("#testSvg")
            if svg_element:
                svg_element.screenshot(path=str(out_path))
                print(f"已截取 Scene 1 ({label}): {out_path}")

        # 2. 截取 Scene 2 contrast (u=0.75 對照成熟期)
        page.evaluate(
            f"""(() => {{
                const svg = document.getElementById('testSvg');
                window.__mounted = window.ClinicVisual.mount(svg, [{json.dumps(scenes[1], ensure_ascii=False)}]);
                const totalDur = window.__mounted.totalDuration;
                window.__mounted.renderAt(0.75 * totalDur);
            }})()"""
        )
        out_path = OUT_DIR / "plan32_scene2_contrast_incision.png"
        svg_element = page.query_selector("#testSvg")
        if svg_element:
            svg_element.screenshot(path=str(out_path))
            print(f"已截取 Scene 2 (contrast): {out_path}")

        # 3. 截取 Scene 3 timeline (u=0.30 急性期加壓冰敷雪花)
        page.evaluate(
            f"""(() => {{
                const svg = document.getElementById('testSvg');
                window.__mounted = window.ClinicVisual.mount(svg, [{json.dumps(scenes[2], ensure_ascii=False)}]);
                const totalDur = window.__mounted.totalDuration;
                window.__mounted.renderAt(0.30 * totalDur);
            }})()"""
        )
        out_path = OUT_DIR / "plan32_scene3_timeline_wound_healing.png"
        svg_element = page.query_selector("#testSvg")
        if svg_element:
            svg_element.screenshot(path=str(out_path))
            print(f"已截取 Scene 3 (timeline): {out_path}")

        browser.close()


if __name__ == "__main__":
    capture_plan32_scenes()
