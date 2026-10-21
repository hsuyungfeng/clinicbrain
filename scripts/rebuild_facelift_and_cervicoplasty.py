#!/usr/bin/env python3
"""
台灣診所 RAG 系統 - 天鵝頸闊頸肌縫合拉皮術與中下臉 SMAS 筋膜拉皮手術深度重構腳本
結合最新網路臨床權威資料（深層脂肪墊減容、二腹肌前腹修整、闊頸肌雙向馬甲對縫、
展延深層 SMAS 提拉、顴骨/咬肌韌帶鬆解、骨膜剛性錨定與零張力無壓縫合防小丑耳）：
1. 增量更新 page_index_trees 臨床推理樹與 summary_text
2. 增量更新 faq_cache 口語高頻諮詢問答
3. 重建 visual_assets 3 幕動畫草稿 Typed IR 規格
"""

from pathlib import Path
import sqlite3
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pageindex.db_writer import upsert_trees
from src.pageindex.faq_writer import upsert_faqs
from src.visual.writer import upsert_assets
from src.visual.ir import validate_ir

DB_PATH = PROJECT_ROOT / "clinic.db"
CLINIC_ID = "3503264627"

REBUILT_TREES = [
    {
        "doc_id": f"{CLINIC_ID}-swan-neck-cervicoplasty",
        "clinic_id": CLINIC_ID,
        "title": "天鵝頸闊頸肌縫合拉皮術（下巴微創隱痕與下顎輪廓線雕塑）",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估下顎至頸部夾角、淺層皮下脂肪與深層脂肪墊（Subplatysmal Fat）分佈、闊頸肌分離垂帶（火雞脖）程度及下巴骨後縮狀況 "
            "2. 鑑別是否合併二腹肌前腹肥厚需適度減容 3. 術前兩週嚴格戒菸、停用抗凝血劑與阿斯匹靈 4. 全身體檢並完成舒眠或全身麻醉安全評估。"
        ),
        "procedure": (
            "手術步驟：1. 舒眠或全身麻醉下施作。於下巴下緣天然皮摺處取約兩公分微創隱痕切口 2. 直視放大視野下精細解離皮瓣，打薄淺層脂肪，"
            "並深入直視切除闊頸肌下方的深層脂肪墊（Subplatysmal Fat）及修整二腹肌前腹 3. 將兩側分離鬆弛的闊頸肌（Platysma）邊緣徹底游離，"
            "進行中央馬甲式雙向交疊對縫（Corset Platysmaplasty），建構強韌肌肉吊帶重塑清晰九十度下顎天鵝頸夾角 4. 皮下微米級減張對位縫合切口。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 局部留置細微引流管一至兩天以防組織液積聚 2. 佩戴專屬頸頜彈性加壓面罩固定，輔助皮瓣與深層肌肉貼合 "
            "3. 前三天頭部抬高仰臥，避免頻繁低頭或劇烈扭轉頸部 4. 按醫囑定時服用消腫藥物與抗生素 5. 下巴切口每日換藥清潔塗抹藥膏。"
        ),
        "maintenance": (
            "長期維持保養：1. 術後七至十天門診拆除切口縫線 2. 塑型面罩建議前兩週全天穿戴，第三至四週改夜間穿戴鞏固組織貼合 "
            "3. 術後一個月內避免仰頭劇烈伸展或重訓 4. 下巴下緣隱痕切口三至六個月逐漸淡化為不明顯細線，締造長效緊緻天鵝頸。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "天鵝頸拉皮經下巴下緣兩公分微創隱痕切口，直視切除闊頸肌下深層脂肪墊，並將分離闊頸肌進行馬甲式雙向交疊對縫（Corset Platysmaplasty）。"
            "術後佩戴彈性面罩加壓塑型，消除火雞脖垂帶與雙下巴，重現清晰緊緻的九十度俐落下顎天鵝頸線條。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-mid-lower-smas-facelift",
        "clinic_id": CLINIC_ID,
        "title": "中下臉 SMAS 筋膜深層拉皮手術（展延式深層提拉與骨膜固定）",
        "category": "special",
        "pre_op": (
            "術前須知：1. 全面評估皮膚、皮下脂肪、SMAS筋膜、維持韌帶及顏面神經走行 2. 評估法令紋、嘴邊肉、木偶紋及下顎緣鬆垂成因 "
            "3. 術前兩週嚴格戒菸、停用抗凝血劑與阿斯匹靈 4. 完成心電圖、胸部X光及全身麻醉術前檢驗。"
        ),
        "procedure": (
            "手術步驟：1. 沿耳前耳屏天然輪廓摺痕順著耳垂繞至耳後髮際隱痕切口進入 2. 展延式深層筋膜提拉（Extended Deep Plane SMAS），"
            "進入深層間隙徹底鬆解顴骨韌帶與咬肌維持韌帶 3. 將下垂 SMAS 筋膜連同頰脂肪墊複合體向上後方四十五度角立體提拉復位，"
            "並以強韌抗吸收線牢牢錨定於深層骨膜（Periosteum）上承擔所有拉力 4. 修剪多餘鬆弛表皮，進行零張力精密減張對位縫合，杜絕耳垂牽拉變形。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 放置負壓引流管（通常一至兩天視引流量拔除）預防皮下血腫 2. 全臉佩戴彈性加壓面罩 3. 前三天頭部抬高臥床並局部冷敷 "
            "4. 每日使用無菌生理食鹽水與抗生素藥膏換藥，嚴防傷口感染。"
        ),
        "maintenance": (
            "長期維持保養：1. 術後七至十天分段拆線，持續佩戴塑臉面罩二至四週鞏固貼合 2. 拆線一週後開始塗抹除疤凝膠，避免陽光直射疤痕 "
            "3. 一個月內避免大笑、劇烈運動或按摩臉部 4. 深層骨架筋膜重置提供穩定長效之年輕輪廓。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "中下臉拉皮採展延式深層筋膜（Extended Deep Plane）提拉，鬆解顴骨與咬肌維持韌帶，將筋膜牢固錨定於骨膜承擔拉力。"
            "表皮採零張力無壓縫合杜絕耳垂牽拉變形，術後引流管防血腫、面罩加壓塑型，根本改善法令紋與嘴邊肉下垂。"
        ),
    },
]

REBUILT_FAQS = [
    {
        "question": "天鵝頸手術跟一般的抽雙下巴、打電音波拉皮有什麼本質區別？",
        "answer": (
            "電音波只能緊緻淺層表皮，抽脂只能抽掉皮下淺層脂肪；但火雞脖垂帶與雙下巴下垂的關鍵元兇，往往是深層的「闊頸肌兩側鬆弛分離」與「深層脂肪墊（Subplatysmal Fat）堆積」。"
            "天鵝頸手術直接進入肌肉層將深層脂肪減容，並將分離的闊頸肌像馬甲一樣緊緊折疊縫合固定（Corset Platysmaplasty），形成天然肌肉吊帶，這是非手術儀器無法做到的解剖結構重塑。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-swan-neck-cervicoplasty",
    },
    {
        "question": "天鵝頸手術的傷口在哪裡？術後抬頭會不會很緊繃不舒服？",
        "answer": (
            "手術切口隱藏在下巴下緣約兩公分的天然皮膚橫紋處，站立或社交距離完全看不到，癒合後隨時間淡化為不明顯細線。術後初期抬頭會有些微拉緊感，"
            "這正是闊頸肌被緊緻拉平的正常生理反應，通常一至兩週隨組織適應即自然緩解，術後下顎線立體俐落。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-swan-neck-cervicoplasty",
    },
    {
        "question": "中下臉拉皮和埋線拉皮、音波拉提最大的差別是什麼？",
        "answer": (
            "音波與埋線主要透過熱能收縮或線材倒鉤暫時牽拉軟組織，屬於輕度保養，對深層嚴重鬆垂的地基難以根本復位；中下臉 SMAS 拉皮手術則是在放大視野下徹底鬆解顴骨與咬肌維持韌帶，"
            "將移位的 SMAS 筋膜地基多層往上復位並牢固縫合錨定於堅韌骨膜上，同時修除多餘贅皮，效果深刻自然且維持長達八至十二年。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-mid-lower-smas-facelift",
    },
    {
        "question": "中下臉拉皮手術的傷口會很明顯嗎？耳垂會不會變形？",
        "answer": (
            "手術切口沿耳前耳屏天然輪廓摺痕順著耳垂繞至耳後髮際，癒合後疤痕相當隱密。凡登拉皮技術最關鍵特色在於將拉力完全由深層 SMAS 筋膜與骨膜承擔，"
            "表面皮膚採「零張力無壓縫合」，因此完全不會發生耳垂被往下牽拉扯長變形的「小丑耳（Pixie Ear）」問題。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-mid-lower-smas-facelift",
    },
]

REBUILT_VISUAL_ASSETS = [
    {
        "clinic_id": CLINIC_ID,
        "topic_key": f"tree-{CLINIC_ID}-swan-neck-cervicoplasty",
        "title": "天鵝頸闊頸肌縫合拉皮術原理圖解",
        "keywords": ["天鵝頸", "闊頸肌縫合", "深層取脂", "微創隱痕", "下顎線雕塑"],
        "ir": {
            "topic_key": f"tree-{CLINIC_ID}-swan-neck-cervicoplasty",
            "title": "天鵝頸闊頸肌縫合拉皮術原理圖解",
            "keywords": ["天鵝頸", "闊頸肌縫合", "深層取脂", "微創隱痕", "下顎線雕塑"],
            "scenes": [
                {
                    "blueprint": "corset_platysmaplasty",
                    "title": "微創入路與闊頸肌馬甲對縫",
                    "caption": "經下巴下緣天然皮摺兩公分微創隱痕切口，直視清除闊頸肌下深層脂肪墊，並將兩側分離之闊頸肌進行馬甲式雙向對縫，重塑九十度俐落下顎天鵝頸夾角。",
                    "labels": [
                        {"text": "下巴天然皮摺", "tone": "neutral"},
                        {"text": "深層脂肪減容", "tone": "neutral"},
                        {"text": "馬甲式內對縫", "tone": "optimal"},
                    ],
                    "params": {
                        "layer_labels": ["表皮與皮下層", "闊頸肌深層墊", "頸前筋膜深層"],
                        "muscle_label": "兩側闊頸肌",
                        "fat_label": "深層脂肪墊",
                        "suture_label": "馬甲式對縫",
                        "suture_fill": "accent",
                        "step_labels": ["皮摺微創入路", "雙向馬甲對縫", "九十度俐落角"],
                    },
                    "duration_sec": 8,
                },
                {
                    "blueprint": "contrast",
                    "title": "手術處置方式深度對比",
                    "caption": "相較於傳統大範圍切開手術易留下長痕跡且拉力集中於表皮，天鵝頸微創馬甲對縫由肌肉層承受張力，切口隱密且線條俐落自然。",
                    "labels": [
                        {"text": "傳統大切口", "tone": "warning"},
                        {"text": "微創馬甲縫", "tone": "optimal"},
                    ],
                    "params": {
                        "left": {
                            "title": "傳統大範圍切口",
                            "note": "切口長張力大",
                            "mode": "wide_incision",
                            "core_effect": "dim",
                            "core_label": "下顎張力牽拉",
                            "footnote": "切口較長且術後牽扯感明顯",
                            "unit_fill": "warn",
                        },
                        "right": {
                            "title": "下巴微創隱痕",
                            "note": "肌肉馬甲對縫",
                            "mode": "minimal_incision",
                            "rows": 3,
                            "per_row": 5,
                            "footnote": "隱蔽微創切口減輕組織張力",
                            "unit_fill": "ok",
                        },
                    },
                    "duration_sec": 8,
                },
                {
                    "blueprint": "timeline",
                    "title": "術後照護與貼合進程",
                    "caption": "術後初期佩戴專屬加壓面罩減輕組織液積聚，微創切口平整隱痕，整體下顎線緊緻與肌肉修復進度因人而異需由醫師當面評估。",
                    "labels": [
                        {"text": "初期加壓包紮", "tone": "neutral"},
                        {"text": "天鵝頸輪廓穩定", "tone": "optimal"},
                    ],
                    "params": {
                        "milestones": ["加壓面罩", "組織貼合", "俐落天鵝頸"],
                        "unit_effect": "mature",
                        "connectors": "wound_healing",
                        "units": 3,
                        "unit_fill": "accent",
                    },
                    "duration_sec": 8,
                },
            ],
        },
        "metadata": {
            "origin": "web_rebuilt_expert",
            "doc_id": f"{CLINIC_ID}-swan-neck-cervicoplasty",
        },
    },
    {
        "clinic_id": CLINIC_ID,
        "topic_key": f"tree-{CLINIC_ID}-mid-lower-smas-facelift",
        "title": "中下臉筋膜深層拉皮手術原理圖解",
        "keywords": ["中下臉拉皮", "SMAS筋膜", "骨膜錨定", "展延深層提拉", "零張力縫合"],
        "ir": {
            "topic_key": f"tree-{CLINIC_ID}-mid-lower-smas-facelift",
            "title": "中下臉筋膜深層拉皮手術原理圖解",
            "keywords": ["中下臉拉皮", "SMAS筋膜", "骨膜錨定", "展延深層提拉", "零張力縫合"],
            "scenes": [
                {
                    "blueprint": "deep_plane_facelift",
                    "title": "深層筋膜重塑與骨膜錨定",
                    "caption": "經耳前自然輪廓隱痕切口進入深層間隙，徹底鬆解顴骨與咬肌維持韌帶，將下垂筋膜地基向上後方立體重塑，牢固錨定於骨膜上，表皮零張力減張縫合。",
                    "labels": [
                        {"text": "SMAS筋膜層", "tone": "neutral"},
                        {"text": "韌帶解離鬆解", "tone": "neutral"},
                        {"text": "骨膜堅固錨定", "tone": "optimal"},
                    ],
                    "params": {
                        "layer_labels": ["表皮輪廓層", "SMAS筋膜瓣", "堅韌骨膜基底"],
                        "smas_label": "SMAS筋膜瓣",
                        "anchor_label": "骨膜錨定點",
                        "ligament_label": "維持韌帶",
                        "suture_fill": "accent",
                        "step_labels": ["解離維持韌帶", "立體重塑提拉", "骨膜牢固錨定"],
                    },
                    "duration_sec": 8,
                },
                {
                    "blueprint": "contrast",
                    "title": "拉皮技術理念深度對比",
                    "caption": "傳統拉皮僅修剪表皮，張力全在皮膚導致面具臉且耳垂被向下牽拉扯長；深層拉皮由堅固骨膜承受所有拉力，表皮零張力無壓縫合保護原生耳形。",
                    "labels": [
                        {"text": "傳統單純拉皮", "tone": "warning"},
                        {"text": "筋膜骨膜錨定", "tone": "optimal"},
                    ],
                    "params": {
                        "left": {
                            "title": "傳統單純拉皮",
                            "note": "表皮張力過大",
                            "mode": "wide_incision",
                            "core_effect": "dim",
                            "core_label": "耳垂牽拉變形",
                            "footnote": "拉力全在表皮易致小丑耳",
                            "unit_fill": "warn",
                        },
                        "right": {
                            "title": "深層筋膜錨定",
                            "note": "表皮零張力縫合",
                            "mode": "minimal_incision",
                            "rows": 3,
                            "per_row": 5,
                            "footnote": "骨膜承受拉力保護耳垂自然",
                            "unit_fill": "ok",
                        },
                    },
                    "duration_sec": 8,
                },
                {
                    "blueprint": "timeline",
                    "title": "術後復原與重塑進程",
                    "caption": "術後留置細微負壓引流管排除滲液，佩戴面罩加壓塑型，深層筋膜貼合與輪廓年輕化維持程度因人而異需由醫師當面評估。",
                    "labels": [
                        {"text": "負壓引流防腫", "tone": "neutral"},
                        {"text": "骨架級年輕輪廓", "tone": "optimal"},
                    ],
                    "params": {
                        "milestones": ["負壓引流", "分段拆線", "緊緻年輕態"],
                        "unit_effect": "mature",
                        "connectors": "wound_healing",
                        "units": 3,
                        "unit_fill": "accent",
                    },
                    "duration_sec": 8,
                },
            ],
        },
        "metadata": {
            "origin": "web_rebuilt_expert",
            "doc_id": f"{CLINIC_ID}-mid-lower-smas-facelift",
        },
    },
]


def execute_rebuild():
    conn = sqlite3.connect(DB_PATH)
    try:
        print("1. 正在更新臨床推理樹 (page_index_trees)...")
        ins_t, upd_t, unc_t = upsert_trees(conn, REBUILT_TREES, source_type="clinic_upload", review_status="approved")
        print(f"   推理樹更新完成: 新增 {ins_t}, 更新 {upd_t}, 未變 {unc_t}")

        print("2. 正在更新高頻 FAQ (faq_cache)...")
        ins_f, upd_f, unc_f = upsert_faqs(conn, REBUILT_FAQS, source_type="clinic_upload", commit=True)
        print(f"   FAQ 更新完成: 新增 {ins_f}, 更新 {upd_f}, 未變 {unc_f}")

        print("3. 正在更新視覺解說卡 (visual_assets)...")
        res_v = upsert_assets(conn, REBUILT_VISUAL_ASSETS, source_type="llm_generated", commit=True)
        print(f"   視覺解說卡更新完成: {res_v}")

        # 驗證 FTS5 與資料庫
        cur = conn.cursor()
        for doc in REBUILT_TREES:
            cur.execute("SELECT doc_id, content_version, title FROM page_index_trees WHERE doc_id = ?", (doc["doc_id"],))
            print("   Tree 列況:", cur.fetchone())

        for a in REBUILT_VISUAL_ASSETS:
            cur.execute("SELECT id, clinic_id, topic_key, content_version, review_status FROM visual_assets WHERE topic_key = ?", (a["topic_key"],))
            print("   Asset 列況:", cur.fetchone())

    finally:
        conn.close()


if __name__ == "__main__":
    execute_rebuild()
