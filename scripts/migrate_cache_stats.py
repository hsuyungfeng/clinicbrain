#!/usr/bin/env python3
"""
cache_stats 資料表結構遷移腳本（Phase 07 CACHE-03）。
將 clinic_schema.sql 中的 cache_stats 與相關索引套用至指定資料庫。

安全規範：
- 正式庫套用採防禦式設計：若目標為正式 clinic.db，必須明確帶有 --confirm-prod-backup 旗標。
- 嚴禁直接於腳本內重複內嵌 DDL，一律由 src/db/clinic_schema.sql 擷取以維護單一權威來源。

使用範例：
    # 測試與備份複本套用
    python3 scripts/migrate_cache_stats.py --db /path/to/test.db

    # 正式庫套用流程（必須先備份）
    cp clinic.db clinic.db.bak-$(date +%Y%m%d)
    python3 scripts/migrate_cache_stats.py --confirm-prod-backup
"""

import argparse
import os
from pathlib import Path
import sqlite3
import sys

# 將專案根目錄加入搜尋路徑
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SCHEMA_PATH = PROJECT_ROOT / "src" / "db" / "clinic_schema.sql"
PROD_DB_PATH = PROJECT_ROOT / "clinic.db"


def extract_cache_stats_ddl(schema_text: str) -> str:
    """自 clinic_schema.sql 內容擷取 cache_stats 區段之 DDL 語句。"""
    start_marker = "CREATE " + "TABLE IF NOT EXISTS cache_stats"
    end_marker = "-- ========================================\n-- Sample Data"

    start_pos = schema_text.find(start_marker)
    if start_pos == -1:
        raise RuntimeError("無法於 schema 檔案中找到 cache_stats 表定義起點！")

    end_pos = schema_text.find(end_marker, start_pos)
    if end_pos != -1:
        ddl = schema_text[start_pos:end_pos].strip()
    else:
        ddl = schema_text[start_pos:].strip()

    return ddl


def apply_cache_stats_schema(db_path: Path) -> None:
    """冪等地將 cache_stats 結構套用至目標資料庫。"""
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"找不到 schema 檔案：{SCHEMA_PATH}")

    schema_text = SCHEMA_PATH.read_text(encoding="utf-8")
    ddl = extract_cache_stats_ddl(schema_text)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(ddl)
        conn.commit()
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="clinicbrain cache_stats 資料表結構遷移工具",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=PROD_DB_PATH,
        help="目標 SQLite 資料庫路徑",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="僅預覽將執行的 DDL 語句，不修改資料庫",
    )
    parser.add_argument(
        "--confirm-prod-backup",
        action="store_true",
        default=False,
        help="確認已備份正式 clinic.db（目標為正式庫時為必填保護旗標）",
    )

    args = parser.parse_args(argv)
    target_path = Path(args.db)

    # 1. 檢查檔案是否存在（不得自動建立不存在之檔案）
    if not target_path.exists():
        print(f"❌ 錯誤：目標資料庫檔案不存在：{target_path}", file=sys.stderr)
        return 2

    # 2. 針對正式庫的安全防禦檢核（此拒絕分支必須在任何 sqlite3.connect 呼叫之前 return）
    try:
        is_prod = target_path.resolve() == PROD_DB_PATH.resolve()
    except Exception:
        is_prod = str(target_path) == str(PROD_DB_PATH)

    if is_prod and not args.confirm_prod_backup:
        print(
            "❌ 【操作拒絕】目標為正式資料庫 clinic.db！\n"
            "為避免未預期變更，請先手動完成備份：\n"
            "  cp clinic.db clinic.db.bak-$(date +%Y%m%d)\n"
            "備份完成後，請明確加上 --confirm-prod-backup 旗標再次執行：\n"
            "  python3 scripts/migrate_cache_stats.py --confirm-prod-backup",
            file=sys.stderr,
        )
        return 2

    # 3. 預覽模式
    if args.dry_run:
        schema_text = SCHEMA_PATH.read_text(encoding="utf-8")
        ddl = extract_cache_stats_ddl(schema_text)
        print("🔍 【預覽模式】將執行的 DDL 語法如下（未修改資料庫）：")
        print("=" * 60)
        print(ddl)
        print("=" * 60)
        return 0

    # 4. 執行遷移
    apply_cache_stats_schema(target_path)

    # 5. 驗證遷移結果
    conn = sqlite3.connect(str(target_path))
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(cache_stats)")
    columns = [row[1] for row in cursor.fetchall()]
    conn.close()

    print(f"✅ 成功將 cache_stats 結構套用至：{target_path}")
    print(f"   欄位結構：{columns}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
