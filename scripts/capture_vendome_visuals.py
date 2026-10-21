#!/usr/bin/env python3
"""
使用 Playwright 截取凡登 3 大代表性療程的視覺解說動畫卡片實際畫面。
"""

from __future__ import annotations

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT_DIR = Path("/home/hsu/.gemini/antigravity-cli/brain/c33449a9-2e9f-4993-ae32-6a016e23cf97")


def capture():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.on("console", lambda m: print("CONSOLE:", m.text))
        page.on("pageerror", lambda e: print("PAGEERROR:", e))
        
        # 開啟管理後台
        page.goto("http://127.0.0.1:8000/admin/index.html")

        # 切換至 🎬 待簽核動畫 分頁
        page.wait_for_selector('button[data-tab="tab-visuals"]', state="visible", timeout=10000)
        page.click('button[data-tab="tab-visuals"]')

        # 篩選凡登診所
        page.wait_for_selector("#visualsFilterClinic", timeout=10000)
        # 等待選項載入
        time.sleep(1)
        page.select_option("#visualsFilterClinic", "3503264627")
        time.sleep(1)

        # 等待卡片容器
        page.wait_for_selector(".visual-review-card", timeout=10000)
        time.sleep(1.5)

        cards = page.query_selector_all(".visual-review-card")
        print(f"找到 {len(cards)} 張凡登待簽核視覺卡")

        # 截取全螢幕列表
        overview_path = OUT_DIR / "vendome_visual_cards_overview.png"
        page.screenshot(path=str(overview_path))
        print(f"已儲存總覽截圖: {overview_path}")

        # 逐張卡片進一步拖動播放並截取精細畫面
        filenames = [
            "vendome_card_smas_facelift.png",
            "vendome_card_swan_neck.png",
            "vendome_card_thermage_flx.png",
        ]

        for idx, card in enumerate(cards[:3]):
            card.scroll_into_view_if_needed()
            time.sleep(0.3)

            scrubber = card.query_selector("input.visual-review-scrubber")
            if scrubber:
                max_val = float(scrubber.get_attribute("max") or "10")
                half_val = round(max_val * 0.5, 1)
                page.evaluate(
                    "(obj) => { obj.el.value = obj.val; obj.el.dispatchEvent(new Event('input')); }",
                    {"el": scrubber, "val": str(half_val)}
                )
                time.sleep(0.5)

            out_path = OUT_DIR / filenames[idx]
            card.screenshot(path=str(out_path))
            print(f"已截取卡片 {idx+1}: {out_path}")

        browser.close()


if __name__ == "__main__":
    capture()
