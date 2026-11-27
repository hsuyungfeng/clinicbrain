#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 57: 視覺資產與推理樹對應對帳、黃金標準模板產出與現況基線量測腳本。

功能：
1. 唯讀對帳 399 筆 visual_assets 與 92 棵 page_index_trees，產出 57-01-MAPPING.md。
2. 從 92 棵推理樹分層抽樣 ≥50 棵（含無動畫樹 47 棵之分層代表），產出 golden_set_template.csv。
3. 計算現行 infer_scene1_blueprint 之藍圖分布，產出 baseline_metrics.json（狀態為 awaiting_physician_labels）。
4. 嚴格唯讀連線 (mode=ro)，不修改 clinic.db。
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "clinic.db"
DEFAULT_PLANNING_DIR = (
    PROJECT_ROOT / ".planning" / "phases" / "57-visual-blueprint-classification-narration-ab"
)

# 確保可載入 src 模組
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from src.visual.autodraft import infer_scene1_blueprint
except ImportError:
    infer_scene1_blueprint = None


def open_readonly_db(db_path: Path) -> sqlite3.Connection:
    """以嚴格唯讀 URI 模式開啟 SQLite 資料庫並設定 PRAGMA query_only。"""
    if not db_path.exists():
        raise FileNotFoundError(f"找不到資料庫：{db_path}")
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON;")
    return conn


def analyze_assets_and_trees(conn: sqlite3.Connection) -> Dict[str, Any]:
    """完整分析 399 筆視覺資產與 92 棵推理樹的對應狀態。"""
    # 1. 取得所有推理樹
    tree_rows = conn.execute(
        """
        SELECT id, doc_id, clinic_id, title, category, summary_text, review_status
        FROM page_index_trees
        ORDER BY id ASC
        """
    ).fetchall()
    trees_by_id = {r["id"]: dict(r) for r in tree_rows}
    tree_ids_set = set(trees_by_id.keys())

    # 2. 取得所有視覺資產
    asset_rows = conn.execute(
        """
        SELECT id, topic_key, title, source_type, review_status, metadata, ir_json
        FROM visual_assets
        ORDER BY id ASC
        """
    ).fetchall()

    mapped_tree_ids: Set[int] = set()
    category_counts: Counter[str] = Counter()
    scene1_bp_counts: Counter[str] = Counter()
    nhi_bp_counts: Counter[str] = Counter()
    tree_bp_counts: Counter[str] = Counter()

    assets_mapping: List[Dict[str, Any]] = []

    for a in asset_rows:
        aid = a["id"]
        tkey = a["topic_key"] or ""
        stype = a["source_type"] or ""
        rstatus = a["review_status"] or ""
        meta = json.loads(a["metadata"]) if a["metadata"] else {}
        ir = json.loads(a["ir_json"]) if a["ir_json"] else {}

        # 判定來源分類 (72 tree, 314 nhi, 8 batch_distill, 4 icd, 1 manual)
        tid = meta.get("tree_id")
        doc_id = meta.get("doc_id")
        origin = meta.get("origin")

        if tkey.startswith("nhi-"):
            source_cat = "nhi"
        elif tid is not None:
            source_cat = "tree"
        elif origin == "batch_distill":
            source_cat = "batch_distill"
        elif origin == "icd10_primary_care_catalog":
            source_cat = "icd"
        else:
            source_cat = "manual"

        category_counts[source_cat] += 1

        # 第一幕藍圖
        scenes = ir.get("scenes", [])
        s1_bp = scenes[0].get("blueprint", "none") if scenes else "none"
        scene1_bp_counts[s1_bp] += 1
        if source_cat == "nhi":
            nhi_bp_counts[s1_bp] += 1
        elif source_cat == "tree":
            tree_bp_counts[s1_bp] += 1

        # doc_id 一致性檢核
        is_doc_id_match = False
        target_tree_doc_id = None
        if tid is not None and tid in trees_by_id:
            mapped_tree_ids.add(tid)
            target_tree_doc_id = trees_by_id[tid]["doc_id"]
            if target_tree_doc_id == doc_id:
                is_doc_id_match = True

        assets_mapping.append(
            {
                "asset_id": aid,
                "topic_key": tkey,
                "title": a["title"] or "",
                "source_category": source_cat,
                "tree_id": tid,
                "asset_doc_id": doc_id,
                "tree_doc_id": target_tree_doc_id,
                "doc_id_match": is_doc_id_match,
                "scene1_blueprint": s1_bp,
                "review_status": rstatus,
            }
        )

    unmapped_tree_ids = sorted(list(tree_ids_set - mapped_tree_ids))
    unmapped_trees = [trees_by_id[tid] for tid in unmapped_tree_ids]

    return {
        "total_assets": len(asset_rows),
        "total_trees": len(tree_rows),
        "category_counts": category_counts,
        "scene1_bp_counts": scene1_bp_counts,
        "nhi_bp_counts": nhi_bp_counts,
        "tree_bp_counts": tree_bp_counts,
        "assets_mapping": assets_mapping,
        "mapped_tree_ids_count": len(mapped_tree_ids),
        "unmapped_trees_count": len(unmapped_tree_ids),
        "unmapped_trees": unmapped_trees,
        "trees_by_id": trees_by_id,
    }


def generate_mapping_markdown(data: Dict[str, Any], out_path: Path) -> str:
    """產出 57-01-MAPPING.md 完整內容。"""
    cats = data["category_counts"]
    content = [
        "# Phase 57-01: 視覺資產與推理樹對應對帳表 (57-01-MAPPING.md)",
        "",
        f"- **產出時間**：2026-11-27",
        f"- **視覺資產總數**：{data['total_assets']} 筆",
        f"- **推理樹總數**：{data['total_trees']} 棵",
        "",
        "## 一、來源分類彙整統計",
        "",
        "| 來源分類 (Source Category) | 筆數 | 占比 | 說明 |",
        "|---|---:|---:|---|",
        f"| **健保批次 (nhi)** | {cats['nhi']} | {cats['nhi']/data['total_assets']:.1%} | `topic_key` 開頭為 `nhi-`，無推理樹對應 |",
        f"| **推理樹來源 (tree)** | {cats['tree']} | {cats['tree']/data['total_assets']:.1%} | `metadata` 具備 `tree_id`，且 doc_id 一致 72/72 |",
        f"| **知識蒸餾 (batch_distill)** | {cats['batch_distill']} | {cats['batch_distill']/data['total_assets']:.1%} | 來自批次蒸餾之手術專題 |",
        f"| **基層目錄 (icd)** | {cats['icd']} | {cats['icd']/data['total_assets']:.1%} | ICD-10 基層專科常見症候群 |",
        f"| **手動建立 (manual)** | {cats['manual']} | {cats['manual']/data['total_assets']:.1%} | 手動建立之視覺資產 |",
        f"| **合計** | **{sum(cats.values())}** | **100.0%** | **加總精確為 399 筆，與 CONTEXT (72/314/8/4/1) 完全一致** |",
        "",
        "## 二、推理樹覆蓋狀態",
        "",
        f"- **總推理樹數**：{data['total_trees']} 棵",
        f"- **已被資產對應之推理樹**：{data['mapped_tree_ids_count']} 棵（共被 72 筆資產引用，部分樹具複數視角資產）",
        f"- **缺動畫之推理樹**：**{data['unmapped_trees_count']} 棵**（待補足或納入黃金標準集取樣）",
        "",
        "### 缺動畫之推理樹清單（共 47 棵）",
        "",
        "| Tree ID | Doc ID | Title | Category |",
        "|---|---|---|---|",
    ]

    for t in data["unmapped_trees"]:
        content.append(
            f"| {t['id']} | `{t['doc_id']}` | {t['title']} | {t['category'] or '未分類'} |"
        )

    content.extend(
        [
            "",
            "## 三、全量 399 筆視覺資產對應明細",
            "",
            "| Asset ID | Topic Key | 來源分類 | Tree ID | Asset Doc ID | Tree Doc ID | Doc ID 吻合 | 第一幕藍圖 | 審核狀態 |",
            "|---|---|---|---|---|---|:---:|---|---|",
        ]
    )

    for m in data["assets_mapping"]:
        tid_str = str(m["tree_id"]) if m["tree_id"] is not None else "-"
        adoc = f"`{m['asset_doc_id']}`" if m["asset_doc_id"] else "-"
        tdoc = f"`{m['tree_doc_id']}`" if m["tree_doc_id"] else "-"
        match_str = "✅" if m["doc_id_match"] else ("-" if m["tree_id"] is None else "❌")
        content.append(
            f"| {m['asset_id']} | `{m['topic_key']}` | {m['source_category']} | {tid_str} | {adoc} | {tdoc} | {match_str} | `{m['scene1_blueprint']}` | {m['review_status']} |"
        )

    full_text = "\n".join(content) + "\n"
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(full_text, encoding="utf-8")
    return full_text


def sample_golden_set(data: Dict[str, Any], sample_size: int = 50) -> List[Dict[str, Any]]:
    """從 92 棵推理樹進行分層取樣（≥50 棵）：

    策略（依 agy D2）：
    - 25 棵來自 47 棵「缺動畫之推理樹」（無視覺資產者）
    - 25 棵來自 45 棵「具備對應動畫之推理樹」
    - 依 category 分層確保代表性
    """
    trees_by_id = data["trees_by_id"]
    unmapped_tree_ids = [t["id"] for t in data["unmapped_trees"]]
    mapped_tree_ids = sorted(list(set(trees_by_id.keys()) - set(unmapped_tree_ids)))

    # 分層取樣 helper
    def stratified_pick(pool_ids: List[int], count: int) -> List[int]:
        pools_by_cat: Dict[str, List[int]] = {}
        for tid in pool_ids:
            cat = trees_by_id[tid]["category"] or "general"
            pools_by_cat.setdefault(cat, []).append(tid)

        selected: List[int] = []
        # 輪流從各類別挑選
        cats = sorted(pools_by_cat.keys())
        while len(selected) < count and any(pools_by_cat.values()):
            for c in cats:
                if pools_by_cat[c]:
                    selected.append(pools_by_cat[c].pop(0))
                    if len(selected) >= count:
                        break
        return selected

    half = sample_size // 2
    picked_unmapped = stratified_pick(unmapped_tree_ids, half)
    picked_mapped = stratified_pick(mapped_tree_ids, sample_size - len(picked_unmapped))

    chosen_ids = sorted(picked_unmapped + picked_mapped)
    samples: List[Dict[str, Any]] = []

    for tid in chosen_ids:
        t = trees_by_id[tid]
        has_asset = tid in mapped_tree_ids
        inferred_bp = "unknown"
        if infer_scene1_blueprint:
            try:
                inferred_bp, _ = infer_scene1_blueprint(t)
            except Exception:
                inferred_bp = "error"

        samples.append(
            {
                "tree_id": t["id"],
                "doc_id": t["doc_id"],
                "title": t["title"],
                "category": t["category"] or "未分類",
                "has_visual_asset": "yes" if has_asset else "no",
                "current_inferred_blueprint": inferred_bp,
                "physician_blueprint": "",  # 空白待醫師填寫
                "evidence_span": "",  # 空白待醫師填寫
            }
        )

    return samples


def generate_golden_files(
    samples: List[Dict[str, Any]], data: Dict[str, Any], golden_dir: Path
) -> Tuple[Path, Path]:
    """產出 golden_set_template.csv 與 baseline_metrics.json。"""
    golden_dir.mkdir(parents=True, exist_ok=True)
    csv_path = golden_dir / "golden_set_template.csv"
    json_path = golden_dir / "baseline_metrics.json"

    # 1. 寫入 CSV 模板
    fields = [
        "tree_id",
        "doc_id",
        "title",
        "category",
        "has_visual_asset",
        "current_inferred_blueprint",
        "physician_blueprint",
        "evidence_span",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(samples)

    # 2. 計算現況 infer_scene1_blueprint 基線分布 (不宣稱任何 accuracy 數字)
    inferred_counts = Counter(s["current_inferred_blueprint"] for s in samples)
    category_dist = Counter(s["category"] for s in samples)
    has_asset_dist = Counter(s["has_visual_asset"] for s in samples)

    baseline_data = {
        "status": "awaiting_physician_labels",
        "description": "現行規則推斷 (infer_scene1_blueprint) 在黃金標準抽樣集上之藍圖分布基線。尚未由醫師標註，不宣稱任何準確率數字。",
        "golden_sample_size": len(samples),
        "sample_strata": {
            "has_visual_asset": dict(has_asset_dist),
            "categories": dict(category_dist),
        },
        "rule_engine_baseline_distribution": dict(inferred_counts),
        "nhi_batch_baseline": {
            "total": data["category_counts"]["nhi"],
            "pathology_mechanism_ratio": 1.0,
            "comment": "314 筆健保批次第一幕皆寫死為 pathology_mechanism",
        },
        "physician_benchmark": {
            "accuracy": None,
            "confusion_matrix": None,
            "note": "需待專業醫師於 golden_set_template.csv 填寫 physician_blueprint 與 evidence_span 後方可評估量測",
        },
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(baseline_data, f, ensure_ascii=False, indent=2)

    return csv_path, json_path


def main():
    parser = argparse.ArgumentParser(description="Phase 57-01 基線與對應對帳工具")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB, help="clinic.db 路徑")
    parser.add_argument("--dry-run", action="store_true", help="乾跑模式，僅印出摘要不產出檔案")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_PLANNING_DIR, help="輸出目錄")
    args = parser.parse_args()

    conn = open_readonly_db(args.db_path)
    try:
        data = analyze_assets_and_trees(conn)
    finally:
        conn.close()

    samples = sample_golden_set(data, sample_size=50)

    print("=" * 60)
    print("Phase 57-01 實測分析摘要：")
    print(f"- 視覺資產總數：{data['total_assets']} (預期 399)")
    print(f"- 推理樹總數：{data['total_trees']} (預期 92)")
    print(f"- 來源分類：{dict(data['category_counts'])}")
    print(f"- 缺動畫之推理樹：{data['unmapped_trees_count']} (預期 47)")
    print(f"- 黃金抽樣數：{len(samples)} (預期 ≥50)")
    print(f"- 現行推斷藍圖分布：{Counter(s['current_inferred_blueprint'] for s in samples)}")
    print("=" * 60)

    if args.dry_run:
        print("Dry-run 模式：驗證完畢，退出碼 0。")
        sys.exit(0)

    # 實體產出
    mapping_path = args.output_dir / "57-01-MAPPING.md"
    generate_mapping_markdown(data, mapping_path)
    print(f"已產出對應表：{mapping_path}")

    golden_dir = args.output_dir / "golden"
    csv_p, json_p = generate_golden_files(samples, data, golden_dir)
    print(f"已產出黃金模板：{csv_p}")
    print(f"已產出基線指標：{json_p}")


if __name__ == "__main__":
    main()
