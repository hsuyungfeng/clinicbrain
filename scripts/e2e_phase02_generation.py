#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - Phase 02 端到端驗證腳本
依據 .planning/phases/02-local-llm-layer/TASK-PLAN.md TASK-04 規格：
1. 嚴格於暫存複本資料庫上執行，絕不碰觸正式 clinic.db
2. 呼叫 local_llm_call 生成 3 筆真實臨床推理樹（淨膚雷射、水飛梭、自體脂肪補臉）
3. 驗證 parse_and_validate 通過
4. 呼叫 db_writer.upsert_trees 寫入暫存資料庫複本
5. 驗證正式 clinic.db hash 完全無變化
"""

import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

# 專案路徑初始化
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.pageindex.llm_client import local_llm_call, check_llm_health
from src.pageindex.prompt_template import generate_tree, to_upsert_row, parse_and_validate
from src.pageindex.db_writer import upsert_trees

PROD_DB = PROJECT_ROOT / "clinic.db"


def get_file_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main():
    print("==================================================")
    print("Phase 02 本地 LLM 推理層端到端驗證 (TASK-04)")
    print("==================================================")

    # 1. 檢查正式資料庫存在並記錄 Hash
    if not PROD_DB.exists():
        print(f"錯誤：找不到正式資料庫 {PROD_DB}")
        sys.exit(1)
    
    hash_before = get_file_sha256(PROD_DB)
    print(f"正式 clinic.db SHA-256 (執行前): {hash_before}")

    # 2. 建立隔離資料庫複本
    temp_dir = Path(tempfile.mkdtemp(prefix="clinic_e2e_"))
    test_db = temp_dir / "clinic_isolated.db"
    shutil.copy2(PROD_DB, test_db)
    print(f"已建立獨立測試資料庫複本: {test_db}")

    # 3. 檢查本地 LLM 服務存活
    model_name = check_llm_health()
    print(f"本地 llama-server 正常運行，模型: {model_name}\n")

    # 4. 目標生成療程清單（完全避開既有 6 筆範本）
    targets = [
        {
            "doc_id": "zhiyan-clinic-toning-laser",
            "procedure_name": "淨膚雷射",
            "category": "special",
            "context": "常規醫美低能量淨膚雷射（1064nm銣雅鉻雷射），改善暗沉、膚色不均、細緻毛孔，非侵入性保養型療程。",
        },
        {
            "doc_id": "zhiyan-clinic-hydrafacial",
            "procedure_name": "水飛梭",
            "category": "special",
            "context": "非侵入性深層清潔與水潤導入療程（海菲秀/水飛梭），透過水渦流技術溫和清除老廢角質與粉刺，並注入玻尿酸及抗氧化精華保濕。",
        },
        {
            "doc_id": "zhiyan-clinic-autologous-fat-grafting",
            "procedure_name": "自體脂肪補臉",
            "category": "special",
            "context": "抽取腹部或大腿自體多餘脂肪，經離心純化後分層注射移植於臉頰、蘋果肌、太陽穴等凹陷處，改善面部輪廓立體度。",
        },
    ]

    conn = sqlite3.connect(str(test_db))
    generated_results = []

    for item in targets:
        doc_id = item["doc_id"]
        pname = item["procedure_name"]
        cat = item["category"]
        ctx = item["context"]

        print(f"--------------------------------------------------")
        print(f"正在生成: 【{pname}】 (doc_id: {doc_id})...")
        t0 = time.time()
        try:
            tree = generate_tree(pname, local_llm_call, reference_context=ctx)
            cost = time.time() - t0
            print(f"生成成功！耗時 {cost:.2f} 秒，驗證通過！")
            if tree.warnings:
                print(f"警告注意: {tree.warnings}")

            row = to_upsert_row(doc_id, cat, tree)
            upsert_trees(conn, [row], source_type="llm_generated")
            print(f"已成功寫入測試複本資料庫！")

            generated_results.append({
                "doc_id": doc_id,
                "procedure_name": pname,
                "generation_time_sec": round(cost, 2),
                "tree": {
                    "pre_op": tree.pre_op,
                    "procedure": tree.procedure,
                    "post_op_short": tree.post_op_short,
                    "maintenance": tree.maintenance,
                    "summary_text": tree.summary_text,
                    "warnings": tree.warnings,
                }
            })
        except Exception as e:
            print(f"生成或驗證失敗: {e}")
            raise

    # 5. 驗證資料庫寫入結果
    cursor = conn.cursor()
    cursor.execute(
        "SELECT doc_id, source_type, content_version, summary_text FROM page_index_trees WHERE source_type = 'llm_generated'"
    )
    rows = cursor.fetchall()
    print("\n==================================================")
    print(f"測試資料庫複本驗證：共檢索到 {len(rows)} 筆 llm_generated 樹：")
    for r in rows:
        print(f"- {r[0]} | source: {r[1]} | version: {r[2]} | summary: {r[3][:35]}...")
    conn.close()

    # 6. 正式資料庫 Hash 安全檢核
    hash_after = get_file_sha256(PROD_DB)
    print("\n==================================================")
    print(f"正式 clinic.db SHA-256 (執行前): {hash_before}")
    print(f"正式 clinic.db SHA-256 (執行後): {hash_after}")
    assert hash_before == hash_after, "致命錯誤：正式 clinic.db 被修改！"
    print("安全驗證通過：正式資料庫零修改、零污染！")

    # 7. 輸出結果存檔供交付報告引用
    output_json_path = PROJECT_ROOT / "scripts" / "phase02_generated_trees.json"
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(generated_results, f, ensure_ascii=False, indent=2)
    print(f"生成樹已儲存至: {output_json_path}")


if __name__ == "__main__":
    main()
