"""
用 Playwright 截取美化後的 6 大醫學解剖動畫卡片實際畫面。
"""

from __future__ import annotations

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT_DIR = Path("/home/hsu/.gemini/antigravity-cli/brain/c33449a9-2e9f-4993-ae32-6a016e23cf97")


def capture():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 960})
        page.on("console", lambda m: print("CONSOLE:", m.text))
        page.on("pageerror", lambda e: print("PAGEERROR:", e))
        page.goto("http://127.0.0.1:8000/admin/index.html")

        # 切換至 🎬 待簽核動畫 分頁
        page.wait_for_selector('button[data-tab="tab-visuals"]', state="visible", timeout=10000)
        page.click('button[data-tab="tab-visuals"]')

        # 等待動畫卡片容器載入
        page.wait_for_selector(".visual-review-card", timeout=10000)
        time.sleep(2)

        cards = page.query_selector_all(".visual-review-card")
        print(f"Found {len(cards)} visual cards")

        # 對每一張卡片，點擊播放並讓進度前進到 u=0.55 左右截取最精彩的動態幀
        name_map = {
            0: "beautified_hifu.png",
            1: "beautified_fractional.png",
            2: "beautified_filler.png",
            3: "beautified_rf.png",
            4: "beautified_botox.png",
            5: "beautified_pico.png",
        }

        for idx, card in enumerate(cards):
            card.scroll_into_view_if_needed()
            time.sleep(0.3)

            # 點擊卡片中的播放按鈕或拖曳時間軸到中段
            scrubber = card.query_selector("input.visual-review-scrubber")
            if scrubber:
                # 拖動時間軸至 50%
                max_val = float(scrubber.get_attribute("max") or "10")
                half_val = round(max_val * 0.55, 1)
                page.evaluate("(obj) => { obj.el.value = obj.val; obj.el.dispatchEvent(new Event('input')); }", {"el": scrubber, "val": str(half_val)})
                time.sleep(0.4)

            out_filename = name_map.get(idx, f"beautified_{idx}.png")
            out_path = OUT_DIR / out_filename
            card.screenshot(path=str(out_path))
            print(f"Captured {out_filename}")

        browser.close()


if __name__ == "__main__":
    capture()
