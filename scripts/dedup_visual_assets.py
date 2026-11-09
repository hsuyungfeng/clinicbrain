#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - 醫學視覺動畫去重與舊版清理腳本
清理 visual_assets 中重複同一主體之歷史舊版/冗餘資產，確保每項醫學主題僅保留唯一最新、最高品質之權威資產。
"""

import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "clinic.db"


def get_disease_code(tkey: str) -> str | None:
    """抽取標準化疾病代碼（去除連字號與前綴）。"""
    m_nhi = re.match(r"^nhi-[a-z]\d+-([a-z0-9\-]+)$", tkey)
    if m_nhi:
        return m_nhi.group(1).replace("-", "").lower()
    m_icd = re.match(r"^icd-([a-z0-9\-]+?)-", tkey)
    if m_icd:
        return m_icd.group(1).replace("-", "").lower()
    m_tree_icd = re.match(r"^tree-icd-([a-z0-9\-]+?)-", tkey)
    if m_tree_icd:
        return m_tree_icd.group(1).replace("-", "").lower()
    return None


def get_canonical_subject(tkey: str, title: str) -> str:
    """計算規範化主體識別碼。"""
    # 1. 若屬健保/ICD疾病代碼，以標準化代碼為準
    code = get_disease_code(tkey)
    if code:
        return f"ICD_{code}"

    # 2. 針對個別已知特殊對應（例如舊版未含標準代碼之 ICD 草稿）
    if "peptic-ulcer" in tkey or "消化性潰瘍" in title:
        return "SPECIAL_peptic_ulcer"
    if "eczema" in tkey or "濕疹" in title:
        return "SPECIAL_eczema"
    if "urticaria" in tkey or "蕁麻疹" in title:
        return "SPECIAL_urticaria"
    if "low-back-pain" in tkey or "下背痛" in title:
        return "SPECIAL_low_back_pain"

    # 3. 療程類主題
    clean_k = re.sub(r"^(tree-|clinic-)", "", tkey).strip()
    return f"PROCEDURE_{clean_k}"


def analyze_and_dedup(db_path: Path = DB_PATH, dry_run: bool = False):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, clinic_id, topic_key, title, content_version, updated_at, created_at, ir_json
        FROM visual_assets
        WHERE review_status = 'approved'
        ORDER BY id ASC
        """
    )
    rows = cur.fetchall()

    groups = defaultdict(list)
    for r in rows:
        rid, cid, tkey, title, ver, up_at, cr_at, ir_str = r
        subj = get_canonical_subject(tkey, title)
        ir = json.loads(ir_str)
        durations = [s.get("duration_sec", 0) for s in ir.get("scenes", [])]
        is_24s = (durations == [8, 8, 8])
        is_not_icd = not (tkey.startswith("icd-") or tkey.startswith("tree-icd-"))

        groups[subj].append({
            "id": rid,
            "clinic_id": cid,
            "topic_key": tkey,
            "title": title,
            "version": ver or 1,
            "updated_at": up_at or "",
            "created_at": cr_at or "",
            "durations": durations,
            "is_24s": is_24s,
            "is_not_icd": is_not_icd,
            "is_general": (cid is None),
        })

    report = []
    to_delete_ids = []
    to_keep_ids = []

    for subj, items in groups.items():
        if len(items) == 1:
            to_keep_ids.append(items[0]["id"])
            continue

        # 排序權重：
        # 1. 嚴格 24 秒循環
        # 2. 非舊版 ICD 草稿（新版 NHI 優先）
        # 3. 通用昇華版優先（None 優先，確保全域各端點及匿名諮詢皆可檢索）
        # 4. 版號高者優先
        # 5. 更新時間新者優先
        # 6. 建立時間新者優先
        # 7. ID 流水號新者優先
        sorted_items = sorted(
            items,
            key=lambda x: (
                1 if x["is_24s"] else 0,
                1 if x["is_not_icd"] else 0,
                1 if x["is_general"] else 0,
                x["version"],
                x["updated_at"],
                x["created_at"],
                x["id"],
            ),
            reverse=True,
        )
        keeper = sorted_items[0]
        to_keep_ids.append(keeper["id"])

        del_list = []
        for older in sorted_items[1:]:
            to_delete_ids.append(older["id"])
            del_list.append(older)

        report.append({
            "subject": subj,
            "keeper": keeper,
            "deleted": del_list,
        })

    print(f"=== 分析結果 ===")
    print(f"原始 approved 總數: {len(rows)}")
    print(f"唯一主題數: {len(groups)}")
    print(f"重複主體組數: {len(report)}")
    print(f"保留最新版本數: {len(to_keep_ids)}")
    print(f"清理舊版/冗餘數: {len(to_delete_ids)}")

    if not dry_run and to_delete_ids:
        # 執行批次刪除
        placeholders = ",".join("?" * len(to_delete_ids))
        cur.execute(f"DELETE FROM visual_assets WHERE id IN ({placeholders})", to_delete_ids)
        conn.commit()
        print(f"✅ 成功自資料庫刪除 {len(to_delete_ids)} 筆舊版資產！")

    conn.close()
    return report, to_keep_ids, to_delete_ids


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    analyze_and_dedup(dry_run=dry)
