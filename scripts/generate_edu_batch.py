#!/usr/bin/env python3
"""Phase 53-02/04: 使用 Local LLM 批次生成 7 段結構化衛教 JSON (`edu_json`) 並升級 3 幕 IR。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.visual.edu_generator import build_upgraded_ir, generate_edu_content
from src.visual.edu_schema import EduContent, ensure_edu_columns


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local LLM 批次生成 7 段衛教知識與升級 3 幕動畫 IR")
    parser.add_argument("--db", default=str(ROOT_DIR / "clinic.db"), help="SQLite 資料庫路徑")
    parser.add_argument("--topic-keys", nargs="+", help="指定 topic_key 清單")
    parser.add_argument("--limit", type=int, default=0, help="最多處理筆數（0 代表不限制）")
    parser.add_argument("--all", action="store_true", help="處理全庫 visual_assets")
    parser.add_argument("--resume", action="store_true", help="跳過已有 edu_json 的紀錄（斷點續跑）")
    parser.add_argument("--dry-run", action="store_true", help="僅驗證生成不寫入資料庫")
    parser.add_argument("--skip-ir-upgrade", action="store_true", help="僅寫入 edu_json，不更新 ir_json")
    parser.add_argument("--retries", type=int, default=2, help="單筆失敗重試次數")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.all and not args.topic_keys and args.limit <= 0:
        print("請指定 --topic-keys、--limit 或 --all", file=sys.stderr)
        return 2

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    ensure_edu_columns(conn)

    where_clauses: list[str] = []
    params: list[str] = []
    if args.topic_keys:
        placeholders = ",".join("?" for _ in args.topic_keys)
        where_clauses.append(f"topic_key IN ({placeholders})")
        params.extend(args.topic_keys)
    if args.resume:
        where_clauses.append(
            "(edu_json IS NULL OR TRIM(edu_json) = '' OR ir_json NOT LIKE '%\"care_redflag\"%')"
        )

    sql = "SELECT id, topic_key, title, ir_json, edu_json FROM visual_assets"
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY id ASC"
    if args.limit > 0:
        sql += f" LIMIT {int(args.limit)}"

    rows = conn.execute(sql, params).fetchall()
    total = len(rows)
    print(f"=== Phase 53 衛教知識批次生成｜待處理: {total} 筆 (resume={args.resume}, dry_run={args.dry_run}) ===")

    ok_count = 0
    fail_count = 0
    t0 = time.time()

    for idx, row in enumerate(rows, 1):
        tk = row["topic_key"]
        title = row["title"]
        existing_ir = json.loads(row["ir_json"])
        last_err: Exception | None = None

        for attempt in range(1, args.retries + 2):
            try:
                if args.resume and row["edu_json"] and str(row["edu_json"]).strip():
                    edu = EduContent.model_validate_json(row["edu_json"])
                else:
                    edu = generate_edu_content(tk, title, existing_ir)
                new_ir = existing_ir if args.skip_ir_upgrade else build_upgraded_ir(existing_ir, edu)
                if not args.dry_run:
                    now_iso = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        "UPDATE visual_assets SET edu_json = ?, edu_updated_at = ?, ir_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (
                            json.dumps(edu.model_dump(), ensure_ascii=False),
                            now_iso,
                            json.dumps(new_ir, ensure_ascii=False),
                            row["id"],
                        ),
                    )
                    conn.commit()
                ok_count += 1
                print(f"[{idx}/{total}] ✅ {tk} ({title}) [attempt={attempt}]", flush=True)
                last_err = None
                break
            except Exception as exc:
                last_err = exc
                print(f"[{idx}/{total}] ⚠️ {tk} 第 {attempt} 次嘗試失敗: {exc}", flush=True)

        if last_err is not None:
            fail_count += 1
            print(f"[{idx}/{total}] ❌ {tk} 放棄: {last_err}", file=sys.stderr, flush=True)

    elapsed = time.time() - t0
    print(f"=== 完成｜成功: {ok_count} | 失敗: {fail_count} | 耗時: {elapsed:.1f}s ===")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
