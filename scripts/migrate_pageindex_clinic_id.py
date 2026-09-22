#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - TASK-00 遷移腳本
目的：
1. 為 page_index_trees 資料表新增 clinic_id 欄位 (REFERENCES clinic_info(clinic_id))
2. 將既有 6 筆範本資料填入 clinic_id = 'zhiyan-clinic'
3. 將 doc_id 去除 'zhiyan-clinic-' 前綴，轉換為純療程 slug
特性：冪等設計，可安全重複執行。
"""

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "clinic.db"


def migrate_pageindex_clinic_id(db_path: Path | str) -> bool:
    print(f"=== 開始執行 TASK-00 遷移：{db_path} ===")
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # 1. 檢查 page_index_trees 是否已有 clinic_id 欄位
    cursor.execute("PRAGMA table_info(page_index_trees)")
    columns = [row[1] for row in cursor.fetchall()]
    print(f"現有欄位: {columns}")

    if "clinic_id" not in columns:
        print(">> 執行 ALTER TABLE page_index_trees ADD COLUMN clinic_id...")
        cursor.execute(
            "ALTER TABLE page_index_trees ADD COLUMN clinic_id TEXT REFERENCES clinic_info(clinic_id)"
        )
        conn.commit()
        print(">> 欄位新增成功。")
    else:
        print(">> clinic_id 欄位已存在，跳過 ALTER TABLE。")

    # 2. 顯示遷移前狀態
    cursor.execute("SELECT id, doc_id, clinic_id FROM page_index_trees ORDER BY id")
    before_rows = cursor.fetchall()
    print(f"\n[遷移前] 共 {len(before_rows)} 筆資料：")
    for r in before_rows:
        print(f"  id={r[0]}, doc_id='{r[1]}', clinic_id='{r[2]}'")

    # 3. 填補 clinic_id（若為 NULL 則填入 'zhiyan-clinic'）
    cursor.execute(
        """
        UPDATE page_index_trees
        SET clinic_id = 'zhiyan-clinic'
        WHERE clinic_id IS NULL OR clinic_id = ''
        """
    )
    fill_count = cursor.rowcount
    print(f"\n>> 補齊 clinic_id 筆數: {fill_count}")

    # 4. 去除 doc_id 前綴 'zhiyan-clinic-'
    prefix = "zhiyan-clinic-"
    prefix_len = len(prefix)
    cursor.execute(
        f"""
        UPDATE page_index_trees
        SET doc_id = SUBSTR(doc_id, {prefix_len + 1})
        WHERE doc_id LIKE '{prefix}%'
        """
    )
    deprefix_count = cursor.rowcount
    print(f">> doc_id 去前綴更新筆數: {deprefix_count}")

    conn.commit()

    # 5. 顯示遷移後狀態
    cursor.execute("SELECT id, doc_id, clinic_id, category, source_type FROM page_index_trees ORDER BY id")
    after_rows = cursor.fetchall()
    print(f"\n[遷移後] 共 {len(after_rows)} 筆資料：")
    for r in after_rows:
        print(f"  id={r[0]}, doc_id='{r[1]}', clinic_id='{r[2]}', category='{r[3]}', source='{r[4]}'")

    conn.close()
    print("=== TASK-00 遷移完成 ===\n")
    return True


if __name__ == "__main__":
    target_db = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB_PATH
    if not target_db.exists():
        print(f"錯誤：找不到資料庫 {target_db}")
        sys.exit(1)
    migrate_pageindex_clinic_id(target_db)
