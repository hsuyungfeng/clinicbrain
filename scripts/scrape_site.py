#!/usr/bin/env python3
"""Phase 23 Task 3：網站素材擷取 CLI 入口與生產庫守門腳本 (scripts/scrape_site.py)。

提供安全受限的單站素材擷取與 FAQ 草稿建置 CLI。
結束碼規範：
  0: 正常完成（包含部分網址擷取失敗，或 skipped_locked）
  1: 系統未預期內部例外（stderr 僅輸出例外類別名稱）
  2: 參數錯誤、安全政策拒絕或生產資料庫守門阻擋
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3
import sys
from typing import Optional
import urllib.parse

# 加入專案根目錄
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.config import config
from src.scraper.policy import PolicyError, check_url_allowed, load_allowlist
from src.scraper.runner import (
    OWNERSHIP_FILE,
    ScrapeOptions,
    check_ownership_confirmation,
    run_scrape_urls,
)

DEFAULT_ALLOWLIST = PROJECT_ROOT / "data" / "scraper" / "sources.json"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="clinicbrain 網站素材擷取與 FAQ 草稿建置工具",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="目標網址（可多次指定）",
    )
    parser.add_argument(
        "--urls-file",
        type=str,
        default=None,
        help="包含多筆目標網址之文字檔案路徑（每行一筆，支援 # 註解與空行）",
    )
    parser.add_argument(
        "--clinic-id",
        type=str,
        required=True,
        help="目標診所機構代碼（10 碼數字，如 3503190424）",
    )
    parser.add_argument(
        "--allowlist",
        type=str,
        default=str(DEFAULT_ALLOWLIST),
        help="網域白名單設定檔路徑",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="請求間隔秒數（下限 3.0 秒）",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP 請求超時秒數",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=str(config.db_path),
        help="目標 SQLite 資料庫檔案路徑",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--write",
        action="store_true",
        default=False,
        help="寫入草稿至 faq_cache 資料表（review_status='pending'）",
    )
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="僅預覽產出結果，不對資料庫發出寫入交易",
    )

    parser.add_argument(
        "--allow-prod-db",
        action="store_true",
        default=False,
        help="允許目標為正式 clinic.db 之防禦確認旗標",
    )
    parser.add_argument(
        "--confirm-prod-backup",
        action="store_true",
        default=False,
        help="確認已備份正式 clinic.db 之防禦確認旗標",
    )
    parser.add_argument(
        "--fixture-dir",
        type=str,
        default=None,
        help="以本機 fixture HTML 目錄進行離線模擬擷取",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="明確明示執行真實網域之外部 HTTPS 擷取",
    )
    parser.add_argument(
        "--report-json",
        type=str,
        default=None,
        help="將批次報告另存為 JSON 檔案之路徑",
    )

    args = parser.parse_args(argv)

    # 1. 守門：節流時間下限檢查
    if args.interval < 3.0:
        sys.stderr.write("請求間隔不得小於 3.0 秒\n")
        return 2

    # 2. 守門：執行模式決定
    effective_write = args.write
    if not args.write and not args.dry_run:
        sys.stderr.write("未指定 --write 或 --dry-run，預設以 --dry-run 模式執行\n")
        effective_write = False

    # 3. 守門：來源模式互斥檢查
    if args.fixture_dir and args.live:
        sys.stderr.write("--fixture-dir 與 --live 互斥，無法同時指定\n")
        return 2

    if args.fixture_dir and (args.url or args.urls_file):
        sys.stderr.write("--fixture-dir 模式不可與 --url 或 --urls-file 同時使用\n")
        return 2

    # 4. 收集目標網址
    urls: list[str] = []
    if args.fixture_dir:
        fdir = Path(args.fixture_dir)
        if not fdir.is_dir():
            sys.stderr.write(f"Fixture 目錄不存在: {fdir}\n")
            return 2
        html_files = sorted(fdir.glob("*.html"))
        if not html_files:
            sys.stderr.write(f"Fixture 目錄中無任何 .html 檔案: {fdir}\n")
            return 2
        urls = [f"fixture://{f.name}" for f in html_files]
    else:
        if args.url:
            urls.extend(args.url)
        if args.urls_file:
            ufile = Path(args.urls_file)
            if not ufile.is_file():
                sys.stderr.write(f"網址清單檔案不存在: {ufile}\n")
                return 2
            for line in ufile.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    urls.append(stripped)

        if not urls:
            sys.stderr.write("未提供任何目標擷取網址\n")
            return 2

        # 真實網域模式防線
        if not args.live:
            sys.stderr.write("真實網域請求必須明確指定 --live 旗標\n")
            return 2

        # 檢驗白名單與擁有權授權確認
        try:
            allowlist = load_allowlist(args.allowlist)
            for u in urls:
                check_url_allowed(u, allowlist)
            check_ownership_confirmation(OWNERSHIP_FILE, allowlist)
        except PolicyError as e:
            sys.stderr.write(f"安全政策拒絕: {e.reason}\n")
            return 2
        except Exception as e:
            sys.stderr.write(f"設定檢驗失敗: {e}\n")
            return 2

    # 5. 守門：正式資料庫雙重檢驗 (realpath + os.path.samefile)
    target_db_path = Path(args.db_path)
    if not target_db_path.exists():
        sys.stderr.write(f"資料庫檔案不存在: {target_db_path}\n")
        return 2

    target_real = os.path.realpath(str(target_db_path))
    prod_real = os.path.realpath(str(config.db_path))
    is_prod = target_real == prod_real

    if not is_prod and target_db_path.exists() and Path(config.db_path).exists():
        try:
            is_prod = os.path.samefile(str(target_db_path), str(config.db_path))
        except OSError:
            is_prod = False

    if is_prod and effective_write:
        if not args.allow_prod_db:
            sys.stderr.write("寫入正式資料庫必須明確指定 --allow-prod-db\n")
            return 2
        if not args.confirm_prod_backup:
            sys.stderr.write("寫入正式資料庫必須明確指定 --confirm-prod-backup 確認已備份\n")
            return 2

    # 6. Schema 預檢 (Preflight)
    schema_preflight: Optional[dict[str, bool]] = None
    if not effective_write:
        # dry-run: 以 mode=ro URI 唯讀開庫
        encoded_path = urllib.parse.quote(target_real)
        ro_uri = f"file:{encoded_path}?mode=ro"
        try:
            ro_conn = sqlite3.connect(ro_uri, uri=True)
            cur = ro_conn.cursor()
            cur.execute("PRAGMA table_info(faq_cache)")
            cols = {row[1] for row in cur.fetchall()}
            schema_preflight = {
                "has_metadata_column": "metadata" in cols,
                "has_review_status": "review_status" in cols,
            }
            ro_conn.close()
        except Exception as e:
            sys.stderr.write(f"Dry-run 唯讀檢驗連線失敗: {e}\n")
            return 2
    else:
        # write 模式：若缺少欄位則 Fail-Closed 拒絕執行
        try:
            chk_conn = sqlite3.connect(str(target_db_path))
            cur = chk_conn.cursor()
            cur.execute("PRAGMA table_info(faq_cache)")
            cols = {row[1] for row in cur.fetchall()}
            chk_conn.close()
            if "metadata" not in cols or "review_status" not in cols:
                sys.stderr.write("資料庫缺少 faq_cache.metadata 或 review_status 欄位，請先執行遷移腳本\n")
                return 2
        except Exception as e:
            sys.stderr.write(f"資料庫結構檢驗失敗: {e}\n")
            return 2

    # 7. 執行擷取作業
    options = ScrapeOptions(
        clinic_id=args.clinic_id,
        allowlist_path=args.allowlist,
        ownership_path=OWNERSHIP_FILE,
        min_interval=args.interval,
        timeout=args.timeout,
        write=effective_write,
        db_path=args.db_path,
        fixture_dir=args.fixture_dir,
    )

    try:
        report = run_scrape_urls(urls, options=options)
    except Exception as e:
        sys.stderr.write(f"{type(e).__name__}\n")
        return 1

    if schema_preflight is not None:
        report.schema_preflight = schema_preflight

    if report.status == "skipped_locked":
        sys.stderr.write("夜間批次持鎖中，略過本次擷取作業 (skipped_locked)\n")

    report_json = report.to_json()
    print(report_json)

    if args.report_json:
        try:
            Path(args.report_json).write_text(report_json, encoding="utf-8")
        except Exception as e:
            sys.stderr.write(f"報告檔案寫入失敗: {e}\n")

    if is_prod and effective_write and report.status == "ok":
        sys.stderr.write("提示：clinic.db 受 git 追蹤，請勿直接 git add\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
