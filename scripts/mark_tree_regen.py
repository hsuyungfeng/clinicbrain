#!/usr/bin/env python3
"""
PageIndex 臨床推理樹待重建手動標記工具（Phase 09 BATCH-02 Task 2）。
提供手動標記 (mark)、清除標記 (unmark) 與查詢 (list) 待夜間批次重建之臨床推理樹。

安全規範：
- 正式庫防禦式設計：mark 與 unmark 對正式 clinic.db 操作時，必須明確指定 --allow-prod-db 旗標。
- 拒絕分支必須在任何 sqlite3.connect 呼叫之前 return 2。
- list 指令一律採用 SQLite 唯讀模式 (mode=ro) 開啟連線。
- 單一負責來源：本腳本禁止手寫任何 UPDATE 語句，一律透過 db_writer.set_needs_regeneration 執行。
"""

import argparse
from pathlib import Path
import sqlite3
import sys

# 將專案根目錄加入搜尋路徑
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pageindex.db_writer import set_needs_regeneration

PROD_DB_PATH = PROJECT_ROOT / "clinic.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="clinicbrain PageIndex 臨床推理樹重建標記工具",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=PROD_DB_PATH,
        help="目標 SQLite 資料庫路徑",
    )
    parser.add_argument(
        "--allow-prod-db",
        action="store_true",
        default=False,
        help="確認允許對正式 clinic.db 進行標記更動（正式庫必填保護旗標）",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="子命令")

    # mark 子命令
    parser_mark = subparsers.add_parser("mark", help="標記指定 doc_id 之樹為待重建 (needs_regeneration=1)")
    parser_mark.add_argument("doc_ids", nargs="+", help="欲標記的 doc_id 清單")

    # unmark 子命令
    parser_unmark = subparsers.add_parser("unmark", help="清除指定 doc_id 之重建標記 (needs_regeneration=0)")
    parser_unmark.add_argument("doc_ids", nargs="+", help="欲清除標記的 doc_id 清單")

    # list 子命令
    subparsers.add_parser("list", help="列出當前所有被標記為待重建的樹")

    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help(sys.stderr)
        return 2

    target_path = Path(args.db)

    # 1. 檢查檔案是否存在
    if not target_path.exists():
        print(f"❌ 錯誤：目標資料庫檔案不存在：{target_path}", file=sys.stderr)
        return 2

    # 2. 針對正式庫的寫入防禦檢核（連線前阻斷）
    try:
        is_target_prod = (
            PROD_DB_PATH.exists()
            and target_path.resolve() == PROD_DB_PATH.resolve()
        )
    except Exception:
        is_target_prod = False

    if args.subcommand in ("mark", "unmark"):
        if is_target_prod and not args.allow_prod_db:
            print("=" * 70, file=sys.stderr)
            print("🛑 拒絕操作：目標資料庫為正式環境 clinic.db！", file=sys.stderr)
            print("為了資料安全，對正式庫進行標記更動前請確認操作必要性，並加上 --allow-prod-db 旗標：", file=sys.stderr)
            print(f"    python3 scripts/mark_tree_regen.py --allow-prod-db {args.subcommand} ...", file=sys.stderr)
            print("=" * 70, file=sys.stderr)
            return 2

    # 3. 執行 list 子命令（強制唯讀模式）
    if args.subcommand == "list":
        conn_str = f"file:{target_path.resolve()}?mode=ro"
        conn = sqlite3.connect(conn_str, uri=True)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT doc_id, clinic_id, source_type, content_version
                FROM page_index_trees
                WHERE needs_regeneration = 1
                ORDER BY doc_id ASC
                """
            )
            rows = cur.fetchall()
            if not rows:
                print("目前沒有被標記為待重建的樹。")
                return 0

            print(f"📋 目前待重建的樹清單（共 {len(rows)} 筆）：")
            print("-" * 60)
            print(f"{'doc_id':<30} {'clinic_id':<12} {'source_type':<15} {'版本'}")
            print("-" * 60)
            for doc_id, clinic_id, src_type, ver in rows:
                print(f"{doc_id:<30} {str(clinic_id):<12} {src_type:<15} v{ver}")
            print("-" * 60)
            return 0
        finally:
            conn.close()

    # 4. 執行 mark 或 unmark 子命令
    is_mark = (args.subcommand == "mark")
    conn = sqlite3.connect(str(target_path))
    try:
        changed, missing = set_needs_regeneration(conn, args.doc_ids, is_mark)
        if missing:
            print(f"❌ 錯誤：下列 doc_id 不存在於資料庫中，整批操作已取消：{missing}", file=sys.stderr)
            return 2

        if is_mark:
            print(f"✅ 已成功標記 {changed} 筆樹為待重建 (needs_regeneration=1)。")
            print("💡 提醒：已標記之樹將於下次夜間批次重建；重建僅更新臨床推理四段與摘要，*_physician_notes 不會被改動，且重建結果以 llm_generated 來源寫入。")
        else:
            print(f"✅ 已成功清除 {changed} 筆樹之重建標記 (needs_regeneration=0)。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
