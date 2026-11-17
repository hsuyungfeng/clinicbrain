#!/usr/bin/env python3
"""
將現有資料庫中所有對話/問答 (faq_cache)、臨床推理樹 (page_index_trees) 與視覺解說卡/MP4 (visual_assets)
統一歸類為一般醫學常識（clinic_id = NULL, category = 'general'），使所有病人無論透過任何診所或一般入口皆可查詢。

用法：
    python3 scripts/generalize_all_knowledge.py --db clinic.db --dry-run
    python3 scripts/generalize_all_knowledge.py --db clinic.db --allow-prod-db
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sqlite3
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROD_DB_PATH = PROJECT_ROOT / "clinic.db"


def _open_for_dry_run(db_path: Path) -> sqlite3.Connection:
    """dry-run 專用：來源以 mode=ro 開啟，複製到記憶體後才演算；檔案本身零寫入。"""
    src = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        mem = sqlite3.connect(":memory:")
        src.backup(mem)
    finally:
        src.close()
    return mem


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def generalize_all(conn: sqlite3.Connection) -> dict[str, Counter]:
    """將 faq_cache、page_index_trees 與 visual_assets 中非一般醫學常識之列歸類為一般醫學常識。

    不自行 commit，由呼叫端管理交易。
    """
    report: dict[str, Counter] = {
        "faq_cache": Counter(),
        "page_index_trees": Counter(),
        "visual_assets": Counter(),
    }

    # 1. faq_cache：clinic_id = NULL, category = 'general'（處理 UNIQUE(clinic_id, topic_key, question) 碰撞）
    if _table_exists(conn, "faq_cache"):
        cols = _table_columns(conn, "faq_cache")
        has_review = "review_status" in cols
        select_review = ", review_status" if has_review else ", 'approved' AS review_status"
        rows = conn.execute(
            f"SELECT id, clinic_id, topic_key, question, answer{select_review} "
            "FROM faq_cache WHERE clinic_id IS NOT NULL OR category != 'general' ORDER BY id ASC"
        ).fetchall()
        for row_id, _cid, topic_key, question, answer, review_status in rows:
            report["faq_cache"]["scanned"] += 1
            existing = conn.execute(
                f"SELECT id{select_review} FROM faq_cache "
                "WHERE clinic_id IS NULL AND topic_key IS ? AND question = ?",
                (topic_key, question),
            ).fetchone()
            if existing is not None:
                ex_id, ex_status = existing[0], existing[1]
                if has_review and ex_status != "approved" and review_status == "approved":
                    conn.execute(
                        "UPDATE faq_cache SET answer = ?, category = 'general', "
                        "review_status = 'approved', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (answer, ex_id),
                    )
                    report["faq_cache"]["promoted_existing"] += 1
                conn.execute("DELETE FROM faq_cache WHERE id = ?", (row_id,))
                report["faq_cache"]["deduped"] += 1
            else:
                conn.execute(
                    "UPDATE faq_cache SET clinic_id = NULL, category = 'general', "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (row_id,),
                )
                report["faq_cache"]["updated"] += 1

    # 2. page_index_trees：clinic_id = NULL, category = 'general'（doc_id 為全域 UNIQUE）
    if _table_exists(conn, "page_index_trees"):
        rows = conn.execute(
            "SELECT id FROM page_index_trees "
            "WHERE clinic_id IS NOT NULL OR category != 'general' ORDER BY id ASC"
        ).fetchall()
        for (row_id,) in rows:
            report["page_index_trees"]["scanned"] += 1
            conn.execute(
                "UPDATE page_index_trees SET clinic_id = NULL, category = 'general', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (row_id,),
            )
            report["page_index_trees"]["updated"] += 1

    # 3. visual_assets：clinic_id = NULL（處理 UNIQUE(clinic_id, topic_key) 碰撞）
    if _table_exists(conn, "visual_assets"):
        rows = conn.execute(
            "SELECT id, topic_key, review_status FROM visual_assets "
            "WHERE clinic_id IS NOT NULL ORDER BY id ASC"
        ).fetchall()
        for row_id, topic_key, review_status in rows:
            report["visual_assets"]["scanned"] += 1
            existing = conn.execute(
                "SELECT id, review_status FROM visual_assets "
                "WHERE clinic_id IS NULL AND topic_key = ?",
                (topic_key,),
            ).fetchone()
            if existing is not None:
                conn.execute("DELETE FROM visual_assets WHERE id = ?", (row_id,))
                report["visual_assets"]["deduped"] += 1
            else:
                conn.execute(
                    "UPDATE visual_assets SET clinic_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (row_id,),
                )
                report["visual_assets"]["updated"] += 1

    return report


def _print_report(report: dict[str, Counter], dry_run: bool) -> None:
    label = "【預覽，未寫入資料庫】" if dry_run else "【已寫入資料庫】"
    print(f"一般醫學常識歸類統計 {label}")
    for table, name in (
        ("faq_cache", "問答/對話 (faq_cache)"),
        ("page_index_trees", "臨床推理樹 (page_index_trees)"),
        ("visual_assets", "視覺解說卡/MP4 (visual_assets)"),
    ):
        c = report[table]
        print(f"  {name}：")
        if not c:
            print("    無待遷移資料（皆已為一般醫學常識）")
        else:
            for k in sorted(c):
                print(f"    {k}: {c[k]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="將所有對話、MP4/視覺資產、QA 與推理樹歸類為一般醫學常識"
    )
    parser.add_argument("--db", type=Path, default=PROD_DB_PATH, help="目標 SQLite 資料庫路徑")
    parser.add_argument("--dry-run", action="store_true", help="僅預覽，不寫入資料庫")
    parser.add_argument(
        "--allow-prod-db",
        action="store_true",
        help="允許寫入正式 clinic.db（非 dry-run 且目標為正式庫時必填）",
    )
    args = parser.parse_args(argv)

    db_path: Path = args.db
    if not db_path.exists():
        print(f"❌ 錯誤：目標資料庫不存在：{db_path}", file=sys.stderr)
        return 2

    is_prod = db_path.resolve() == PROD_DB_PATH.resolve()
    if is_prod and not args.dry_run and not args.allow_prod_db:
        print("❌ 拒絕寫入正式 clinic.db：請先備份並加上 --allow-prod-db（或先用 --dry-run 預覽）。", file=sys.stderr)
        return 2

    conn = _open_for_dry_run(db_path) if args.dry_run else sqlite3.connect(str(db_path))
    try:
        conn.execute("BEGIN")
        report = generalize_all(conn)
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"❌ 遷移失敗（已回滾）：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    _print_report(report, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
