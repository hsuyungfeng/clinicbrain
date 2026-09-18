#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - PageIndex 臨床推理樹範本
Phase 01 Task 3: PageIndex schema and tree generation (seed set)

這批範本為人工手寫的高品質繁體中文臨床推理樹，涵蓋緻妍外科診所（醫美診所）
常見療程類型，作為：
1. TASK-004（LLM 生成 prompt）設計時的品質基準（few-shot 範例）
2. 查詢介面（TASK-005）開發期間的可用測試資料
3. 評估套件（TASK-008）的 ground truth 樣本

CONSTRAINT 遵循：
- 全篇繁體中文，不含任何簡體字或英文（藥品學名/國際通用醫療術語除外）
- 絕對禁止出現原始價格數字；不確定給付/收費一律使用「請致電診所確認」
- physician_notes 欄位保留空白，待實際醫師審核填入診所專屬醫囑
"""

import sqlite3
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "clinic.db"

CLINIC_ID = "zhiyan-clinic"

TREES = [
    {
        "doc_id": f"{CLINIC_ID}-electrowave-facelift",
        "category": "special",
        "pre_op": (
            "術前須知：1. 懷孕或裝有心律調節器者不建議施作 2. 臉部有開放性傷口或急性發炎需先治療痊癒 "
            "3. 術前1週避免使用A酸、果酸等刺激性保養品 4. 術前應卸除臉部金屬飾品"
        ),
        "procedure": (
            "療程步驟：電波拉皮利用電磁波加熱真皮層與皮下組織，刺激膠原蛋白新生與緊實。"
            "施作前塗抹導極凝膠，探頭於臉部依序移動加熱，全臉約需40-60分鐘，多數民眾僅感溫熱感，"
            "少數敏感部位可能有短暫刺痛。無需恢復期，可立即返回日常生活。"
        ),
        "post_op_short": (
            "術後照護：1. 術後可能出現輕微泛紅，數小時內會自然消退 2. 當日避免高溫環境（三溫暖、烤箱、泡湯）"
            " 3. 加強保濕，避免臉部乾燥緊繃 4. 術後1週內加強防曬"
        ),
        "maintenance": (
            "長期維持：1. 建議間隔4-6週回診評估效果 2. 效果會隨時間逐漸顯現，通常療程後1-3個月最明顯 "
            "3. 平時應持續防曬與保濕以延長效果 4. 效果可維持約1年，依個人膚質與生活習慣而異"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "電波拉皮術前懷孕、心律調節器者不宜施作，需避開開放性傷口。療程用電磁波加熱真皮層促進"
            "膠原蛋白新生，全臉約40-60分鐘，無恢復期。術後可能輕微泛紅、當日避免高溫環境、加強防曬。"
            "建議4-6週回診評估，效果約可維持1年。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-hyaluronic-acid-filler",
        "category": "special",
        "pre_op": (
            "術前須知：1. 告知醫師是否有凝血功能異常或正在服用抗凝血藥物 2. 術前2週避免服用阿斯匹靈、"
            "魚油等具抗凝血作用之保健品 3. 懷孕或哺乳中不建議施作 4. 若有單純疱疹病史，術前應告知醫師評估是否需預防性投藥"
        ),
        "procedure": (
            "療程步驟：玻尿酸填充利用細針或鈍針將玻尿酸注入皮下或肌肉層，回填流失容量、改善凹陷或雕塑輪廓。"
            "施作前可視需求局部塗抹或注射麻醉藥膏，單一部位施作約15-30分鐘，過程中可能有輕微腫脹感。"
        ),
        "post_op_short": (
            "術後照護：1. 術後24小時內避免按壓、揉捏注射部位 2. 術後3天內避免劇烈運動與高溫環境 "
            "3. 若出現瘀青屬正常現象，通常1-2週內會自然消退 4. 如注射部位出現異常疼痛、發白或皮膚變色，應立即回診"
        ),
        "maintenance": (
            "長期維持：1. 效果約可維持6-18個月，依施打部位與個人代謝速度而異 2. 建議效果消退約七至八成時回診補打"
            " 3. 避免自行按摩注射部位以免移位 4. 定期回診追蹤，確保填充效果自然"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "玻尿酸填充術前應告知凝血功能異常、抗凝血藥物使用及疱疹病史。療程以細針或鈍針注入皮下，"
            "單部位約15-30分鐘。術後24小時避免按壓，3天內避免劇烈運動，瘀青屬正常現象。效果維持"
            "6-18個月，異常疼痛或膚色變化須立即回診。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-fractional-laser",
        "category": "special",
        "pre_op": (
            "術前須知：1. 過敏體質、蟹足腫體質需事先告知醫師 2. 術前2週停止使用A酸、左旋C等刺激性保養品 "
            "3. 術前1個月避免曝曬與日曬機 4. 若有單純疱疹病史應提前告知評估是否需預防性投藥"
        ),
        "procedure": (
            "療程步驟：飛梭雷射利用微創光束在皮膚上製造微小熱損傷點，刺激皮膚自我修復與膠原蛋白新生，"
            "改善痘疤、毛孔與細紋。施作前塗抹表面麻醉藥膏約30-45分鐘，正式治療時間約20-30分鐘，"
            "治療當下有灼熱刺痛感。"
        ),
        "post_op_short": (
            "術後照護：1. 術後臉部會有泛紅、輕微腫脹與結痂脫屑，屬正常修復反應 2. 術後3-5天內避免化妝與"
            "劇烈運動 3. 加強保濕修護，避免摳抓脫屑處 4. 術後2週內須嚴格防曬，避免色素沉澱"
        ),
        "maintenance": (
            "長期維持：1. 建議每4-6週回診一次，療程為一系列多次治療，通常需3-6次達到理想效果 "
            "2. 平時應持續防曬與溫和保養 3. 效果會隨療程次數累積，膚質改善可維持數月至數年，視保養習慣而定"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "飛梭雷射術前避免刺激性保養品、日曬及蟹足腫體質需告知。療程以微創光束刺激皮膚修復，"
            "改善痘疤毛孔，需先敷麻醉藥膏，治療約20-30分鐘。術後泛紅結痂屬正常，須嚴格防曬2週。"
            "建議4-6週回診，通常需3-6次療程。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-hifu-lifting",
        "category": "special",
        "pre_op": (
            "術前須知：1. 懷孕、裝有金屬植入物或心律調節器者不建議施作 2. 臉部有嚴重痤瘡發炎或開放性傷口需先治療"
            " 3. 術前應清潔臉部、卸除彩妝與金屬飾品 4. 甲狀腺疾病患者施作頸部區域前應告知醫師"
        ),
        "procedure": (
            "療程步驟：音波拉提利用聚焦超音波能量作用於皮下筋膜層（SMAS層），刺激深層組織收縮與"
            "膠原蛋白增生，達到提拉緊緻效果。施作全臉約需60-90分鐘，能量作用於深層時可能感受到"
            "明顯的熱感與痠脹感，屬正常反應。"
        ),
        "post_op_short": (
            "術後照護：1. 術後可能出現輕微紅腫、少數人有暫時性麻木感，通常數天內會緩解 2. 當日避免"
            "高溫環境與劇烈運動 3. 加強保濕，避免臉部過度按摩 4. 如出現持續性疼痛或異常腫脹應回診評估"
        ),
        "maintenance": (
            "長期維持：1. 效果會隨時間逐漸顯現，術後1-3個月最為明顯 2. 建議每8-12個月回診評估是否需"
            "加強施作 3. 平時應維持良好生活作息與防曬習慣以延長效果 4. 效果可維持約1-2年，依個人"
            "老化速度與生活習慣而異"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "音波拉提術前懷孕、金屬植入物、心律調節器者不宜施作，甲狀腺疾病需告知醫師。療程以聚焦"
            "超音波作用於SMAS筋膜層，全臉約60-90分鐘，過程有熱感痠脹。術後輕微紅腫或暫時麻木屬正常，"
            "效果1-3個月內顯現，建議8-12個月回診，維持約1-2年。"
        ),
    },
]


def upsert_trees(conn):
    cursor = conn.cursor()
    inserted = 0
    for tree in TREES:
        cursor.execute(
            """
            INSERT OR REPLACE INTO page_index_trees (
                doc_id, category,
                pre_op, pre_op_physician_notes,
                procedure, procedure_physician_notes,
                post_op_short, post_op_short_physician_notes,
                maintenance, maintenance_physician_notes,
                summary_text, version, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tree["doc_id"],
                tree["category"],
                tree["pre_op"],
                tree["pre_op_physician_notes"],
                tree["procedure"],
                tree["procedure_physician_notes"],
                tree["post_op_short"],
                tree["post_op_short_physician_notes"],
                tree["maintenance"],
                tree["maintenance_physician_notes"],
                tree["summary_text"],
                "2.0",
                datetime.now().isoformat(),
            ),
        )
        inserted += 1
    conn.commit()
    return inserted


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"找不到資料庫：{DB_PATH}，請先執行 scripts/seed_database.py")

    conn = sqlite3.connect(str(DB_PATH))
    count = upsert_trees(conn)

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM page_index_trees")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM page_index_fts")
    fts_total = cur.fetchone()[0]

    print(f"寫入/更新 {count} 筆 PageIndex 範本")
    print(f"page_index_trees 總筆數：{total}")
    print(f"page_index_fts 索引筆數：{fts_total}")

    conn.close()


if __name__ == "__main__":
    main()
