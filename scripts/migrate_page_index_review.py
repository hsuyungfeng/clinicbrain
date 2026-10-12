#!/usr/bin/env python3
"""
page_index_trees 審核狀態與標題欄位結構遷移腳本（Phase 21 Plan 21-01）。
為 page_index_trees 資料表新增 title, review_status, reviewed_at, reviewed_by 欄位。

安全規範：
- 正式庫套用採防禦式設計：若目標為正式 clinic.db，必須明確帶有 --confirm-prod-backup 旗標。
- 拒絕分支必須在任何 sqlite3.connect 呼叫之前 return 2。
- 交易性保證：以 isolation_level=None 與 BEGIN IMMEDIATE ... COMMIT 確保原子性，任一步驟失敗即 ROLLBACK。
- 冪等性與半遷移修復：獨立檢查四欄，缺漏欄位自動補齊。
- 既有紀錄處理：既有手寫紀錄 review_status 設為 'approved'，維持零回歸。

使用範例：
    # 測試與備份複本套用
    python3 scripts/migrate_page_index_review.py --db /path/to/test.db

    # 正式庫套用流程（必須先備份）
    cp clinic.db clinic.db.bak-$(date +%Y%m%d)
    python3 scripts/migrate_page_index_review.py --confirm-prod-backup
"""

import argparse
from pathlib import Path
import re
import sqlite3
import sys

# 將專案根目錄加入搜尋路徑
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SCHEMA_PATH = PROJECT_ROOT / "src" / "db" / "clinic_schema.sql"
PROD_DB_PATH = PROJECT_ROOT / "clinic.db"


def extract_column_definition(schema_text: str, table: str, column: str) -> str:
    """自 schema 內容之目標 table 區塊擷取指定欄位之單行定義（無行尾註解與結尾逗號）。"""
    start_marker = "CREATE " + "TABLE IF NOT EXISTS " + table + " ("
    end_marker = "\n);"

    start_pos = schema_text.find(start_marker)
    if start_pos == -1:
        raise RuntimeError(f"無法於 schema 中找到資料表 {table} 之定義區塊！")

    end_pos = schema_text.find(end_marker, start_pos)
    if end_pos == -1:
        raise RuntimeError(f"無法於 schema 中找到資料表 {table} 定義區塊之結束標記！")

    block = schema_text[start_pos:end_pos]

    matched_def = None
    pattern = re.compile(r"^\s+" + re.escape(column) + r"\s+(.+)$")
    for line in block.splitlines():
        m = pattern.match(line)
        if m:
            matched_def = m.group(1)
            break

    if matched_def is None:
        raise RuntimeError(f"無法於資料表 {table} 區塊中找到欄位 {column} 之定義！")

    # 檢查行尾註解
    if "--" in matched_def:
        comment_idx = matched_def.find("--")
        before_comment = matched_def[:comment_idx]
        if before_comment.count("'") % 2 != 0:
            raise RuntimeError(f"欄位 {column} 定義之單引號字面值內包含註解標記，無法解析！")
        raw_def = before_comment
    else:
        raw_def = matched_def

    cleaned = raw_def.rstrip()
    if cleaned.endswith(","):
        cleaned = cleaned[:-1].rstrip()

    if not cleaned:
        raise RuntimeError(f"欄位 {column} 之定義內容為空！")

    if cleaned.count("(") != cleaned.count(")"):
        raise RuntimeError(f"欄位 {column} 之定義括號不平衡！")

    if cleaned.count("'") % 2 != 0:
        raise RuntimeError(f"欄位 {column} 之定義單引號不平衡！")

    return cleaned


def build_add_column_sql(table: str, column: str, definition: str) -> str:
    """組成 ALTER TABLE ... ADD COLUMN 語句。"""
    return f"ALTER TABLE {table} ADD COLUMN {column} {definition}"


def derive_alter_statements(schema_path: Path) -> dict[str, str]:
    """讀取 schema 檔案並衍生 page_index_trees 擴充欄位之 ALTER 語句。"""
    if not schema_path.exists():
        raise FileNotFoundError(f"找不到 schema 檔案：{schema_path}")
    schema_text = schema_path.read_text(encoding="utf-8")
    cols = ["title", "review_status", "reviewed_at", "reviewed_by"]
    res = {}
    for col in cols:
        col_def = extract_column_definition(schema_text, "page_index_trees", col)
        res[col] = build_add_column_sql("page_index_trees", col, col_def)
    return res


def inspect_columns(conn: sqlite3.Connection) -> dict[str, bool]:
    """檢查 page_index_trees 資料表當前結構，回傳目標欄位存在狀況。"""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(page_index_trees);")
    existing_cols = {row[1] for row in cur.fetchall()}
    return {
        "title": "title" in existing_cols,
        "review_status": "review_status" in existing_cols,
        "reviewed_at": "reviewed_at" in existing_cols,
        "reviewed_by": "reviewed_by" in existing_cols,
    }


def migrate_database(db_path: Path, alter_sqls: dict[str, str], dry_run: bool = False) -> tuple[int, list[str]]:
    """執行單一資料庫檔案之結構遷移。回傳 (變更欄位數, 執行訊息清單)。"""
    messages = []
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        col_status = inspect_columns(conn)
        missing_cols = [col for col, exists in col_status.items() if not exists]

        if not missing_cols:
            messages.append("資料表 page_index_trees 欄位結構已完整，無需遷移。")
            return 0, messages

        if dry_run:
            for col in missing_cols:
                messages.append(f"[DRY-RUN] 將執行: {alter_sqls[col]}")
            return len(missing_cols), messages

        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE;")
        try:
            for col in missing_cols:
                sql = alter_sqls[col]
                cur.execute(sql)
                messages.append(f"成功新增欄位: {col}")

            # 欄位預設值為 'approved'（既有手寫／診所上傳列零中斷）。但受審核閘門控管之既有列
            # （llm_generated／web_upload）沒有任何醫師核准紀錄，必須回到 'pending'（Fail-Closed）。
            if "review_status" in missing_cols:
                cur.execute(
                    "UPDATE page_index_trees SET review_status = 'pending' "
                    "WHERE source_type IN ('llm_generated', 'web_upload');"
                )
                messages.append("受控來源（llm_generated／web_upload）既有列已設為 'pending'。")

            cur.execute("COMMIT;")
            return len(missing_cols), messages
        except Exception as e:
            cur.execute("ROLLBACK;")
            messages.append(f"遷移失敗並已回滾：{e}")
            raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="page_index_trees 審核與標題欄位結構遷移工具")
    parser.add_argument("--db", type=str, help="指定資料庫檔案路徑（預設為正式 clinic.db）")
    parser.add_argument("--confirm-prod-backup", action="store_true", help="確認已手動備份正式 clinic.db")
    parser.add_argument("--dry-run", action="store_true", help="模擬執行，不實際寫入資料庫")
    args = parser.parse_args()

    target_db = Path(args.db).resolve() if args.db else PROD_DB_PATH.resolve()
    is_prod = target_db == PROD_DB_PATH.resolve()

    # 正式庫安全防禦：非 dry-run 且為正式庫且未確認備份時，嚴格拒絕
    if not args.dry_run and is_prod and not args.confirm_prod_backup:
        sys.stderr.write(
            "錯誤：目標為正式資料庫 clinic.db，但未提供 --confirm-prod-backup 旗標！\n"
            "請先手動備份正式庫，例如：\n"
            "    cp clinic.db clinic.db.bak-$(date +%Y%m%d)\n"
            "然後重新執行：\n"
            "    python3 scripts/migrate_page_index_review.py --confirm-prod-backup\n"
        )
        sys.exit(2)

    if not target_db.exists():
        sys.stderr.write(f"錯誤：找不到目標資料庫檔案 {target_db}\n")
        sys.exit(1)

    try:
        alter_sqls = derive_alter_statements(SCHEMA_PATH)
    except Exception as e:
        sys.stderr.write(f"解析 schema 欄位失敗：{e}\n")
        sys.exit(1)

    try:
        changed_count, messages = migrate_database(target_db, alter_sqls, dry_run=args.dry_run)
        for msg in messages:
            print(msg)
        print(f"完成！共變更 {changed_count} 個欄位。")
    except Exception as e:
        sys.stderr.write(f"遷移程序發生異常：{e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
