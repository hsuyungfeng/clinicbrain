#!/usr/bin/env python3
"""展示用與正式管線：把通用播放器 player.html 的視覺解說逐格錄製成 MP4（無聲）。

做法：
1. 啟動本機臨時 HTTP 伺服器（根目錄為 repo 根），載入 player.html?bundle=<相對路徑>.json。
2. 等待 window.__player.ready，取得總秒數與場景長度。
3. 以無頭 Chromium 逐格 seek、對 .stage 截圖，結尾預約卡停留指定秒數。
4. 以 ffmpeg 合成 H.264 MP4（yuv420p）。

用法：
    python3 demo/visual/render_video.py --bundle demo/visual/out/autologous.json [--fps 24] [--hold 2.5] [--width 1280] [--out demo/visual/out/xxx.mp4]
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BUNDLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*\.json$")


def is_valid_bundle_path(p: str) -> bool:
    """檢查 bundle 路徑是否符合安全規則（與 player.js 一致）。"""
    if not BUNDLE_RE.match(p):
        return False
    if ".." in p or "//" in p or ":" in p or "\\" in p or any(c.isspace() for c in p):
        return False
    return True


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """靜默 HTTP 處理器，抑制標準輸出/錯誤請求日誌。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

    def log_message(self, format, *args):
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="視覺解說 bundle → MP4 逐格錄製匯出")
    ap.add_argument("--bundle", required=True, help="相對專案根目錄的 bundle JSON 路徑")
    ap.add_argument("--fps", type=int, default=24, help="每秒影格數（預設 24）")
    ap.add_argument("--hold", type=float, default=2.5, help="結尾預約卡畫面停留秒數（預設 2.5）")
    ap.add_argument("--width", type=int, default=1280, help="輸出影片寬度（偶數，預設 1280）")
    ap.add_argument("--src", default=None, help="（已棄用）舊版 full.html 路徑")
    ap.add_argument("--out", default=None, help="輸出影片路徑（預設 demo/visual/out/<topic_key>.mp4）")
    args = ap.parse_args()

    # 1. 檢查工具
    if not shutil.which("ffmpeg"):
        print("找不到 ffmpeg 工具，無法合成影片", file=sys.stderr)
        return 2

    # 2. 驗證 bundle 路徑與檔案存在
    if not is_valid_bundle_path(args.bundle):
        print(f"非法 bundle 路徑參數: {args.bundle}", file=sys.stderr)
        return 2

    bundle_full = PROJECT_ROOT / args.bundle
    if not bundle_full.is_file():
        print(f"找不到指定的 bundle 檔案: {args.bundle}", file=sys.stderr)
        return 2

    try:
        bundle_data = json.loads(bundle_full.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"無法解析 bundle JSON: {e}", file=sys.stderr)
        return 2

    # 3. 決定輸出路徑
    if args.out:
        out = Path(args.out)
    else:
        topic_key = bundle_data.get("topic_key") or bundle_full.stem
        out = PROJECT_ROOT / "demo" / "visual" / "out" / f"{topic_key}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    # 4. 啟動臨時 HTTP 伺服器
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    # 5. 逐格截圖與合成
    tmp = Path(tempfile.mkdtemp(prefix="vidframes_"))
    try:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("找不到 playwright，無法執行截圖", file=sys.stderr)
            return 2

        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch()
                except Exception as e:
                    print(f"無法啟動 Chromium: {e}", file=sys.stderr)
                    return 2

                page = browser.new_page(
                    viewport={"width": args.width + 32, "height": 1000},
                    device_scale_factor=1,
                )
                url = f"http://127.0.0.1:{port}/demo/visual/player.html?bundle={args.bundle}"
                page.goto(url)

                # 等待播放器初始化完成
                page.wait_for_function("() => window.__player && window.__player.ready === true", timeout=15000)
                total_sec = float(page.evaluate("() => window.__player.total"))
                if total_sec <= 0:
                    print("播放器回報總時長為 0，終止錄製", file=sys.stderr)
                    browser.close()
                    return 2

                # 錄製專用樣式：使 stage 寬度吃滿、隱藏結尾的「重新播放」按鈕
                page.add_style_tag(content=".wrap{max-width:none!important}.cta #again{display:none!important}")
                stage = page.locator(".stage")

                n_main = int(total_sec * args.fps)
                n_hold = int(args.hold * args.fps)

                for i in range(n_main):
                    t = i / args.fps
                    page.evaluate("(t) => window.__player.seek(t)", t)
                    stage.screenshot(path=str(tmp / f"f{i:05d}.png"))

                # 結尾：停留預約卡畫面
                page.evaluate("(t) => window.__player.seek(t)", total_sec)
                stage.screenshot(path=str(tmp / f"f{n_main:05d}.png"))
                for j in range(1, n_hold):
                    shutil.copy(tmp / f"f{n_main:05d}.png", tmp / f"f{n_main + j:05d}.png")

                browser.close()
        except Exception as e:
            print(f"截圖錄製過程發生錯誤: {e}", file=sys.stderr)
            return 2

        # 6. ffmpeg 合成
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
        server.shutdown()
        server.server_close()

    print(f"完成：{out}（{n_main + n_hold} 格，{args.fps} fps）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
