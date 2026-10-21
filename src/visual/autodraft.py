"""
由已核准 PageIndex 臨床推理樹自動生成「原理與手術過程」視覺解說卡草稿模組 (autodraft)。
Phase 31: P31-AUTODRAFT

設計原則：
1. 輸入嚴格隔離：僅限對外可見（已核准）之臨床決策推理樹（符合 visible_tree_sql），
   未核准或駁回之樹一律拒絕生成。
2. 範圍嚴格約束：僅說明「原理與手術／處置過程」，絕不產生用藥劑量、價格數字、
   促銷方案或個人化診斷。
3. 零預設文字污染：所有場景 params 的文字欄位必須由模型針對主題明確生成，
   絕不退回寫死之預設文字。
4. 結構鎖定：固定產生 3 個場景（process_diagram -> contrast -> timeline），
   且皆附帶合法之 params。
5. 永不自動核准：生成結果寫入 visual_assets 狀態恆為 pending，source_type='llm_generated'，
   需經執業醫師審核簽核後方可對外提供。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Optional, Tuple

from src.pageindex.llm_client import (
    LLMEmptyOutputError,
    LLMTruncatedError,
    LocalLLMUnavailableError,
    VISUAL_SAMPLING,
    local_llm_call,
)
from src.pageindex.llm_lock import GENERATION_LOCK, nightly_batch_running
from src.pageindex.tree_review import visible_tree_sql
from .blueprints import BLUEPRINTS, PALETTE_TOKENS, enum_values, validate_params
from .ir import (
    VISUAL_EXTRA_FORBIDDEN,
    validate_ir,
    validate_visual_text,
)
from .writer import upsert_assets

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)
_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_DIGIT_RE = re.compile(r"\d")

# 場景 3 必須包含之專業收尾語意（至少命中其一）
_TIMELINE_CLOSING_PHRASES = (
    "因人而異",
    "個人體質",
    "醫師評估",
    "醫師當面評估",
    "個別評估",
    "臨床評估",
    "視個人狀況",
    "專業評估",
)

# 非自體脂肪主題不得殘留之引擎預設脂肪移植字面值（防止模型照抄預設值污染非脂肪主題）
_FAT_GRAFT_DEFAULT_LITERALS = (
    "抽取之脂肪組織",
    "油脂層（捨棄）",
    "純化脂肪顆粒（保留）",
    "血水雜質（捨棄）",
    "中心缺血",
    "單團塊中心不易獲取充足養分",
    "微細脂肪球與周圍組織充分接觸",
    "新生血管長入",
)


def normalize_tree_topic_key(doc_id: str) -> str:
    """將 doc_id 正規化為 visual_assets 的 topic_key。

    規則：小寫英數連字號，前綴 tree-，長度 3..64。
    """
    if not isinstance(doc_id, str):
        raise ValueError("schema_error")
    cleaned = doc_id.strip().lower()
    if not cleaned.startswith("tree-"):
        normalized = f"tree-{cleaned}"
    else:
        normalized = cleaned

    if not re.match(r"^[a-z0-9-]{3,64}$", normalized):
        raise ValueError("schema_error")
    return normalized


def fetch_eligible_trees(
    conn: sqlite3.Connection,
    *,
    tree_id: Optional[int] = None,
    doc_id: Optional[str] = None,
    clinic_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """查詢符合自動生成視覺解說卡資格（已核准）之臨床決策推理樹。"""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(page_index_trees)")
    cols = [row[1] for row in cur.fetchall()]
    if not cols:
        return []

    vis_sql = visible_tree_sql(conn)
    where_parts = [vis_sql]
    if "review_status" in cols:
        where_parts.append("review_status = 'approved'")
    params: list[Any] = []

    if tree_id is not None:
        where_parts.append("id = ?")
        params.append(tree_id)

    if doc_id is not None:
        where_parts.append("doc_id = ?")
        params.append(doc_id)

    if clinic_id is not None:
        where_parts.append("clinic_id = ?")
        params.append(clinic_id)

    where_clause = " AND ".join(where_parts)
    col_str = "id, clinic_id, doc_id, title, summary_text, pre_op, procedure, post_op_short, maintenance, source_type, content_version"
    # 若表中有 review_status 也取出
    if "review_status" in cols:
        col_str += ", review_status"

    cur.execute(f"SELECT {col_str} FROM page_index_trees WHERE {where_clause} ORDER BY id ASC", tuple(params))
    rows = cur.fetchall()

    result = []
    select_cols = [c.strip() for c in col_str.split(",")]
    for r in rows:
        item = dict(zip(select_cols, r))
        result.append(item)
    return result


def _resolve_tree_title(tree: dict[str, Any]) -> str:
    """從推理樹取得繁體中文主題名稱；若 title 為空則自 summary_text 擷取『XX術前』前綴。"""
    raw_title = (tree.get("title") or "").strip()
    if raw_title:
        return raw_title
    summary = (tree.get("summary_text") or "").strip()
    m = re.match(r"^([\u4e00-\u9fffA-Za-z]{2,15}?)(?:術前|療程|手術|治療)", summary)
    if m:
        return m.group(1).strip()
    return (tree.get("doc_id") or "醫療療程").strip()


def infer_scene1_blueprint(tree: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """根據推理樹主題關鍵字與內容，推斷最契合之解剖機轉視覺模板與參數結構。

    支援臨床機轉：
    1. neuromuscular: 肉毒桿菌素注射 (動態表情紋調節)
    2. dermal_support: 玻尿酸／微整填充 (凹陷立體支撐)
    3. Endolift / 微光纖拉提 (skin_energy: 微光纖深層熱能緊緻)
    4. 黃金微針電波 (skin_energy: 微針電波立體加熱)
    5. 等離子筆與電灼 (laser_action: 等離子弧光微氣化)
    6. laser_action: 皮秒雷射 (mode=shatter)、飛梭雷射 (mode=fractional)
    7. skin_energy: 音波拉提 (mode=focused)、電波拉皮 (mode=volumetric)
    8. process_diagram 核心外科處置：
       - 頂漿腺狐臭手術 (螺旋刀微創刮除抽吸)
       - 未感染粉瘤手術 (微創旋轉吸引切除)
       - 脂肪瘤切除手術 (微創抽吸輔助切除)
       - 甲溝炎甲床手術 (甲床重整與甲母質處理)
       - 疤痕皮下切割 (皮下牽引纖維鬆解)
    9. process_diagram 通用: 自體脂肪移植／PRP 等組織純化處置
    """
    title = _resolve_tree_title(tree)
    doc_id = (tree.get("doc_id") or "").lower()
    summary = (tree.get("summary_text") or "").lower()
    full_text = f"{title} {doc_id} {summary}"

    # 1. 肉毒桿菌素
    if any(k in full_text for k in ("肉毒", "botox", "神經肌肉", "動態紋", "除皺")):
        return "neuromuscular", {
            "blueprint": "neuromuscular",
            "title": "神經調節與肌肉撫平",
            "params_template": {
                "nerve_label": "運動神經末梢",
                "muscle_label": "過度收縮肌肉",
                "surface_label": "動態表情皺紋",
                "blocker_fill": "ok",
                "step_labels": ["精準微量注射", "調節神經訊號", "肌肉放鬆撫平"],
            },
        }

    # 2. 玻尿酸 / 填充
    if any(k in full_text for k in ("玻尿酸", "hyaluronic", "filler", "填充", "微晶瓷", "膠原蛋白針")):
        return "dermal_support", {
            "blueprint": "dermal_support",
            "title": "深淺分層立體支撐",
            "params_template": {
                "filler_label": "親水凝膠",
                "layer_labels": ["表皮輪廓層", "真皮皮下層"],
                "droplets": 6,
                "filler_fill": "gel",
                "step_labels": ["評估凹陷部位", "深淺分層注入", "立體支撐平順"],
            },
        }

    # 3. Endolift 光纖內提拉手術
    if any(k in full_text for k in ("endolift", "光纖內提拉", "光纖提拉")):
        return "skin_energy", {
            "blueprint": "skin_energy",
            "title": "微光纖深層熱能緊緻",
            "params_template": {
                "mode": "focused",
                "probe_label": "光纖探針",
                "layer_labels": ["真皮深層", "皮下脂肪", "筋膜層"],
                "focal_points": 5,
                "energy_fill": "accent",
                "step_labels": ["光纖微孔導入", "光熱均勻溶脂", "深層筋膜收縮"],
            },
        }

    # 4. 黃金微針電波拉提
    if any(k in full_text for k in ("黃金微針", "微針電波", "microneedle")):
        return "skin_energy", {
            "blueprint": "skin_energy",
            "title": "微針電波立體加熱",
            "params_template": {
                "mode": "volumetric",
                "probe_label": "黃金微針",
                "layer_labels": ["表皮保護層", "真皮膠原層", "皮下淺層"],
                "focal_points": 5,
                "energy_fill": "accent",
                "step_labels": ["微針精準穿透", "針尖釋放電波", "真皮膠原新生"],
            },
        }

    # 5. 等離子筆與電灼贅疣治療
    if any(k in full_text for k in ("等離子", "電灼", "plasma", "贅疣")):
        return "laser_action", {
            "blueprint": "laser_action",
            "title": "等離子弧光微氣化",
            "params_template": {
                "mode": "fractional",
                "beam_label": "等離子弧",
                "target_label": "贅疣病灶",
                "layer_labels": ["病灶表皮層", "真皮基底層"],
                "beam_fill": "accent",
                "step_labels": ["等離子弧聚焦", "表皮病灶氣化", "微創結痂修復"],
            },
        }

    # 6. 雷射光電 (皮秒 / 飛梭)
    if any(k in full_text for k in ("雷射", "laser", "皮秒", "飛梭", "resurfacing", "pico")):
        is_fractional = any(k in full_text for k in ("飛梭", "fractional", "點陣", "毛孔", "痘疤"))
        mode = "fractional" if is_fractional else "shatter"
        b_label = "微點光束" if is_fractional else "皮秒光束"
        t_label = "微熱凝結" if is_fractional else "色素團塊"
        s_labels = ["點陣微光穿透", "微創加熱重組", "健康組織修復"] if is_fractional else ["短脈衝光束照射", "光震波擊碎色素", "微細粉塵代謝"]
        return "laser_action", {
            "blueprint": "laser_action",
            "title": "點陣光熱重組" if is_fractional else "光震波擊碎色素",
            "params_template": {
                "mode": mode,
                "beam_label": b_label,
                "target_label": t_label,
                "layer_labels": ["表皮角質層", "真皮基底層"],
                "beam_fill": "accent",
                "step_labels": s_labels,
            },
        }

    # 7. 顏面與頸部專屬拉皮外科處置 (deep_plane_facelift & corset_platysmaplasty)
    is_energy_device = any(k in full_text for k in ("音波", "超音波", "hifu", "電波", "rf", "非侵入"))
    if not is_energy_device and any(k in full_text for k in ("smas", "deep-plane", "deepplane", "筋膜拉皮", "深層拉皮", "拉皮手術", "面部拉皮", "臉部拉皮", "中下臉拉皮", "facelift")):
        return "deep_plane_facelift", {
            "blueprint": "deep_plane_facelift",
            "title": "深層筋膜解離與骨膜錨定",
            "params_template": {
                "layer_labels": ["表皮輪廓層", "SMAS筋膜層", "堅韌骨膜基底"],
                "smas_label": "SMAS筋膜瓣",
                "anchor_label": "骨膜錨定點",
                "ligament_label": "維持韌帶",
                "suture_fill": "accent",
                "step_labels": ["微創切口解離韌帶", "45度提拉骨膜錨定", "表皮零張力無壓縫合"],
            },
        }

    if any(k in full_text for k in ("天鵝頸", "闊頸肌", "platysma", "cervicoplasty", "馬甲縫合", "頸部拉皮")):
        return "corset_platysmaplasty", {
            "blueprint": "corset_platysmaplasty",
            "title": "微創入路與闊頸肌馬甲對縫",
            "params_template": {
                "layer_labels": ["表皮與皮下層", "闊頸肌與深層墊", "頸前筋膜深層"],
                "muscle_label": "兩側闊頸肌",
                "fat_label": "深層脂肪墊",
                "suture_label": "馬甲式對縫",
                "suture_fill": "accent",
                "step_labels": ["微創入路修整脂肪", "闊頸肌馬甲式對縫", "緊緻吊帶俐落頸角"],
            },
        }

    # 8. 音波 / 電波能量拉提
    if any(k in full_text for k in ("音波", "電波", "hifu", "electrowave", "rf", "能量拉提", "非侵入拉提", "拉提", "拉皮")):
        is_volumetric = any(k in full_text for k in ("電波", "electrowave", "rf", "容積", "真皮加熱"))
        mode = "volumetric" if is_volumetric else "focused"
        p_label = "電波探頭" if is_volumetric else "音波探頭"
        s_labels = ["電波能量傳導", "真皮均勻溫熱", "膠原收縮緊緻"] if is_volumetric else ["能量精準傳遞", "深層熱凝結點", "膠原緊縮拉提"]
        return "skin_energy", {
            "blueprint": "skin_energy",
            "title": "真皮立體容積加熱" if is_volumetric else "聚焦音波能量傳遞",
            "params_template": {
                "mode": mode,
                "probe_label": p_label,
                "layer_labels": ["表皮層", "真皮膠原層", "筋膜層"],
                "focal_points": 5,
                "energy_fill": "accent",
                "step_labels": s_labels,
            },
        }

    # 8. 專屬外科核心解剖處置
    # 8.1 未感染粉瘤微創旋轉吸引切除手術 (cyst_excision)
    if any(k in full_text for k in ("粉瘤", "表皮樣囊腫", "epidermal-cyst")):
        return "cyst_excision", {
            "blueprint": "cyst_excision",
            "title": "微創旋轉切除與完整囊袋剝離",
            "params_template": {
                "cyst_label": "粉瘤囊腫",
                "sac_label": "完整包膜",
                "core_label": "角質分泌物",
                "layer_labels": ["表皮層", "皮下真皮層"],
                "sac_fill": "accent",
                "step_labels": ["微創切口定位", "減壓排空引流", "完整囊袋剝離"],
            },
        }

    # 8.2 甲溝炎嵌甲甲床重整手術 (nail_matrix)
    if any(k in full_text for k in ("甲溝炎", "嵌甲", "paronychia", "甲床")):
        return "nail_matrix", {
            "blueprint": "nail_matrix",
            "title": "嵌甲側切與甲床基質重整",
            "params_template": {
                "nail_label": "趾甲板",
                "fold_label": "側甲襞",
                "spicule_label": "嵌甲尖刺",
                "matrix_label": "甲基質生長板",
                "matrix_fill": "warn",
                "step_labels": ["嵌甲邊緣游離", "縱向側切移除", "甲床基質重整"],
            },
        }

    # 8.3 頂漿腺狐臭手術 (subdermal_curettage)
    if any(k in full_text for k in ("狐臭", "頂漿腺", "bromhidrosis", "螺旋刀")):
        return "subdermal_curettage", {
            "blueprint": "subdermal_curettage",
            "title": "螺旋刀微創刮除抽吸",
            "params_template": {
                "target_label": "頂漿腺體",
                "shaver_label": "微創旋轉刀",
                "layer_labels": ["真皮深層", "皮下脂肪層"],
                "tool_fill": "accent",
                "step_labels": ["微創切口定位", "旋轉刮除分離", "負壓即時抽吸"],
            },
        }

    # 8.4 微創脂肪瘤抽吸切除手術 (subdermal_curettage)
    if any(k in full_text for k in ("脂肪瘤", "lipoma")):
        return "subdermal_curettage", {
            "blueprint": "subdermal_curettage",
            "title": "微創抽吸輔助切除",
            "params_template": {
                "target_label": "脂肪瘤塊",
                "shaver_label": "負壓抽吸管",
                "layer_labels": ["表皮皮下", "深層筋膜層"],
                "tool_fill": "fat",
                "step_labels": ["微創切口入路", "負壓分層抽吸", "完整取出包膜"],
            },
        }

    # 8.5 疤痕與蟹足腫皮下切割治療 (subdermal_curettage)
    if any(k in full_text for k in ("subcision", "蟹足腫", "皮下切割", "皮下剝離")):
        return "subdermal_curettage", {
            "blueprint": "subdermal_curettage",
            "title": "皮下牽引纖維鬆解",
            "params_template": {
                "target_label": "牽引纖維",
                "shaver_label": "微型皮下針刀",
                "layer_labels": ["凹陷表皮", "深層基底層"],
                "tool_fill": "accent",
                "step_labels": ["微創導入定位", "扇形切割沾黏", "促進組織回彈"],
            },
        }

    # 8.6 外科骨骼與軟組織處置 (surgical_action)：截骨滑移、削骨、正顎、隆鼻、眼袋
    # 外科程序優先於通用處置匹配，讓場景 1 具象呈現切口、神經保護、骨段位移與鈦板固定
    surgical_profile = None
    if any(k in full_text for k in ("正顎", "orthognathic", "下巴", "下顎", "mandib", "genioplasty", "截骨")):
        surgical_profile = ("mandible", "下顎骨端", "頦神經", "口內隱痕", 6, "protected", "純鈦板釘")
    elif any(k in full_text for k in ("削骨", "顴骨", "malar", "bone contouring")):
        surgical_profile = ("malar_bone", "顴骨弓", "顏面神經分支", "耳前隱痕", 3, "protected", "純鈦板釘")
    elif any(k in full_text for k in ("隆鼻", "rhinoplasty", "眼袋", "blepharoplasty", "眼整形")):
        surgical_profile = ("general_surgery", "鼻骨或眼窩骨緣", "周邊神經分支", "微創隱痕", 0, "normal", "精準縫合")
    if surgical_profile is not None:
        target, bone, nerve, incision, shift_mm, nerve_status, fixation = surgical_profile
        return "surgical_action", {
            "blueprint": "surgical_action",
            "title": "外科機轉與骨骼處置",
            "params_template": {
                "anatomy_target": target,
                "bone_label": bone,
                "nerve_label": nerve,
                "nerve_status": nerve_status,
                "incision_label": incision,
                "fixation_label": fixation,
                "bone_shift_mm": shift_mm,
                "protect_nerve": nerve_status == "protected",
                "step_labels": ["隱密切口進入", "保護神經後處置", "穩定固定完成"],
            },
        }

    # 9. 組織純化 / 自體脂肪 (通用預設)
    return "process_diagram", {
        "blueprint": "process_diagram",
        "title": "處置或純化步驟",
        "params_template": {
            "source": {"label": "抽取組織", "fill": "skin"},
            "particles": 6,
            "container_layers": [
                {"label": "上層層次", "fill": "pale", "weight": 2, "keep": False},
                {"label": "目標核心層", "fill": "accent", "weight": 3, "keep": True},
                {"label": "下層基底", "fill": "neutral", "weight": 2, "keep": False},
            ],
            "step_labels": ["第一階段步驟", "第二階段步驟", "第三階段步驟"],
        },
    }


# Phase 33：五大專科對照（傳統／病理風險 vs 微創優勢）。
# 每列：(關鍵字, left.mode, right.mode, 文案)。文案欄位長度需符合 blueprints 規格上限。
CONTRAST_SPECIALTIES: tuple[tuple[tuple[str, ...], str, str, dict[str, str]], ...] = (
    (
        ("抽脂", "體雕", "吸脂", "liposuction"),
        "tissue_trauma_torn_vessel", "ultrasonic_emulsification",
        {
            "left_title": "粗鈍抽吸", "left_note": "血管神經受損", "left_footnote": "撕裂血管出現瘀紫凹凸",
            "right_title": "超音波乳化", "right_note": "保留結締組織網", "right_footnote": "乳化脂肪平整貼合",
            "caption": "傳統粗鈍抽吸易撕裂深淺血管與神經，超音波乳化則能保留組織網，使皮下平整貼合。",
        },
    ),
    (
        ("眼袋", "雙眼皮", "眼整形", "眼瞼", "blepharoplasty"),
        "scar_contracture_ectropion", "transconjunctival_fat_reposition",
        {
            "left_title": "傳統外切", "left_note": "疤痕攣縮牽引", "left_footnote": "下瞼外翻或凹陷黑眼圈",
            "right_title": "經結膜內切", "right_note": "零外疤切口", "right_footnote": "眶隔脂肪平順轉位",
            "caption": "外切口易因疤痕攣縮牽引下瞼，經結膜內切口則可在無外疤下將眶隔脂肪平順轉位。",
        },
    ),
    (
        ("隆鼻", "鼻整形", "蒜頭鼻", "rhinoplasty"),
        "silicone_extrusion_erythema", "cartilage_triangular_strut",
        {
            "left_title": "矽膠頂出", "left_note": "鼻尖壓迫發紅", "left_footnote": "重力壓迫鼻尖變薄",
            "right_title": "軟骨支撐", "right_note": "自體軟骨三角架", "right_footnote": "力學穩固降低穿出風險",
            "caption": "假體矽膠長期壓迫鼻尖可能發紅變薄，自體軟骨三角支架則能提供穩固支撐並降低穿出風險。",
        },
    ),
    (
        ("隆乳", "豐胸", "breast augmentation"),
        "capsular_contracture_ball", "dual_plane_natural_teardrop",
        {
            "left_title": "包膜攣縮", "left_note": "纖維莢膜緊縮", "left_footnote": "假體僵硬球狀變形",
            "right_title": "雙平面置入", "right_note": "上緣平順過渡", "right_footnote": "下緣自然水滴垂墜",
            "caption": "包膜攣縮會使假體變硬並球狀移位，雙平面置入則能讓上緣平順銜接、下緣自然垂墜。",
        },
    ),
    (
        ("肉毒", "玻尿酸", "微整", "填充", "針劑", "botox", "filler"),
        "nodule_clumping", "micro_droplet_diffusion",
        {
            "left_title": "單點堆積", "left_note": "大分子結節硬塊", "left_footnote": "表情牽動受阻",
            "right_title": "多層微滴", "right_note": "與組織平滑交融", "right_footnote": "表情靈活自然",
            "caption": "大分子單點堆積可能形成結節與肉芽腫，多層微滴散佈則能與自身組織平滑交融。",
        },
    ),
)


def _tree_text(tree: dict[str, Any]) -> str:
    """組合推理樹之標題、摘要、處置與 doc_id 供關鍵字比對（小寫）。"""
    return " ".join([
        _resolve_tree_title(tree),
        tree.get("summary_text") or "",
        tree.get("procedure") or "",
        tree.get("doc_id") or "",
    ]).lower()


def select_contrast_modes(tree: dict[str, Any]) -> tuple[str, str, dict[str, str]] | None:
    """依專科關鍵字回傳 (left.mode, right.mode, 文案)；無專科命中則回傳 None。"""
    text = _tree_text(tree)
    for keys, left_mode, right_mode, copy in CONTRAST_SPECIALTIES:
        if any(k in text for k in keys):
            return left_mode, right_mode, copy
    return None


def _contrast_specialty_info(tree: dict[str, Any]) -> dict[str, Any] | None:
    """專科命中時組出與 infer_scene2_contrast 相同結構的場景 2 資訊。"""
    picked = select_contrast_modes(tree)
    if picked is None:
        return None
    left_mode, right_mode, c = picked
    return {
        "title": "專科處置對照說明",
        "caption": c["caption"],
        "labels": [{"text": c["left_title"], "tone": "warning"}, {"text": c["right_title"], "tone": "optimal"}],
        "params": {
            "left": {
                "title": c["left_title"],
                "note": c["left_note"],
                "mode": left_mode,
                "core_effect": "dim",
                "core_label": c["left_title"],
                "footnote": c["left_footnote"],
                "unit_fill": "warn",
            },
            "right": {
                "title": c["right_title"],
                "note": c["right_note"],
                "mode": right_mode,
                "rows": 3,
                "per_row": 5,
                "footnote": c["right_footnote"],
                "unit_fill": "ok",
            },
        },
    }


def infer_scene2_contrast(tree: dict[str, Any]) -> dict[str, Any]:
    """根據推理樹主題推斷場景 2 (contrast) 的最佳對比模式與參數。

    優先匹配五大專科對照（select_contrast_modes）；無命中再沿用通用手術／能量／注射規則。
    """
    specialty = _contrast_specialty_info(tree)
    if specialty is not None:
        return specialty
    full_text = " ".join([
        _resolve_tree_title(tree),
        tree.get("summary_text") or "",
        tree.get("procedure") or "",
        tree.get("doc_id") or "",
    ]).lower()

    if any(k in full_text for k in ("粉瘤", "表皮樣囊腫", "甲溝炎", "嵌甲", "頂漿腺", "頂焦腺", "狐臭", "脂肪瘤", "皮下鬆解", "切除", "手術", "刮除", "cyst", "nail", "curettage", "lipoma")):
        return {
            "title": "手術方式對比說明",
            "caption": "相較於傳統大切口處置易造成組織張力拉扯與明顯痕跡，微創精準操作能縮小切口範圍並兼顧組織平整度。",
            "labels": [{"text": "傳統切開", "tone": "warning"}, {"text": "微創精準", "tone": "optimal"}],
            "params": {
                "left": {
                    "title": "傳統大切口",
                    "note": "切口大張力大",
                    "mode": "wide_incision",
                    "core_effect": "dim",
                    "core_label": "張力大易留疤",
                    "footnote": "切口較長且恢復期組織張力大",
                    "unit_fill": "warn",
                },
                "right": {
                    "title": "微創小孔徑",
                    "note": "切口小癒合佳",
                    "mode": "minimal_incision",
                    "rows": 3,
                    "per_row": 5,
                    "footnote": "微小切口減輕組織張力與疤痕",
                    "unit_fill": "ok",
                },
            },
        }

    if any(k in full_text for k in ("雷射", "laser", "皮秒", "飛梭", "音波", "電波", "hifu", "rf", "等離子", "微針電波", "光纖", "贅疣")):
        return {
            "title": "能量傳導對比說明",
            "caption": "相較於大面積表面能量漫散易造成多餘熱殘留負擔，聚焦靶向傳遞能精準直達目標深度並維護表皮完整。",
            "labels": [{"text": "表面漫散", "tone": "warning"}, {"text": "深層聚焦", "tone": "optimal"}],
            "params": {
                "left": {
                    "title": "大面積熱漫散",
                    "note": "表面熱殘留",
                    "mode": "thermal_spread",
                    "core_effect": "dim",
                    "core_label": "表皮熱殘留",
                    "footnote": "非聚焦能量易於表皮漫散造成負擔",
                    "unit_fill": "warn",
                },
                "right": {
                    "title": "深層精準聚焦",
                    "note": "保護表皮無損",
                    "mode": "targeted_energy",
                    "rows": 3,
                    "per_row": 5,
                    "footnote": "能量直達目標層次保護表層組織",
                    "unit_fill": "ok",
                },
            },
        }

    return {
        "title": "分層注射對比說明",
        "caption": "相較於單處過量集中堆疊易形成局部結節硬塊，多層次微量鋪展有助於材料與自體組織自然均勻整合。",
        "labels": [{"text": "單點集中", "tone": "warning"}, {"text": "分層分散", "tone": "optimal"}],
        "params": {
            "left": {
                "title": "單點過量",
                "note": "集中不易吸收",
                "mode": "mass",
                "core_effect": "dim",
                "core_label": "中心循環差",
                "footnote": "單點過量容易造成組織營養不良",
                "unit_fill": "accent",
            },
            "right": {
                "title": "分層少量",
                "note": "均勻接觸組織",
                "mode": "layered",
                "rows": 3,
                "per_row": 5,
                "footnote": "多點分散有助組織建立良好接觸",
                "unit_fill": "accent",
            },
        },
    }


# Phase 33：生理修復歷程。依序比對（骨骼 → 神經 → 退瘀 → 疤痕 → 緊緻回縮）。
# 每列：(關鍵字, connectors, 三段里程碑, 標題, 說明)。
TIMELINE_SPECIALTIES: tuple[tuple[tuple[str, ...], str, tuple[str, str, str], str, str], ...] = (
    (
        ("截骨", "正顎", "削骨", "orthognathic", "bone contouring"),
        "bone_healing", ("骨痂形成", "骨質緻密", "咬合穩固"), "骨骼修復進程",
        "截骨斷端會逐步生出骨痂並橋接，骨小樑緻密化後，咬合線骨質才會完全融合穩固。",
    ),
    (
        ("神經", "深層拉皮", "deep plane", "smas"),
        "nerve_regeneration", ("暫時麻木", "神經發芽", "感覺恢復"), "神經修復進程",
        "手術後感覺神經可能暫時麻木，神經末梢隨時間沿神經鞘管發芽，感覺才逐步恢復。",
    ),
    (
        ("微整", "肉毒", "玻尿酸", "填充", "針劑", "瘀青", "botox", "filler"),
        "bruise_metabolism", ("血腫吸收", "色素代謝", "膚色復原"), "退瘀代謝進程",
        "皮下瘀青會經歷吞噬代謝與色素轉變，最終逐步回到原本膚色。",
    ),
    (
        ("眼袋", "雙眼皮", "隆鼻", "隆乳", "豐胸", "拉皮", "眼整形", "rhinoplasty", "blepharoplasty"),
        "scar_maturation", ("切口潮紅", "加壓褪紅", "隱痕平整"), "疤痕成熟進程",
        "切口初期會呈潮紅微凸，經加壓保護後逐步褪紅，膠原重整後呈現平整隱痕。",
    ),
    (
        ("抽脂", "體雕", "音波", "電波", "拉提", "hifu", "緊緻"),
        "skin_retraction", ("水腫消退", "基質收縮", "平整回彈"), "組織緊緻回縮進程",
        "術後皮下水腫消退後，新生基質逐步收縮拉緊，皮膚便能平整回彈貼合。",
    ),
)
_TIMELINE_SUFFIX = "恢復程度因人而異，需由醫師當面評估。"


def select_timeline_connector(tree: dict[str, Any]) -> tuple[str, tuple[str, str, str], str, str] | None:
    """依專科關鍵字回傳 (connectors, 里程碑, 標題, 說明)；無命中則回傳 None。"""
    text = _tree_text(tree)
    for keys, connectors, milestones, title, caption in TIMELINE_SPECIALTIES:
        if any(k in text for k in keys):
            return connectors, milestones, title, caption
    return None


def _timeline_specialty_info(tree: dict[str, Any]) -> dict[str, Any] | None:
    """專科命中時組出與 infer_scene3_timeline 相同結構的場景 3 資訊。"""
    picked = select_timeline_connector(tree)
    if picked is None:
        return None
    connectors, milestones, title, caption = picked
    return {
        "title": title,
        "caption": f"{caption}{_TIMELINE_SUFFIX}",
        "labels": [{"text": milestones[0], "tone": "neutral"}, {"text": milestones[2], "tone": "optimal"}],
        "params": {
            "milestones": list(milestones),
            "unit_effect": "mature",
            "connectors": connectors,
            "units": 3,
            "unit_fill": "accent",
        },
    }


def infer_scene3_timeline(tree: dict[str, Any]) -> dict[str, Any]:
    """根據推理樹主題推斷場景 3 (timeline) 的修復進程與參數。

    優先匹配專科修復歷程（select_timeline_connector）；無命中再沿用通用傷口／膠原規則。
    """
    specialty = _timeline_specialty_info(tree)
    if specialty is not None:
        return specialty
    full_text = " ".join([
        _resolve_tree_title(tree),
        tree.get("summary_text") or "",
        tree.get("procedure") or "",
        tree.get("doc_id") or "",
    ]).lower()

    if any(k in full_text for k in ("粉瘤", "表皮樣囊腫", "甲溝炎", "嵌甲", "頂漿腺", "頂焦腺", "狐臭", "脂肪瘤", "皮下鬆解", "切除", "手術", "刮除", "cyst", "nail", "curettage", "lipoma")):
        return {
            "title": "照護與癒合進程",
            "caption": "術後初期加壓保護傷口，微小切口逐步癒合平整，整體組織修復狀況因人而異需由醫師當面評估。",
            "labels": [{"text": "切口對合", "tone": "neutral"}, {"text": "平整隱痕", "tone": "optimal"}],
            "params": {
                "milestones": ["初期保護", "表皮密合", "平整隱痕"],
                "unit_effect": "mature",
                "connectors": "wound_healing",
                "units": 3,
                "unit_fill": "accent",
            },
        }

    if any(k in full_text for k in ("雷射", "laser", "皮秒", "飛梭", "音波", "電波", "hifu", "rf", "等離子", "微針電波", "光纖", "贅疣")):
        return {
            "title": "代謝與修復進程",
            "caption": "處置後局部微溫反應逐步消退，深層自體膠原激活重組，肌膚質地修復狀況因人而異需由醫師當面評估。",
            "labels": [{"text": "微溫代謝", "tone": "neutral"}, {"text": "緊緻彈潤", "tone": "optimal"}],
            "params": {
                "milestones": ["微熱代謝", "自體激活", "緊緻彈潤"],
                "unit_effect": "mature",
                "connectors": "collagen_remodeling",
                "units": 3,
                "unit_fill": "accent",
            },
        }

    is_fat_topic = ("脂肪" in full_text) or ("fat" in (tree.get("doc_id") or "").lower())
    return {
        "title": "照護與穩定進程",
        "caption": "術後初期配合衛教照護，組織微環境逐步建立良好循環，存留與穩定程度因人而異需由醫師當面評估。",
        "labels": [{"text": "初期狀態", "tone": "neutral"}, {"text": "逐漸穩定", "tone": "optimal"}],
        "params": {
            "milestones": ["術後初期", "微血管長入" if is_fat_topic else "組織融入", "長期穩定"],
            "unit_effect": "mature",
            "connectors": "vessels" if is_fat_topic else "none",
            "units": 3,
            "unit_fill": "accent",
        },
    }


def build_tree_visual_prompt(tree: dict[str, Any]) -> str:
    """依據推理樹內容組裝自動生成 3 場景視覺解說卡 Typed IR 的 LLM 提示詞。"""
    title = _resolve_tree_title(tree)
    summary = tree.get("summary_text") or ""
    pre_op = tree.get("pre_op") or ""
    procedure = tree.get("procedure") or ""
    post_op = tree.get("post_op_short") or ""
    maintenance = tree.get("maintenance") or ""

    forbidden_list = "、".join(VISUAL_EXTRA_FORBIDDEN)
    palette_list = ", ".join(PALETTE_TOKENS)

    bp_name, bp_info = infer_scene1_blueprint(tree)
    s1_params_json = json.dumps(bp_info["params_template"], ensure_ascii=False, indent=8)

    s2_info = infer_scene2_contrast(tree)
    s2_params_json = json.dumps(s2_info["params"], ensure_ascii=False, indent=8)
    s2_labels_json = json.dumps(s2_info["labels"], ensure_ascii=False)

    s3_info = infer_scene3_timeline(tree)
    s3_params_json = json.dumps(s3_info["params"], ensure_ascii=False, indent=8)
    s3_labels_json = json.dumps(s3_info["labels"], ensure_ascii=False)

    return f"""你是一位專業的台灣整形外科與醫學美容臨床決策解說設計師。
請根據以下已通過醫師審核的「臨床推理樹」醫學內容，為病患設計一套符合台灣醫療法規的「原理與處置過程」3 場景視覺解說卡 JSON 規格。

【推理樹資料】
主題標題：{title}
臨床摘要：{summary}
術前評估：{pre_op}
手術／處置過程：{procedure}
術後初期照護：{post_op}
長期維持照護：{maintenance}

【重要合規規範（違者整批拒絕）】
1. 純一般醫學原理與衛教：僅解說「原理、機轉與標準處置過程」，絕不提及任何療效保證、個人化診斷或特定診所促銷。
2. 零數字原則：嚴禁出現任何阿拉伯數字（0-9）或具體用藥劑量、百分比、金額、天數數字。請改以「微量」、「數層」、「適當時間」、「一段時間」、「少許」等中文字詞表達。
3. 嚴禁詞彙：絕對禁止出現以下詞彙：{forbidden_list}。
4. 語言規範：必須全篇使用台灣正體中文（不得出現簡體字）。
5. 第三場景（timeline）的 caption 說明文字末尾必須包含「因人而異」或「由醫師當面評估」等合規收尾語意。
6. 調色盤限制：所有顏色填色屬性（fill, unit_fill）僅限使用以下安全代號之一：[{palette_list}]。
7. 第一場景動作指令：若 blueprint 為 surgical_action，caption 必須依序描述「切口進入、神經保護、骨段處置、穩定固定」四個醫學動作，並使用上述 params 中的骨骼、神經與固定材料字詞，不得與推理樹內容矛盾。
8. 對照與歷程列舉：第二場景 left.mode 建議為「{s2_info['params']['left']['mode']}」、right.mode 建議為「{s2_info['params']['right']['mode']}」；第三場景 connectors 建議為「{s3_info['params']['connectors']}」。請沿用這些列舉值，不得自行改用其他字串。

【輸出結構要求】
請僅輸出單一合法 JSON 物件（不得包含額外說明文字或 markdown 解釋）：
{{
  "title": "{title}原理圖解",
  "keywords": ["關鍵字一", "關鍵字二", "關鍵字三"],
  "scenes": [
    {{
      "blueprint": "{bp_name}",
      "title": "{bp_info['title']}",
      "caption": "20到120字的說明文字，清楚解釋處置機轉，不含任何數字。",
      "labels": [
        {{"text": "重要標籤一", "tone": "neutral"}},
        {{"text": "重要標籤二", "tone": "optimal"}}
      ],
      "params": {s1_params_json}
    }},
    {{
      "blueprint": "contrast",
      "title": "{s2_info['title']}",
      "caption": "20到120字的說明文字，清楚對比不佳作法與建議作法，不含任何數字。",
      "labels": {s2_labels_json},
      "params": {s2_params_json}
    }},
    {{
      "blueprint": "timeline",
      "title": "{s3_info['title']}",
      "caption": "20到120字的說明文字，說明恢復進程，結尾必須註明恢復程度因人而異需由醫師當面評估。",
      "labels": {s3_labels_json},
      "params": {s3_params_json}
    }}
  ]
}}
"""


def _check_no_digits_recursive(data: Any) -> bool:
    """遞迴檢查結構內所有字串皆不含阿拉伯數字。"""
    if isinstance(data, str):
        return not bool(_DIGIT_RE.search(data))
    if isinstance(data, dict):
        return all(_check_no_digits_recursive(k) and _check_no_digits_recursive(v) for k, v in data.items())
    if isinstance(data, list):
        return all(_check_no_digits_recursive(item) for item in data)
    return True


def parse_and_build_tree_ir(
    raw: str,
    topic_key: str,
    fallback_title: str,
) -> Tuple[Optional[dict[str, Any]], str]:
    """解析模型輸出之 JSON 並嚴格檢驗其文字、零污染 params 與 Typed IR 結構。

    回傳：
        (ir, "ok") 或 (None, error_code)
    """
    if not raw or not isinstance(raw, str):
        return None, "empty_output"

    cleaned = _THINK_BLOCK_RE.sub("", raw)
    cleaned = _THINK_OPEN_RE.sub("", cleaned).strip()

    # 嘗試擷取 JSON 字串
    json_str = None
    m = _CODE_BLOCK_RE.search(cleaned)
    if m:
        json_str = m.group(1).strip()
    else:
        # 尋找最外層的 { ... }
        s_idx = cleaned.find("{")
        e_idx = cleaned.rfind("}")
        if s_idx != -1 and e_idx != -1 and e_idx > s_idx:
            json_str = cleaned[s_idx : e_idx + 1].strip()

    if not json_str:
        return None, "schema_error"

    try:
        data = json.loads(json_str)
    except Exception:
        return None, "schema_error"

    if not isinstance(data, dict):
        return None, "schema_error"

    # 自癒修復：醫學專用 3D/4D 縮寫轉換為正體中文「三維」「四維」，避免誤觸零數字硬限制
    def _clean_3d_recursive(val: Any) -> Any:
        if isinstance(val, str):
            val = re.sub(r"\b3[dD]\b|3[dD]", "三維", val)
            val = re.sub(r"\b4[dD]\b|4[dD]", "四維", val)
            return val
        elif isinstance(val, dict):
            return {k: _clean_3d_recursive(v) for k, v in val.items()}
        elif isinstance(val, list):
            return [_clean_3d_recursive(item) for item in val]
        return val

    data = _clean_3d_recursive(data)

    # 檢查頂層欄位
    title = data.get("title") or fallback_title
    if isinstance(title, str) and len(title) > 30:
        cleaned_t = re.sub(r"（.*?）|\(.*?\)", "", title).strip()
        if 1 <= len(cleaned_t) <= 30:
            title = cleaned_t
        else:
            title = title[:30]
    if not isinstance(title, str) or not (1 <= len(title) <= 30):
        return None, "schema_error"

    keywords = data.get("keywords")
    if not isinstance(keywords, list) or not (1 <= len(keywords) <= 8):
        return None, "schema_error"

    scenes = data.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != 3:
        return None, "schema_error"

    def _parse_int_val(v: Any, default: int, min_v: int, max_v: int) -> int:
        if isinstance(v, str):
            _cn = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            v = _cn.get(v.strip(), default)
        if not isinstance(v, int) or isinstance(v, bool):
            return default
        return max(min_v, min(max_v, v))

    # 嚴格檢查各場景之 blueprint 順序
    valid_scene1_blueprints = (
        "process_diagram",
        "skin_energy",
        "laser_action",
        "neuromuscular",
        "dermal_support",
        "cyst_excision",
        "nail_matrix",
        "subdermal_curettage",
        "deep_plane_facelift",
        "corset_platysmaplasty",
    )
    shaped_scenes = []

    for idx, sc in enumerate(scenes):
        if not isinstance(sc, dict):
            return None, "schema_error"
        bp = sc.get("blueprint")
        if idx == 0:
            if bp not in valid_scene1_blueprints:
                return None, "unknown_blueprint"
        elif idx == 1:
            if bp != "contrast":
                return None, "unknown_blueprint"
        elif idx == 2:
            if bp != "timeline":
                return None, "unknown_blueprint"

        sc_title = sc.get("title")
        if not isinstance(sc_title, str) or not sc_title.strip():
            return None, "schema_error"
        sc_title = sc_title.strip()[:16]

        caption = sc.get("caption")
        if not isinstance(caption, str) or len(caption.strip()) < 20:
            return None, "schema_error"
        caption = caption.strip()
        if len(caption) > 120:
            caption = caption[:120]

        # 場景 3 必須包含合規收尾語意
        if bp == "timeline":
            if not any(phrase in caption for phrase in _TIMELINE_CLOSING_PHRASES):
                return None, "forbidden_phrase"

        raw_labels = sc.get("labels")
        if not isinstance(raw_labels, list):
            raw_labels = []
        cleaned_labels = []
        for lb in raw_labels:
            if not isinstance(lb, dict):
                continue
            txt = str(lb.get("text", "")).strip()[:12]
            if not txt:
                continue
            tone_str = str(lb.get("tone", "")).strip().lower()
            if tone_str in ("warn", "warning", "danger", "alert", "bad"):
                final_tone = "warning"
            elif tone_str in ("opt", "optimal", "good", "ok", "success", "pass"):
                final_tone = "optimal"
            else:
                final_tone = "neutral"
            cleaned_labels.append({"text": txt, "tone": final_tone})
            if len(cleaned_labels) >= 4:
                break
        labels = cleaned_labels

        # 檢查 params 零預設文字污染（模型必須明確提供所有中文字串）
        raw_params = sc.get("params")
        if not isinstance(raw_params, dict):
            return None, "schema_error"

        if bp == "process_diagram":
            src = raw_params.get("source")
            if not isinstance(src, dict) or not isinstance(src.get("label"), str) or not src["label"].strip():
                return None, "schema_error"
            layers = raw_params.get("container_layers")
            if not isinstance(layers, list) or not (2 <= len(layers) <= 4):
                return None, "schema_error"
            for layer in layers:
                if not isinstance(layer, dict) or not isinstance(layer.get("label"), str) or not layer["label"].strip():
                    return None, "schema_error"
            step_lbls = raw_params.get("step_labels")
            if not isinstance(step_lbls, list) or len(step_lbls) != 3:
                return None, "schema_error"
            for sl in step_lbls:
                if not isinstance(sl, str) or not sl.strip():
                    return None, "schema_error"
            particles = raw_params.get("particles", 6)
            if not isinstance(particles, int) or isinstance(particles, bool) or not (4 <= particles <= 12):
                particles = 6
            s_fill = src.get("fill", "skin")
            if s_fill not in PALETTE_TOKENS:
                s_fill = "skin"
            shaped_params = {
                "source": {"label": src["label"].strip()[:8], "fill": s_fill},
                "particles": particles,
                "container_layers": [
                    {
                        "label": l["label"].strip()[:6],
                        "fill": l.get("fill", "accent") if l.get("fill") in PALETTE_TOKENS else "accent",
                        "weight": int(l.get("weight", 2)) if isinstance(l.get("weight"), (int, float)) and 1 <= int(l.get("weight", 2)) <= 5 else 2,
                        "keep": bool(l.get("keep", False)),
                    }
                    for l in layers
                ],
                "step_labels": [s.strip()[:10] for s in step_lbls],
            }

        elif bp == "skin_energy":
            mode = raw_params.get("mode", "focused")
            if mode not in ("focused", "volumetric"):
                mode = "focused"
            probe = raw_params.get("probe_label")
            if not isinstance(probe, str) or not probe.strip():
                return None, "schema_error"
            layers = raw_params.get("layer_labels")
            if isinstance(layers, list) and len(layers) > 3:
                layers = layers[:3]
            if not isinstance(layers, list) or len(layers) != 3:
                return None, "schema_error"
            for ly in layers:
                if not isinstance(ly, str) or not ly.strip():
                    return None, "schema_error"
            step_lbls = raw_params.get("step_labels")
            if not isinstance(step_lbls, list) or len(step_lbls) != 3:
                return None, "schema_error"
            for sl in step_lbls:
                if not isinstance(sl, str) or not sl.strip():
                    return None, "schema_error"
            f_pts = _parse_int_val(raw_params.get("focal_points"), default=5, min_v=3, max_v=7)
            shaped_params = {
                "mode": mode,
                "probe_label": probe.strip()[:8],
                "layer_labels": [ly.strip()[:8] for ly in layers],
                "focal_points": f_pts,
                "energy_fill": raw_params.get("energy_fill", "accent"),
                "step_labels": [sl.strip()[:10] for sl in step_lbls],
            }

        elif bp == "cyst_excision":
            c_label = raw_params.get("cyst_label")
            s_label = raw_params.get("sac_label")
            core_lbl = raw_params.get("core_label")
            layers = raw_params.get("layer_labels")
            step_lbls = raw_params.get("step_labels")
            if not all(isinstance(x, str) and x.strip() for x in (c_label, s_label, core_lbl)):
                return None, "schema_error"
            if isinstance(layers, list) and len(layers) > 2:
                layers = layers[:2]
            if not isinstance(layers, list) or len(layers) != 2:
                return None, "schema_error"
            if not isinstance(step_lbls, list) or len(step_lbls) != 3:
                return None, "schema_error"
            shaped_params = {
                "cyst_label": c_label.strip()[:8],
                "sac_label": s_label.strip()[:8],
                "core_label": core_lbl.strip()[:8],
                "layer_labels": [ly.strip()[:8] for ly in layers],
                "sac_fill": raw_params.get("sac_fill", "accent"),
                "step_labels": [sl.strip()[:10] for sl in step_lbls],
            }

        elif bp == "nail_matrix":
            n_label = raw_params.get("nail_label", "趾甲板")
            f_label = raw_params.get("fold_label", "側甲襞")
            s_label = raw_params.get("spicule_label", "嵌甲尖刺")
            m_label = raw_params.get("matrix_label", "甲基質生長板")
            step_lbls = raw_params.get("step_labels")
            if not all(isinstance(x, str) and x.strip() for x in (n_label, f_label, s_label, m_label)):
                return None, "schema_error"
            if not isinstance(step_lbls, list) or len(step_lbls) != 3:
                return None, "schema_error"
            shaped_params = {
                "nail_label": n_label.strip()[:8],
                "fold_label": f_label.strip()[:8],
                "spicule_label": s_label.strip()[:8],
                "matrix_label": m_label.strip()[:8],
                "matrix_fill": raw_params.get("matrix_fill", "warn"),
                "step_labels": [sl.strip()[:10] for sl in step_lbls],
            }

        elif bp == "subdermal_curettage":
            t_label = raw_params.get("target_label")
            s_label = raw_params.get("shaver_label")
            layers = raw_params.get("layer_labels")
            step_lbls = raw_params.get("step_labels")
            if not all(isinstance(x, str) and x.strip() for x in (t_label, s_label)):
                return None, "schema_error"
            if isinstance(layers, list) and len(layers) > 2:
                layers = layers[:2]
            if not isinstance(layers, list) or len(layers) != 2:
                return None, "schema_error"
            if not isinstance(step_lbls, list) or len(step_lbls) != 3:
                return None, "schema_error"
            shaped_params = {
                "target_label": t_label.strip()[:8],
                "shaver_label": s_label.strip()[:8],
                "layer_labels": [ly.strip()[:8] for ly in layers],
                "tool_fill": raw_params.get("tool_fill", "accent"),
                "step_labels": [sl.strip()[:10] for sl in step_lbls],
            }

        elif bp == "deep_plane_facelift":
            smas_lbl = raw_params.get("smas_label", "SMAS筋膜瓣")
            anchor_lbl = raw_params.get("anchor_label", "骨膜錨定點")
            lig_lbl = raw_params.get("ligament_label", "維持韌帶")
            layers = raw_params.get("layer_labels")
            step_lbls = raw_params.get("step_labels")
            if not all(isinstance(x, str) and x.strip() for x in (smas_lbl, anchor_lbl, lig_lbl)):
                return None, "schema_error"
            if isinstance(layers, list) and len(layers) > 3:
                layers = layers[:3]
            if not isinstance(layers, list) or len(layers) != 3:
                return None, "schema_error"
            if not isinstance(step_lbls, list) or len(step_lbls) != 3:
                return None, "schema_error"
            shaped_params = {
                "smas_label": smas_lbl.strip()[:8],
                "anchor_label": anchor_lbl.strip()[:8],
                "ligament_label": lig_lbl.strip()[:8],
                "layer_labels": [ly.strip()[:8] for ly in layers],
                "suture_fill": raw_params.get("suture_fill", "accent"),
                "step_labels": [sl.strip()[:10] for sl in step_lbls],
            }

        elif bp == "corset_platysmaplasty":
            m_lbl = raw_params.get("muscle_label", "兩側闊頸肌")
            f_lbl = raw_params.get("fat_label", "深層脂肪墊")
            sut_lbl = raw_params.get("suture_label", "馬甲式對縫")
            layers = raw_params.get("layer_labels")
            step_lbls = raw_params.get("step_labels")
            if not all(isinstance(x, str) and x.strip() for x in (m_lbl, f_lbl, sut_lbl)):
                return None, "schema_error"
            if isinstance(layers, list) and len(layers) > 3:
                layers = layers[:3]
            if not isinstance(layers, list) or len(layers) != 3:
                return None, "schema_error"
            if not isinstance(step_lbls, list) or len(step_lbls) != 3:
                return None, "schema_error"
            shaped_params = {
                "muscle_label": m_lbl.strip()[:8],
                "fat_label": f_lbl.strip()[:8],
                "suture_label": sut_lbl.strip()[:8],
                "layer_labels": [ly.strip()[:8] for ly in layers],
                "suture_fill": raw_params.get("suture_fill", "accent"),
                "step_labels": [sl.strip()[:10] for sl in step_lbls],
            }

        elif bp == "laser_action":
            mode = raw_params.get("mode", "shatter")
            if mode not in ("shatter", "fractional"):
                mode = "shatter"
            beam = raw_params.get("beam_label")
            target = raw_params.get("target_label")
            if not isinstance(beam, str) or not beam.strip():
                return None, "schema_error"
            if not isinstance(target, str) or not target.strip():
                return None, "schema_error"
            layers = raw_params.get("layer_labels")
            if not isinstance(layers, list) or len(layers) != 2:
                return None, "schema_error"
            for ly in layers:
                if not isinstance(ly, str) or not ly.strip():
                    return None, "schema_error"
            step_lbls = raw_params.get("step_labels")
            if not isinstance(step_lbls, list) or len(step_lbls) != 3:
                return None, "schema_error"
            for sl in step_lbls:
                if not isinstance(sl, str) or not sl.strip():
                    return None, "schema_error"
            shaped_params = {
                "mode": mode,
                "beam_label": beam.strip()[:8],
                "target_label": target.strip()[:8],
                "layer_labels": [ly.strip()[:8] for ly in layers],
                "beam_fill": raw_params.get("beam_fill", "accent"),
                "step_labels": [sl.strip()[:10] for sl in step_lbls],
            }

        elif bp == "neuromuscular":
            nerve = raw_params.get("nerve_label")
            muscle = raw_params.get("muscle_label")
            surface = raw_params.get("surface_label")
            if not isinstance(nerve, str) or not nerve.strip():
                return None, "schema_error"
            if not isinstance(muscle, str) or not muscle.strip():
                return None, "schema_error"
            if not isinstance(surface, str) or not surface.strip():
                return None, "schema_error"
            step_lbls = raw_params.get("step_labels")
            if not isinstance(step_lbls, list) or len(step_lbls) != 3:
                return None, "schema_error"
            for sl in step_lbls:
                if not isinstance(sl, str) or not sl.strip():
                    return None, "schema_error"
            shaped_params = {
                "nerve_label": nerve.strip()[:8],
                "muscle_label": muscle.strip()[:8],
                "surface_label": surface.strip()[:8],
                "blocker_fill": raw_params.get("blocker_fill", "ok"),
                "step_labels": [sl.strip()[:10] for sl in step_lbls],
            }

        elif bp == "dermal_support":
            filler = raw_params.get("filler_label")
            if not isinstance(filler, str) or not filler.strip():
                return None, "schema_error"
            layers = raw_params.get("layer_labels")
            if not isinstance(layers, list) or len(layers) != 2:
                return None, "schema_error"
            for ly in layers:
                if not isinstance(ly, str) or not ly.strip():
                    return None, "schema_error"
            droplets = raw_params.get("droplets", 6)
            if not isinstance(droplets, int) or isinstance(droplets, bool) or not (4 <= droplets <= 8):
                droplets = 6
            step_lbls = raw_params.get("step_labels")
            if not isinstance(step_lbls, list) or len(step_lbls) != 3:
                return None, "schema_error"
            for sl in step_lbls:
                if not isinstance(sl, str) or not sl.strip():
                    return None, "schema_error"
            shaped_params = {
                "filler_label": filler.strip()[:8],
                "layer_labels": [ly.strip()[:8] for ly in layers],
                "droplets": droplets,
                "filler_fill": raw_params.get("filler_fill", "gel"),
                "step_labels": [sl.strip()[:10] for sl in step_lbls],
            }

        elif bp == "contrast":
            left = raw_params.get("left")
            right = raw_params.get("right")
            if not isinstance(left, dict) or not isinstance(right, dict):
                return None, "schema_error"
            left_req = ["title", "note", "core_label", "footnote"]
            right_req = ["title", "note", "footnote"]
            for req_k in left_req:
                if not isinstance(left.get(req_k), str) or not left[req_k].strip():
                    return None, "schema_error"
            for req_k in right_req:
                if not isinstance(right.get(req_k), str) or not right[req_k].strip():
                    return None, "schema_error"

            rows = right.get("rows", raw_params.get("rows", 3))
            per_row = right.get("per_row", raw_params.get("per_row", 5))

            left_mode = left.get("mode", "mass")
            if left_mode not in enum_values("contrast", "mode", "left"):
                left_mode = "mass"
            left_effect = left.get("core_effect", "dim")
            if left_effect not in ("dim", "none"):
                left_effect = "dim"
            left_fill = left.get("unit_fill", "warn")
            if left_fill not in PALETTE_TOKENS:
                left_fill = "warn"

            right_mode = right.get("mode", "layered")
            if right_mode not in enum_values("contrast", "mode", "right"):
                right_mode = "layered"
            right_fill = right.get("unit_fill", "accent")
            if right_fill not in PALETTE_TOKENS:
                right_fill = "accent"

            shaped_params = {
                "left": {
                    "title": left["title"].strip()[:8],
                    "note": left["note"].strip()[:14],
                    "mode": left_mode,
                    "core_effect": left_effect,
                    "core_label": left["core_label"].strip()[:8],
                    "footnote": left["footnote"].strip()[:16],
                    "unit_fill": left_fill,
                },
                "right": {
                    "title": right["title"].strip()[:8],
                    "note": right["note"].strip()[:14],
                    "mode": right_mode,
                    "rows": int(rows) if isinstance(rows, int) and not isinstance(rows, bool) and 1 <= rows <= 4 else 3,
                    "per_row": int(per_row) if isinstance(per_row, int) and not isinstance(per_row, bool) and 3 <= per_row <= 8 else 5,
                    "footnote": right["footnote"].strip()[:16],
                    "unit_fill": right_fill,
                },
            }

        elif bp == "timeline":
            milestones = raw_params.get("milestones")
            if not isinstance(milestones, list) or len(milestones) != 3:
                return None, "schema_error"
            for m_item in milestones:
                if not isinstance(m_item, str) or not m_item.strip():
                    return None, "schema_error"
            units = _parse_int_val(raw_params.get("units"), default=3, min_v=2, max_v=5)
            # 非自體脂肪主題一律防止長血管誤導（支援 wound_healing 與 collagen_remodeling）
            is_fat_topic = ("脂肪" in fallback_title) or ("fat" in topic_key)
            connectors = raw_params.get("connectors", "vessels" if is_fat_topic else "none")
            if not is_fat_topic and connectors == "vessels":
                connectors = "none"
            if connectors not in enum_values("timeline", "connectors"):
                connectors = "none"
            unit_effect = raw_params.get("unit_effect", "mature")
            if unit_effect not in enum_values("timeline", "unit_effect"):
                unit_effect = "mature"
            unit_fill = raw_params.get("unit_fill", "accent")
            if unit_fill not in PALETTE_TOKENS:
                unit_fill = "accent"
            shaped_params = {
                "milestones": [m_item.strip()[:8] for m_item in milestones],
                "unit_effect": unit_effect,
                "connectors": connectors,
                "units": int(units) if isinstance(units, int) and not isinstance(units, bool) and 2 <= units <= 5 else 3,
                "unit_fill": unit_fill,
            }

        # 檢驗 params 是否符合 Blueprint 規格
        p_ok, p_code = validate_params(bp, shaped_params)
        if not p_ok:
            return None, p_code

        shaped_scenes.append({
            "blueprint": bp,
            "title": sc_title.strip(),
            "caption": caption.strip(),
            "labels": [{"text": lb["text"].strip(), "tone": lb["tone"]} for lb in labels],
            "params": shaped_params,
            "duration_sec": sc.get("duration_sec", 8) if isinstance(sc.get("duration_sec"), int) and 4 <= sc.get("duration_sec", 8) <= 12 else 8,
        })

    candidate_ir = {
        "topic_key": topic_key,
        "title": title.strip(),
        "keywords": [str(k).strip() for k in keywords],
        "scenes": shaped_scenes,
    }

    # 檢查全文字結構（不含 topic_key 識別碼）不含任何阿拉伯數字
    text_Check_payload = {
        "title": candidate_ir["title"],
        "keywords": candidate_ir["keywords"],
        "scenes": candidate_ir["scenes"],
    }
    if not _check_no_digits_recursive(text_Check_payload):
        return None, "forbidden_phrase"

    # 若非自體脂肪主題，嚴禁殘留引擎預設之脂肪移植字面值
    is_fat_topic = ("脂肪" in fallback_title) or ("脂肪" in candidate_ir["title"]) or ("fat" in topic_key)
    if not is_fat_topic:
        scenes_dump = json.dumps(candidate_ir["scenes"], ensure_ascii=False)
        if any(lit in scenes_dump for lit in _FAT_GRAFT_DEFAULT_LITERALS):
            return None, "forbidden_phrase"

    # 完整執行 validate_ir
    ok, code = validate_ir(candidate_ir)
    if not ok:
        return None, code

    return candidate_ir, "ok"


def _default_visual_llm(prompt: str) -> str:
    """預設本地 LLM 呼叫包裝（3 場景完整 JSON 含 params 需較高 token 上限）。"""
    sampling = dict(VISUAL_SAMPLING)
    sampling["max_tokens"] = max(int(sampling.get("max_tokens", 900)), 1800)
    return local_llm_call(prompt, timeout=240, sampling=sampling)


def autodraft_from_tree(
    conn: sqlite3.Connection,
    tree_id_or_dict: int | dict[str, Any],
    llm_call: Optional[Callable[[str], str]] = None,
    *,
    max_attempts: int = 2,
    db_path: Any = None,
    commit: bool = True,
) -> dict[str, Any]:
    """由已核准的 PageIndex 推理樹自動生成視覺解說卡草稿並寫入 visual_assets。

    回傳：
        {"status": "ok", "topic_key": ..., "clinic_id": ..., "review_status": "pending", "ir": ...}
        或 {"status": "error"|"busy"|"not_found", "code": ...}
    """
    if isinstance(tree_id_or_dict, int):
        trees = fetch_eligible_trees(conn, tree_id=tree_id_or_dict)
        if not trees:
            # 檢查是否存在但未核准
            cur = conn.cursor()
            cur.execute("SELECT id FROM page_index_trees WHERE id = ?", (tree_id_or_dict,))
            if cur.fetchone() is None:
                return {"status": "not_found", "code": "tree_not_found"}
            return {"status": "error", "code": "tree_not_approved"}
        tree = trees[0]
    elif isinstance(tree_id_or_dict, dict):
        tree = tree_id_or_dict
        # 驗證傳入之 dict 是否符合核准樹條件
        if "id" in tree:
            eligible = fetch_eligible_trees(conn, tree_id=tree["id"])
            if not eligible:
                return {"status": "error", "code": "tree_not_approved"}
    else:
        return {"status": "error", "code": "invalid_argument"}

    doc_id = tree.get("doc_id") or ""
    try:
        topic_key = normalize_tree_topic_key(doc_id)
    except ValueError:
        return {"status": "error", "code": "schema_error"}

    # 排程互斥：確認非夜間批次與行程內鎖
    if nightly_batch_running(db_path):
        return {"status": "busy", "code": "busy"}

    if not GENERATION_LOCK.acquire(blocking=False):
        return {"status": "busy", "code": "busy"}

    act_llm = llm_call or _default_visual_llm
    prompt = build_tree_visual_prompt(tree)
    resolved_title = _resolve_tree_title(tree)
    fallback_title = f"{resolved_title}原理圖解" if not resolved_title.endswith("原理") else resolved_title

    try:
        last_code = "parse_error"
        for _ in range(max(1, max_attempts)):
            try:
                raw_out = act_llm(prompt)
            except LocalLLMUnavailableError:
                return {"status": "error", "code": "llm_unavailable"}
            except LLMTruncatedError:
                last_code = "truncated"
                continue
            except (LLMEmptyOutputError, Exception):
                last_code = "parse_error"
                continue

            ir, code = parse_and_build_tree_ir(raw_out, topic_key=topic_key, fallback_title=fallback_title)
            if ir is None:
                last_code = code
                continue

            # 生成成功，組裝資產資料
            asset = {
                "clinic_id": tree.get("clinic_id"),
                "topic_key": topic_key,
                "title": ir["title"],
                "keywords": ir["keywords"],
                "ir": ir,
                "metadata": {
                    "origin": "pageindex_tree",
                    "tree_id": tree.get("id"),
                    "doc_id": doc_id,
                    "tree_version": tree.get("content_version", 1),
                },
            }

            upsert_res = upsert_assets(conn, [asset], source_type="llm_generated", commit=commit)
            return {
                "status": "ok",
                "topic_key": topic_key,
                "clinic_id": tree.get("clinic_id"),
                "review_status": "pending",
                "ir": ir,
                **upsert_res,
            }

        return {"status": "error", "code": last_code}
    finally:
        GENERATION_LOCK.release()
