#!/usr/bin/env python3
"""
Phase 32 Plan 32-01 Task 3：既有診所已核准資產一鍵昇華為一般醫學共用資產。

用法：
    python3 scripts/promote_clinic_assets_to_general.py --db <副本.db> --dry-run
    python3 scripts/promote_clinic_assets_to_general.py --db <副本.db>
    python3 scripts/promote_clinic_assets_to_general.py --clinic-id 3503264627 --db <副本.db>
    寫入正式庫 clinic.db 必須明確加上 --allow-prod-db。

行為：
- 掃描 review_status='approved' 且 clinic_id IS NOT NULL 之視覺解說卡與推理樹。
- 逐筆呼叫與「醫師核准時」完全相同的權威函式：
    視覺：src/visual/review.py:promote_visual_row
    推理樹：src/pageindex/tree_review.py:promote_tree
  因此 CLI 與線上核准的昇華規則與占位判定一致，不另立第二套邏輯。
- 單一交易：任一列驗證失敗即整批回滾（exit 1），不留半套資料；錯誤訊息只含代碼與主題鍵，不含醫療內容。
- --dry-run：以唯讀開啟來源、備份到記憶體後實際演算，報告結果；檔案絕不被寫入，也不需 --allow-prod-db。

結束碼：0 完成；1 非預期錯誤（已回滾）；2 參數或正式庫防護拒絕。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pageindex.tree_review import has_tree_review_status, promote_tree  # noqa: E402
from src.visual.review import promote_visual_row  # noqa: E402
from src.visual.writer import has_visual_assets_table  # noqa: E402

PROD_DB_PATH = PROJECT_ROOT / "clinic.db"


def _open_for_dry_run(db_path: Path) -> sqlite3.Connection:
    """dry-run 專用：來源以 mode=ro 開啟，複製到記憶體後才演算；檔案本身零寫入。"""
    src = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        mem = sqlite3.connect(":memory:")
        src.backup(mem)
    finally:
        src.close()
    return mem


def _visual_candidates(conn: sqlite3.Connection, clinic_id: Optional[str]) -> list[tuple[Any, ...]] | None:
    if not has_visual_assets_table(conn):
        return None
    sql = (
        "SELECT id, clinic_id, topic_key, title, keywords, ir_json, source_type, metadata "
        "FROM visual_assets WHERE review_status = 'approved' AND clinic_id IS NOT NULL"
    )
    params: list[Any] = []
    if clinic_id:
        sql += " AND clinic_id = ?"
        params.append(clinic_id)
    sql += " ORDER BY id ASC"
    return conn.execute(sql, params).fetchall()


def _tree_candidates(conn: sqlite3.Connection, clinic_id: Optional[str]) -> list[int] | None:
    if not has_tree_review_status(conn):
        return None
    sql = "SELECT id FROM page_index_trees WHERE review_status = 'approved' AND clinic_id IS NOT NULL"
    params: list[Any] = []
    if clinic_id:
        sql += " AND clinic_id = ?"
        params.append(clinic_id)
    sql += " ORDER BY id ASC"
    return [r[0] for r in conn.execute(sql, params).fetchall()]


def promote_all(conn: sqlite3.Connection, clinic_id: Optional[str] = None) -> dict[str, Counter]:
    """執行昇華並回傳統計。不 commit；由呼叫端決定交易邊界。"""
    report: dict[str, Counter] = {"visual": Counter(), "tree": Counter()}

    visuals = _visual_candidates(conn, clinic_id)
    if visuals is None:
        report["visual"]["schema_missing"] += 1
    else:
        for row in visuals:
            _, cid, topic_key, title, keywords, ir_json, source_type, metadata = row
            report["visual"]["scanned"] += 1
            res = promote_visual_row(
                conn,
                clinic_id=cid,
                topic_key=topic_key,
                title=title,
                keywords_json=keywords,
                ir_json=ir_json,
                source_type=source_type,
                metadata=metadata,
            )
            report["visual"][res["status"] if res["status"] != "skipped" else f"skipped:{res['reason']}"] += 1

    trees = _tree_candidates(conn, clinic_id)
    if trees is None:
        report["tree"]["schema_missing"] += 1
    else:
        for tree_id in trees:
            report["tree"]["scanned"] += 1
            res = promote_tree(conn, tree_id)
            report["tree"][res["status"] if res["status"] != "skipped" else f"skipped:{res['reason']}"] += 1

    return report


def _print_report(report: dict[str, Counter], dry_run: bool) -> None:
    title = "【預覽，未寫入任何資料】" if dry_run else "【已寫入】"
    print(f"昇華統計 {title}")
    for kind, label in (("visual", "視覺解說卡"), ("tree", "臨床推理樹")):
        c = report[kind]
        if not c:
            print(f"  {label}：無資料")
            continue
        print(f"  {label}：")
        for key in sorted(c):
            print(f"    {key}: {c[key]}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="將已核准的診所專屬資產一鍵昇華為一般醫學共用資產（Phase 32）",
    )
    parser.add_argument("--db", type=Path, default=PROD_DB_PATH, help="目標 SQLite 資料庫路徑")
    parser.add_argument("--clinic-id", type=str, default=None, help="只處理指定診所（選填）")
    parser.add_argument("--dry-run", action="store_true", help="只預覽，不寫入任何資料")
    parser.add_argument(
        "--allow-prod-db",
        action="store_true",
        help="確認允許寫入正式 clinic.db（非 dry-run 且目標為正式庫時必填）",
    )
    args = parser.parse_args(argv)

    db_path: Path = args.db
    if not db_path.exists():
        print(f"❌ 錯誤：目標資料庫檔案不存在：{db_path}", file=sys.stderr)
        return 2

    try:
        is_prod = db_path.resolve() == PROD_DB_PATH.resolve()
    except Exception:
        is_prod = str(db_path) == str(PROD_DB_PATH)

    # 正式庫防護必須在任何寫入連線之前
    if is_prod and not args.dry_run and not args.allow_prod_db:
        print(
            "❌ 【操作拒絕】目標為正式資料庫 clinic.db！\n"
            "寫入昇華必須明確加上 --allow-prod-db；建議先以 --dry-run 或副本預覽。",
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        conn = _open_for_dry_run(db_path)
    else:
        conn = sqlite3.connect(str(db_path))

    try:
        report = promote_all(conn, clinic_id=args.clinic_id)
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    except Exception as exc:  # 任一列失敗即整批回滾，訊息只含型別，不回顯內容
        conn.rollback()
        print(f"❌ 昇華失敗，已整批回滾（未寫入任何資料）：{type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    _print_report(report, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
