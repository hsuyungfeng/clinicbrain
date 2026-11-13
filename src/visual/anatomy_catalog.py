"""
src/visual/anatomy_catalog.py - 3D 臨床解剖結構化目錄與 PageIndex 關聯契約

遵循 docs/anatomy-3d-architecture.md 規格：
1. 建立專科與 PageIndex 療程（doc_id）之解剖結構映射 (anatomy_metadata)
2. 內建四段式臨床步驟聯動設定 (pre_op, procedure, post_op_short, maintenance)
3. 嚴格法規防線：強制經過 deep_mask_prices() 價格清洗、全繁體中文台灣專科標準名詞、法定免責聲明
"""

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
    "hifu-lifting": {
        "doc_id": "hifu-lifting",
        "anatomy_target": "facial_smas",
        "specialty_zh": "顏面淺筋膜與神經解剖",
        "specialty": "aesthetic_plastic_surgery",
        "model_src": "/static/anatomy/neurovascular.glb",
        "camera": {
            "default_position": [0.0, 1.2, 5.0],
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
    "blepharoplasty": {
        "doc_id": "blepharoplasty",
        "anatomy_target": "eyelid_levator_aponeurosis",
        "specialty_zh": "眼周眼輪匝肌與提眼肌腱膜",
        "specialty": "aesthetic_plastic_surgery",
        "model_src": "/static/anatomy/context.glb",
        "camera": {
            "default_position": [0.0, 1.5, 4.2],
            "target": [0.0, 0.2, 0.0],
            "pitch": 8.0,
            "yaw": 0.0,
            "zoom": 1.5,
        },
        "interactive_steps": [
            {
                "step_key": "pre_op",
                "action": "warning_zone",
                "target_mesh": "orbital_septum",
                "glow_color": "#FF4D4F",
                "camera_fly_to": {"zoom": 1.6, "duration": 1.0},
                "caption": "評估上瞼提肌肌力、眼窩脂肪突出量與眼瞼下垂程度，避開滑車上神經分支。",
            },
            {
                "step_key": "procedure",
                "action": "highlight_layer",
                "target_mesh": "levator_aponeurosis",
                "glow_color": "#F59E0B",
                "camera_fly_to": {"zoom": 2.0, "duration": 1.2},
                "caption": "精確分離眼輪匝肌與眶隔，將真皮固定於提上瞼肌腱膜或瞼板上緣，形成自然重瞼摺痕。",
            },
            {
                "step_key": "post_op_short",
                "action": "highlight_layer",
                "target_mesh": "orbicularis_oculi",
                "glow_color": "#38BDF8",
                "camera_fly_to": {"zoom": 1.7, "duration": 1.0},
                "caption": "術後七十二小時內冰敷減輕眼周皮下瘀血，五至七天拆線。",
            },
            {
                "step_key": "maintenance",
                "action": "highlight_layer",
                "target_mesh": "levator_aponeurosis",
                "glow_color": "#10B981",
                "camera_fly_to": {"zoom": 1.4, "duration": 1.0},
                "caption": "疤痕成熟淡化，提眼肌張力穩定，眼神深邃明亮。",
            },
        ],
    },
    "rhinoplasty": {
        "doc_id": "rhinoplasty",
        "anatomy_target": "nasal_cartilage_framework",
        "specialty_zh": "鼻背骨與外側下鼻翼軟骨",
        "specialty": "aesthetic_plastic_surgery",
        "model_src": "/static/anatomy/context.glb",
        "camera": {
            "default_position": [0.8, 1.3, 4.0],
            "target": [0.0, 0.0, 0.0],
            "pitch": 15.0,
            "yaw": 30.0,
            "zoom": 1.6,
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
                "camera_fly_to": {"zoom": 2.1, "duration": 1.2},
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
    "dental-implant": {
        "doc_id": "dental-implant",
        "anatomy_target": "mandibular_nerve_canal",
        "specialty_zh": "齒槽骨吸收與下齒槽神經管安全距",
        "specialty": "dental_surgery",
        "model_src": "/static/anatomy/neurovascular.glb",
        "camera": {
            "default_position": [0.0, 0.8, 4.5],
            "target": [0.0, -0.2, 0.0],
            "pitch": -10.0,
            "yaw": -15.0,
            "zoom": 1.5,
        },
        "interactive_steps": [
            {
                "step_key": "pre_op",
                "action": "warning_zone",
                "target_mesh": "inferior_alveolar_nerve",
                "glow_color": "#FF4D4F",
                "camera_fly_to": {"zoom": 1.8, "duration": 1.0},
                "caption": "透過 3D 電腦斷層精密量測齒槽骨高度，保留至少二毫米安全邊距以遠離下齒槽神經管。",
            },
            {
                "step_key": "procedure",
                "action": "highlight_layer",
                "target_mesh": "alveolar_bone_fixture",
                "glow_color": "#FFB800",
                "camera_fly_to": {"zoom": 2.2, "duration": 1.2},
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

# 預設通用解剖設定（當查無特定 doc_id 時之保守安全回退）
DEFAULT_ANATOMY_METADATA: Dict[str, Any] = {
    "doc_id": "default-general",
    "anatomy_target": "general_head_neck",
    "specialty_zh": "頭頸與面部臨床解剖概覽",
    "specialty": "general_surgery",
    "model_src": "/static/anatomy/neurovascular.glb",
    "camera": {
        "default_position": [0.0, 1.2, 5.0],
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


def get_anatomy_metadata(doc_id: str) -> Dict[str, Any]:
    """
    取得特定 doc_id 之 3D 解剖中繼資料與互動步驟設定。
    保證：
    1. 100% 透過 deep_mask_prices() 清洗，零價格外洩
    2. 附加法定常駐免責聲明
    3. 未比對到 doc_id 時回傳結構完整的通用預設資料（Fail-Safe）
    """
    raw_data = ANATOMY_CATALOG.get(doc_id, DEFAULT_ANATOMY_METADATA).copy()
    raw_data["disclaimer"] = STATUTORY_ANATOMY_DISCLAIMER_ZH_TW

    # 執行嚴格價格清洗
    cleaned = deep_mask_prices(raw_data)
    return cleaned
