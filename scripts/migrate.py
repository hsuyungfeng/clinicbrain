#!/usr/bin/env python3
"""
統一資料庫遷移管理器（Phase 47 Wave 3）。

以 `schema_migrations` 資料表統一追蹤既有的 9 支資料庫遷移腳本，
支援 `--status`（唯讀檢視狀態）與 `--apply`（依序執行尚未套用的遷移）。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class MigrationSpec:
    version: str
    script_name: str
    description: str


MIGRATIONS: tuple[MigrationSpec, ...] = (
    MigrationSpec("001_cache_stats", "migrate_cache_stats.py", "快取命中統計表 (cache_stats)"),
    MigrationSpec("002_faq_review_status", "migrate_faq_review_status.py", "FAQ 審核狀態欄位"),
    MigrationSpec("003_faq_metadata", "migrate_faq_metadata.py", "FAQ 來源 metadata 欄位"),
    MigrationSpec("004_page_index_review", "migrate_page_index_review.py", "臨床推理樹審核狀態欄位"),
    MigrationSpec("005_pageindex_clinic_id", "migrate_pageindex_clinic_id.py", "PageIndex 診所代碼遷移"),
    MigrationSpec("006_soap_schema", "migrate_soap_schema.py", "SOAP 語音與全文檢索表"),
    MigrationSpec("007_to_nhi_code", "migrate_to_nhi_code.py", "健保特約機構代碼對齊"),
    MigrationSpec("008_visual_assets", "migrate_visual_assets.py", "視覺解說卡資產表 (visual_assets)"),
    MigrationSpec("009_visual_template_override", "migrate_visual_template_override.py", "視覺模板覆寫欄位"),
)


def _has_migrations_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    return row is not None


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            script_name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def get_migration_status(db_path: Path) -> list[dict]:
    """回傳各遷移腳本的套用狀態（不修改資料庫）。"""
    applied: dict[str, str] = {}
    if db_path.exists():
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            if _has_migrations_table(conn):
                for ver, ts in conn.execute("SELECT version, applied_at FROM schema_migrations"):
                    applied[ver] = ts
        finally:
            conn.close()

    rows = []
    for spec in MIGRATIONS:
        script_path = PROJECT_ROOT / "scripts" / spec.script_name
        rows.append(
            {
                "version": spec.version,
                "script": spec.script_name,
                "exists": script_path.exists(),
                "applied": spec.version in applied,
                "applied_at": applied.get(spec.version),
                "description": spec.description,
            }
        )
    return rows


def apply_migrations(db_path: Path, dry_run: bool = False) -> int:
    """依序執行尚未紀錄於 schema_migrations 的遷移腳本。"""
    status_rows = get_migration_status(db_path)
    pending = [row for row in status_rows if not row["applied"]]
    if not pending:
        print("所有遷移均已套用，無待執行項目。")
        return 0

    if dry_run:
        for row in pending:
            print(f"[DRY-RUN] 將套用：{row['version']} ({row['script']})")
        return 0

    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_migrations_table(conn)
        for row in pending:
            script_path = PROJECT_ROOT / "scripts" / row["script"]
            if not script_path.exists():
                print(f"略過缺失腳本：{script_path}", file=sys.stderr)
                continue
            print(f"執行遷移：{row['version']} ({row['script']})...")
            res = subprocess.run([sys.executable, str(script_path)], cwd=str(PROJECT_ROOT))
            if res.returncode != 0:
                print(f"遷移失敗（exit={res.returncode}）：{row['script']}", file=sys.stderr)
                return res.returncode
            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO schema_migrations (version, script_name, applied_at) VALUES (?, ?, ?)",
                (row["version"], row["script"], now_iso),
            )
            conn.commit()
    finally:
        conn.close()
    print(f"完成 {len(pending)} 項遷移。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="clinicbrain 統一資料庫遷移工具")
    parser.add_argument("--db", type=Path, default=PROJECT_ROOT / "clinic.db", help="目標 SQLite 檔案")
    parser.add_argument("--status", action="store_true", help="顯示各遷移腳本狀態")
    parser.add_argument("--apply", action="store_true", help="依序套用未執行之遷移")
    parser.add_argument("--dry-run", action="store_true", help="僅預覽待執行遷移")
    args = parser.parse_args()

    if args.apply:
        return apply_migrations(args.db, dry_run=args.dry_run)

    rows = get_migration_status(args.db)
    for row in rows:
        mark = "APPLIED" if row["applied"] else "PENDING"
        ts = f" ({row['applied_at']})" if row["applied_at"] else ""
        print(f"[{mark}] {row['version']} -> {row['script']}{ts} | {row['description']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
