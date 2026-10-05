#!/usr/bin/env python3
"""
FAQ 醫師審核工具 CLI（Phase 09 BATCH-01 Task 2 / Phase 12 GC-04, DEBT-03）。
提供醫師進行 LLM 預生成常見問答之檢視 (list/show)、核准 (approve)、駁回 (reject)、重置 (reset) 與重生成標記 (mark-regen)。

安全規範：
- 正式庫防禦式設計：寫入子命令（approve/reject/reset/mark-regen）對正式 clinic.db 操作時，必須明確帶有 --allow-prod-db 旗標。
- 拒絕分支必須在任何 sqlite3.connect 呼叫之前 return 2。
- list 與 show 查詢指令全程強制採用 SQLite 唯讀模式 (mode=ro) 開啟連線，且輸出不寫入日誌。
- 單一負責來源：本腳本禁止手寫任何 UPDATE 語句，一律透過 faq_review 模組執行。
- 人工把關：本工具不提供批次全選核准，所有核准操作必須逐筆指定明確 ID，且核准前會再次執行多層醫療合規驗證。
"""

import argparse
from pathlib import Path
import sqlite3
import sys

# 將專案根目錄加入搜尋路徑
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pageindex.faq_conflicts import find_similar_clinic_faqs
from src.pageindex.faq_review import (
    REVIEW_APPROVED,
    REVIEW_PENDING,
    REVIEW_REJECTED,
    count_by_status,
    get_faq,
    has_review_status,
    list_faqs,
    mark_for_regeneration,
    set_review_status,
    validation_report,
)
from src.query.faq_shortcut import CLINIC_RELATED_FLOOR

PROD_DB_PATH = PROJECT_ROOT / "clinic.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="clinicbrain FAQ 醫師審核工具",
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
        help="確認允許對正式 clinic.db 進行審核狀態變更（正式庫必填保護旗標）",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="子命令")

    # list 子命令
    parser_list = subparsers.add_parser("list", help="列出指定狀態的 LLM 常見問答")
    parser_list.add_argument(
        "--status",
        choices=[REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED],
        default=REVIEW_PENDING,
        help="篩選審核狀態",
    )
    parser_list.add_argument(
        "--topic",
        type=str,
        default=None,
        help="篩選指定主題識別碼 (topic_key)",
    )
    parser_list.add_argument(
        "--limit",
        type=int,
        default=50,
        help="顯示數量上限",
    )

    # show 子命令
    parser_show = subparsers.add_parser("show", help="檢視指定 ID 問答之完整內容")
    parser_show.add_argument("id", type=int, help="欲檢視之 FAQ ID")

    # approve 子命令
    parser_app = subparsers.add_parser("approve", help="核准指定 ID 之常見問答")
    parser_app.add_argument("ids", type=int, nargs="+", help="欲核准的 FAQ ID 清單")

    # reject 子命令
    parser_rej = subparsers.add_parser("reject", help="駁回指定 ID 之常見問答")
    parser_rej.add_argument("ids", type=int, nargs="+", help="欲駁回的 FAQ ID 清單")

    # reset 子命令
    parser_rst = subparsers.add_parser("reset", help="重置指定 ID 之審核狀態為待審核 (pending)")
    parser_rst.add_argument("ids", type=int, nargs="+", help="欲重置的 FAQ ID 清單")

    # mark-regen 子命令
    parser_mr = subparsers.add_parser("mark-regen", help="標記指定被駁回之 FAQ 為待重新生成")
    parser_mr.add_argument("ids", type=int, nargs="+", help="欲標記重新生成的 FAQ ID 清單")

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

    is_write_cmd = args.subcommand in ("approve", "reject", "reset", "mark-regen")
    if is_write_cmd and is_target_prod and not args.allow_prod_db:
        print("=" * 70, file=sys.stderr)
        print("🛑 拒絕操作：目標資料庫為正式環境 clinic.db！", file=sys.stderr)
        print("為了資料安全，對正式庫進行審核狀態變更前請確認操作必要性，並加上 --allow-prod-db 旗標：", file=sys.stderr)
        print(f"    python3 scripts/review_faq.py --allow-prod-db {args.subcommand} ...", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        return 2

    # 3. 唯讀命令：list 與 show
    if args.subcommand in ("list", "show"):
        conn_str = f"file:{target_path.resolve()}?mode=ro"
        conn = sqlite3.connect(conn_str, uri=True)
        try:
            if not has_review_status(conn):
                print(
                    "❌ 錯誤：目標資料庫尚未建立審核欄位！請先執行遷移腳本：\n"
                    f"    python3 scripts/migrate_faq_review_status.py --db {target_path}",
                    file=sys.stderr,
                )
                return 2

            if args.subcommand == "list":
                faqs = list_faqs(conn, status=args.status, limit=args.limit, topic_key=args.topic)
                counts = count_by_status(conn)

                if not faqs:
                    filter_msg = f"（主題: {args.topic}）" if args.topic else ""
                    print(f"目前沒有狀態為 '{args.status}' {filter_msg}的 LLM 生成常見問答。")
                else:
                    print(f"📋 狀態為 '{args.status}' 的 LLM 生成問答清單（共 {len(faqs)} 筆）：")
                    print("-" * 88)
                    print(f"{'ID':<6} {'類別':<8} {'機構代碼':<12} {'主題/療程':<20} {'來源':<14} {'驗證':<6} {'問題摘要'}")
                    print("-" * 88)
                    for f in faqs:
                        c_id = f["clinic_id"] or "通用"
                        t_key = f["topic_key"] or "無"
                        s_type = f.get("source_type", "llm_generated")
                        v_rep = validation_report(f)
                        v_status = "OK" if v_rep["ok"] else "FAIL"
                        q_summary = f["question"][:28] + ("..." if len(f["question"]) > 28 else "")
                        print(f"{f['id']:<6} {f['category']:<8} {c_id:<12} {t_key:<20} {s_type:<14} {v_status:<6} {q_summary}")
                        if not v_rep["ok"] and v_rep["reason"]:
                            print(f"       ↳ 驗證未通過原因: {v_rep['reason']}")
                    print("-" * 88)

                print(f"📊 目前各審核狀態筆數統計：{counts}")
                return 0

            elif args.subcommand == "show":
                faq = get_faq(conn, args.id)
                if not faq:
                    print(f"❌ 找不到 ID 為 {args.id} 的常見問答記錄。", file=sys.stderr)
                    return 1

                print("=" * 60)
                print(f"FAQ 詳細記錄 (ID: {faq['id']})")
                print("=" * 60)
                print(f"機構代碼：{faq['clinic_id'] or '無 (通用類別)'}")
                print(f"主題識別：{faq['topic_key'] or '無'}")
                print(f"問答類別：{faq['category']}")
                print(f"審核狀態：{faq.get('review_status', '未定義')}")
                print(f"審核時間：{faq.get('reviewed_at') or '尚未審核'}")
                print("-" * 60)
                print(f"【問題】\n{faq['question']}")
                print("-" * 60)
                print(f"【解答】\n{faq['answer']}")
                print("-" * 60)
                print("【生成來源】")
                print(f"資料來源：{faq.get('source_type', '未知')}")
                print(f"內容版本：v{faq.get('content_version', 1)}")
                print(f"主題識別：{faq.get('topic_key') or '無'}")
                print(f"審核狀態：{faq.get('review_status', '未定義')}")
                print("-" * 60)
                print("【驗證結果】")
                v_rep = validation_report(faq)
                warn_note = "（已含何時該就醫警訊檢核）" if faq.get("category") == "general" else ""
                v_txt = "通過 (OK)" if v_rep["ok"] else f"不通過 (FAIL: {v_rep['reason']})"
                print(f"醫療合規驗證：{v_txt} {warn_note}")

                if faq.get("category") == "general" and not faq.get("clinic_id"):
                    print("-" * 60)
                    print("【相近診所 FAQ（供人工比對是否衝突）】")
                    similars = find_similar_clinic_faqs(conn, faq["question"])
                    if not similars:
                        print(f"  （無覆蓋率 >= {CLINIC_RELATED_FLOOR:.2f} 的診所 FAQ）")
                    else:
                        for sim in similars:
                            ans_preview = sim["answer"][:80] + ("..." if len(sim["answer"]) > 80 else "")
                            print(
                                f"  [ID {sim['id']}] Q: {sim['question']} "
                                f"(覆蓋率 query: {sim['query_coverage']:.2f}, question: {sim['question_coverage']:.2f})"
                            )
                            print(f"         A: {ans_preview}")
                    print("⚠️  注意：覆蓋率只是詞彙守衛，不是主題守衛：未列出不代表沒有衝突，請自行比對同主題診所指示。")

                print("=" * 60)
                return 0
        finally:
            conn.close()

    # 4. 寫入命令：mark-regen
    if args.subcommand == "mark-regen":
        conn = sqlite3.connect(str(target_path))
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            if not has_review_status(conn):
                print(
                    "❌ 錯誤：目標資料庫尚未建立審核欄位！請先執行遷移腳本：\n"
                    f"    python3 scripts/migrate_faq_review_status.py --db {target_path}",
                    file=sys.stderr,
                )
                return 2

            res = mark_for_regeneration(conn, args.ids)
            if res.changed:
                print(f"✅ 已標記重新生成：{res.changed}，下次夜間批次將重新生成（結果一律 pending）")

            if res.skipped:
                print("⚠️ 下列項目未進行標記：")
                for f_id, reason in res.skipped:
                    print(f"  - ID {f_id}: {reason}")
                return 1

            return 0
        finally:
            conn.close()

    # 5. 寫入命令：approve / reject / reset
    target_status = {
        "approve": REVIEW_APPROVED,
        "reject": REVIEW_REJECTED,
        "reset": REVIEW_PENDING,
    }[args.subcommand]

    conn = sqlite3.connect(str(target_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        if not has_review_status(conn):
            print(
                "❌ 錯誤：目標資料庫尚未建立審核欄位！請先執行遷移腳本：\n"
                f"    python3 scripts/migrate_faq_review_status.py --db {target_path}",
                file=sys.stderr,
            )
            return 2

        # 若為核准操作，先印出即將核准的內容與驗證結果
        if args.subcommand == "approve":
            print("🔍 審核前內容預覽：")
            for f_id in args.ids:
                item = get_faq(conn, f_id)
                if item:
                    v_rep = validation_report(item)
                    v_txt = "通過 (OK)" if v_rep["ok"] else f"不通過 ({v_rep['reason']})"
                    print(f"  [ID {f_id}] Q: {item['question']}")
                    print(f"         A: {item['answer']}")
                    print(f"         驗證: {v_txt}")

        res = set_review_status(
            conn,
            args.ids,
            target_status,
            enforce_general_warning=(args.subcommand == "approve"),
        )

        action_name = {"approve": "核准", "reject": "駁回", "reset": "重置"}[args.subcommand]
        if res.changed:
            print(f"✅ 已成功{action_name}項目: {res.changed}")

        if res.skipped:
            print(f"⚠️ 下列項目未進行{action_name}：")
            for f_id, reason in res.skipped:
                print(f"  - ID {f_id}: {reason}")
            return 1

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
