#!/usr/bin/env python3
"""
由已核准 PageIndex 臨床推理樹自動生成視覺解說卡草稿 CLI 工具 (Phase 31 P31-AUTODRAFT)。

使用範例：
    # 預覽可生成推理樹與提示詞（唯讀預覽）
    python3 scripts/autodraft_visual_from_trees.py --db /path/to/test.db --dry-run

    # 指定單一 doc-id 生成
    python3 scripts/autodraft_visual_from_trees.py --db /path/to/test.db --doc-id hifu-lifting

    # 正式庫執行（必須明確帶 --allow-prod-db）
    python3 scripts/autodraft_visual_from_trees.py --allow-prod-db --doc-id hifu-lifting
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
import sys
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.visual.autodraft import (
    autodraft_from_tree,
    build_tree_visual_prompt,
    fetch_eligible_trees,
    normalize_tree_topic_key,
)
from src.visual.writer import has_visual_assets_table

PROD_DB_PATH = PROJECT_ROOT / "clinic.db"


def _open_ro(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="從已核准 PageIndex 臨床推理樹自動生成視覺解說卡草稿",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=PROD_DB_PATH,
        help="目標 SQLite 資料庫路徑",
    )
    parser.add_argument(
        "--doc-id",
        type=str,
        default=None,
        help="指定生成單一推理樹 doc_id（選填）",
    )
    parser.add_argument(
        "--clinic-id",
        type=str,
        default=None,
        help="篩選特定診所之推理樹（選填）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="僅預覽目標推理樹與生成提示詞，不呼叫 LLM 且不寫入資料庫",
    )
    parser.add_argument(
        "--allow-prod-db",
        action="store_true",
        default=False,
        help="確認允許對正式 clinic.db 進行草稿寫入（正式庫寫入必填旗標）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="強制重新生成已存在之視覺解說卡（預設跳過已存在項目）",
    )
    parser.add_argument(
        "--v2-candidate",
        action="store_true",
        default=False,
        help="平行生成 -v2 候選草稿列（不覆寫線上已核准之 V1 資產，供審核擇優後晉升）",
    )

    parser.add_argument(
        "--k",
        type=int,
        default=1,
        help="Harness² 任務級候選數（>1 時探索多個合法候選並選取最高臨床對齊分數）",
    )
    parser.add_argument(
        "--mode",
        choices=("sequential", "parallel"),
        default="sequential",
        help="候選遞迴模式：sequential 依批評逐輪精煉；parallel 各自獨立生成後評分",
    )

    args = parser.parse_args(argv)
    if args.k < 1:
        parser.error("--k 必須為正整數")
    target_path = Path(args.db)

    # 1. 正式庫安全檢核：寫入模式必須在連線前檢查
    if not args.dry_run:
        try:
            is_prod = target_path.resolve() == PROD_DB_PATH.resolve()
        except Exception:
            is_prod = str(target_path) == str(PROD_DB_PATH)

        if is_prod and not args.allow_prod_db:
            print(
                "❌ 【操作拒絕】目標為正式資料庫 clinic.db！\n"
                "執行生成寫入必須明確加上 --allow-prod-db 旗標。",
                file=sys.stderr,
            )
            return 2

    if not target_path.exists():
        print(f"❌ 錯誤：目標資料庫檔案不存在：{target_path}", file=sys.stderr)
        return 2

    # 2. 唯讀預覽模式
    if args.dry_run:
        try:
            conn = _open_ro(target_path)
        except Exception as e:
            print(f"❌ 錯誤：無法以唯讀模式開啟資料庫：{e}", file=sys.stderr)
            return 2

        try:
            trees = fetch_eligible_trees(conn, doc_id=args.doc_id, clinic_id=args.clinic_id)
            if not trees:
                if args.doc_id:
                    print(f"❌ 找不到符合資格或尚未核准之推理樹：doc_id='{args.doc_id}'", file=sys.stderr)
                    return 1
                print("（目前無符合資格之已核准推理樹）")
                return 0

            print(f"🔍 【預覽模式】共找到 {len(trees)} 筆符合資格之推理樹：")
            print("=" * 60)
            for idx, tree in enumerate(trees, 1):
                clinic_label = f"clinic_id={tree.get('clinic_id')}" if tree.get("clinic_id") else "一般醫學 (NULL)"
                print(f"[{idx}] doc_id: {tree['doc_id']} | 標題: {tree.get('title')} | 範圍: {clinic_label}")
                prompt = build_tree_visual_prompt(tree)
                print(f"--- 提示詞預覽（前 200 字）---\n{prompt[:200]}...\n")
            print("=" * 60)
            return 0
        finally:
            conn.close()

    # 3. 執行生成模式
    conn = sqlite3.connect(str(target_path))
    try:
        if not has_visual_assets_table(conn):
            print("❌ 目標資料庫尚未建立 visual_assets 資料表，請先執行遷移腳本。", file=sys.stderr)
            return 2

        trees = fetch_eligible_trees(conn, doc_id=args.doc_id, clinic_id=args.clinic_id)
        if not trees:
            if args.doc_id:
                print(f"❌ 找不到符合資格或尚未核准之推理樹：doc_id='{args.doc_id}'", file=sys.stderr)
                return 1
            print("（目前無符合資格之已核准推理樹）")
            return 0

        # 查詢已存在之視覺資產鍵值，預設跳過已存在項目
        cur = conn.cursor()
        cur.execute("SELECT topic_key FROM visual_assets")
        existing_keys = {row[0] for row in cur.fetchall()}

        suffix = "-v2" if args.v2_candidate else ""
        success_count = 0
        skipped_count = 0
        for tree in trees:
            doc_id = tree["doc_id"]
            try:
                norm_key = normalize_tree_topic_key(doc_id)
            except Exception:
                norm_key = f"tree-{doc_id}"

            target_key = f"{norm_key}{suffix}"
            alt_key = f"tree-{doc_id}{suffix}"

            if not args.force and (target_key in existing_keys or alt_key in existing_keys):
                print(f"⏭️ 跳過已存在之視覺資產：topic_key='{target_key}'（如欲覆寫請加上 --force）")
                skipped_count += 1
                continue

            print(f"⏳ 正在生成動畫草稿：doc_id='{doc_id}' -> topic_key='{target_key}' ...")
            res = autodraft_from_tree(
                conn, tree, db_path=target_path, topic_key_suffix=suffix,
                k_candidates=args.k, recursion_mode=args.mode,
            )
            if res.get("status") == "ok":
                print(f"✅ 成功生成並寫入草稿：topic_key='{res['topic_key']}'（狀態：{res['review_status']}）")
                success_count += 1
                existing_keys.add(res['topic_key'])
            else:
                print(f"❌ 生成失敗：doc_id='{doc_id}', 錯誤碼={res.get('code')}", file=sys.stderr)
                if args.doc_id:
                    return 1

        print(f"🎉 處理完成：本次新生成 {success_count} 筆、跳過已存在 {skipped_count} 筆（目標候選共 {len(trees)} 筆）。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
