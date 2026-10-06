#!/usr/bin/env python3
"""
soap_records 與 soap_records_fts 資料表結構遷移腳本（Phase 14）。
將 clinic_schema.sql 中的 soap_records、soap_records_fts 與同步觸發器套用至指定資料庫。

安全規範：
- 正式庫套用採防禦式設計：若目標為正式 clinic.db，必須明確帶有 --confirm-prod-backup 旗標。
- 嚴禁直接於腳本內重複內嵌 DDL，一律由 src/db/clinic_schema.sql 擷取以維護單一權威來源。

使用範例：
    # 測試與備份複本套用
    python3 scripts/migrate_soap_schema.py --db /path/to/test.db

    # 正式庫套用流程（必須先備份）
    cp clinic.db clinic.db.bak-$(date +%Y%m%d)
    python3 scripts/migrate_soap_schema.py --confirm-prod-backup
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


def extract_soap_ddl(schema_text: str) -> str:
    """自 clinic_schema.sql 內容擷取 SOAP 區段之 DDL 語句。"""
    start_marker = "CREATE TABLE IF NOT EXISTS soap_records"
    end_marker = "-- ========================================\n-- Sample Data"

    start_pos = schema_text.find(start_marker)
    if start_pos == -1:
        raise RuntimeError("無法於 schema 檔案中找到 soap_records 表定義起點！")

    end_pos = schema_text.find(end_marker, start_pos)
    if end_pos != -1:
        ddl = schema_text[start_pos:end_pos].strip()
    else:
        ddl = schema_text[start_pos:].strip()

    return ddl


def apply_soap_schema(db_path: Path) -> None:
    """冪等地將 soap_records 結構套用至目標資料庫。"""
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"找不到 schema 檔案：{SCHEMA_PATH}")

    schema_text = SCHEMA_PATH.read_text(encoding="utf-8")
    ddl = extract_soap_ddl(schema_text)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(ddl)
        conn.commit()
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="clinicbrain soap_records 資料表結構遷移工具",
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
        is_prod = target_path.resolve().samefile(PROD_DB_PATH.resolve())
    except FileNotFoundError:
        is_prod = target_path.resolve() == PROD_DB_PATH.resolve()

    if is_prod and not args.confirm_prod_backup:
        print(
            "🛑 拒絕操作正式資料庫！\n"
            "您嘗試對正式 clinic.db 執行 schema 遷移，但未提供 --confirm-prod-backup 旗標。\n"
            "請先手動備份正式庫，例如：\n"
            "  cp clinic.db clinic.db.bak-$(date +%Y%m%d)\n"
            "備份完成後，請重新執行並附加確認旗標：\n"
            "  python3 scripts/migrate_soap_schema.py --confirm-prod-backup",
            file=sys.stderr,
        )
        return 2

    # 3. 讀取與擷取 DDL
    try:
        schema_text = SCHEMA_PATH.read_text(encoding="utf-8")
        ddl = extract_soap_ddl(schema_text)
    except Exception as e:
        print(f"❌ 讀取或解析 schema 失敗：{e}", file=sys.stderr)
        return 1

    # 4. Dry-run 模式預覽
    if args.dry_run:
        print("🔍 [Dry-Run 模式] 將對目標資料庫執行的 DDL 如下：")
        print("--------------------------------------------------")
        print(ddl)
        print("--------------------------------------------------")
        print("✨ Dry-Run 完成，未對資料庫進行任何實質修改。")
        return 0

    # 5. 實際套用遷移
    try:
        print(f"🚀 開始將 SOAP schema 套用至：{target_path}")
        apply_soap_schema(target_path)
        print("✅ 遷移完成！soap_records、soap_records_fts 與觸發器已就緒。")
        return 0
    except Exception as e:
        print(f"❌ 遷移執行失敗：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
