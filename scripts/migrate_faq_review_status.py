#!/usr/bin/env python3
"""
faq_cache 審核狀態欄位結構遷移腳本（Phase 09 BATCH-01）。
為 faq_cache 資料表新增 review_status 與 reviewed_at 審核欄位。

安全規範：
- 正式庫套用採防禦式設計：若目標為正式 clinic.db，必須明確帶有 --confirm-prod-backup 旗標。
- 拒絕分支必須在任何 sqlite3.connect 呼叫之前 return 2。
- 交易性保證：以 isolation_level=None 與 BEGIN IMMEDIATE ... COMMIT 確保原子性，任一步驟失敗即 ROLLBACK。
- 冪等性與半遷移修復：獨立檢查兩欄，缺漏欄位自動補齊，並回填 llm_generated 內容為 pending。

使用範例：
    # 測試與備份複本套用
    python3 scripts/migrate_faq_review_status.py --db /path/to/test.db

    # 正式庫套用流程（必須先備份）
    cp clinic.db clinic.db.bak-$(date +%Y%m%d)
    python3 scripts/migrate_faq_review_status.py --confirm-prod-backup
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


def derive_alter_statements(schema_path: Path) -> tuple[str, str]:
    """讀取 schema 檔案並衍生 review_status 與 reviewed_at 之 ALTER 語句。"""
    if not schema_path.exists():
        raise FileNotFoundError(f"找不到 schema 檔案：{schema_path}")
    schema_text = schema_path.read_text(encoding="utf-8")
    status_def = extract_column_definition(schema_text, "faq_cache", "review_status")
    reviewed_at_def = extract_column_definition(schema_text, "faq_cache", "reviewed_at")
    return (
        build_add_column_sql("faq_cache", "review_status", status_def),
        build_add_column_sql("faq_cache", "reviewed_at", reviewed_at_def),
    )


# 模組級常數（由 clinic_schema.sql 擷取衍生，單一來源；做成常數以便測試 monkeypatch 驗證交易回滾）
ALTER_REVIEW_STATUS_SQL, ALTER_REVIEWED_AT_SQL = derive_alter_statements(SCHEMA_PATH)


def _existing_review_columns(conn: sqlite3.Connection) -> set[str]:
    """取得 faq_cache 現存的審核相關欄位集合。"""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(faq_cache)")
    cols = {row[1] for row in cur.fetchall()}
    return cols & {"review_status", "reviewed_at"}


def has_review_status_column(conn: sqlite3.Connection) -> bool:
    """檢查 faq_cache 是否同時包含 review_status 與 reviewed_at 兩欄。"""
    return len(_existing_review_columns(conn)) == 2


def apply_review_status_migration(db_path: Path, schema_path: Path | None = None) -> dict:
    """
    冪等地將 review_status 與 reviewed_at 結構套用至目標資料庫。

    回傳：
        dict: {"added": list[str], "backfilled_pending": int, "repaired_half_state": bool}
    """
    if schema_path is None:
        status_sql = ALTER_REVIEW_STATUS_SQL
        at_sql = ALTER_REVIEWED_AT_SQL
    else:
        status_sql, at_sql = derive_alter_statements(schema_path)

    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")

        # 1. 檢查 faq_cache 是否存在
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='faq_cache'")
        if not cur.fetchone():
            conn.execute("ROLLBACK")
            raise RuntimeError("目標資料庫中找不到 faq_cache 資料表，請先套用 clinic_schema.sql！")

        existing_cols = _existing_review_columns(conn)
        is_half_state = (len(existing_cols) == 1)
        added: list[str] = []

        # 2. 補齊缺漏欄位
        if "review_status" not in existing_cols:
            conn.execute(status_sql)
            added.append("review_status")

        if "reviewed_at" not in existing_cols:
            conn.execute(at_sql)
            added.append("reviewed_at")

        # 3. 回填 llm_generated 為 pending（Fail-Closed 原則）
        # 僅在初次新增 review_status 或修復半遷移狀態時回填，避免覆蓋已核准項目
        needs_backfill = ("review_status" in added) or is_half_state
        backfilled_pending = 0
        if needs_backfill:
            cur.execute(
                "UPDATE faq_cache SET review_status = 'pending' WHERE source_type = 'llm_generated'"
            )
            backfilled_pending = cur.rowcount

        conn.execute("COMMIT")
        return {
            "added": added,
            "backfilled_pending": backfilled_pending,
            "repaired_half_state": is_half_state,
        }
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="clinicbrain faq_cache 審核狀態欄位遷移工具",
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
        help="僅預覽將執行的 DDL 與遷移操作，不修改資料庫",
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
        is_target_prod = (
            PROD_DB_PATH.exists()
            and target_path.resolve() == PROD_DB_PATH.resolve()
        )
    except Exception:
        is_target_prod = False

    if is_target_prod and not args.confirm_prod_backup:
        print("=" * 70, file=sys.stderr)
        print("🛑 拒絕操作：目標資料庫為正式環境 clinic.db！", file=sys.stderr)
        print("為了資料安全，執行正式庫遷移前請務必先手動備份資料庫：", file=sys.stderr)
        print("    cp clinic.db clinic.db.bak-$(date +%Y%m%d)", file=sys.stderr)
        print("確認已備份完成後，請加上 --confirm-prod-backup 旗標重新執行：", file=sys.stderr)
        print("    python3 scripts/migrate_faq_review_status.py --confirm-prod-backup", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        return 2

    # 3. Dry-run 模式：僅預覽將執行的動作，不進行連線寫入
    if args.dry_run:
        print("🔍 [DRY-RUN] 預覽將對目標資料庫執行的遷移語句：")
        print("-" * 50)
        print(f"目標資料庫：{target_path}")
        print("1. 檢查並新增欄位：")
        print(f"   {ALTER_REVIEW_STATUS_SQL};")
        print(f"   {ALTER_REVIEWED_AT_SQL};")
        print("2. 回填 llm_generated 記錄為 pending：")
        print("   UPDATE faq_cache SET review_status = 'pending' WHERE source_type = 'llm_generated';")
        print("-" * 50)
        print("✨ [DRY-RUN] 預覽完成，未進行任何實際寫入。")
        return 0

    # 4. 執行遷移
    try:
        result = apply_review_status_migration(target_path)
    except Exception as e:
        print(f"❌ 遷移執行失敗：{e}", file=sys.stderr)
        return 1

    # 5. 印出遷移摘要與狀態筆數
    conn = sqlite3.connect(str(target_path))
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(faq_cache)")
        cols = [r[1] for r in cur.fetchall()]
        cur.execute("SELECT review_status, COUNT(*) FROM faq_cache GROUP BY review_status")
        counts = dict(cur.fetchall())
    finally:
        conn.close()

    print("✅ 結構遷移完成！")
    print(f"目標資料庫：{target_path}")
    print(f"新增欄位：{result['added'] or '無（欄位已存在）'}")
    print(f"回填 pending 筆數：{result['backfilled_pending']}")
    print(f"半遷移狀態修復：{'是' if result['repaired_half_state'] else '否'}")
    print(f"現有欄位清單：{cols}")
    print(f"各審核狀態筆數統計：{counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
