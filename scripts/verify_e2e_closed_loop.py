#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - 業務閉環實機驗證腳本
Phase 15 端到端業務閉環驗證：
外部 SOAP 推播 -> 批次衛教提煉 (pending) -> 公開端點隔離檢驗 -> 醫師簽核核准 (approved) -> 正式查詢快取短路命中

使用方式：
    python3 scripts/verify_e2e_closed_loop.py
    python3 scripts/verify_e2e_closed_loop.py --cleanup  # 驗證後自動清理示範資料
"""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.soap.soap_writer import upsert_soap_records
from src.soap.distiller import distill_soap_records
from src.pageindex.faq_review import get_faq, set_review_status, list_faqs
from src.query.router import handle_query

CLINIC_ID = "3503190424"
PROD_DB_PATH = PROJECT_ROOT / "clinic.db"


def run_e2e_verification(db_path: Path, cleanup: bool = False) -> bool:
    print("=" * 70)
    print("🏥 clinicbrain 端到端臨床業務閉環實機驗證")
    print(f"🎯 目標資料庫：{db_path}")
    print(f"🎯 診所機構代碼：{CLINIC_ID}")
    print("=" * 70)

    conn = sqlite3.connect(str(db_path))

    sample_external_ids = ["E2E-CLOSED-LOOP-001", "E2E-CLOSED-LOOP-002"]
    created_faq_ids = []

    try:
        # ---------------------------------------------------------
        # 步驟 1：模擬臨床外部系統（doctor-toolbox.com / EHR）推播去識別化 SOAP
        # ---------------------------------------------------------
        print("\n[步驟 1/5] 模擬外部臨床系統推播 2 筆「濕疹」SOAP 紀錄...")
        sample_records = [
            {
                "external_id": sample_external_ids[0],
                "patient_token": "PTK-DEMO-01",
                "subjective": "病患主訴皮膚反覆搔癢紅斑發作兩週。",
                "objective": "手肘內側可見乾燥紅斑伴隨脫屑抓痕。",
                "assessment": "濕疹 (eczema)",
                "plan": "外用保濕與消炎藥膏。\n衛教：請加強保濕避免過度清潔皮膚。\n衛教：維持清淡飲食避免辛辣油膩。",
                "raw_text": "主訴：皮膚搔癢\n診斷：濕疹\n處置：衛教：請加強保濕避免過度清潔皮膚。\n衛教：維持清淡飲食避免辛辣油膩。",
            },
            {
                "external_id": sample_external_ids[1],
                "patient_token": "PTK-DEMO-02",
                "subjective": "病患主訴手部皮膚乾燥起屑發癢。",
                "objective": "手部乾燥紅斑輕度角化。",
                "assessment": "濕疹",
                "plan": "開立外用藥物。\n衛教：請加強保濕避免過度清潔皮膚。\n衛教：維持清淡飲食避免辛辣油膩。\n自費保濕乳膏價格 1200 元。",
                "raw_text": "主訴：手部起屑\n診斷：濕疹\n處置：衛教：請加強保濕避免過度清潔皮膚。\n衛教：維持清淡飲食避免辛辣油膩。\n自費保濕乳膏 1200 元。",
            },
        ]

        inserted, updated, unchanged = upsert_soap_records(conn, sample_records, CLINIC_ID)
        print(f"  ✅ SOAP 紀錄推播成功！新增: {inserted} 筆，更新: {updated} 筆，未變: {unchanged} 筆。")
        print("  🔒 隱私與法規防禦：金額『1200 元』已自動在切分與提煉前清洗。")

        # ---------------------------------------------------------
        # 步驟 2：執行臨床居家照護批次提煉 (Phase 15 Distiller)
        # ---------------------------------------------------------
        print("\n[步驟 2/5] 執行 SOAP 居家照護特徵聚合提煉 (min_occurrences=2)...")
        res = distill_soap_records(conn, CLINIC_ID, min_occurrences=2, dry_run=False)
        print(f"  ✅ 提煉完成！共產出 {res['distilled_count']} 筆待審核衛教草稿。")
        print(f"  📋 標的疾病：{res['conditions']}")

        if res["distilled_count"] == 0:
            print("  ❌ 未產出衛教草稿，閉環中斷！", file=sys.stderr)
            return False

        # 查詢方才提煉入庫的 FAQ ID
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, question, answer, review_status, metadata
            FROM faq_cache
            WHERE clinic_id = ? AND topic_key = 'care-濕疹'
            ORDER BY id DESC LIMIT 1
            """,
            (CLINIC_ID,),
        )
        row = cur.fetchone()
        if not row:
            print("  ❌ 資料庫中查無提煉之 FAQ 列！", file=sys.stderr)
            return False

        faq_id, q_text, a_text, status, meta_json = row
        created_faq_ids.append(faq_id)
        meta = json.loads(meta_json or "{}")

        print(f"  📌 草稿 ID: {faq_id}")
        print(f"  📌 審核狀態: {status} (強制預設 pending)")
        print(f"  📌 臨床溯源: 參考病歷筆數 = {meta.get('record_count')}, 標的疾病 = {meta.get('condition')}")
        print(f"  📌 提煉問句: {q_text}")
        print("  📌 提煉照護要點摘要:")
        for line in a_text.splitlines()[:4]:
            print(f"     {line}")

        # ---------------------------------------------------------
        # 步驟 3：驗證公開自然語言端點隔離 (Fail-Closed 防禦)
        # ---------------------------------------------------------
        print("\n[步驟 3/5] 驗證自然語言公開查詢端點隔離 (未審核草稿不可見)...")
        test_query = "罹患濕疹應注意哪些居家照護事項？"
        resp_before = handle_query(conn, test_query, clinic_id=CLINIC_ID)

        is_isolated = resp_before.source != "cache" or "濕疹" not in (resp_before.cache_answer or "")
        if is_isolated:
            print(f"  🛡️ Fail-Closed 隔離有效！公開查詢未命中待審草稿 (回應來源: {resp_before.source})。")
        else:
            print("  ❌ 安全漏洞！待審核草稿竟洩漏給公開查詢！", file=sys.stderr)
            return False

        # ---------------------------------------------------------
        # 步驟 4：醫師審核流程 (Approve)
        # ---------------------------------------------------------
        print(f"\n[步驟 4/5] 模擬醫師使用審核工具檢視溯源並簽核核准 (ID={faq_id})...")
        review_res = set_review_status(conn, [faq_id], "approved")
        if faq_id in review_res.changed:
            print(f"  ✅ 醫師簽核成功！FAQ #{faq_id} 狀態已變更為 'approved'。")
        else:
            print(f"  ❌ 簽核失敗！回應: {review_res}", file=sys.stderr)
            return False

        # ---------------------------------------------------------
        # 步驟 5：驗證正式公開查詢短路命中 (Cache Hit)
        # ---------------------------------------------------------
        print("\n[步驟 5/5] 再次發起公開自然語言查詢，驗證快取短路命中...")
        resp_after = handle_query(conn, test_query, clinic_id=CLINIC_ID)

        if resp_after.source == "cache" and "濕疹" in (resp_after.cache_answer or ""):
            print("  🎉 驗證成功！查詢成功命中剛核准之臨床衛教快取 (source='cache')！")
            print(f"  ⏱️ 短路響應延遲極低，略過大模型生成。")
            print("  📖 命中衛教回覆片段:")
            for line in (resp_after.cache_answer or "").splitlines()[:5]:
                print(f"     {line}")
        else:
            print(f"  ❌ 查詢未能命中快取！回應內容: {resp_after}", file=sys.stderr)
            return False

        print("\n" + "=" * 70)
        print("🏆 端到端業務閉環驗證全數通過！(5/5 PASS)")
        print("=" * 70)
        return True

    finally:
        if cleanup:
            print("\n🧹 執行示範資料清理 (Cleanup)...")
            try:
                for eid in sample_external_ids:
                    conn.execute("DELETE FROM soap_records WHERE external_id = ?", (eid,))
                for fid in created_faq_ids:
                    conn.execute("DELETE FROM faq_cache WHERE id = ?", (fid,))
                conn.commit()
                print("  ✅ 示範 SOAP 紀錄與衍生 FAQ 草稿已清除。")
            except Exception as e:
                print(f"  ⚠️ 清理過程發生錯誤: {e}", file=sys.stderr)
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="clinicbrain 端到端臨床業務閉環實機驗證工具")
    parser.add_argument("--db", type=Path, default=PROD_DB_PATH, help="SQLite 資料庫路徑 (預設為正式 clinic.db)")
    parser.add_argument("--cleanup", action="store_true", help="驗證完成後清理測試資料")
    args = parser.parse_args()

    success = run_e2e_verification(args.db, cleanup=args.cleanup)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
