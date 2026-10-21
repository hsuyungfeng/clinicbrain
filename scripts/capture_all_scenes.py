#!/usr/bin/env python3
"""
截取凡登兩張外科拉皮卡片的完整 3 幕場景畫面 (Scene 1, Scene 2, Scene 3)
"""

from __future__ import annotations

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT_DIR = Path("/home/hsu/.gemini/antigravity-cli/brain/c33449a9-2e9f-4993-ae32-6a016e23cf97")


def capture_all():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1100})
        page.on("console", lambda m: print("CONSOLE:", m.text))
        page.on("pageerror", lambda e: print("PAGEERROR:", e))

        page.goto("http://127.0.0.1:8000/admin/index.html")

        page.wait_for_selector('button[data-tab="tab-visuals"]', state="visible", timeout=10000)
        page.click('button[data-tab="tab-visuals"]')

        page.wait_for_selector("#visualsFilterClinic", timeout=10000)
        time.sleep(1)
        page.select_option("#visualsFilterClinic", "3503264627")
        time.sleep(1.5)

        cards = page.query_selector_all(".visual-review-card")
        print(f"找到 {len(cards)} 張凡登視覺卡")

        # 卡片 1: 中下臉 SMAS 筋膜深層拉皮
        # 卡片 2: 天鵝頸闊頸肌馬甲對縫
        card_configs = [
            ("smas_facelift", cards[0]),
            ("swan_neck", cards[1]),
        ]

        scene_times = [
            ("scene1", 4.0),   # Scene 1: 0~8s (t=4s 中期動態)
            ("scene2", 12.0),  # Scene 2: 8~16s (t=12s 對比)
            ("scene3", 20.0),  # Scene 3: 16~24s (t=20s 時間軸進程)
        ]

        for card_prefix, card in card_configs:
            card.scroll_into_view_if_needed()
            time.sleep(0.3)

            scrubber = card.query_selector("input.visual-review-scrubber")
            for sc_name, sc_time in scene_times:
                if scrubber:
                    page.evaluate(
                        "(obj) => { obj.el.value = obj.val; obj.el.dispatchEvent(new Event('input')); }",
                        {"el": scrubber, "val": str(sc_time)}
                    )
                    time.sleep(0.6)

                out_file = OUT_DIR / f"{card_prefix}_{sc_name}.png"
                card.screenshot(path=str(out_file))
                print(f"已截取 {card_prefix} 的 {sc_name}: {out_file}")

        browser.close()


if __name__ == "__main__":
    capture_all()
