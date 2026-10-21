#!/usr/bin/env python3
"""
凡登整形外科診所（3503264627）3 組代表性手術/醫美 3 幕動畫解說卡試行生成腳本。
目標：
1. 3503264627-swan-neck-cervicoplasty (天鵝頸闊頸肌縫合拉皮術)
2. 3503264627-mid-lower-smas-facelift (中下臉 SMAS 筋膜深層拉皮手術)
3. 3503264627-thermage-flx-rf (Thermage FLX 鳳凰電波單極緊膚療程)

結合本地 Qwen3.8-27B-FP8 與多型態解剖動畫模板，產出合規 3 幕 Typed IR 並寫入 visual_assets 表。
"""

from pathlib import Path
import sqlite3
import sys
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.visual.autodraft import autodraft_from_tree
from src.visual.ir import validate_ir

DB_PATH = PROJECT_ROOT / "clinic.db"
CLINIC_ID = "3503264627"

TARGET_DOC_IDS = [
    f"{CLINIC_ID}-swan-neck-cervicoplasty",
    f"{CLINIC_ID}-mid-lower-smas-facelift",
    f"{CLINIC_ID}-thermage-flx-rf",
]


def draft_top3():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "SELECT id, doc_id, clinic_id, title, procedure, pre_op, post_op_short, maintenance, summary_text "
        "FROM page_index_trees WHERE doc_id IN (?, ?, ?)",
        TARGET_DOC_IDS,
    )
    rows = cur.fetchall()
    col_names = [d[0] for d in cur.description]
    trees = [dict(zip(col_names, r)) for r in rows]

    print(f"找到 {len(trees)} 筆凡登代表性療程推理樹，準備呼叫本地 Qwen3.8-27B-FP8 生成 3 幕動畫草稿...")

    results = []
    for t in trees:
        doc_id = t["doc_id"]
        title = t["title"]
        print(f"\n▶ 正在生成: {title} ({doc_id}) ...")
        res = autodraft_from_tree(conn, t, commit=True)
        if res.get("status") == "ok":
            print(f"  ✅ 生成成功！topic_key={res.get('topic_key')}, title={res.get('ir', {}).get('title')}")
            results.append(res)
        else:
            print(f"  ❌ 生成失敗: {res}")

    # 驗證資料庫寫入現況
    cur.execute(
        "SELECT id, clinic_id, topic_key, title, review_status, content_version FROM visual_assets WHERE clinic_id = ?",
        (CLINIC_ID,),
    )
    saved = cur.fetchall()
    print(f"\n📊 凡登 visual_assets 資料庫現存記錄 ({len(saved)} 筆):")
    for row in saved:
        print(f"  - ID:{row[0]} | clinic:{row[1]} | {row[2]} | {row[3]} | 狀態:{row[4]} | 版號:{row[5]}")

    conn.close()


if __name__ == "__main__":
    draft_top3()
