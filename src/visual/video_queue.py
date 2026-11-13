"""
Phase 43: 自動化動態解說動畫影片佇列引擎 (src/visual/video_queue.py)

功能：
1. 直接自資料庫 visual_assets 讀取已核准的 ir_json，動態構建解說動畫 bundle。
2. SHA-256 增量快取機制：比較 ir_json 雜湊與現有影片 metadata，避免重複消耗算力渲染。
3. 支援雙尺寸輸出：
   - landscape: 16:9 橫屏 (1920x1080) 適用院所電視看板。
   - portrait:  9:16 豎屏 (1080x1920) 適用 IG Reels / LINE 官方帳號短影音。
4. 本機確定性逐格截圖與 ffmpeg H.264 (yuv420p) 影片無聲合成。
"""

from __future__ import annotations

import functools
import hashlib
import http.server
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import threading
from typing import Any, Dict, List, Literal, Optional, Tuple

logger = logging.getLogger("clinicbrain.video_queue")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_VIDEO_DIR = PROJECT_ROOT / "data" / "videos"

# 預設診所備用資訊（緻妍外科診所）
DEFAULT_CLINIC_INFO = {
    "name": "緻妍外科診所",
    "phone": "04-2382-0888",
    "disclaimer": "本解說僅供衛教參考，實際療程與處置需由專科醫師親自評估"
}

AspectType = Literal["landscape", "portrait"]


def compute_ir_sha256(ir_data: Any) -> str:
    """計算 IR 結構的標準化 SHA-256 雜湊值。"""
    if isinstance(ir_data, str):
        try:
            ir_dict = json.loads(ir_data)
        except Exception:
            ir_dict = {"raw": ir_data}
    else:
        ir_dict = ir_data

    canonical = json.dumps(ir_dict, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_asset_bundle_data(conn: sqlite3.Connection, topic_key: str) -> Dict[str, Any]:
    """自資料庫查詢視覺資產並組裝完整的解說 Bundle 資料物件。"""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT clinic_id, topic_key, title, ir_json, review_status
        FROM visual_assets
        WHERE topic_key = ?
        """,
        (topic_key,),
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"找不到視覺資產：{topic_key}")

    clinic_id, t_key, title, ir_raw, review_status = row
    ir = json.loads(ir_raw) if isinstance(ir_raw, str) else ir_raw

    clinic_name = DEFAULT_CLINIC_INFO["name"]
    clinic_phone = DEFAULT_CLINIC_INFO["phone"]

    if clinic_id:
        cursor.execute("SELECT name, phone FROM clinic_info WHERE clinic_id = ?", (clinic_id,))
        c_row = cursor.fetchone()
        if c_row:
            clinic_name = c_row[0] or clinic_name
            clinic_phone = c_row[1] or clinic_phone

    clean_phone = "".join(ch for ch in clinic_phone if ch.isdigit())
    booking_url = f"tel:{clean_phone}" if clean_phone else f"tel:{DEFAULT_CLINIC_INFO['phone']}"

    return {
        "schema_version": "1.0",
        "topic_key": t_key,
        "title": title,
        "sub_title": "3幕向量醫學動畫解說",
        "scenes": ir.get("scenes", []),
        "clinic": {
            "name": clinic_name,
            "phone": clinic_phone,
            "booking_url": booking_url,
            "disclaimer": DEFAULT_CLINIC_INFO["disclaimer"],
        },
        "_ir_sha256": compute_ir_sha256(ir),
    }


class DynamicBundleHandler(http.server.SimpleHTTPRequestHandler):
    """支援記憶體動態 Bundle 提供的靜默 HTTP 伺服器處理器。"""

    def __init__(self, *args, dynamic_bundles: Optional[Dict[str, str]] = None, **kwargs):
        self.dynamic_bundles = dynamic_bundles or {}
        super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

    def log_message(self, format, *args):
        # 靜默日誌，避免干擾主控台
        pass

    def do_GET(self):
        # 截獲動態 Bundle 請求（例如 /_dynamic_bundle.json）
        path = self.path.split("?")[0]
        if path in self.dynamic_bundles:
            content = self.dynamic_bundles[path].encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        super().do_GET()


def render_asset_to_video(
    conn: sqlite3.Connection,
    topic_key: str,
    output_dir: Optional[Path] = None,
    aspect: AspectType = "landscape",
    fps: int = 24,
    hold_sec: float = 2.5,
    force: bool = False,
) -> Dict[str, Any]:
    """將資料庫指定主題渲染為 MP4 影片檔案。"""
    out_dir = Path(output_dir) if output_dir else DEFAULT_VIDEO_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. 檢查 ffmpeg 與 Playwright
    if not shutil.which("ffmpeg"):
        raise RuntimeError("系統環境未安裝 ffmpeg 工具，無法合成 MP4 影片")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("未安裝 playwright 套件，無法啟動無頭瀏覽器逐格錄製")

    # 2. 取得資料庫資料並計算 SHA-256
    bundle_data = get_asset_bundle_data(conn, topic_key)
    ir_sha256 = bundle_data["_ir_sha256"]

    mp4_filename = f"{topic_key}_{aspect}.mp4"
    meta_filename = f"{topic_key}_{aspect}.meta.json"
    mp4_path = out_dir / mp4_filename
    meta_path = out_dir / meta_filename

    # 3. 增量快取檢查（若影片存在且 SHA-256 一致則跳過）
    if not force and mp4_path.exists() and meta_path.exists() and mp4_path.stat().st_size > 0:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("sha256") == ir_sha256:
                return {
                    "status": "skipped",
                    "topic_key": topic_key,
                    "aspect": aspect,
                    "path": str(mp4_path),
                    "sha256": ir_sha256,
                    "reason": "cache_hit_ir_unchanged",
                }
        except Exception:
            pass

    # 4. 啟動臨時 HTTP 伺服器並掛載記憶體動態 Bundle
    # 命名符合 player.js 的 BUNDLE_PATTERN (字母開頭，以 .json 結尾)
    bundle_rel_path = f"dynamic/{topic_key}_{aspect}.json"
    bundle_url_path = f"/{bundle_rel_path}"
    dynamic_map = {bundle_url_path: json.dumps(bundle_data, ensure_ascii=False)}

    handler_factory = functools.partial(DynamicBundleHandler, dynamic_bundles=dynamic_map)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_factory)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    tmp_dir = Path(tempfile.mkdtemp(prefix=f"vid_{topic_key}_{aspect}_"))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            # 視口寬度給予餘量，確保 stage 完整繪製
            page = browser.new_page(
                viewport={"width": 1400, "height": 1000},
                device_scale_factor=1,
            )

            player_url = f"http://127.0.0.1:{port}/demo/visual/player.html?bundle={bundle_rel_path}"
            page.goto(player_url)

            # 等待播放器完成初始化
            page.wait_for_function("() => window.__player && window.__player.ready === true", timeout=20000)
            total_sec = float(page.evaluate("() => window.__player.total"))
            if total_sec <= 0:
                raise RuntimeError(f"播放器回報總秒數異常 (total={total_sec})")

            # 注入無頭錄製專用 CSS：舞台全寬、移除重新播放按鈕
            page.add_style_tag(content=".wrap{max-width:none!important;padding:0!important}.card{border:none!important;box-shadow:none!important;padding:0!important}.stage{border-radius:0!important;border:none!important}.cta #again{display:none!important}")
            stage = page.locator(".stage")

            n_main = int(total_sec * fps)
            n_hold = int(hold_sec * fps)

            # 逐格 seek 截圖
            for i in range(n_main):
                t = i / fps
                page.evaluate("(t) => window.__player.seek(t)", t)
                stage.screenshot(path=str(tmp_dir / f"f{i:05d}.png"))

            # 結尾：停留預約卡畫面
            page.evaluate("(t) => window.__player.seek(t)", total_sec)
            last_frame = tmp_dir / f"f{n_main:05d}.png"
            stage.screenshot(path=str(last_frame))
            for j in range(1, n_hold):
                shutil.copy(last_frame, tmp_dir / f"f{n_main + j:05d}.png")

            browser.close()

        # 5. ffmpeg 尺寸與濾鏡參數構建
        # landscape: 1920x1080 (16:9), portrait: 1080x1920 (9:16)
        if aspect == "portrait":
            vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=#0b1120,setsar=1"
        else:
            vf = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=#0b1120,setsar=1"

        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-i",
            str(tmp_dir / "f%05d.png"),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "20",
            "-preset",
            "fast",
            "-movflags",
            "+faststart",
            str(mp4_path),
        ]

        subprocess.run(ffmpeg_cmd, check=True)

        # 6. 寫入 metadata sidecar
        meta_data = {
            "topic_key": topic_key,
            "aspect": aspect,
            "sha256": ir_sha256,
            "fps": fps,
            "frames": n_main + n_hold,
            "duration_sec": total_sec + hold_sec,
            "size_bytes": mp4_path.stat().st_size,
        }
        meta_path.write_text(json.dumps(meta_data, indent=2, ensure_ascii=False), encoding="utf-8")

        return {
            "status": "rendered",
            "topic_key": topic_key,
            "aspect": aspect,
            "path": str(mp4_path),
            "sha256": ir_sha256,
            "frames": n_main + n_hold,
            "duration": total_sec + hold_sec,
            "size_bytes": mp4_path.stat().st_size,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        server.shutdown()
        server.server_close()


def batch_render_queue(
    conn: sqlite3.Connection,
    output_dir: Optional[Path] = None,
    limit: Optional[int] = None,
    aspect: str = "landscape",
    force: bool = False,
    only_topic_keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """批次掃描已核准的視覺資產並排程自動渲染。"""
    cursor = conn.cursor()
    if only_topic_keys:
        placeholders = ",".join("?" for _ in only_topic_keys)
        cursor.execute(
            f"SELECT topic_key FROM visual_assets WHERE topic_key IN ({placeholders}) AND review_status = 'approved'",
            only_topic_keys,
        )
    else:
        cursor.execute("SELECT topic_key FROM visual_assets WHERE review_status = 'approved' ORDER BY id ASC")

    rows = cursor.fetchall()
    topic_keys = [r[0] for r in rows]

    if limit and limit > 0:
        topic_keys = topic_keys[:limit]

    aspects_to_run: List[AspectType] = []
    if aspect == "both":
        aspects_to_run = ["landscape", "portrait"]
    elif aspect in ("landscape", "portrait"):
        aspects_to_run = [aspect]
    else:
        raise ValueError(f"不支援的 aspect 規格：{aspect} (必須為 landscape, portrait 或 both)")

    results = []
    rendered_count = 0
    skipped_count = 0
    failed_count = 0

    for tk in topic_keys:
        for asp in aspects_to_run:
            try:
                res = render_asset_to_video(
                    conn=conn,
                    topic_key=tk,
                    output_dir=output_dir,
                    aspect=asp,
                    force=force,
                )
                results.append(res)
                if res["status"] == "rendered":
                    rendered_count += 1
                elif res["status"] == "skipped":
                    skipped_count += 1
            except Exception as e:
                failed_count += 1
                results.append({
                    "status": "failed",
                    "topic_key": tk,
                    "aspect": asp,
                    "error": str(e),
                })
                logger.error(f"主題 {tk} ({asp}) 渲染失敗: {e}")

    return {
        "total_tasks": len(topic_keys) * len(aspects_to_run),
        "rendered": rendered_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "details": results,
    }
