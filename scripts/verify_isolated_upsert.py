#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - 測試複本寫入與隔離驗證
將真實生成的 3 筆療程樹寫入隔離資料庫複本，驗證 schema 與 UPSERT 正確性。
"""

import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.pageindex.prompt_template import parse_and_validate, to_upsert_row, GeneratedTree
from src.pageindex.db_writer import upsert_trees

PROD_DB = PROJECT_ROOT / "clinic.db"
TREES_JSON_PATH = PROJECT_ROOT / "scripts" / "phase02_generated_trees.json"

TREES_DATA = [
    {
        "doc_id": "zhiyan-clinic-toning-laser",
        "procedure_name": "淨膚雷射",
        "category": "special",
        "generation_time_sec": 74.30,
        "tree": {
            "pre_op": "術前須知：1.請告知醫師皮膚病史、用藥史與過敏史，尤其近期使用光敏性藥物、口服A酸或外用刺激性保養品者。2.近期有曬傷、明顯曬黑、活動性痤瘡、開放性傷口或疱疹發作者，建議先處理或延後施作。3.術前請卸除彩妝、清潔臉部，避免使用含酒精、果酸、水楊酸或去角質成分的產品。4.懷孕或哺乳者應主動告知醫師，由醫師評估是否適合施作。",
            "procedure": "療程步驟與原理：淨膚雷射通常以低能量雷射或光子能量作用於表皮層，針對色素沉著、微血管擴張與膚色不均等問題進行改善。能量被目標組織吸收後，可促進色素代謝與皮膚修復，使膚色看起來較均勻。施作前醫師會依膚況選擇適合的參數，過程中可能出現輕微熱感、刺癢或針刺感，多數人可耐受；實際感受因人而異。",
            "post_op_short": "術後短期照護：1.術後可能有輕微紅腫、乾燥、結痂或暫時性色素變化，屬常見反應，通常會隨時間改善。2.加強保濕與防曬，外出可使用帽子、陽傘等物理遮蔽。3.避免使用熱水洗脸、蒸氣、三溫暖、烤箱或劇烈運動，以免加重紅腫。4.避免抓撓、剝落結痂或使用刺激性保養品；若出現持續疼痛、明顯水疱或異常腫脹，應回診評估。",
            "maintenance": "長期維持保養：1.防曬是維持膚色均勻的重要習慣，建議日常使用防曬產品並配合物理遮蔽。2.維持溫和清潔與保濕，避免過度去角質或使用刺激性成分。3.生活作息、壓力與睡眠可能影響皮膚狀態，建議保持規律作息。4.淨膚雷射效果因人而異，多數情況下需依醫師評估安排複診或後續照護，不宜自行頻繁施作。",
            "summary_text": "淨膚雷射術前應告知用藥與皮膚狀況，近期曬傷、發炎或傷口未癒合者不宜施作，並清潔臉部。療程以低能量作用於表皮色素與微血管，改善暗沉與膚色不均，過程可能有輕微熱感。術後加強保濕防曬，避免高溫與刺激性保養，紅腫結痂多屬常見。長期應維持防曬、溫和護膚與規律作息，依醫師建議回診。",
            "warnings": []
        }
    },
    {
        "doc_id": "zhiyan-clinic-hydrafacial",
        "procedure_name": "水飛梭",
        "category": "special",
        "generation_time_sec": 70.04,
        "tree": {
            "pre_op": "術前須知：1.告知醫師皮膚狀況、過敏史與用藥史，並說明是否懷孕或哺乳。2.若臉部有開放性傷口、明顯發炎、嚴重痤瘡，或近期進行過侵入性療程，應先請醫師評估。3.術前卸除彩妝並清潔臉部，避免使用厚重保養品。4.敏感肌或曾對清潔、導入成分過敏者，應提前告知醫師。",
            "procedure": "療程步驟：水飛梭屬於非侵入性深層清潔與保濕導入療程，利用水渦流技術溫和去除老廢角質並清潔毛孔，同時輔助玻尿酸及抗氧化精華導入，幫助皮膚維持水潤與舒緩。過程多數情況下以輕微水流感或吸力感為主，實際感受會因人而異。",
            "post_op_short": "術後短期照護：1.可能出現短暫泛紅、輕微緊繃或局部溫熱感，多數情況下會自行緩解。2.當日避免高溫環境、劇烈運動與用力摩擦臉部。3.使用溫和清潔產品並加強保濕，暫時避免刺激性去角質成分。4.若持續疼痛、腫脹明顯、破皮或出現異常不適，應回診請醫師評估。",
            "maintenance": "長期維持保養：1.可依皮膚狀況與需求，定期回診評估是否適合重複施作。2.日常維持防曬、溫和清潔與穩定保濕。3.避免熬夜、吸菸、過度擠壓粉刺或頻繁使用刺激性產品。4.效果因人而異，應依個人膚況、生活習慣與季節變化調整保養節奏。",
            "summary_text": "水飛梭術前需說明過敏史、用藥史、皮膚狀況及是否懷孕哺乳，並卸妝清潔臉部。療程以水渦流技術溫和清潔角質與毛孔，同時導入玻尿酸和抗氧化精華保濕舒緩，過程多為輕微水流或吸力感。術後可能短暫泛紅或緊繃，應避免高溫、摩擦與刺激產品，加強溫和保濕。長期靠防曬、清潔、保濕與定期回診評估維持，效果因人而異。",
            "warnings": []
        }
    },
    {
        "doc_id": "zhiyan-clinic-autologous-fat-grafting",
        "procedure_name": "自體脂肪補臉",
        "category": "special",
        "generation_time_sec": 78.54,
        "tree": {
            "pre_op": "術前須知：1.請告知醫師完整病史，包括凝血功能異常、抗凝血藥物或阿斯匹靈使用、糖尿病、免疫疾病、皮膚感染、疤痕體質與過敏史。2.抽脂部位與注射部位若有發炎、開放性傷口或嚴重痤瘡，應先處理。3.懷孕、哺乳或計畫懷孕者應告知醫師並評估是否暫緩施作。4.若使用鎮靜、全身麻醉或較長時間施作，請依醫師指示禁食禁水，並安排陪同人員。5.術前清潔臉部與抽脂部位，避免彩妝、香水與刺激性保養品。",
            "procedure": "療程步驟與原理：自體脂肪補臉會先評估面部凹陷與輪廓需求，再抽取腹部或大腿等部位多餘脂肪，經過離心純化與處理後，以分層注射方式移植至臉頰、蘋果肌、太陽穴等需要支撐的部位。其原理是利用自身脂肪組織提供局部填充與支撐，部分脂肪在術後存活後可改善凹陷外觀。施作時間與麻醉方式會依部位範圍、脂肪量及個人狀況而異；脂肪存活程度因人而異，初期可能有部分吸收，是否需補打應由醫師評估。",
            "post_op_short": "術後短期照護：1.抽脂部位可能出現腫脹、瘀青、酸脹或觸痛，注射部位可能有紅腫、硬塊或不平整感，多數會隨時間逐漸改善。2.請依醫師指示清潔傷口、冰敷與使用藥物，避免自行用力按摩或揉壓治療部位。3.短期內避免劇烈運動、高溫環境、蒸氣、熱水澡與過度拉扯臉部。4.建議清淡飲食，避免菸酒，以降低腫脹與感染風險。5.若出現持續加劇的疼痛、發燒、明顯紅腫化膿、異常出血、呼吸不順或嚴重不對稱，應盡快回診評估。",
            "maintenance": "長期維持保養：1.自體脂肪效果需時間穩定，術後初期部分脂肪吸收屬常見現象，最終外觀因人而異。2.建議定期回診，由醫師評估輪廓對稱度、硬塊狀況與是否需要補打。3.平時維持防曬、保濕與良好作息，有助於皮膚狀態穩定。4.避免體重快速大幅波動，以免影響面部脂肪分布與整體輪廓。5.若長期存在明顯硬塊、疼痛、不對稱或外觀變化，應回診進一步評估。",
            "summary_text": "自體脂肪補臉術前應告知病史、用藥、感染與懷孕哺乳狀況，並依醫師指示準備麻醉與清潔部位。療程抽取腹部或大腿多餘脂肪，純化後分層注入臉頰、蘋果肌等凹陷處，以自身組織提供支撐。術後可能腫脹、瘀青或暫時不平整，應避免按摩與劇烈運動。效果因人而異，需定期回診評估是否補打。",
            "warnings": []
        }
    }
]


def get_file_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main():
    print("1. 檢查正式 clinic.db Hash...")
    hash_before = get_file_sha256(PROD_DB)
    print(f"正式 clinic.db SHA-256 (執行前): {hash_before}")

    # 存檔真實生成內容
    with open(TREES_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(TREES_DATA, f, ensure_ascii=False, indent=2)
    print(f"已儲存 3 筆生成樹資料至: {TREES_JSON_PATH}")

    # 建立臨時隔離目錄與複本
    temp_dir = Path(tempfile.mkdtemp(prefix="clinic_test_phase02_"))
    isolated_db_path = temp_dir / "clinic_isolated.db"
    shutil.copy2(PROD_DB, isolated_db_path)
    print(f"建立隔離資料庫複本於: {isolated_db_path}")

    conn = sqlite3.connect(str(isolated_db_path))

    # 逐一驗證並寫入
    for item in TREES_DATA:
        doc_id = item["doc_id"]
        category = item["category"]
        raw_json = json.dumps(item["tree"], ensure_ascii=False)
        tree = parse_and_validate(raw_json)
        row = to_upsert_row(doc_id, category, tree)
        upsert_trees(conn, [row], source_type="llm_generated")
        print(f"成功寫入複本: {doc_id} (耗時 {item['generation_time_sec']}s)")

    # 查詢確認
    cursor = conn.cursor()
    cursor.execute(
        "SELECT doc_id, category, source_type, content_version, summary_text FROM page_index_trees WHERE source_type = 'llm_generated'"
    )
    rows = cursor.fetchall()
    print(f"\n複本資料庫查詢確認：共 {len(rows)} 筆 llm_generated 樹：")
    for r in rows:
        print(f"- {r[0]} | cat: {r[1]} | source: {r[2]} | ver: {r[3]} | summary: {r[4][:30]}...")
    assert len(rows) == 3, f"寫入筆數不符：預期 3 筆，實際 {len(rows)} 筆"

    conn.close()

    # 再次檢查正式 clinic.db Hash
    hash_after = get_file_sha256(PROD_DB)
    print(f"\n正式 clinic.db SHA-256 (執行後): {hash_after}")
    assert hash_before == hash_after, "正式 clinic.db 遭篡改！"
    print("隔離驗證完全合格！正式資料庫零修改。")


if __name__ == "__main__":
    main()
