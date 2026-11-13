#!/usr/bin/env python3
"""
Phase 43: 自動化動態解說動畫影片佇列 CLI 工具 (scripts/run_video_render_queue.py)。

功能：
- 支援單筆特定主題 (--topic-key) 或全庫已核准主題 (--all) 自動批次渲染。
- 支援雙尺寸規格 (--aspect landscape | portrait | both)。
- 支援增量快取防重染（未帶 --force 時自動跳過 SHA-256 未變更項目）。
- 支援唯讀盤點模式 (--dry-run)，不啟動瀏覽器與 ffmpeg，僅顯示待處理清單。
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sqlite3
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.visual.video_queue import (
    DEFAULT_VIDEO_DIR,
    compute_ir_sha256,
    render_asset_to_video,
    batch_render_queue,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_video_render_queue")


def parse_args(args=None):
    ap = argparse.ArgumentParser(description="醫學向量解說動畫自動離線影片渲染佇列")
    target_group = ap.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--topic-key", help="指定單一視覺資產主題代碼 (例如 hifu-lifting)")
    target_group.add_argument("--all", action="store_true", help="批次掃描全庫已審核通過之視覺資產")

    ap.add_argument("--aspect", choices=["landscape", "portrait", "both"], default="landscape", help="輸出解析度規格：landscape (16:9), portrait (9:16), 或 both (預設: landscape)")
    ap.add_argument("--limit", type=int, default=None, help="批次渲染最大主題數量上限")
    ap.add_argument("--out-dir", type=str, default=str(DEFAULT_VIDEO_DIR), help="MP4 檔案輸出目錄 (預設: data/videos)")
    ap.add_argument("--force", action="store_true", help="強制重新渲染覆寫現有影片 (略過增量快取)")
    ap.add_argument("--dry-run", action="store_true", help="僅盤點待渲染主題，不啟動 Chromium 實質渲染")
    ap.add_argument("--db-path", type=str, default="clinic.db", help="SQLite 資料庫路徑 (預設: clinic.db)")
    return ap.parse_args(args)


def main(args=None) -> int:
    opts = parse_args(args)
    db_file = Path(opts.db_path)
    if not db_file.exists():
        print(f"錯誤：找不到資料庫檔案 {db_file}", file=sys.stderr)
        return 2

    out_dir = Path(opts.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.cursor()

        # 1. 盤點目標主題
        if opts.topic_key:
            cursor.execute("SELECT topic_key, title, ir_json FROM visual_assets WHERE topic_key = ?", (opts.topic_key,))
            row = cursor.fetchone()
            if not row:
                print(f"錯誤：資料庫中找不到主題 '{opts.topic_key}'", file=sys.stderr)
                return 2
            targets = [row]
        else:
            query = "SELECT topic_key, title, ir_json FROM visual_assets WHERE review_status = 'approved' ORDER BY id ASC"
            if opts.limit and opts.limit > 0:
                query += f" LIMIT {opts.limit}"
            cursor.execute(query)
            targets = cursor.fetchall()

        if not targets:
            print("目前沒有待渲染的主題資產。")
            return 0

        aspects = ["landscape", "portrait"] if opts.aspect == "both" else [opts.aspect]
        print(f"============================================================")
        print(f"  ClinicBrain 醫學解說動畫影片離線渲染佇列")
        print(f"  目標主題數: {len(targets)} 筆 | 規格: {opts.aspect} | 輸出: {out_dir}")
        print(f"  強制覆寫: {'是' if opts.force else '否 (增量快取啟用)'} | 模式: {'DRY-RUN 預檢' if opts.dry_run else '實質渲染'}")
        print(f"============================================================")

        # 2. Dry-run 模式：僅檢查快取狀態
        if opts.dry_run:
            to_render = 0
            to_skip = 0
            for tk, title, ir_raw in targets:
                sha = compute_ir_sha256(ir_raw)
                for asp in aspects:
                    mp4 = out_dir / f"{tk}_{asp}.mp4"
                    meta = out_dir / f"{tk}_{asp}.meta.json"
                    is_cached = False
                    if mp4.exists() and meta.exists() and mp4.stat().st_size > 0 and not opts.force:
                        try:
                            m = json.loads(meta.read_text(encoding="utf-8"))
                            if m.get("sha256") == sha:
                                is_cached = True
                        except Exception:
                            pass
                    status_badge = "[快取命中·跳過]" if is_cached else "[待渲染·需要生成]"
                    if is_cached:
                        to_skip += 1
                    else:
                        to_render += 1
                    print(f"  {status_badge} {tk} ({asp}) - {title}")
            print(f"------------------------------------------------------------")
            print(f"Dry-run 盤點完畢：待渲染 {to_render} 部，快取跳過 {to_skip} 部，總任務 {to_render + to_skip} 項")
            return 0

        # 3. 實質渲染模式
        start_time = time.time()
        rendered_cnt = 0
        skipped_cnt = 0
        failed_cnt = 0

        for idx, (tk, title, _) in enumerate(targets, 1):
            print(f"\n[{idx}/{len(targets)}] 處理主題：{tk}（{title}）...")
            for asp in aspects:
                sub_start = time.time()
                try:
                    res = render_asset_to_video(
                        conn=conn,
                        topic_key=tk,
                        output_dir=out_dir,
                        aspect=asp,
                        force=opts.force,
                    )
                    elapsed = time.time() - sub_start
                    if res["status"] == "rendered":
                        rendered_cnt += 1
                        size_mb = res.get("size_bytes", 0) / (1024 * 1024)
                        print(f"  ✅ [{asp}] 渲染成功: {res['path']} ({size_mb:.2f} MB, {res.get('duration', 0):.1f}s, 耗時 {elapsed:.1f}s)")
                    else:
                        skipped_cnt += 1
                        print(f"  ⏭️ [{asp}] 快取命中跳過 (SHA-256 未變更)")
                except Exception as e:
                    failed_cnt += 1
                    logger.error(f"  ❌ [{asp}] 渲染失敗: {e}")

        total_elapsed = time.time() - start_time
        print(f"\n============================================================")
        print(f"  影片佇列執行完成！總耗時: {total_elapsed:.1f} 秒")
        print(f"  總產出: 成功生成 {rendered_cnt} 部 | 增量跳過 {skipped_cnt} 部 | 失敗 {failed_cnt} 部")
        print(f"============================================================")
        return 0 if failed_cnt == 0 else 1

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
