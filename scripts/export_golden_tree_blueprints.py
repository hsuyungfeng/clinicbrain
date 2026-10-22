#!/usr/bin/env python3
"""Phase 34 Plan 01: 49 筆已核准診所推理樹 Scene 1 Blueprint 黃金檔匯出工具。

以唯讀模式（SQLite `file:...?mode=ro` URI）開啟資料庫，對所有
`page_index_trees` 中 `review_status='approved'` 且 `clinic_id IS NOT NULL`
之推理樹，套用 `src.visual.autodraft.infer_scene1_blueprint` 推斷 Scene 1
Blueprint，寫出排序的 JSON 黃金檔（`data/visual/golden/tree_blueprints_49.json`）。

設計守門（must-have）：
- 絕不呼叫本地 LLM（只執行純函式 `infer_scene1_blueprint`）。
- 絕不開啟可寫連線（一律 `mode=ro`，連上後再以 `PRAGMA query_only` 雙重確認）。
- 只記錄識別資訊與模板：`doc_id`、`clinic_id`、`title`、`blueprint`；
  不記錄完整 summary、四段臨床內容、醫師註記或其他可能含個資／價格的欄位。
- 任何例外（找不到表、推斷錯誤）一律以非零結束碼中止，不產生半截黃金檔。

用法：
    python3 scripts/export_golden_tree_blueprints.py --db clinic.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.visual.autodraft import infer_scene1_blueprint  # noqa: E402

DEFAULT_OUT = PROJECT_ROOT / "data" / "visual" / "golden" / "tree_blueprints_49.json"


def _open_readonly(db_path: Path) -> sqlite3.Connection:
    """以唯讀 URI 開啟資料庫，並附加 PRAGMA query_only 雙重防禦。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON;")
    return conn


def export_golden(db_path: Path, out_path: Path) -> dict:
    """匯出黃金檔，回傳摘要 dict（含筆數與模板分佈）。"""
    if not db_path.exists():
        raise FileNotFoundError(f"找不到資料庫：{db_path}")
    conn = _open_readonly(db_path)
    try:
        # 確認表存在且含必要欄位，避免半截輸出
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(page_index_trees)")}
        required = {"doc_id", "clinic_id", "title", "summary_text", "review_status"}
        missing = required - cols
        if missing:
            raise RuntimeError(f"page_index_trees 缺少欄位：{sorted(missing)}")

        rows = conn.execute(
            """
            SELECT doc_id, clinic_id, title, summary_text
            FROM page_index_trees
            WHERE review_status = 'approved' AND clinic_id IS NOT NULL
            ORDER BY doc_id
            """
        ).fetchall()
    finally:
        conn.close()

    entries = []
    from collections import Counter

    dist = Counter()
    for row in rows:
        tree = dict(row)
        blueprint, _reason = infer_scene1_blueprint(tree)
        dist[blueprint] += 1
        entries.append(
            {
                "doc_id": tree["doc_id"],
                "clinic_id": tree["clinic_id"],
                "title": tree["title"],
                "blueprint": blueprint,
            }
        )

    # 依 doc_id 排序（SQL 已排序，這裡再保證一次）
    entries.sort(key=lambda e: e["doc_id"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"count": len(entries), "distribution": dict(sorted(dist.items()))}


def main() -> int:
    parser = argparse.ArgumentParser(description="匯出 49 筆推理樹 Scene 1 Blueprint 黃金檔（唯讀）")
    parser.add_argument("--db", default=str(PROJECT_ROOT / "clinic.db"), help="資料庫路徑（預設 clinic.db，唯讀開啟）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="黃金檔輸出路徑")
    args = parser.parse_args()

    try:
        summary = export_golden(Path(args.db), Path(args.out))
    except Exception as exc:  # noqa: BLE001 - 頂層守門，不產生半截黃金檔
        print(f"黃金檔匯出失敗（中止，不寫出檔案）：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"已匯出 {summary['count']} 筆至 {args.out}")
    for bp, n in summary["distribution"].items():
        print(f"  {bp}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
