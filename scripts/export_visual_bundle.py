#!/usr/bin/env python3
"""
視覺解說卡 bundle 匯出工具（Phase 30 P30-BUNDLE）。
自 visual_assets 匯出與公開 find_visual 同形之 JSON bundle，提供通用播放器與影片匯出使用。

安全規範：
- 全程以唯讀連線（mode=ro）開啟資料庫，絕無任何寫入操作。
- 預設僅匯出 approved 狀態資產；--allow-pending 僅限非正式庫路徑。
- 專案正式庫 clinic.db 嚴格禁止 --allow-pending（連線前以結束碼 2 拒絕）。
- 匯出前強制重新執行 validate_ir，遭竄改或不合格者拒絕匯出（結束碼 1）。
- params 由 blueprints.merge_defaults 補齊預設值，duration_sec 缺省時補齊模板預設。
- 輸出不含資料庫 id、review_status、metadata、keywords 等內部與審核欄位。
- 檔案已存在時預設不覆蓋（結束碼 1），需明確使用 --force。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.visual.blueprints import BLUEPRINTS, merge_defaults
from src.visual.ir import validate_ir
from src.visual.writer import has_visual_assets_table

PROD_DB_PATH = PROJECT_ROOT / "clinic.db"

DEFAULT_DURATIONS = {
    "process_diagram": 8,
    "contrast": 9,
    "timeline": 7,
}


def _open_ro(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)


def export_bundle(
    db_path: Path,
    topic_key: str,
    out_path: Path,
    allow_pending: bool = False,
    force: bool = False,
    clinic_id: Optional[str] = None,
) -> int:
    resolved_db = db_path.resolve()

    # 安全邊界：正式庫絕不允許匯出 pending 資產
    if allow_pending and resolved_db == PROD_DB_PATH.resolve():
        print("錯誤：專案正式資料庫 clinic.db 禁止使用 --allow-pending 匯出未核准資產", file=sys.stderr)
        return 2

    # 防意外覆寫檢查
    if out_path.exists() and not force:
        print(f"錯誤：輸出檔案已存在: {out_path}，請使用 --force 允許覆寫", file=sys.stderr)
        return 1

    if not db_path.exists():
        print(f"錯誤：找不到資料庫檔案: {db_path}", file=sys.stderr)
        return 2

    try:
        conn = _open_ro(db_path)
    except Exception as e:
        print(f"錯誤：無法以唯讀模式開啟資料庫: {e}", file=sys.stderr)
        return 2

    try:
        if not has_visual_assets_table(conn):
            print("錯誤：資料庫尚未建立 visual_assets 資料表，請先執行遷移腳本", file=sys.stderr)
            return 2

        allowed_statuses = ("approved", "pending") if allow_pending else ("approved",)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(visual_assets)")
        has_clinic_col = "clinic_id" in [r[1] for r in cur.fetchall()]

        if has_clinic_col:
            cur.execute(
                "SELECT topic_key, title, ir_json, review_status FROM visual_assets WHERE clinic_id IS ? AND topic_key = ?",
                (clinic_id, topic_key),
            )
        else:
            cur.execute(
                "SELECT topic_key, title, ir_json, review_status FROM visual_assets WHERE topic_key = ?",
                (topic_key,),
            )
        row = cur.fetchone()
        if not row:
            print(f"錯誤：找不到主題: '{topic_key}'", file=sys.stderr)
            return 1

        db_topic, db_title, ir_json_str, review_status = row
        if review_status not in allowed_statuses:
            print(
                f"錯誤：主題 '{topic_key}' 審核狀態為 '{review_status}'，不在允許匯出範圍 {allowed_statuses} 內",
                file=sys.stderr,
            )
            return 1

        try:
            ir_data = json.loads(ir_json_str)
        except Exception as e:
            print(f"錯誤：ir_json 解析失敗: {e}", file=sys.stderr)
            return 1

        # 匯出前強制執行 validate_ir
        ok, err_code = validate_ir(ir_data)
        if not ok:
            print(f"錯誤：主題 '{topic_key}' 之 IR 內容驗證失敗，代碼: {err_code}", file=sys.stderr)
            return 1

        # 整形公開 bundle
        raw_scenes = ir_data.get("scenes", [])
        shaped_scenes = []

        for sc in raw_scenes:
            bp = str(sc.get("blueprint", ""))
            raw_params = sc.get("params")

            # 補齊預設 params
            if bp in BLUEPRINTS:
                full_params = merge_defaults(bp, raw_params)
            else:
                full_params = raw_params or {}

            # 補齊時長
            dur = sc.get("duration_sec")
            if dur is None or not isinstance(dur, int) or isinstance(dur, bool) or not (4 <= dur <= 12):
                dur = DEFAULT_DURATIONS.get(bp, 8)

            raw_labels = sc.get("labels", [])
            shaped_labels = [
                {
                    "text": str(lb.get("text", "")),
                    "tone": str(lb.get("tone", "neutral")),
                }
                for lb in raw_labels
                if isinstance(lb, dict)
            ]

            shaped_scenes.append({
                "blueprint": bp,
                "title": str(sc.get("title", "")),
                "caption": str(sc.get("caption", "")),
                "labels": shaped_labels,
                "params": full_params,
                "duration_sec": dur,
            })

        bundle_data = {
            "topic_key": str(ir_data.get("topic_key", topic_key)),
            "title": str(ir_data.get("title", db_title)),
            "scenes": shaped_scenes,
        }

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(bundle_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 0
    finally:
        conn.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="從 visual_assets 匯出公開視覺解說卡 bundle JSON",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=PROD_DB_PATH,
        help="SQLite 資料庫路徑",
    )
    parser.add_argument(
        "--topic",
        type=str,
        required=True,
        help="欲匯出之主題代碼 (topic_key)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="輸出 JSON 檔案路徑",
    )
    parser.add_argument(
        "--allow-pending",
        action="store_true",
        default=False,
        help="允許匯出 pending 狀態資產（僅限非正式庫路徑）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="若輸出檔案已存在則強制覆寫",
    )
    parser.add_argument(
        "--clinic-id",
        type=str,
        default=None,
        help="診所代碼（選填，預設 None 匯出一般醫學資產）",
    )

    args = parser.parse_args(argv)
    return export_bundle(
        db_path=args.db,
        topic_key=args.topic,
        out_path=args.out,
        allow_pending=args.allow_pending,
        force=args.force,
        clinic_id=args.clinic_id,
    )


if __name__ == "__main__":
    sys.exit(main())
