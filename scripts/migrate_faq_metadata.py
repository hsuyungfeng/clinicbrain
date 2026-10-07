#!/usr/bin/env python3
"""
faq_cache.metadata 欄位結構遷移腳本（Phase 15）。

DDL 由 src/db/clinic_schema.sql 擷取（單一來源）。寫入路徑（faq_writer）不會自動 ALTER，
正式庫須先備份，並明確帶 --confirm-prod-backup 才會執行；拒絕分支在任何 connect 之前 return 2。

    cp clinic.db clinic.db.bak-$(date +%Y%m%d)
    python3 scripts/migrate_faq_metadata.py --confirm-prod-backup
"""

import argparse
from pathlib import Path
import sqlite3
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.migrate_faq_review_status import extract_column_definition, build_add_column_sql

SCHEMA_PATH = PROJECT_ROOT / "src" / "db" / "clinic_schema.sql"
PROD_DB_PATH = PROJECT_ROOT / "clinic.db"


def apply_metadata_migration(db_path: Path) -> bool:
    """冪等新增 metadata 欄位；回傳是否有新增。"""
    definition = extract_column_definition(
        SCHEMA_PATH.read_text(encoding="utf-8"), "faq_cache", "metadata"
    )
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "faq_cache" not in tables:
            conn.execute("ROLLBACK")
            raise RuntimeError("目標資料庫中找不到 faq_cache 資料表，請先套用 clinic_schema.sql！")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(faq_cache)")}
        added = False
        if "metadata" not in cols:
            conn.execute(build_add_column_sql("faq_cache", "metadata", definition))
            added = True
        conn.execute("COMMIT")
        return added
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="clinicbrain faq_cache.metadata 欄位遷移工具")
    parser.add_argument("--db", type=Path, default=PROD_DB_PATH, help="目標 SQLite 資料庫路徑")
    parser.add_argument("--dry-run", action="store_true", help="僅預覽，不修改資料庫")
    parser.add_argument("--confirm-prod-backup", action="store_true", help="確認已備份正式 clinic.db")
    args = parser.parse_args(argv)
    target = Path(args.db)

    if not target.exists():
        print(f"❌ 錯誤：目標資料庫檔案不存在：{target}", file=sys.stderr)
        return 2

    try:
        is_prod = PROD_DB_PATH.exists() and target.resolve() == PROD_DB_PATH.resolve()
    except Exception:
        is_prod = False

    if not args.dry_run and is_prod and not args.confirm_prod_backup:
        print(
            "🛑 拒絕操作正式資料庫！請先備份：cp clinic.db clinic.db.bak-$(date +%Y%m%d)\n"
            "再加上 --confirm-prod-backup 重新執行。",
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        d = extract_column_definition(SCHEMA_PATH.read_text(encoding="utf-8"), "faq_cache", "metadata")
        print(f"🔍 [DRY-RUN] 將執行：{build_add_column_sql('faq_cache', 'metadata', d)};")
        return 0

    try:
        added = apply_metadata_migration(target)
    except Exception as e:
        print(f"❌ 遷移執行失敗：{e}", file=sys.stderr)
        return 1
    print("✅ 已新增 metadata 欄位" if added else "✅ metadata 欄位已存在，無需變更")
    return 0


if __name__ == "__main__":
    sys.exit(main())
