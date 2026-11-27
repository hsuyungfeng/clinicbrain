#!/usr/bin/env python3
"""Phase 54-02: 每日權威醫學新知自動巡檢腳本（僅產出 pending 提案，絕不直接覆寫 approved）。"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.refresh.detector import evaluate_and_propose, select_refresh_candidates
from src.refresh.schema import ensure_refresh_tables
from src.refresh.sources import fetch_official_feeds, fetch_pubmed_evidence


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="每日權威醫學新知巡檢（產生 pending 待審提案）")
    p.add_argument("--db", default=str(ROOT_DIR / "clinic.db"))
    p.add_argument("--daily-quota", type=int, default=15)
    p.add_argument("--target-type", choices=["all", "faq", "tree", "visual_edu"], default="all")
    p.add_argument("--topic-keys", nargs="+")
    p.add_argument("--check-feeds", action="store_true", help="同時掃描台灣衛福部/CDC/TFDA 官方 RSS 公告")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def _extract_pubmed_query(title: str, key: str) -> str:
    tokens = [w for w in key.replace("-", " ").split() if w.isascii() and len(w) > 2]
    if tokens:
        return " ".join(tokens[:4])
    return title


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args()
    conn = sqlite3.connect(args.db)
    ensure_refresh_tables(conn)

    feed_items = fetch_official_feeds() if args.check_feeds else []
    candidates = select_refresh_candidates(
        conn,
        daily_quota=args.daily_quota,
        target_type=args.target_type,
        topic_keys=args.topic_keys,
    )

    stats = {"checked": len(candidates), "unchanged": 0, "proposed": 0, "skipped": 0, "errors": 0}
    print(f"=== Phase 54 每日醫學新知巡檢｜候選={len(candidates)} | RSS={len(feed_items)} | dry_run={args.dry_run} ===")

    for idx, cand in enumerate(candidates, 1):
        try:
            q = _extract_pubmed_query(cand.title, cand.target_key)
            evs = fetch_pubmed_evidence(q, max_results=2)
            for fi in feed_items:
                if any(tok in fi.title for tok in cand.title.split()[:2] if len(tok) >= 2):
                    evs.insert(0, fi)
            outcome = evaluate_and_propose(conn, cand, evs, dry_run=args.dry_run)
            stats[outcome] += 1
            print(f"[{idx}/{len(candidates)}] {cand.target_type}:{cand.target_key} ({cand.title[:20]}) -> {outcome}")
        except Exception as exc:
            stats["errors"] += 1
            print(f"[{idx}/{len(candidates)}] ⚠️ {cand.target_type}:{cand.target_key} 失敗: {exc}", file=sys.stderr)

    conn.close()
    print(f"=== 巡檢完成｜{stats} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
