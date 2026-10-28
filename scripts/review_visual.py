#!/usr/bin/env python3
"""
視覺解說卡醫師審核 CLI 工具（Phase 29 P29-REVIEW）。
提供 list / show / approve / reject 四項子命令。

安全規範：
- list 與 show 全程以唯讀連線（mode=ro）開啟。
- show 固定附醒目提示「請逐句確認醫學敘述與用詞後再核准」。
- approve 與 reject 對正式 clinic.db 操作時必須明確帶 --allow-prod-db，未帶於連線前結束碼 2。
- 狀態變更一律透過 src.visual.review.set_review_status（approve 前自動重新執行 validate_ir）。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sqlite3
import sys
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.visual.review import adopt_v2_candidate, discard_v2_candidate, set_review_status
from src.visual.writer import has_visual_assets_table

PROD_DB_PATH = PROJECT_ROOT / "clinic.db"
REVIEW_WARNING_BANNER = "⚠️ 【醫師審核提醒】請逐句確認醫學敘述與用詞後再核准！"


def _open_ro(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)


def _slug(topic_key: str) -> str:
    """去除 tree- 與診所代碼前綴，取得療程 slug（用於跨診所同名偵測）。"""
    base = re.sub(r"^tree-", "", topic_key)
    return re.sub(r"^\d{10}-", "", base)


def _risk_scores(conn: sqlite3.Connection) -> dict[tuple, int]:
    """計算每筆草稿的審核風險分數；只讀取，不改變任何審核狀態。"""
    rows = conn.execute("SELECT topic_key, clinic_id, ir_json FROM visual_assets").fetchall()
    slug_clinics: dict[str, set] = {}
    for tk, cid, _ in rows:
        slug_clinics.setdefault(_slug(tk), set()).add(cid)
    scores: dict[tuple, int] = {}
    for tk, cid, ir in rows:
        try:
            scenes = json.loads(ir).get("scenes", [])
        except Exception:
            scenes = []
        blueprints = {sc.get("blueprint") for sc in scenes if isinstance(sc, dict)}
        score = 3 if "surgical_action" in blueprints else (2 if "contrast" in blueprints else 0)
        if len(slug_clinics.get(_slug(tk), set())) > 1:
            score += 1
        scores[(tk, cid)] = score
    return scores


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="clinicbrain 視覺解說卡醫師審核工具",
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
        help="確認允許對正式 clinic.db 進行審核狀態變更（正式庫寫入必填旗標）",
    )
    parser.add_argument(
        "--clinic-id",
        type=str,
        default=None,
        help="診所代碼（選填，預設 None 針對一般醫學資產）",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="審核子命令")

    p_list = subparsers.add_parser("list", help="列出所有視覺解說卡資產與狀態")
    p_list.add_argument("--clinic-id", type=str, default=argparse.SUPPRESS, help="診所代碼（選填）")
    p_list.add_argument("--risk-order", action="store_true", help="依風險分數排序（外科 +3、對照 +2、跨診所同名 +1），只影響顯示順序")

    p_show = subparsers.add_parser("show", help="檢視指定主題之完整場景內容")
    p_show.add_argument("topic_key", type=str, help="主題識別碼 (topic_key)")
    p_show.add_argument("--clinic-id", type=str, default=argparse.SUPPRESS, help="診所代碼（選填）")

    p_app = subparsers.add_parser("approve", help="核准指定主題之視覺解說卡")
    p_app.add_argument("topic_key", type=str, help="欲核准之主題識別碼 (topic_key)")
    p_app.add_argument("--clinic-id", type=str, default=argparse.SUPPRESS, help="診所代碼（選填）")

    p_rej = subparsers.add_parser("reject", help="駁回指定主題之視覺解說卡")
    p_rej.add_argument("topic_key", type=str, help="欲駁回之主題識別碼 (topic_key)")
    p_rej.add_argument("--clinic-id", type=str, default=argparse.SUPPRESS, help="診所代碼（選填）")

    p_prom = subparsers.add_parser("promote-v2", help="採納 -v2 候選列取代原本 V1 並設為 approved（同時清理 -v2 暫存列）")
    p_prom.add_argument("topic_key", type=str, help="欲晉升之 -v2 主題識別碼（如 tree-hifu-lifting-v2 或 tree-hifu-lifting）")
    p_prom.add_argument("--clinic-id", type=str, default=argparse.SUPPRESS, help="診所代碼（選填）")
    p_prom.add_argument("--keep-v2", action="store_true", default=False, help="晉升後保留 -v2 列不刪除")

    p_disc = subparsers.add_parser("discard-v2", help="捨棄 -v2 候選列並保留原本 V1 原封不動")
    p_disc.add_argument("topic_key", type=str, help="欲捨棄之 -v2 主題識別碼（如 tree-hifu-lifting-v2）")
    p_disc.add_argument("--clinic-id", type=str, default=argparse.SUPPRESS, help="診所代碼（選填）")

    args = parser.parse_args(argv)
    if not args.subcommand:
        parser.print_help()
        return 2

    target_path = Path(args.db)

    # 寫入子命令對正式庫的保護檢核（必須在任何 sqlite3.connect 之前）
    if args.subcommand in ("approve", "reject", "promote-v2", "discard-v2"):
        try:
            is_prod = target_path.resolve() == PROD_DB_PATH.resolve()
        except Exception:
            is_prod = str(target_path) == str(PROD_DB_PATH)

        if is_prod and not args.allow_prod_db:
            print(
                "❌ 【操作拒絕】目標為正式資料庫 clinic.db！\n"
                "執行 approve / reject 必須明確加上 --allow-prod-db 旗標。",
                file=sys.stderr,
            )
            return 2

    if not target_path.exists():
        print(f"❌ 錯誤：目標資料庫檔案不存在：{target_path}", file=sys.stderr)
        return 2

    # 支援子命令與主命令的 clinic_id 整合
    clinic_id = getattr(args, "clinic_id", None)

    if args.subcommand == "list":
        conn = _open_ro(target_path)
        try:
            if not has_visual_assets_table(conn):
                print("❌ 目標資料庫尚未建立 visual_assets 資料表。", file=sys.stderr)
                return 2
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(visual_assets)")
            has_clinic_col = "clinic_id" in [r[1] for r in cur.fetchall()]

            if has_clinic_col:
                if clinic_id is not None:
                    cur.execute(
                        "SELECT topic_key, title, review_status, content_version, source_type, reviewed_at, clinic_id "
                        "FROM visual_assets WHERE clinic_id IS ? ORDER BY id ASC",
                        (clinic_id,),
                    )
                else:
                    cur.execute(
                        "SELECT topic_key, title, review_status, content_version, source_type, reviewed_at, clinic_id "
                        "FROM visual_assets ORDER BY id ASC"
                    )
            else:
                cur.execute(
                    "SELECT topic_key, title, review_status, content_version, source_type, reviewed_at "
                    "FROM visual_assets ORDER BY id ASC"
                )
            rows = cur.fetchall()
            if not rows:
                print("（目前無任何視覺解說卡資產）")
                return 0
            if getattr(args, "risk_order", False):
                scores = _risk_scores(conn)
                rows = sorted(
                    rows,
                    key=lambda r: (-scores.get((r[0], r[6] if has_clinic_col else None), 0), r[0]),
                )
            for r in rows:
                clinic_label = f" | clinic={r[6]}" if (has_clinic_col and r[6]) else ""
                print(
                    f"{r[0]} | status={r[2]} | v{r[3]} | source={r[4]} | title={r[1]} | reviewed_at={r[5] or '-'}{clinic_label}"
                )
            return 0
        finally:
            conn.close()

    if args.subcommand == "show":
        conn = _open_ro(target_path)
        try:
            if not has_visual_assets_table(conn):
                print("❌ 目標資料庫尚未建立 visual_assets 資料表。", file=sys.stderr)
                return 2
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(visual_assets)")
            has_clinic_col = "clinic_id" in [r[1] for r in cur.fetchall()]

            if has_clinic_col:
                cur.execute(
                    "SELECT topic_key, title, keywords, ir_json, review_status, content_version, clinic_id "
                    "FROM visual_assets WHERE clinic_id IS ? AND topic_key = ?",
                    (clinic_id, args.topic_key),
                )
            else:
                cur.execute(
                    "SELECT topic_key, title, keywords, ir_json, review_status, content_version "
                    "FROM visual_assets WHERE topic_key = ?",
                    (args.topic_key,),
                )
            row = cur.fetchone()
            if row is None:
                print(f"❌ 找不到主題：{args.topic_key}", file=sys.stderr)
                return 1

            ir = json.loads(row[3])
            print(REVIEW_WARNING_BANNER)
            print("=" * 60)
            clinic_text = f" | 診所：{row[6]}" if (has_clinic_col and row[6]) else " | 診所：一般醫學"
            print(f"主題：{row[0]}（{row[1]}）| 狀態：{row[4]} | 版本：v{row[5]}{clinic_text}")
            print(f"關鍵字：{row[2]}")
            print("-" * 60)
            for idx, sc in enumerate(ir.get("scenes", []), 1):
                lbls = ", ".join(f"{lb['text']}({lb['tone']})" for lb in sc.get("labels", []))
                print(f"[場景 {idx}] ({sc.get('blueprint')}) {sc.get('title')}")
                print(f"  說明：{sc.get('caption')}")
                print(f"  標籤：{lbls}")
            print("=" * 60)
            print(REVIEW_WARNING_BANNER)
            return 0
        finally:
            conn.close()

    # approve / reject / promote-v2 / discard-v2
    conn = sqlite3.connect(str(target_path))
    try:
        if not has_visual_assets_table(conn):
            print("❌ 目標資料庫尚未建立 visual_assets 資料表。", file=sys.stderr)
            return 2

        if args.subcommand == "promote-v2":
            res = adopt_v2_candidate(
                conn,
                args.topic_key,
                clinic_id=clinic_id,
                keep_v2_row=getattr(args, "keep_v2", False),
            )
            if res["status"] == "not_found":
                print(f"❌ 找不到 V2 候選主題：{res.get('v2_topic_key')}", file=sys.stderr)
                return 1
            if res["status"] != "ok":
                print(f"❌ 晉升 V2 失敗：code={res.get('code')}", file=sys.stderr)
                return 1
            print(
                f"✅ 已採納 {res['v2_topic_key']} 取代 {res['base_topic_key']}（狀態：approved，已清理暫存列：{res['v2_removed']}）"
            )
            return 0

        if args.subcommand == "discard-v2":
            res = discard_v2_candidate(conn, args.topic_key, clinic_id=clinic_id)
            if res["status"] == "not_found":
                print(f"❌ 找不到 V2 候選主題：{res.get('v2_topic_key')}", file=sys.stderr)
                return 1
            if res["status"] != "ok":
                print(f"❌ 捨棄 V2 失敗：code={res.get('code')}", file=sys.stderr)
                return 1
            print(f"🗑️ 已捨棄 V2 候選列 {res['v2_topic_key']}（線上 V1 維持不變）")
            return 0

        target_status = "approved" if args.subcommand == "approve" else "rejected"
        res = set_review_status(conn, args.topic_key, target_status, clinic_id=clinic_id)
        if res["status"] == "not_found":
            print(f"❌ 找不到主題：{args.topic_key}", file=sys.stderr)
            return 1
        if res["status"] == "validation_failed":
            print(f"❌ 審核驗證未通過：code={res.get('code')}", file=sys.stderr)
            return 1

        print(f"✅ 主題 {args.topic_key} 狀態已更新為：{res['review_status']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
