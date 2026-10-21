#!/usr/bin/env python3
"""Phase 33 Plan 33-02：專科對照與修復歷程之無頭瀏覽器截圖（多進度點）。

用法：
    python3 scripts/capture_plan33_scenes.py [輸出目錄]
需要 Playwright（系統 python3 可用）。輸出為每個場景在 u=0.3/0.7/1.0 的 PNG。
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENGINE = PROJECT_ROOT / "src" / "web" / "static" / "visual_engine.js"

SCENES = {
    "lipo_contrast": ("contrast", {"left": {"mode": "tissue_trauma_torn_vessel", "title": "粗鈍抽吸", "note": "血管神經受損", "core_label": "撕裂血管", "footnote": "撕裂血管出現瘀紫凹凸"}, "right": {"mode": "ultrasonic_emulsification", "title": "超音波乳化", "note": "保留結締組織網", "footnote": "乳化脂肪平整貼合"}}),
    "rhino_contrast": ("contrast", {"left": {"mode": "silicone_extrusion_erythema", "title": "矽膠頂出", "note": "鼻尖壓迫發紅", "core_label": "鼻尖發紅", "footnote": "重力壓迫鼻尖變薄"}, "right": {"mode": "cartilage_triangular_strut", "title": "軟骨支撐", "note": "自體軟骨三角架", "footnote": "力學穩固降低穿出風險"}}),
    "eye_contrast": ("contrast", {"left": {"mode": "scar_contracture_ectropion", "title": "傳統外切", "note": "疤痕攣縮牽引", "core_label": "下瞼外翻", "footnote": "下瞼外翻或凹陷黑眼圈"}, "right": {"mode": "transconjunctival_fat_reposition", "title": "經結膜內切", "note": "零外疤切口", "footnote": "眶隔脂肪平順轉位"}}),
    "bone_timeline": ("timeline", {"connectors": "bone_healing", "milestones": ["骨痂形成", "骨質緻密", "咬合穩固"]}),
    "bruise_timeline": ("timeline", {"connectors": "bruise_metabolism", "milestones": ["血腫吸收", "色素代謝", "膚色復原"]}),
}
PROGRESS = (0.3, 0.7, 1.0)


def main(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    html = out_dir / "plan33_capture.html"
    html.write_text(
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        '<body style="margin:0;background:#000"><svg id="s" width="800" height="510" viewBox="0 0 800 510"></svg>'
        f'<script src="{ENGINE.as_uri()}"></script></body></html>',
        encoding="utf-8",
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 510})
        page.goto(html.as_uri())
        for name, (bp, params) in SCENES.items():
            for f in PROGRESS:
                page.evaluate(
                    """([bp, params, f]) => {
                        const svg = document.getElementById('s'); svg.innerHTML = '';
                        const m = window.ClinicVisual.mount(svg, [{blueprint: bp, title: 't', params: params}]);
                        m.renderAt(f * m.totalDuration);
                    }""",
                    [bp, params, f],
                )
                page.screenshot(path=str(out_dir / f"{name}_{int(f * 10)}.png"))
        browser.close()
    print(f"captured {len(SCENES) * len(PROGRESS)} frames -> {out_dir}")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "tmp" / "plan33_screens"
    raise SystemExit(main(target))
