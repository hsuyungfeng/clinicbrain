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
import sqlite3
import sys

# 將專案根目錄加入搜尋路徑
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PROD_DB_PATH = PROJECT_ROOT / "clinic.db"

# 模組級常數（與 clinic_schema.sql 嚴格一致，做成常數以便測試 monkeypatch 驗證交易回滾）
ALTER_REVIEW_STATUS_SQL = (
    "ALTER TABLE faq_cache ADD COLUMN review_status TEXT NOT NULL DEFAULT 'approved' "
    "CHECK (review_status IN ('pending', 'approved', 'rejected'))"
)
ALTER_REVIEWED_AT_SQL = "ALTER TABLE faq_cache ADD COLUMN reviewed_at TIMESTAMP"


def _existing_review_columns(conn: sqlite3.Connection) -> set[str]:
    """取得 faq_cache 現存的審核相關欄位集合。"""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(faq_cache)")
    cols = {row[1] for row in cur.fetchall()}
    return cols & {"review_status", "reviewed_at"}


def has_review_status_column(conn: sqlite3.Connection) -> bool:
    """檢查 faq_cache 是否同時包含 review_status 與 reviewed_at 兩欄。"""
    return len(_existing_review_columns(conn)) == 2


def apply_review_status_migration(db_path: Path) -> dict:
    """
    冪等地將 review_status 與 reviewed_at 結構套用至目標資料庫。

    回傳：
        dict: {"added": list[str], "backfilled_pending": int, "repaired_half_state": bool}
    """
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
            conn.execute(ALTER_REVIEW_STATUS_SQL)
            added.append("review_status")

        if "reviewed_at" not in existing_cols:
            conn.execute(ALTER_REVIEWED_AT_SQL)
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
