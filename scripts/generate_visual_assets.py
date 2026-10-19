#!/usr/bin/env python3
"""
視覺解說卡本地 LLM 預生成 CLI 工具（Phase 29 P29-GEN）。

安全規範：
- --dry-run 只載入並驗證骨架、印出規劃，絕不連線資料庫、絕不呼叫 LLM。
- 預設拒絕操作正式庫：目標為正式 clinic.db 時，未帶 --allow-prod-db 於連線前以結束碼 2 拒絕。
- 未遷移的資料庫（缺少 visual_assets 表）以結束碼 2 退出並印出遷移指引，不自動建表。
- 生成產出一律以 upsert_assets(source_type='llm_generated') 寫入 pending；絕不提供自動核准旗標。
- 生成失敗僅印出結構化代碼，不印出模型輸出原文，並以結束碼 1 退出。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
import sys
from typing import Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pageindex.llm_client import VISUAL_SAMPLING, local_llm_call
from src.visual.generator import DEFAULT_SKELETON_DIR, generate_ir, load_skeleton
from src.visual.writer import has_visual_assets_table, upsert_assets

PROD_DB_PATH = PROJECT_ROOT / "clinic.db"


def _resolve_skeleton_paths(topic: Optional[str]) -> list[Path]:
    if topic:
        p = DEFAULT_SKELETON_DIR / f"{topic}.json"
        if not p.exists():
            raise FileNotFoundError(f"找不到主題骨架檔：{p}")
        return [p]
    return sorted(DEFAULT_SKELETON_DIR.glob("*.json"))


def main(
    argv: Optional[list[str]] = None,
    llm_call: Optional[Callable[[str], str]] = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="clinicbrain 視覺解說卡本地 LLM 預生成工具",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=PROD_DB_PATH,
        help="目標 SQLite 資料庫路徑",
    )
    parser.add_argument(
        "--topic",
        type=str,
        default=None,
        help="指定單一主題識別碼 (topic_key)，省略則處理所有骨架檔",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="僅載入並驗證骨架檔、印出規劃，不連線資料庫、不呼叫 LLM",
    )
    parser.add_argument(
        "--allow-prod-db",
        action="store_true",
        default=False,
        help="確認允許對正式 clinic.db 寫入待審核資產（正式庫必填保護旗標）",
    )

    args = parser.parse_args(argv)

    # 1. 載入並驗證所有目標骨架檔
    try:
        skel_paths = _resolve_skeleton_paths(args.topic)
        if not skel_paths:
            print("❌ 錯誤：找不到任何骨架檔案。", file=sys.stderr)
            return 2
        skeletons = [load_skeleton(p) for p in skel_paths]
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ 骨架載入失敗：{e}", file=sys.stderr)
        return 2

    # 2. --dry-run 模式：不連線資料庫、不呼叫 LLM
    if args.dry_run:
        print("🔍 【預覽模式】已驗證骨架規劃清單（未連線資料庫、未呼叫 LLM）：")
        for sk in skeletons:
            print(f"  - topic_key={sk['topic_key']} | title={sk['title']} | scenes={len(sk['scenes'])}")
        return 0

    target_path = Path(args.db)

    # 3. 正式庫保護檢核（必須在任何 sqlite3.connect 之前）
    try:
        is_prod = target_path.resolve() == PROD_DB_PATH.resolve()
    except Exception:
        is_prod = str(target_path) == str(PROD_DB_PATH)

    if is_prod and not args.allow_prod_db:
        print(
            "❌ 【操作拒絕】目標為正式資料庫 clinic.db！\n"
            "若確認要將預生成草稿寫入正式庫，請明確加上 --allow-prod-db 旗標。",
            file=sys.stderr,
        )
        return 2

    if not target_path.exists():
        print(f"❌ 錯誤：目標資料庫檔案不存在：{target_path}", file=sys.stderr)
        return 2

    # 4. 檢查資料庫是否已遷移
    conn = sqlite3.connect(str(target_path))
    try:
        if not has_visual_assets_table(conn):
            print(
                "❌ 錯誤：目標資料庫尚未建立 visual_assets 資料表！\n"
                "請先執行遷移腳本：python3 scripts/migrate_visual_assets.py --db <PATH>",
                file=sys.stderr,
            )
            return 2

        effective_llm = llm_call or (
            lambda p: local_llm_call(p, timeout=240, sampling=dict(VISUAL_SAMPLING))
        )

        any_failed = False
        for sk in skeletons:
            tkey = sk["topic_key"]
            ir, code = generate_ir(sk, effective_llm, max_attempts=2, db_path=target_path)
            if ir is None or code != "ok":
                print(f"❌ 主題 {tkey} 生成失敗：code={code}", file=sys.stderr)
                any_failed = True
                continue

            res = upsert_assets(
                conn,
                [
                    {
                        "topic_key": ir["topic_key"],
                        "title": ir["title"],
                        "keywords": ir["keywords"],
                        "ir": ir,
                    }
                ],
                source_type="llm_generated",
            )
            print(
                f"✅ 主題 {tkey} 已寫入待審佇列 (pending)："
                f"inserted={res['inserted']}, updated={res['updated']}, unchanged={res['unchanged']}"
            )

        return 1 if any_failed else 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
