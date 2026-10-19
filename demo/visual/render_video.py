#!/usr/bin/env python3
"""展示用：把 full.html 的時間軸播放器逐格錄製成 MP4（無聲）。

做法：以無頭 Chromium 開啟 full.html，對每一格設定時間（拖曳進度條等價）、對 .stage 截圖，
再以 ffmpeg 合成 H.264。同一份 HTML 同時是互動播放器與影片來源，不需另寫影片模板。

用法：
    python3 demo/visual/render_video.py [--fps 24] [--hold 2.5] [--width 1280] [--out demo/visual/out/xxx.mp4]
僅讀取 demo/visual/full.html（file://），不連任何服務、不碰資料庫。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
TOTAL_SEC = 24.0  # 與 full.html 的 TOTAL 一致


def main() -> int:
    ap = argparse.ArgumentParser(description="full.html → MP4（逐格錄製，無聲）")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--hold", type=float, default=2.5, help="結尾預約畫面停留秒數")
    ap.add_argument("--width", type=int, default=1280, help="輸出影片寬度（偶數）")
    ap.add_argument("--src", default=str(HERE / "full.html"))
    ap.add_argument("--out", default=str(HERE / "out" / "autologous-fat-grafting.mp4"))
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        print("找不到 ffmpeg", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    n_main = int(TOTAL_SEC * args.fps)          # 主片段格數
    n_hold = int(args.hold * args.fps)          # 結尾停留格數
    tmp = Path(tempfile.mkdtemp(prefix="vidframes_"))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": args.width + 32, "height": 1000}, device_scale_factor=1)
            page.goto(Path(args.src).resolve().as_uri())
            # 錄製專用樣式：拿掉寬度上限，讓舞台吃滿寬度；隱藏結尾的「重新播放」按鈕
            page.add_style_tag(content=".wrap{max-width:none!important}.cta #again{display:none!important}")
            page.wait_for_timeout(300)
            stage = page.locator(".stage")

            def seek(sec: float) -> None:
                page.evaluate(
                    "(v)=>{const s=document.getElementById('seek');s.value=v;s.dispatchEvent(new Event('input'));}",
                    round(sec / TOTAL_SEC * 1000),
                )

            for i in range(n_main):
                seek(i / args.fps)
                stage.screenshot(path=str(tmp / f"f{i:05d}.png"))
            # 結尾：最後一格（預約畫面）重複 hold 秒
            seek(TOTAL_SEC)
            stage.screenshot(path=str(tmp / f"f{n_main:05d}.png"))
            for j in range(1, n_hold):
                shutil.copy(tmp / f"f{n_main:05d}.png", tmp / f"f{n_main + j:05d}.png")
            browser.close()

        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(args.fps),
                "-i", str(tmp / "f%05d.png"),
                "-vf", f"scale={args.width}:-2:flags=lanczos",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart",
                str(out),
            ],
            check=True,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"完成：{out}（{n_main + n_hold} 格，{args.fps} fps）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
