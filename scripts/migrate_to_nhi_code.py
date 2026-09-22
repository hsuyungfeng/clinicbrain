#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - TASK-01 遷移腳本
目的：
將資料庫中所有 clinic_id = 'zhiyan-clinic' 的資料記錄，遷移為台灣健保代碼 '3503190424'。
涵蓋四張資料表：
1. clinic_info
2. clinic_hours
3. clinic_custom_notes
4. page_index_trees
特性：冪等設計，附外鍵約束檢查 (PRAGMA foreign_key_check)。
"""

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "clinic.db"

OLD_CLINIC_ID = "zhiyan-clinic"
NEW_CLINIC_ID = "3503190424"

TABLES = (
    "clinic_info",
    "clinic_hours",
    "clinic_custom_notes",
    "page_index_trees",
)


def migrate_to_nhi_code(db_path: Path | str) -> bool:
    print(f"=== 開始執行 TASK-01 遷移：{db_path} ===")
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # 1. 遷移前狀態盤點
    print("\n[遷移前 clinic_id 分布統計]：")
    for tbl in TABLES:
        cursor.execute(f"SELECT clinic_id, COUNT(*) FROM {tbl} GROUP BY clinic_id")
        stats = cursor.fetchall()
        print(f"  {tbl}: {stats}")

    # 2. 執行遷移更新（在同一交易中進行，暫時關閉外鍵以允許父子表鍵值同步）
    cursor.execute("PRAGMA foreign_keys = OFF")
    conn.execute("BEGIN TRANSACTION")

    try:
        total_updated = 0
        for tbl in TABLES:
            cursor.execute(
                f"UPDATE {tbl} SET clinic_id = ? WHERE clinic_id = ?",
                (NEW_CLINIC_ID, OLD_CLINIC_ID),
            )
            count = cursor.rowcount
            total_updated += count
            print(f">> {tbl} 更新筆數: {count}")

        conn.commit()
        print(f"\n>> 交易提交成功，共更新 {total_updated} 筆記錄。")
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"錯誤：遷移過程中發生異常已回滾：{e}")
        raise

    # 3. 重新啟用外鍵並執行完整外鍵一致性檢查
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA foreign_key_check")
    fk_violations = cursor.fetchall()
    if fk_violations:
        conn.close()
        raise RuntimeError(f"外鍵完整性檢查失敗，存在違規：{fk_violations}")
    print(">> 外鍵完整性檢查通過 (PRAGMA foreign_key_check: 無違規)。")

    # 4. 遷移後狀態盤點
    print("\n[遷移後 clinic_id 分布統計]：")
    for tbl in TABLES:
        cursor.execute(f"SELECT clinic_id, COUNT(*) FROM {tbl} GROUP BY clinic_id")
        stats = cursor.fetchall()
        print(f"  {tbl}: {stats}")

    conn.close()
    print("=== TASK-01 遷移完成 ===\n")
    return True


if __name__ == "__main__":
    target_db = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB_PATH
    if not target_db.exists():
        print(f"錯誤：找不到資料庫 {target_db}")
        sys.exit(1)
    migrate_to_nhi_code(target_db)
