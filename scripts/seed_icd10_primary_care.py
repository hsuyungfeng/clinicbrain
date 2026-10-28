#!/usr/bin/env python3
"""臺灣基層診所 36 項 ICD-10 高頻疾病目錄種子寫入 CLI (Phase 35)。

用法：
  python3 scripts/seed_icd10_primary_care.py --dry-run
  python3 scripts/seed_icd10_primary_care.py --db <測試複本> [--specialty ent_peds_fm] [--approve-visuals]

安全規範：
- --dry-run 僅離線驗證並印出摘要，不連線任何資料庫。
- 目標為正式 clinic.db 時，未帶 --allow-prod-db 於連線前以結束碼 2 拒絕。
- 結束碼：0 成功；1 未預期錯誤；2 參數或前置檢查拒絕。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.visual.icd10_catalog import (  # noqa: E402
    SPECIALTY_TARGETS,
    load_icd10_catalog,
    seed_icd10_catalog,
    validate_catalog_entry,
)

PROD_DB_PATH = PROJECT_ROOT / "clinic.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="寫入臺灣基層診所 36 項 ICD-10 疾病目錄（一般醫學共用）")
    parser.add_argument("--db", default=str(PROD_DB_PATH), help="目標 SQLite 路徑（預設為正式庫，需 --allow-prod-db）")
    parser.add_argument("--specialty", default=None, choices=sorted(SPECIALTY_TARGETS), help="僅處理指定專科")
    parser.add_argument("--dry-run", action="store_true", help="僅離線驗證並印出摘要，不連線資料庫")
    parser.add_argument("--allow-prod-db", action="store_true", help="確認允許寫入正式 clinic.db")
    parser.add_argument("--approve-visuals", action="store_true", help="同時核准視覺卡（預設維持 pending）")
    parser.add_argument("--approve-trees", action="store_true", help="同時核准 36 棵一般醫學推理樹（預設維持 pending）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    catalog = load_icd10_catalog()
    if args.specialty:
        catalog = [e for e in catalog if e["specialty"] == args.specialty]

    # 1. 離線驗證（不連線資料庫）
    failures = []
    for entry in catalog:
        ok, code = validate_catalog_entry(entry)
        if not ok:
            failures.append((entry.get("topic_key", "?"), code))
    if failures:
        for topic, code in failures:
            print(f"❌ 驗證失敗：{topic} -> {code}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"🔍 【預覽模式】共 {len(catalog)} 筆條目通過離線驗證（未連線資料庫）：")
        counts: dict[str, int] = {}
        for entry in catalog:
            counts[entry["specialty"]] = counts.get(entry["specialty"], 0) + 1
            print(f"  - {entry['icd10_code']:<9} {entry['topic_key']:<30} {entry['ir']['title']}")
        for spec, n in counts.items():
            print(f"  專科 {spec}: {n} 筆")
        return 0

    # 2. 正式庫保護（必須在任何 sqlite3.connect 之前）
    target = Path(args.db)
    try:
        is_prod = target.resolve() == PROD_DB_PATH.resolve()
    except OSError:
        is_prod = str(target) == str(PROD_DB_PATH)
    if is_prod and not args.allow_prod_db:
        print(
            "❌ 【操作拒絕】目標為正式資料庫 clinic.db！\n"
            "若確認要寫入 ICD-10 目錄，請明確加上 --allow-prod-db 旗標。",
            file=sys.stderr,
        )
        return 2

    if not target.exists():
        print(f"❌ 錯誤：目標資料庫檔案不存在：{target}", file=sys.stderr)
        return 2

    # 3. 寫入（單一交易；任一錯誤整批回滾）
    conn = sqlite3.connect(str(target))
    try:
        result = seed_icd10_catalog(
            conn,
            catalog,
            approve_visuals=args.approve_visuals,
            approve_trees=args.approve_trees,
            commit=True,
        )
    except RuntimeError as exc:
        conn.rollback()
        print(f"❌ 前置檢查失敗（資料庫可能尚未遷移）：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f"❌ 寫入失敗：{type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    v = result["visuals"]
    f = result["faqs"]
    tr = result["trees"]
    print(f"推理樹（一般醫學）新增 {tr[0]} / 更新 {tr[1]} / 未變 {tr[2]}")
    print(
        f"✅ 完成：視覺卡 新增 {v['inserted']} / 更新 {v['updated']} / 未變 {v['unchanged']}；"
        f"核准 {result['approved']} 筆；"
        f"衛教 FAQ 新增 {f[0]} / 更新 {f[1]} / 未變 {f[2]}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
