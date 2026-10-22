#!/usr/bin/env python3
"""Phase 34 Plan 03：為 visual_assets 新增 template_override 欄位（冪等、交易性）。

欄位定義取自 src/db/clinic_schema.sql（單一來源），沿用 migrate_faq_review_status 的擷取函式。
正式庫 clinic.db 寫入必須加 --confirm-prod-backup（且須先手動備份）。
--dry-run 只印出將執行的 SQL，不寫入。
"""

from __future__ import annotations

import argparse
import importlib.util
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "src" / "db" / "clinic_schema.sql"
PROD_DB = PROJECT_ROOT / "clinic.db"
TABLE = "visual_assets"
COLUMN = "template_override"


def _load_extractor():
    spec = importlib.util.spec_from_file_location(
        "migrate_faq_review_status", PROJECT_ROOT / "scripts" / "migrate_faq_review_status.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.extract_column_definition


def plan_migration(db_path: Path) -> tuple[bool, str]:
    """回傳 (是否需要執行, 將執行的 SQL)。"""
    definition = _load_extractor()(SCHEMA_PATH.read_text(encoding="utf-8"), TABLE, COLUMN)
    sql = f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} {definition};"
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({TABLE})")}
    finally:
        conn.close()
    return (COLUMN not in cols), sql


def apply_migration(db_path: Path) -> bool:
    needed, sql = plan_migration(db_path)
    if not needed:
        return False
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(sql)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="visual_assets.template_override 遷移（冪等）")
    parser.add_argument("--db", type=Path, default=PROD_DB)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-prod-backup", action="store_true")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"找不到資料庫：{args.db}", file=sys.stderr)
        return 2
    is_prod = args.db.resolve() == PROD_DB.resolve()
    if is_prod and not args.dry_run and not args.confirm_prod_backup:
        print("拒絕：目標為正式庫 clinic.db，請先手動備份並加上 --confirm-prod-backup。", file=sys.stderr)
        return 2

    needed, sql = plan_migration(args.db)
    if args.dry_run:
        print(("將執行：" + sql) if needed else "欄位已存在，無需變更（dry-run）。")
        return 0
    if apply_migration(args.db):
        print(f"已套用：{sql}")
    else:
        print("欄位已存在，無需變更。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
