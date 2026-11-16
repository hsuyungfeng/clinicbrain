"""每日診斷碼與網路趨勢衛教覆蓋率檢查 CLI 入口。

範例：
  python3 scripts/run_daily_gap_check.py --db clinic.db --clinic-id 3503190424 --dry-run --json
  python3 scripts/run_daily_gap_check.py --db /tmp/test.db --icd-json icd.json --trend-url https://...
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.routes.query import deep_mask_prices
from src.batch.gap_checker import run_gap_check


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="每日 ICD-10 與醫療趨勢衛教覆蓋率檢查")
    parser.add_argument("--db", default="clinic.db", help="SQLite 資料庫路徑")
    parser.add_argument("--clinic-id", default=None, help="診所代碼（掃描 soap_records）")
    parser.add_argument("--icd-json", default=None, help="外部聚合診斷碼 JSON 檔路徑")
    parser.add_argument("--trend-url", action="append", default=[], help="每日趨勢來源 HTTPS URL")
    parser.add_argument("--allowlist", default=None, help="網域白名單 JSON 檔路徑")
    parser.add_argument("--max-topics", type=int, default=10, help="最多檢查主題數")
    parser.add_argument("--dry-run", action="store_true", help="僅盤點報表，不寫入資料庫")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式輸出報表")
    args = parser.parse_args(argv)

    agg_data = None
    if args.icd_json:
        agg_data = json.loads(Path(args.icd_json).read_text(encoding="utf-8"))

    conn = sqlite3.connect(args.db)
    try:
        report = run_gap_check(
            conn,
            clinic_id=args.clinic_id,
            aggregated_icd10=agg_data,
            trend_urls=args.trend_url,
            allowlist_path=args.allowlist,
            dry_run=args.dry_run,
            max_topics=args.max_topics,
        )
    finally:
        conn.close()

    payload = deep_mask_prices(report.as_dict())
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"[GapCheck] total={report.total_topics} covered={report.covered} "
            f"partial={report.partial} uncovered={report.uncovered} "
            f"inserted_pending={report.inserted_pending} dry_run={report.dry_run}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
