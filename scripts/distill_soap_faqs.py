#!/usr/bin/env python3
"""
clinicbrain 臨床 SOAP 衛教提煉批次腳本 (distill_soap_faqs.py)。
Phase 15: 臨床 SOAP 衛教提煉與審核流 (15-03)

從指定診所之去識別化 soap_records 中分析 Assessment 與 Plan，
萃取高頻疾病的居家照護重點，生成符合法規與價格清洗標準之衛教 FAQ 草稿 (source_type='soap_distilled', review_status='pending')。

安全規範：
- 正式庫防禦式設計：寫入操作對正式 clinic.db 執行時，必須明確帶有 --confirm-prod-backup 旗標。
- 拒絕分支在連線與寫入前 return 2。
- dry-run 模式預覽產出結果，並執行事務回滾 (rollback)，確保零資料庫異動。

使用範例：
    # 預覽提煉結果
    python3 scripts/distill_soap_faqs.py --clinic-id 3503190424 --dry-run

    # 正式庫執行提煉（必須先確認備份）
    python3 scripts/distill_soap_faqs.py --clinic-id 3503190424 --confirm-prod-backup
"""

import argparse
from pathlib import Path
import sqlite3
import sys

# 將專案根目錄加入搜尋路徑
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.soap.distiller import distill_soap_records

PROD_DB_PATH = PROJECT_ROOT / "clinic.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="clinicbrain SOAP 臨床衛教提煉工具",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--clinic-id",
        type=str,
        required=True,
        help="目標診所代碼（如 3503190424）",
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=2,
        help="照護重點最低出現頻率門檻",
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
        help="僅預覽提煉與產出結果，不對資料庫進行任何實質修改",
    )
    parser.add_argument(
        "--confirm-prod-backup",
        action="store_true",
        default=False,
        help="確認已備份正式 clinic.db（目標為正式庫且非 dry-run 時為必填保護旗標）",
    )

    args = parser.parse_args(argv)
    target_path = Path(args.db)

    # 1. 檢查檔案是否存在
    if not target_path.exists():
        print(f"❌ 錯誤：目標資料庫檔案不存在：{target_path}", file=sys.stderr)
        return 2

    # 2. 針對正式庫的安全防禦檢核
    try:
        is_target_prod = (
            PROD_DB_PATH.exists()
            and target_path.resolve() == PROD_DB_PATH.resolve()
        )
    except Exception:
        is_target_prod = False

    if not args.dry_run and is_target_prod and not args.confirm_prod_backup:
        print(
            "🛑 拒絕操作正式資料庫！\n"
            "您嘗試對正式 clinic.db 執行衛教提煉寫入，但未提供 --confirm-prod-backup 旗標。\n"
            "請先手動備份正式庫，例如：\n"
            "  cp clinic.db clinic.db.bak-$(date +%Y%m%d)\n"
            "備份完成後，請重新執行並附加確認旗標：\n"
            f"  python3 scripts/distill_soap_faqs.py --clinic-id {args.clinic_id} --confirm-prod-backup",
            file=sys.stderr,
        )
        return 2

    # 3. Dry-Run 模式預覽
    if args.dry_run:
        conn = sqlite3.connect(f"file:{target_path.resolve()}?mode=ro", uri=True)
        try:
            res = distill_soap_records(conn, args.clinic_id, args.min_occurrences, dry_run=True)
            print(f"🔍 [Dry-Run 模式] 診所 '{args.clinic_id}' 的 SOAP 衛教提煉預覽結果：")
            print(f"✨ 預計產出 {res['distilled_count']} 筆衛教 FAQ 草稿（標的疾病：{res['conditions']}）。")
            for idx, f in enumerate(res["faqs"]):
                print("=" * 60)
                print(f"草稿 #{idx+1} (topic: {f['topic_key']})")
                print(f"問：{f['question']}")
                print("-" * 60)
                print(f"答：\n{f['answer']}")
            print("=" * 60)
            print("✨ Dry-Run 完成，未對資料庫進行任何實質修改。")
            return 0
        finally:
            conn.close()

    # 4. 實際執行提煉寫入
    conn = sqlite3.connect(str(target_path))
    try:
        print(f"🚀 開始對診所 '{args.clinic_id}' 執行 SOAP 臨床衛教提煉...")
        try:
            res = distill_soap_records(conn, args.clinic_id, args.min_occurrences)
        except RuntimeError as e:
            print(f"❌ 提煉中止：{e}", file=sys.stderr)
            return 2
        print(f"✅ 提煉完成！成功產出 {res['distilled_count']} 筆待審核衛教草稿（標的疾病：{res['conditions']}）。")
        print("提示：提煉草稿預設為 'pending' 狀態，請使用 review_faq 工具進行醫師簽核。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
