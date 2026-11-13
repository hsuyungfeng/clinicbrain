"""
src/visual/anatomy_catalog.py - 3D 臨床解剖結構化目錄與 PageIndex 關聯契約

遵循 docs/anatomy-3d-architecture.md 規格：
1. 完整涵蓋臨床決策樹（doc_id）之專科解剖結構映射 (anatomy_metadata)
2. 支援前綴去除（如 3503264627-paronychia-matrixectomy 自動對應 paronychia-matrixectomy）
3. 內建四段式臨床步驟聯動設定 (pre_op, procedure, post_op_short, maintenance)
4. 嚴格法規防線：強制經過 deep_mask_prices() 價格清洗、全繁體中文台灣專科標準名詞、法定免責聲明
"""

import re
from typing import Any, Dict, Optional
try:
    from src.api.routes.query import deep_mask_prices
except ImportError:
    from ..api.routes.query import deep_mask_prices

# 法定常駐免責聲明 (符合醫療法與專科倫理)
STATUTORY_ANATOMY_DISCLAIMER_ZH_TW = (
    "3D 解剖模型僅供衛教輔助參考，解剖結構存在個人體質差異，實際手術計畫以門診醫師親自評估為準。"
)

ANATOMY_CATALOG: Dict[str, Dict[str, Any]] = {
    # 1. 音波拉提系列
    "hifu-lifting": {
        "doc_id": "hifu-lifting",
        "anatomy_target": "facial_smas",
        "specialty_zh": "顏面淺筋膜與神經解剖",
        "specialty": "aesthetic_plastic_surgery",
        "model_src": "/static/anatomy/neurovascular.glb",
        "camera": {
            "default_position": [0.0, 1.2, 4.5],
            "target": [0.0, 0.0, 0.0],
            "pitch": 12.0,
            "yaw": -25.0,
            "zoom": 1.35,
        },
        "interactive_steps": [
            {
                "step_key": "pre_op",
                "action": "warning_zone",
                "target_mesh": "nerve_marginal_mandibular",
                "glow_color": "#FF4D4F",
                "camera_fly_to": {"zoom": 1.4, "duration": 1.0},
                "caption": "術前精密評估下頜緣神經支與眶上神經走行，嚴格規劃禁打避開區域，杜絕面神經麻痺可能。",
            },
            {
                "step_key": "procedure",
                "action": "highlight_layer",
                "target_mesh": "mesh_smas_layer",
                "glow_color": "#FFB800",
                "camera_fly_to": {"zoom": 1.8, "duration": 1.2},
                "caption": "音波聚焦能量穿透表皮與真皮，精準聚焦於皮下四點五毫米之淺筋膜層（SMAS），產生熱凝固收縮點。",
            },
            {
                "step_key": "post_op_short",
                "action": "highlight_layer",
                "target_mesh": "mesh_smas_layer",
                "glow_color": "#38BDF8",
                "camera_fly_to": {"zoom": 1.5, "duration": 1.0},
                "caption": "術後數日內淺筋膜與周邊真皮組織進行熱反應修復，可能伴隨微度壓痛與水腫，此為良性組織新生過程。",
            },
            {
                "step_key": "maintenance",
                "action": "highlight_layer",
                "target_mesh": "mesh_smas_layer",
                "glow_color": "#10B981",
                "camera_fly_to": {"zoom": 1.3, "duration": 1.0},
                "caption": "深層膠原蛋白支架全面新生重組，提拉效果可長效維持十二至十八個月。",
            },
        ],
    },

    # 2. 皮秒雷射
    "laser-skin-resurfacing": {
        "doc_id": "laser-skin-resurfacing",
        "anatomy_target": "epidermal_dermal_junction",
        "specialty_zh": "表皮黑素小體與真皮乳突層解剖",
        "specialty": "dermatology",
        "model_src": "/static/anatomy/context.glb",
        "camera": {
            "default_position": [0.0, 1.8, 3.8],
            "target": [0.0, 0.4, 0.0],
            "pitch": 25.0,
            "yaw": 0.0,
            "zoom": 1.6,
        },
        "interactive_steps": [
            {
                "step_key": "pre_op",
                "action": "warning_zone",
                "target_mesh": "melanocyte_layer",
                "glow_color": "#FF4D4F",
                "caption": "評估皮瓣膚質分型（Fitzpatrick scale），預防雷射術後反黑（PIH）與深層肝斑活化。",
            },
            {
                "step_key": "procedure",
                "action": "highlight_layer",
                "target_mesh": "pigment_cluster",
                "glow_color": "#06B6D4",
                "camera_fly_to": {"zoom": 2.2, "duration": 1.2},
                "caption": "光機械衝擊波（Photoacoustic effect）於萬億分之一秒粉碎真皮淺層黑色素，誘發空泡化效應（LIOB）。",
            },
            {
                "step_key": "post_op_short",
                "action": "highlight_layer",
                "target_mesh": "epidermis",
                "glow_color": "#38BDF8",
                "caption": "表皮輕微泛紅薄結痂，二十四小時內加強物理防曬與神經醯胺保濕修復。",
            },
            {
                "step_key": "maintenance",
                "action": "highlight_layer",
                "target_mesh": "collagen_dermis",
                "glow_color": "#10B981",
                "caption": "啟動真皮膠原重塑，毛孔細緻度與膚色均勻度持續改善。",
            },
        ],
    },

    # 3. 肉毒桿菌素注射
    "botox-injection": {
        "doc_id": "botox-injection",
        "anatomy_target": "neuromuscular_junction",
        "specialty_zh": "神經肌肉接合處與表情肌解剖",
        "specialty": "aesthetic_medicine",
        "model_src": "/static/anatomy/neurovascular.glb",
        "camera": {
            "default_position": [0.0, 1.0, 4.2],
            "target": [0.0, -0.1, 0.0],
            "pitch": -5.0,
            "yaw": -30.0,
            "zoom": 1.5,
        },
        "interactive_steps": [
            {
                "step_key": "pre_op",
                "action": "warning_zone",
                "target_mesh": "nerve_marginal_mandibular",
                "glow_color": "#FF4D4F",
                "caption": "精確勾勒咬肌後界與顴弓下安全三角，避免注射波及笑肌造成表情僵硬。",
            },
            {
                "step_key": "procedure",
                "action": "highlight_layer",
                "target_mesh": "masseter_muscle",
                "glow_color": "#8B5CF6",
                "camera_fly_to": {"zoom": 1.9, "duration": 1.2},
                "caption": "精準將肉毒桿菌素注射至咀嚼肌或動態紋肌腹深層，阻斷神經末梢乙醯膽鹼（ACh）釋放。",
            },
            {
                "step_key": "post_op_short",
                "action": "highlight_layer",
                "target_mesh": "masseter_muscle",
                "glow_color": "#38BDF8",
                "caption": "四小時內勿平躺或揉搓局部，避免藥劑微擴散至非目標肌群。",
            },
            {
                "step_key": "maintenance",
                "action": "highlight_layer",
                "target_mesh": "masseter_muscle",
                "glow_color": "#10B981",
                "caption": "肌肉廢用性微縮小定型，效果可維持四至六個月。",
            },
        ],
    },

    # 4. 電波拉皮 / 微針電波
    "electrowave-facelift": {
        "doc_id": "electrowave-facelift",
        "anatomy_target": "dermal_fibrous_septa",
        "specialty_zh": "真皮三維立體容積式加熱解剖",
        "specialty": "aesthetic_plastic_surgery",
        "model_src": "/static/anatomy/neurovascular.glb",
        "camera": {
            "default_position": [0.0, 1.2, 4.6],
            "target": [0.0, 0.1, 0.0],
            "pitch": 10.0,
            "yaw": 20.0,
            "zoom": 1.4,
        },
        "interactive_steps": [
            {
                "step_key": "pre_op",
                "action": "warning_zone",
                "target_mesh": "epidermis",
                "glow_color": "#FF4D4F",
                "caption": "冷卻噴劑同步監測表皮阻抗，嚴防表皮燙傷並確保深層熱容積蓄積。",
            },
            {
                "step_key": "procedure",
                "action": "highlight_layer",
                "target_mesh": "dermis_bulk",
                "glow_color": "#F97316",
                "camera_fly_to": {"zoom": 1.9, "duration": 1.2},
                "caption": "單極電波電流穿透真皮深層與皮下纖維中隔（Fibrous Septa），使膠原蛋白三螺旋立即緊縮。",
            },
            {
                "step_key": "post_op_short",
                "action": "highlight_layer",
                "target_mesh": "dermis_bulk",
                "glow_color": "#38BDF8",
                "caption": "輕度水腫在一至二天內消退，即刻呈現緊實輪廓感。",
            },
            {
                "step_key": "maintenance",
                "action": "highlight_layer",
                "target_mesh": "dermis_bulk",
                "glow_color": "#10B981",
                "caption": "持續觸發成纖維細胞合成新生膠原蛋白與彈力素，長效維持達一至兩年。",
            },
        ],
    },

    # 5. 玻尿酸皮下填充
    "hyaluronic-acid-filler": {
        "doc_id": "hyaluronic-acid-filler",
        "anatomy_target": "periosteal_supra_fat",
        "specialty_zh": "骨膜上深層支撐與血管走行動線",
        "specialty": "aesthetic_medicine",
        "model_src": "/static/anatomy/neurovascular.glb",
        "camera": {
            "default_position": [0.0, 1.1, 4.3],
            "target": [0.0, 0.0, 0.0],
            "pitch": 5.0,
            "yaw": -15.0,
            "zoom": 1.45,
        },
        "interactive_steps": [
            {
                "step_key": "pre_op",
                "action": "warning_zone",
                "target_mesh": "facial_artery",
                "glow_color": "#FF4D4F",
                "caption": "精密避開面動脈、角動脈與滑車上動脈走行，落實鈍針抽吸無回血操作。",
            },
            {
                "step_key": "procedure",
                "action": "highlight_layer",
                "target_mesh": "periosteal_deposit",
                "glow_color": "#EC4899",
                "camera_fly_to": {"zoom": 1.85, "duration": 1.2},
                "caption": "高交聯大分子玻尿酸錨定於深層骨膜上支撐韌帶，重塑中軸中下臉立體容積。",
            },
            {
                "step_key": "post_op_short",
                "action": "highlight_layer",
                "target_mesh": "periosteal_deposit",
                "glow_color": "#38BDF8",
                "caption": "初期避免劇烈擠壓或熱敷，玻尿酸與自體組織水分吸附融合定型。",
            },
            {
                "step_key": "maintenance",
                "action": "highlight_layer",
                "target_mesh": "periosteal_deposit",
                "glow_color": "#10B981",
                "caption": "均勻微降解維持約九至十五個月，線條平滑柔和自然。",
            },
        ],
    },

    # 6. 未感染粉瘤微創旋轉吸引切除手術
    "epidermal-cyst-excision": {
        "doc_id": "epidermal-cyst-excision",
        "anatomy_target": "epidermoid_cyst_capsule",
        "specialty_zh": "表皮囊腫囊壁與皮下剝離解剖",
        "specialty": "dermatologic_surgery",
        "model_src": "/static/anatomy/context.glb",
        "camera": {
            "default_position": [0.0, 1.5, 3.8],
            "target": [0.0, 0.2, 0.0],
            "pitch": 20.0,
            "yaw": 10.0,
            "zoom": 1.7,
        },
        "interactive_steps": [
            {
                "step_key": "pre_op",
                "action": "warning_zone",
                "target_mesh": "cyst_wall",
                "glow_color": "#FF4D4F",
                "caption": "高頻超音波定位粉瘤開口（Punctum）與囊壁邊界，確認無急性紅腫破裂感染。",
            },
            {
                "step_key": "procedure",
                "action": "highlight_layer",
                "target_mesh": "cyst_wall",
                "glow_color": "#FACC15",
                "camera_fly_to": {"zoom": 2.2, "duration": 1.2},
                "caption": "經由兩至三毫米微創小孔，以專利微創旋轉吸引刀刨碎內容物並完整剝除整顆角質囊壁，杜絕復發。",
            },
            {
                "step_key": "post_op_short",
                "action": "highlight_layer",
                "target_mesh": "dermis",
                "glow_color": "#38BDF8",
                "caption": "局部加壓包紮避免血腫形成，四十八小時後換藥，傷口隱痕癒合迅速。",
            },
            {
                "step_key": "maintenance",
                "action": "highlight_layer",
                "target_mesh": "subcutaneous_tissue",
                "glow_color": "#10B981",
                "caption": "皮下空腔肉芽組織長平，囊壁零殘留，長期復發率小於百分之一。",
            },
        ],
    },

    # 7. 甲溝炎嵌甲甲床重整手術
    "paronychia-matrixectomy": {
        "doc_id": "paronychia-matrixectomy",
        "anatomy_target": "nail_germinal_matrix",
        "specialty_zh": "側甲摺、甲床與甲基質生長中心解剖",
        "specialty": "dermatologic_surgery",
        "model_src": "/static/anatomy/context.glb",
        "camera": {
            "default_position": [0.0, 0.5, 3.5],
            "target": [0.0, -0.3, 0.0],
            "pitch": -25.0,
            "yaw": 0.0,
            "zoom": 1.8,
        },
        "interactive_steps": [
            {
                "step_key": "pre_op",
                "action": "warning_zone",
                "target_mesh": "digital_nerve",
                "glow_color": "#FF4D4F",
                "caption": "指/趾神經阻斷局部麻醉，精密評估肉芽腫脹範圍與嵌入側甲板深度。",
            },
            {
                "step_key": "procedure",
                "action": "highlight_layer",
                "target_mesh": "nail_matrix",
                "glow_color": "#EF4444",
                "camera_fly_to": {"zoom": 2.3, "duration": 1.2},
                "caption": "縱向縱切移除刺入軟組織之患側五分之一甲板，並徹底破壞燒灼根部甲基質生長中心（Partial Matrixectomy）。",
            },
            {
                "step_key": "post_op_short",
                "action": "highlight_layer",
                "target_mesh": "lateral_nail_fold",
                "glow_color": "#38BDF8",
                "caption": "術後抬高患肢減輕搏動性抽痛，定時優碘換藥保持乾燥，通常三日內疼痛大幅緩解。",
            },
            {
                "step_key": "maintenance",
                "action": "highlight_layer",
                "target_mesh": "nail_plate",
                "glow_color": "#10B981",
                "caption": "新長出指甲寬度永久變窄，徹底根治倒插卷甲與反覆甲溝化膿。",
            },
        ],
    },

    # 8. 微創螺旋刀頂漿腺狐臭手術
    "bromhidrosis-rotary-cutter": {
        "doc_id": "bromhidrosis-rotary-cutter",
        "anatomy_target": "apocrine_gland_dermal_junction",
        "specialty_zh": "腋下真皮下頂漿汗腺與血管網解剖",
        "specialty": "plastic_surgery",
        "model_src": "/static/anatomy/context.glb",
        "camera": {
            "default_position": [0.5, 1.2, 4.0],
            "target": [0.0, 0.0, 0.0],
            "pitch": 15.0,
            "yaw": 40.0,
            "zoom": 1.5,
        },
        "interactive_steps": [
            {
                "step_key": "pre_op",
                "action": "warning_zone",
                "target_mesh": "axillary_artery_vein",
                "glow_color": "#FF4D4F",
                "caption": "染色標記腋毛分佈範圍，辨識深層腋動靜脈與臂神經叢，限定淺層皮下安全平面。",
            },
            {
                "step_key": "procedure",
                "action": "highlight_layer",
                "target_mesh": "apocrine_gland",
                "glow_color": "#F59E0B",
                "camera_fly_to": {"zoom": 2.0, "duration": 1.2},
                "caption": "經半公分微創切口伸入電動旋轉刮刀，精密刮除真皮下交界處百分之九十以上頂漿腺體並抽吸導出。",
            },
            {
                "step_key": "post_op_short",
                "action": "highlight_layer",
                "target_mesh": "axillary_skin",
                "glow_color": "#38BDF8",
                "caption": "八字固定加壓包紮三天以促進皮瓣緊密貼合，兩週內避免患肢劇烈抬舉或提重物。",
            },
            {
                "step_key": "maintenance",
                "action": "highlight_layer",
                "target_mesh": "axillary_skin",
                "glow_color": "#10B981",
                "caption": "頂漿腺永久去除無法再生，異味根除率達百分之九十五以上。",
            },
        ],
    },

    # 9. Endolift 光纖內提拉手術
    "endolift-laser": {
        "doc_id": "endolift-laser",
        "anatomy_target": "subdermal_optical_fiber_smas",
        "specialty_zh": "皮下光纖傳導與脂肪微融解剖",
        "specialty": "aesthetic_plastic_surgery",
        "model_src": "/static/anatomy/neurovascular.glb",
        "camera": {
            "default_position": [0.0, 0.9, 4.2],
            "target": [0.0, -0.1, 0.0],
            "pitch": 8.0,
            "yaw": -20.0,
            "zoom": 1.55,
        },
        "interactive_steps": [
            {
                "step_key": "pre_op",
                "action": "warning_zone",
                "target_mesh": "facial_nerve_branch",
                "glow_color": "#FF4D4F",
                "caption": "下頜緣線條與雙下巴脂肪厚度精確測量，避開下頜緣神經走行層次。",
            },
            {
                "step_key": "procedure",
                "action": "highlight_layer",
                "target_mesh": "fiber_laser_path",
                "glow_color": "#F43F5E",
                "camera_fly_to": {"zoom": 1.95, "duration": 1.2},
                "caption": "免開刀髮絲級微米光纖伸入皮下脂肪層，釋放十四百七十奈米特定波長，同時達成選擇性溶脂與筋膜緊縮。",
            },
            {
                "step_key": "post_op_short",
                "action": "highlight_layer",
                "target_mesh": "subdermal_tissue",
                "glow_color": "#38BDF8",
                "caption": "針孔微創無疤痕，佩戴下巴加壓彈性頭套三至五天以加速組織定型消腫。",
            },
            {
                "step_key": "maintenance",
                "action": "highlight_layer",
                "target_mesh": "jawline_contour",
                "glow_color": "#10B981",
                "caption": "深層膠原持續緊縮，下顎線條與雙下巴緊實度在三個月達到巔峰。",
            },
        ],
    },

    # 10. 微創脂肪瘤抽吸切除手術
    "lipoma-aspiration": {
        "doc_id": "lipoma-aspiration",
        "anatomy_target": "lipoma_fibrous_capsule",
        "specialty_zh": "脂肪瘤包膜與深層皮下組織解剖",
        "specialty": "dermatologic_surgery",
        "model_src": "/static/anatomy/context.glb",
        "camera": {
            "default_position": [0.0, 1.3, 4.0],
            "target": [0.0, 0.1, 0.0],
            "pitch": 15.0,
            "yaw": -10.0,
            "zoom": 1.5,
        },
        "interactive_steps": [
            {
                "step_key": "pre_op",
                "action": "warning_zone",
                "target_mesh": "muscular_fascia",
                "glow_color": "#FF4D4F",
                "caption": "觸診與軟組織超音波確認腫塊與深層肌膜之活動度，排除深部肌肉浸潤性血管脂肪瘤。",
            },
            {
                "step_key": "procedure",
                "action": "highlight_layer",
                "target_mesh": "lipoma_lobule",
                "glow_color": "#FBBF24",
                "camera_fly_to": {"zoom": 2.0, "duration": 1.2},
                "caption": "腫脹麻醉下經三毫米切口伸入鈍頭抽吸管，水動力乳化脂肪小葉並將整片纖維囊袋完整取出。",
            },
            {
                "step_key": "post_op_short",
                "action": "highlight_layer",
                "target_mesh": "subcutaneous_bed",
                "glow_color": "#38BDF8",
                "caption": "術後局部彈性加壓固定防止空腔積液（Seroma），依醫囑換藥。",
            },
            {
                "step_key": "maintenance",
                "action": "highlight_layer",
                "target_mesh": "subcutaneous_bed",
                "glow_color": "#10B981",
                "caption": "囊袋完整移除後局部外觀平整，極低復發率。",
            },
        ],
    },

    # 11. 雙眼皮 / 眼整形手術
    "blepharoplasty": {
        "doc_id": "blepharoplasty",
        "anatomy_target": "eyelid_levator_aponeurosis",
        "specialty_zh": "眼周眼輪匝肌與提眼肌腱膜",
        "specialty": "aesthetic_plastic_surgery",
        "model_src": "/static/anatomy/context.glb",
        "camera": {
            "default_position": [0.0, 1.5, 3.8],
            "target": [0.0, 0.2, 0.0],
            "pitch": 10.0,
            "yaw": 0.0,
            "zoom": 1.65,
        },
        "interactive_steps": [
            {
                "step_key": "pre_op",
                "action": "warning_zone",
                "target_mesh": "orbital_septum",
                "glow_color": "#FF4D4F",
                "caption": "評估上瞼提肌肌力、眼窩脂肪突出量與眼瞼下垂程度，避開滑車上神經分支。",
            },
            {
                "step_key": "procedure",
                "action": "highlight_layer",
                "target_mesh": "levator_aponeurosis",
                "glow_color": "#F59E0B",
                "camera_fly_to": {"zoom": 2.1, "duration": 1.2},
                "caption": "精確分離眼輪匝肌與眶隔，將真皮固定於提上瞼肌腱膜或瞼板上緣，形成自然重瞼摺痕。",
            },
            {
                "step_key": "post_op_short",
                "action": "highlight_layer",
                "target_mesh": "orbicularis_oculi",
                "glow_color": "#38BDF8",
                "caption": "術後七十二小時內冰敷減輕眼周皮下瘀血，五至七天拆線。",
            },
            {
                "step_key": "maintenance",
                "action": "highlight_layer",
                "target_mesh": "levator_aponeurosis",
                "glow_color": "#10B981",
                "caption": "疤痕成熟淡化，提眼肌張力穩定，眼神深邃明亮。",
            },
        ],
    },

    # 12. 隆鼻手術
    "rhinoplasty": {
        "doc_id": "rhinoplasty",
        "anatomy_target": "nasal_cartilage_framework",
        "specialty_zh": "鼻背骨與外側下鼻翼軟骨",
        "specialty": "aesthetic_plastic_surgery",
        "model_src": "/static/anatomy/context.glb",
        "camera": {
            "default_position": [0.8, 1.3, 3.8],
            "target": [0.0, 0.0, 0.0],
            "pitch": 15.0,
            "yaw": 30.0,
            "zoom": 1.7,
        },
        "interactive_steps": [
            {
                "step_key": "pre_op",
                "action": "warning_zone",
                "target_mesh": "nasal_artery_angular",
                "glow_color": "#FF4D4F",
                "caption": "精密標記鼻背動脈、鼻翼角動脈走行動線，防範假體壓迫或血流受阻。",
            },
            {
                "step_key": "procedure",
                "action": "highlight_layer",
                "target_mesh": "nasal_septum_cartilage",
                "glow_color": "#F59E0B",
                "camera_fly_to": {"zoom": 2.2, "duration": 1.2},
                "caption": "以自體軟骨或複合支架重建鼻中隔伸展支撐（SEG），穩固塑形鼻尖表現點。",
            },
            {
                "step_key": "post_op_short",
                "action": "highlight_layer",
                "target_mesh": "nasal_bone",
                "glow_color": "#38BDF8",
                "caption": "術後配戴熱塑鼻板固定一週，避免外力撞擊與劇烈晃動。",
            },
            {
                "step_key": "maintenance",
                "action": "highlight_layer",
                "target_mesh": "nasal_tip",
                "glow_color": "#10B981",
                "caption": "六至十二個月鼻部組織水腫完全消退，鼻樑與鼻尖線條完全定型。",
            },
        ],
    },

    # 13. 人工植牙
    "dental-implant": {
        "doc_id": "dental-implant",
        "anatomy_target": "mandibular_nerve_canal",
        "specialty_zh": "齒槽骨吸收與下齒槽神經管安全距",
        "specialty": "dental_surgery",
        "model_src": "/static/anatomy/neurovascular.glb",
        "camera": {
            "default_position": [0.0, 0.8, 4.2],
            "target": [0.0, -0.2, 0.0],
            "pitch": -12.0,
            "yaw": -20.0,
            "zoom": 1.6,
        },
        "interactive_steps": [
            {
                "step_key": "pre_op",
                "action": "warning_zone",
                "target_mesh": "inferior_alveolar_nerve",
                "glow_color": "#FF4D4F",
                "camera_fly_to": {"zoom": 1.9, "duration": 1.0},
                "caption": "透過 3D 電腦斷層精密量測齒槽骨高度，保留至少二毫米安全邊距以遠離下齒槽神經管。",
            },
            {
                "step_key": "procedure",
                "action": "highlight_layer",
                "target_mesh": "alveolar_bone_fixture",
                "glow_color": "#FFB800",
                "camera_fly_to": {"zoom": 2.3, "duration": 1.2},
                "caption": "純鈦人工牙根植入皮質骨與海綿骨，啟動骨整合生理反應（Osseointegration）。",
            },
            {
                "step_key": "post_op_short",
                "action": "highlight_layer",
                "target_mesh": "gingival_tissue",
                "glow_color": "#38BDF8",
                "caption": "初期避免患側咀嚼硬物，溫鹽水漱口維護牙周清潔，七至十天傷口癒合。",
            },
            {
                "step_key": "maintenance",
                "action": "highlight_layer",
                "target_mesh": "implant_crown",
                "glow_color": "#10B981",
                "caption": "裝戴全瓷牙冠後，每半年定期洗牙回診追蹤骨水平維持狀況。",
            },
        ],
    },
}

# 別名與同義詞對照表（支援診所前綴或相近專有名詞自動正規化）
_SYNONYM_MAP: Dict[str, str] = {
    "picosecond-laser-rejuvenation": "laser-skin-resurfacing",
    "fractional-laser": "laser-skin-resurfacing",
    "qray-frx-fractional-laser": "laser-skin-resurfacing",
    "nd-yag-laser-toning": "laser-skin-resurfacing",
    "bbl-broadband-light": "laser-skin-resurfacing",
    "hydrafacial-deep-cleansing": "laser-skin-resurfacing",
    "asce-rose-exosome-regeneration": "laser-skin-resurfacing",
    "rejuran-pdrn-skin-healer": "laser-skin-resurfacing",
    "chronic-migraine-botox-decompression": "botox-injection",
    "microneedle-rf": "electrowave-facelift",
    "thermage-flx-rf": "electrowave-facelift",
    "renuvion-helium-plasma": "electrowave-facelift",
    "ultherapy-focused-ultrasound": "hifu-lifting",
    "ultraformer-mpt-hifu": "hifu-lifting",
    "full-deep-plane-facelift": "hifu-lifting",
    "mid-lower-smas-facelift": "hifu-lifting",
    "swan-neck-cervicoplasty": "hifu-lifting",
    "hyaluronic-acid-dermal-filler": "hyaluronic-acid-filler",
    "overfilled-face-syndrome-correction": "hyaluronic-acid-filler",
    "blepharoplasty-eye-contouring": "blepharoplasty",
    "structural-autologous-rhinoplasty": "rhinoplasty",
    "bulbous-nose-rhinoplasty": "rhinoplasty",
    "chin-augmentation-genioplasty": "dental-implant",
    "facial-bone-contouring": "dental-implant",
    "orthognathic-surgery": "dental-implant",
    "scar-subcision": "epidermal-cyst-excision",
    "plasma-pen-electrocautery": "epidermal-cyst-excision",
}

# 預設通用解剖設定（當查無特定 doc_id 時之保守安全回退）
DEFAULT_ANATOMY_METADATA: Dict[str, Any] = {
    "doc_id": "default-general",
    "anatomy_target": "general_head_neck",
    "specialty_zh": "臨床立體解剖層次概覽",
    "specialty": "general_surgery",
    "model_src": "/static/anatomy/neurovascular.glb",
    "camera": {
        "default_position": [0.0, 1.2, 4.5],
        "target": [0.0, 0.0, 0.0],
        "pitch": 0.0,
        "yaw": 0.0,
        "zoom": 1.2,
    },
    "interactive_steps": [
        {
            "step_key": "pre_op",
            "action": "warning_zone",
            "glow_color": "#FF4D4F",
            "caption": "術前完整評估局部神經血管走行與個人解剖體質差異，建立安全邊界。",
        },
        {
            "step_key": "procedure",
            "action": "highlight_layer",
            "glow_color": "#FFB800",
            "caption": "由專科醫師嚴格遵照解剖解剖層次進行治療，精準作用於目標結構。",
        },
        {
            "step_key": "post_op_short",
            "action": "highlight_layer",
            "glow_color": "#38BDF8",
            "caption": "術後初期組織修復反應，遵照醫囑冰敷或用藥以利消腫。",
        },
        {
            "step_key": "maintenance",
            "action": "highlight_layer",
            "glow_color": "#10B981",
            "caption": "長期組織穩定與追蹤維護，確保治療成果持久。",
        },
    ],
}


def canonicalize_doc_id(doc_id: str) -> str:
    """
    去除機構代碼前綴（如 3503264627-paronychia-matrixectomy -> paronychia-matrixectomy），
    並查詢同義詞映射表。
    """
    if not doc_id:
        return ""
    clean = re.sub(r"^\d{10}-", "", doc_id.strip())
    if clean in ANATOMY_CATALOG:
        return clean
    if clean in _SYNONYM_MAP:
        return _SYNONYM_MAP[clean]
    return clean


def get_anatomy_metadata(doc_id: str) -> Dict[str, Any]:
    """
    取得特定 doc_id 之 3D 解剖中繼資料與互動步驟設定。
    保證：
    1. 支援前綴去除與同義詞對照
    2. 100% 透過 deep_mask_prices() 清洗，零價格外洩
    3. 附加法定常駐免責聲明
    4. 未比對到 doc_id 時回傳結構完整的通用預設資料（Fail-Safe）
    """
    canon_id = canonicalize_doc_id(doc_id)
    if canon_id in ANATOMY_CATALOG:
        raw_data = ANATOMY_CATALOG[canon_id].copy()
        raw_data["doc_id"] = doc_id  # 保留請求的原始 doc_id
    else:
        raw_data = DEFAULT_ANATOMY_METADATA.copy()

    raw_data["disclaimer"] = STATUTORY_ANATOMY_DISCLAIMER_ZH_TW

    # 執行嚴格價格清洗
    cleaned = deep_mask_prices(raw_data)
    return cleaned
