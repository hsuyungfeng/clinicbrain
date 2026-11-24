#!/usr/bin/env python3
"""Phase 56-02: ClinicBrain + Ornith + raea 社群短影音批次渲染 CLI。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.visual.raea_pipeline import DEFAULT_VIDEO_DIR, is_raea_available, render_reel_with_raea
from src.visual.reel_script import generate_reel_script


def _list_available_topics(conn: sqlite3.Connection, video_dir: Path, limit: int) -> list[str]:
    cur = conn.cursor()
    cur.execute("SELECT topic_key FROM visual_assets ORDER BY id ASC")
    found: list[str] = []
    for (t_key,) in cur.fetchall():
        if (video_dir / f"{t_key}_portrait.mp4").is_file():
            found.append(t_key)
            if len(found) >= limit:
                break
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="ClinicBrain + Ornith + raea 短影音批次渲染工具")
    ap.add_argument("--topic-key", help="指定單一 topic_key")
    ap.add_argument("--all", action="store_true", help="批次處理具備 portrait.mp4 之主題")
    ap.add_argument("--limit", type=int, default=5, help="--all 時最多處理筆數（預設 5）")
    ap.add_argument("--skip-llm", action="store_true", help="略過 Ornith-1.5-35B，直接使用確定性降級文案")
    ap.add_argument("--max-sec", type=float, default=None, help="截短輸出秒數（測試用）")
    ap.add_argument("--quality", default="high", choices=["draft", "high", "master"])
    ap.add_argument("--force", action="store_true", help="忽略快取強制重渲")
    ap.add_argument("--dry-run", action="store_true", help="僅檢視計畫與腳本，不實際渲染影片")
    args = ap.parse_args()

    if not args.topic_key and not args.all:
        ap.error("請指定 --topic-key 或 --all")

    db_path = PROJECT_ROOT / "clinic.db"
    conn = sqlite3.connect(str(db_path))
    try:
        topics = [args.topic_key] if args.topic_key else _list_available_topics(conn, DEFAULT_VIDEO_DIR, args.limit)
        if not topics:
            print("找不到符合條件之 portrait.mp4 主題", file=sys.stderr)
            return 1

        results = []
        for t in topics:
            if args.dry_run:
                src_mp4 = DEFAULT_VIDEO_DIR / f"{t}_portrait.mp4"
                script = generate_reel_script(conn, t, use_llm=not args.skip_llm)
                results.append({
                    "topic_key": t,
                    "dry_run": True,
                    "portrait_exists": src_mp4.is_file(),
                    "raea_available": is_raea_available(),
                    "script_source": script.source,
                    "hook_title": script.hook_title,
                })
            else:
                res = render_reel_with_raea(
                    conn,
                    t,
                    use_llm=not args.skip_llm,
                    quality=args.quality,
                    max_sec=args.max_sec,
                    force=args.force,
                )
                results.append(res)

        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
