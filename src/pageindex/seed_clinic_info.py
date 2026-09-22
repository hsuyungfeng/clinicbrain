#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - 診所基本資料種子腳本 (clinic_info)
Phase 04 Task 1: 補齊 clinic_info 種子腳本缺口，支援從零重建資料庫。

診所基本資料（緻妍外科診所）：
- clinic_id: 3503190424（台灣健保特約醫事機構代碼）
- 寫入方式：INSERT OR IGNORE / UPSERT，保證多次執行冪等性。
"""

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "clinic.db"

CLINIC_ID = "3503190424"  # 緻妍外科診所，台灣健保特約醫事機構代碼

ZHIYAN_CLINIC_INFO = {
    "clinic_id": CLINIC_ID,
    "name": "緻妍外科診所",
    "phone": "(04) 2320-0000",
    "address": "台中市西區台灣大道二段100號",
    "website": "https://www.zhiyan-clinic.com",
    "opening_date": None,
    "clinic_type": "醫美診所",
}


def seed_clinic_info(conn: sqlite3.Connection) -> int:
    """寫入或更新 clinic_info 基本資料。回傳寫入/更新之筆數（若已存在且內容一致則跳過，回傳 0）。"""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT name, phone, address, website, opening_date, clinic_type
        FROM clinic_info
        WHERE clinic_id = ?
        """,
        (CLINIC_ID,),
    )
    existing = cursor.fetchone()
    target_values = (
        ZHIYAN_CLINIC_INFO["name"],
        ZHIYAN_CLINIC_INFO["phone"],
        ZHIYAN_CLINIC_INFO["address"],
        ZHIYAN_CLINIC_INFO["website"],
        ZHIYAN_CLINIC_INFO["opening_date"],
        ZHIYAN_CLINIC_INFO["clinic_type"],
    )

    if existing is not None and existing == target_values:
        return 0

    cursor.execute(
        """
        INSERT INTO clinic_info (
            clinic_id, name, phone, address, website, opening_date, clinic_type,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(clinic_id) DO UPDATE SET
            name = excluded.name,
            phone = excluded.phone,
            address = excluded.address,
            website = excluded.website,
            opening_date = excluded.opening_date,
            clinic_type = excluded.clinic_type,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            ZHIYAN_CLINIC_INFO["clinic_id"],
            ZHIYAN_CLINIC_INFO["name"],
            ZHIYAN_CLINIC_INFO["phone"],
            ZHIYAN_CLINIC_INFO["address"],
            ZHIYAN_CLINIC_INFO["website"],
            ZHIYAN_CLINIC_INFO["opening_date"],
            ZHIYAN_CLINIC_INFO["clinic_type"],
        ),
    )
    conn.commit()
    return 1


def main():
    db_path = DEFAULT_DB_PATH
    print(f"正在寫入 clinic_info 種子資料至 {db_path}...")
    conn = sqlite3.connect(str(db_path))
    count = seed_clinic_info(conn)
    cursor = conn.cursor()
    cursor.execute("SELECT clinic_id, name, phone, address, clinic_type FROM clinic_info WHERE clinic_id = ?", (CLINIC_ID,))
    row = cursor.fetchone()
    print(f"寫入/更新成功 (rowcount: {count})：")
    print(f"  clinic_id: {row[0]}, name: {row[1]}, phone: {row[2]}, address: {row[3]}, type: {row[4]}")
    conn.close()


if __name__ == "__main__":
    main()
