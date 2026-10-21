#!/usr/bin/env python3
"""場景 3 生理修復歷程動態演進截圖腳本。

截取 5 大專科（骨骼、退瘀、疤痕、神經、緊緻）在三階段（u=0.15、0.50、0.90）的圖文動態畫面，並拼成總覽圖。
"""
import sys
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENGINE = PROJECT_ROOT / "src" / "web" / "static" / "visual_engine.js"

SPECIALTY_TIMELINES = {
    "scar": ("timeline", {"connectors": "scar_maturation", "milestones": ["切口潮紅", "加壓褪紅", "隱痕平整"]}),
    "bone": ("timeline", {"connectors": "bone_healing", "milestones": ["骨痂形成", "骨質緻密", "咬合穩固"]}),
    "bruise": ("timeline", {"connectors": "bruise_metabolism", "milestones": ["血腫吸收", "色素代謝", "膚色復原"]}),
    "nerve": ("timeline", {"connectors": "nerve_regeneration", "milestones": ["暫時麻木", "神經發芽", "感覺恢復"]}),
    "skin": ("timeline", {"connectors": "skin_retraction", "milestones": ["水腫消退", "基質收縮", "平整回彈"]}),
}

STAGES = [
    (0.15, "stage1_early"),
    (0.50, "stage2_repair"),
    (0.90, "stage3_stable"),
]


def main(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    html = out_dir / "capture_s3.html"
    html.write_text(
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        '<body style="margin:0;background:#000"><svg id="s" width="800" height="510" viewBox="0 0 800 510"></svg>'
        f'<script src="{ENGINE.as_uri()}"></script></body></html>',
        encoding="utf-8",
    )

    captured_files = {}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 510})
        page.goto(html.as_uri())

        for spec_name, (bp, params) in SPECIALTY_TIMELINES.items():
            captured_files[spec_name] = []
            for u_val, stage_name in STAGES:
                page.evaluate(
                    """([bp, params, u]) => {
                        const svg = document.getElementById('s');
                        svg.innerHTML = '';
                        const m = window.ClinicVisual.mount(svg, [{blueprint: bp, title: 't', params: params}]);
                        m.renderAt(u * m.totalDuration);
                    }""",
                    [bp, params, u_val],
                )
                img_path = out_dir / f"{spec_name}_{stage_name}.png"
                page.screenshot(path=str(img_path))
                captured_files[spec_name].append(img_path)
                print(f"Captured: {img_path.name}")

        browser.close()

    # 製作拼圖：5 行 x 3 列 (每張縮小至 400x255)
    cols = 3
    rows = len(SPECIALTY_TIMELINES)
    w_thumb, h_thumb = 400, 255
    montage = Image.new("RGB", (cols * w_thumb, rows * h_thumb), color=(15, 23, 42))

    for r_idx, (spec_name, img_paths) in enumerate(captured_files.items()):
        for c_idx, path in enumerate(img_paths):
            im = Image.open(path).resize((w_thumb, h_thumb))
            montage.paste(im, (c_idx * w_thumb, r_idx * h_thumb))

    montage_path = out_dir / "scene3_evolution_montage.png"
    montage.save(montage_path)
    print(f"Saved montage: {montage_path} ({montage.size[0]}x{montage.size[1]})")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "demo" / "visual" / "out" / "scene3_evolution"
    sys.exit(main(out))
