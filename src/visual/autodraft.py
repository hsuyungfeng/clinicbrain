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
import os
from datetime import datetime, timezone
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
from .blueprints import BLUEPRINTS, PALETTE_TOKENS, default_params, enum_values, validate_params
from .ir import (
    VISUAL_EXTRA_FORBIDDEN,
    validate_ir,
    validate_visual_text,
)
from .writer import upsert_assets
from .harness_optimizer import (
    EXCELLENT_THRESHOLD,
    build_alignment_critique_prompt,
    format_lessons_for_prompt,
    score_visual_ir_alignment,
    select_lessons_for_tree,
)

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
    """（Phase 34）若草稿有 template_override 且為已註冊模板，直接採用，不做關鍵字推斷。"""
    override = tree.get("template_override")
    if isinstance(override, str) and override in BLUEPRINTS:
        return override, {"blueprint": override, "title": "依醫師指定模板", "params_template": default_params(override)}
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

    # 8. 專屬外科核心解剖處置
    # 8.1 外科骨骼與軟組織處置 (surgical_action)：截骨滑移、削骨、正顎、隆鼻、眼袋
    # 外科程序優先於通用能量處置匹配，讓場景 1 具象呈現切口、神經保護、骨段位移與鈦板固定
    surgical_profile = None
    # 非侵入能量儀器（音波／電波）內文常提及「下顎線」等部位詞，不得誤判為外科骨骼處置
    is_energy_device = any(k in full_text for k in ("音波", "電波", "hifu", "ultherapy", "ultraformer", "thermage"))
    if is_energy_device:
        pass
    elif any(k in full_text for k in ("正顎", "orthognathic", "下巴", "下顎", "mandib", "genioplasty", "截骨")):
        surgical_profile = ("mandible", "下顎骨端", "頦神經", "口內隱痕", 6, "protected", "純鈦板釘")
    elif any(k in full_text for k in ("削骨", "顴骨", "malar", "bone contouring")):
        surgical_profile = ("malar_bone", "顴骨弓", "顏面神經分支", "耳前隱痕", 3, "protected", "純鈦板釘")
    elif any(k in full_text for k in ("隆鼻", "rhinoplasty", "眼袋", "blepharoplasty", "眼整形", "雙眼皮", "產後媽媽", "腹直肌", "身形修復")):
        surgical_profile = ("general_surgery", "筋膜組織與骨架", "周邊感覺神經", "隱痕切口", 0, "normal", "分層精密縫合")
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

    # 8.2 未感染粉瘤微創旋轉吸引切除手術 (cyst_excision)
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

    # 8.3 甲溝炎嵌甲甲床重整手術 (nail_matrix)
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

    # 8.4 頂漿腺狐臭手術 (subdermal_curettage)
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

    # 8.5 微創脂肪瘤抽吸切除手術 (subdermal_curettage)
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

    # 8.6 疤痕與蟹足腫皮下切割治療 (subdermal_curettage)
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

    # 8.7 FUE 微創毛囊單位精準植髮 (subdermal_curettage)
    if any(k in full_text for k in ("植髮", "毛囊", "fue", "hair-transplantation")):
        return "subdermal_curettage", {
            "blueprint": "subdermal_curettage",
            "title": "微創鑽取與顯微毛囊移植",
            "params_template": {
                "target_label": "毛囊單位",
                "shaver_label": "微創鑽取針",
                "layer_labels": ["頭皮表層", "深層毛囊層"],
                "tool_fill": "accent",
                "step_labels": ["顯微環鑽提取", "精細分株修整", "依毛流角植入"],
            },
        }

    # 8.8 音波 / 電波能量拉提
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


def _build_tree_visual_prompt_base(tree: dict[str, Any]) -> str:
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


_PATHOLOGY_ORGAN_SYSTEMS: tuple[str, ...] = tuple(BLUEPRINTS["pathology_mechanism"]["params"]["organ_system"]["values"])
_PATHOLOGY_ORGAN_DEFAULT_LABEL: dict[str, str] = {
    "respiratory_mucosa": "呼吸道黏膜",
    "vascular_metabolic": "動脈管壁",
    "gi_tract": "胃腸黏膜",
    "skin_barrier": "表皮屏障",
    "joint_spine": "關節軟骨",
    "uro_pelvic": "膀胱黏膜",
}


def _shape_pathology_params(raw_params: dict[str, Any]) -> dict[str, Any]:
    """將模型輸出塑形為 pathology_mechanism 註冊規格；缺漏欄位以規格預設補齊（單一來源 BLUEPRINTS）。

    註：規格欄位為 organ_label／trigger_label／defense_label／accent_fill；
    提示詞中的 highlight_fill 對應 accent_fill，不在規格內的欄位一律捨棄。
    """
    shaped = default_params("pathology_mechanism")
    organ = raw_params.get("organ_system", shaped["organ_system"])
    shaped["organ_system"] = organ if organ in _PATHOLOGY_ORGAN_SYSTEMS else "respiratory_mucosa"
    if not (isinstance(raw_params.get("organ_label"), str) and raw_params["organ_label"].strip()):
        shaped["organ_label"] = _PATHOLOGY_ORGAN_DEFAULT_LABEL[shaped["organ_system"]]
    for key in ("organ_label", "lesion_label", "trigger_label", "defense_label"):
        val = raw_params.get(key)
        if isinstance(val, str) and val.strip():
            shaped[key] = val.strip()[:8]
    sev = raw_params.get("severity_level")
    if isinstance(sev, int) and not isinstance(sev, bool) and 1 <= sev <= 5:
        shaped["severity_level"] = sev
    fill = raw_params.get("accent_fill", raw_params.get("highlight_fill"))
    if fill in PALETTE_TOKENS:
        shaped["accent_fill"] = fill
    steps = raw_params.get("step_labels")
    if isinstance(steps, list) and len(steps) == 3 and all(isinstance(x, str) and x.strip() for x in steps):
        shaped["step_labels"] = [x.strip()[:10] for x in steps]
    return shaped


def _shape_scene_labels(raw_labels: Any) -> list[dict[str, str]]:
    if not isinstance(raw_labels, list):
        return []
    cleaned_labels: list[dict[str, str]] = []
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
    return cleaned_labels


def parse_and_build_tree_ir(
    raw: str,
    topic_key: str,
    fallback_title: str,
) -> Tuple[Optional[dict[str, Any]], str]:
    """解析模型輸出之 JSON 並嚴格檢驗其文字、零污染 params 與 Typed IR 結構。

    回傳：
        (ir, "ok") 或 (None, error_code)
    """
    from src.visual.autodraft_ir import (
        VALID_SCENE1_BLUEPRINTS,
        extract_ir_json,
        shape_scene1_params,
        shape_scene2_contrast_params,
        shape_scene3_timeline_params,
    )

    data, err_code = extract_ir_json(raw)
    if data is None:
        return None, err_code

    title = data.get("title") or fallback_title
    if isinstance(title, str) and len(title) > 30:
        cleaned_t = re.sub(r"（.*?）|\(.*?\)", "", title).strip()
        title = cleaned_t if 1 <= len(cleaned_t) <= 30 else title[:30]
    if not isinstance(title, str) or not (1 <= len(title) <= 30):
        return None, "schema_error"

    keywords = data.get("keywords")
    if not isinstance(keywords, list) or not (1 <= len(keywords) <= 8):
        return None, "schema_error"

    scenes = data.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != 3:
        return None, "schema_error"

    shaped_scenes = []
    for idx, sc in enumerate(scenes):
        if not isinstance(sc, dict):
            return None, "schema_error"
        bp = sc.get("blueprint")
        if idx == 0 and bp not in VALID_SCENE1_BLUEPRINTS:
            return None, "unknown_blueprint"
        if idx == 1 and bp != "contrast":
            return None, "unknown_blueprint"
        if idx == 2 and bp != "timeline":
            return None, "unknown_blueprint"

        sc_title = sc.get("title")
        if not isinstance(sc_title, str) or not sc_title.strip():
            return None, "schema_error"
        sc_title = sc_title.strip()[:16]

        caption = sc.get("caption")
        if not isinstance(caption, str) or len(caption.strip()) < 20:
            return None, "schema_error"
        caption = caption.strip()[:120]

        if bp == "timeline" and not any(phrase in caption for phrase in _TIMELINE_CLOSING_PHRASES):
            return None, "forbidden_phrase"

        labels = _shape_scene_labels(sc.get("labels"))
        raw_params = sc.get("params")
        if not isinstance(raw_params, dict):
            return None, "schema_error"

        if idx == 0:
            shaped_params = shape_scene1_params(bp, raw_params, _shape_pathology_params)
        elif idx == 1:
            shaped_params = shape_scene2_contrast_params(raw_params)
        else:
            shaped_params = shape_scene3_timeline_params(raw_params, topic_key, fallback_title)

        if shaped_params is None:
            return None, "schema_error"

        p_ok, p_code = validate_params(bp, shaped_params)
        if not p_ok:
            return None, p_code

        dur = sc.get("duration_sec", 8)
        shaped_scenes.append({
            "blueprint": bp,
            "title": sc_title,
            "caption": caption,
            "labels": labels,
            "params": shaped_params,
            "duration_sec": dur if isinstance(dur, int) and 4 <= dur <= 12 else 8,
        })

    candidate_ir = {
        "topic_key": topic_key,
        "title": title.strip(),
        "keywords": [str(k).strip() for k in keywords],
        "scenes": shaped_scenes,
    }

    text_check_payload = {
        "title": candidate_ir["title"],
        "keywords": candidate_ir["keywords"],
        "scenes": candidate_ir["scenes"],
    }
    if not _check_no_digits_recursive(text_check_payload):
        return None, "forbidden_phrase"

    is_fat_topic = ("脂肪" in fallback_title) or ("脂肪" in candidate_ir["title"]) or ("fat" in topic_key)
    if not is_fat_topic:
        scenes_dump = json.dumps(candidate_ir["scenes"], ensure_ascii=False)
        if any(lit in scenes_dump for lit in _FAT_GRAFT_DEFAULT_LITERALS):
            return None, "forbidden_phrase"

    ok, code = validate_ir(candidate_ir)
    if not ok:
        return None, code

    return candidate_ir, "ok"


def _default_visual_llm(prompt: str) -> str:
    """預設本地 LLM 呼叫包裝（3 場景完整 JSON 含 params 需較高 token 上限）。"""
    sampling = dict(VISUAL_SAMPLING)
    sampling["max_tokens"] = max(int(sampling.get("max_tokens", 900)), 1800)
    return local_llm_call(prompt, timeout=240, sampling=sampling)


_SELF_HEALING_FEEDBACK_MAP: dict[str, str] = {
    "forbidden_phrase": (
        "【上一次生成未通過合規檢驗（forbidden_phrase），請嚴格修正】：\n"
        "一、所有文字欄位（title、keywords、caption、labels、params 內各標籤與 step_labels、milestones）"
        "【絕對禁止出現任何半形或全形阿拉伯數字（零至九請一律寫成國字：一、二、三）】。\n"
        "二、嚴禁使用保證療效詞彙（如：保證、根治、百分之百、永久、零風險、完全無痛、存活率）。\n"
        "三、第三幕（timeline）的 caption 結尾必須包含「恢復程度因人而異，需由醫師當面評估。」。"
    ),
    "schema_error": (
        "【上一次生成未通過結構檢驗（schema_error），請嚴格修正】：\n"
        "請確認輸出為單一合法 JSON 物件，scenes 必須恰好三幕，且各欄位字數符合上限："
        "卡片 title 十至十六字、場景 title 不超過十六字、caption 二十至一百二十字、"
        "labels 每項不超過十二字、step_labels 每項不超過十字、milestones 恰好三項且每項不超過八字、"
        "contrast 左右 title 與 core_label 不超過八字、note 不超過十四字、footnote 不超過十六字。"
    ),
    "unknown_blueprint": (
        "【上一次生成使用了未知的藍圖（unknown_blueprint），請嚴格修正】：\n"
        "第二幕 blueprint 必須為 contrast，第三幕必須為 timeline；"
        "第一幕僅能從合法的十二種藍圖（surgical_action、deep_plane_facelift、corset_platysmaplasty、"
        "cyst_excision、nail_matrix、subdermal_curettage、process_diagram、skin_energy、"
        "laser_action、neuromuscular、dermal_support、pathology_mechanism）中選用；"
        "基層診所疾病請優先使用 pathology_mechanism。"
    ),
    "text_unsafe": (
        "【上一次生成含有不安全字元（text_unsafe），請嚴格修正】：\n"
        "所有文字欄位嚴禁包含尖括號、HTML 標籤、網址或腳本語法，僅能使用純繁體中文與標準標點符號。"
    ),
    "dosage_prescription": (
        "【上一次生成觸發處方或劑量限制（dosage_prescription），請嚴格修正】：\n"
        "嚴禁提及具體藥品劑量、注射單位、每日服藥次數或停藥指示；請改以一般解剖原理與「依醫師指示評估」表述。"
    ),
    "price_leak": (
        "【上一次生成含有費用或價格字樣（price_leak），請嚴格修正】：\n"
        "嚴禁提及任何金額、費用、價格或促銷字眼。"
    ),
    "simplified_chinese": (
        "【上一次生成含有簡體字（simplified_chinese），請嚴格修正】：\n"
        "全篇所有文字必須使用台灣繁體中文（正體字），嚴禁出現任何簡體字。"
    ),
    "truncated": (
        "【上一次生成因長度過長被截斷（truncated），請嚴格修正】：\n"
        "請直接輸出緊湊的純 JSON 物件，不要附加額外說明，並將各幕 caption 精簡控制在三十五至七十字之間。"
    ),
    "parse_error": (
        "【上一次輸出無法解析為合法 JSON（parse_error），請嚴格修正】：\n"
        "請只輸出純 JSON 物件本體，確保所有雙引號與大括號正確閉合，不要加上任何解釋文字。"
    ),
}


def build_self_healing_feedback(error_code: str) -> str:
    """將驗證失敗代碼轉為具體、不洩漏原文的繁體中文自癒修正提示詞（純函式）。"""
    code = (error_code or "parse_error").strip()
    return _SELF_HEALING_FEEDBACK_MAP.get(code, _SELF_HEALING_FEEDBACK_MAP["parse_error"])


def _lookup_template_override(conn: sqlite3.Connection, clinic_id: Any, topic_key: str) -> Optional[str]:
    """讀取既有草稿的醫師覆寫模板；欄位或列不存在時回傳 None（向後相容）。"""
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(visual_assets)")}
        if "template_override" not in cols:
            return None
        row = conn.execute(
            "SELECT template_override FROM visual_assets WHERE clinic_id IS ? AND topic_key = ?",
            (clinic_id, topic_key),
        ).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row and row[0] else None


def build_tree_visual_prompt(tree: dict[str, Any]) -> str:
    """依據推理樹內容組裝 Typed IR 提示詞，並自動注入命中之 Harness² 治理經驗防護欄。"""
    base = _build_tree_visual_prompt_base(tree)
    lessons_block = format_lessons_for_prompt(select_lessons_for_tree(tree))
    return f"{base}\n\n{lessons_block}" if lessons_block else base


def _generate_candidate(
    act_llm: Callable[[str], str],
    prompt: str,
    topic_key: str,
    fallback_title: str,
    max_attempts: int,
) -> Tuple[Optional[dict[str, Any]], str]:
    """單一候選的生成與自癒重試；回傳 (ir, "ok") 或 (None, 錯誤代碼)。"""
    last_code = "parse_error"
    for attempt in range(max(1, max_attempts)):
        call_prompt = prompt if attempt == 0 else f"{prompt}\n\n{build_self_healing_feedback(last_code)}"
        try:
            raw_out = act_llm(call_prompt)
        except LocalLLMUnavailableError:
            return None, "llm_unavailable"
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
        return ir, "ok"
    return None, last_code


def autodraft_from_tree(
    conn: sqlite3.Connection,
    tree_id_or_dict: int | dict[str, Any],
    llm_call: Optional[Callable[[str], str]] = None,
    *,
    max_attempts: int = 3,
    db_path: Any = None,
    commit: bool = True,
    topic_key_suffix: str = "",
    k_candidates: int = 1,
    recursion_mode: str = "sequential",
) -> dict[str, Any]:
    """由已核准的 PageIndex 推理樹自動生成視覺解說卡草稿並寫入 visual_assets。

    參數：
        topic_key_suffix: 選填後綴（如 '-v2'），用於平行繪製候選版本而不覆蓋線上已核准之 V1 資產。

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
        base_topic_key = normalize_tree_topic_key(doc_id)
    except ValueError:
        return {"status": "error", "code": "schema_error"}

    suffix = (topic_key_suffix or "").strip()
    topic_key = f"{base_topic_key}{suffix}" if suffix else base_topic_key

    # Phase 34：醫師覆寫模板（visual_assets.template_override）優先於關鍵字推斷；非法值直接拒絕，不呼叫 LLM
    override = _lookup_template_override(conn, tree.get("clinic_id"), topic_key)
    if override is None and suffix:
        override = _lookup_template_override(conn, tree.get("clinic_id"), base_topic_key)
    if override is not None:
        if override not in BLUEPRINTS:
            return {"status": "error", "code": "unknown_blueprint"}
        tree = {**tree, "template_override": override}

    # 排程互斥：確認非夜間批次與行程內鎖
    if nightly_batch_running(db_path):
        return {"status": "busy", "code": "busy"}

    if not GENERATION_LOCK.acquire(blocking=False):
        return {"status": "busy", "code": "busy"}

    if recursion_mode not in ("sequential", "parallel") or not isinstance(k_candidates, int) or k_candidates < 1:
        GENERATION_LOCK.release()
        return {"status": "error", "code": "invalid_argument"}

    act_llm = llm_call or _default_visual_llm
    prompt = build_tree_visual_prompt(tree)
    resolved_title = _resolve_tree_title(tree)
    fallback_title = f"{resolved_title}原理圖解" if not resolved_title.endswith("原理") else resolved_title

    try:
        # Harness² 任務級遞迴：探索最多 k 個合法候選，依臨床對齊分數選優
        candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        last_code = "parse_error"
        round_prompt = prompt
        for _round in range(k_candidates):
            ir, code = _generate_candidate(act_llm, round_prompt, topic_key, fallback_title, max_attempts)
            if ir is None:
                if code == "llm_unavailable":
                    return {"status": "error", "code": "llm_unavailable"}
                last_code = code
                continue
            report = score_visual_ir_alignment(tree, ir)
            candidates.append((ir, report))
            if recursion_mode == "sequential":
                if report["score"] >= EXCELLENT_THRESHOLD:
                    break
                round_prompt = build_alignment_critique_prompt(prompt, ir, report)
            # parallel 模式：每輪皆由原始提示詞獨立生成，互不影響

        if not candidates:
            return {"status": "error", "code": last_code}

        ir, report = max(candidates, key=lambda item: item[1]["score"])

        meta_dict: dict[str, Any] = {
            "origin": "pageindex_tree",
            "tree_id": tree.get("id"),
            "doc_id": doc_id,
            "tree_version": tree.get("content_version", 1),
            # 追溯用：產生時間（UTC）與產生程序 PID，供日後查明草稿由哪次執行寫入
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "generator_pid": os.getpid(),
            "harness_score": report["score"],
            "harness_k": k_candidates,
            "harness_mode": recursion_mode,
            "harness_candidates_explored": len(candidates),
            "harness_penalties": report["penalties"],
        }
        if suffix:
            meta_dict["candidate_for"] = base_topic_key
            meta_dict["edition"] = suffix.lstrip("-")

        asset = {
            "clinic_id": tree.get("clinic_id"),
            "topic_key": topic_key,
            "title": ir["title"],
            "keywords": ir["keywords"],
            "ir": ir,
            "metadata": meta_dict,
        }

        upsert_res = upsert_assets(conn, [asset], source_type="llm_generated", commit=commit)
        return {
            "status": "ok",
            "topic_key": topic_key,
            "clinic_id": tree.get("clinic_id"),
            "review_status": "pending",
            "ir": ir,
            "harness_score": report["score"],
            "harness_mode": recursion_mode,
            "harness_k": k_candidates,
            **upsert_res,
        }
    finally:
        GENERATION_LOCK.release()


def find_trees_missing_visual_assets(
    conn: sqlite3.Connection,
    clinic_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """查詢尚未建立對應視覺資產 (visual_assets) 之已核准臨床推理樹。

    對應規則（Mapping Rule）：
    1. 推理樹 doc_id 與視覺資產 topic_key 之一對一對應關係透過 normalize_tree_topic_key(doc_id) 決定：
       - 若 doc_id 開頭非 'tree-'，則前綴加上 'tree-'；
       - 所有英文字元轉小寫，去頭尾空白，僅允許小寫英數字與連字號（例如 doc_id='picosecond' 對應 topic_key='tree-picosecond'）。
    2. 比對條件：若 visual_assets 中已存在對應之 topic_key（若有指定 clinic_id 則匹配該 clinic_id 或全域 NULL 資產），
       即代表該推理樹已具備視覺資產，不列入缺失清單。
    3. 排序與上限：結果嚴格依 doc_id 遞增排序 (doc_id ASC)，保證輸出順序確定；若傳入 limit 則最多取 limit 筆。
    """
    from .writer import has_visual_assets_table

    if not has_visual_assets_table(conn):
        return []

    eligible = fetch_eligible_trees(conn, clinic_id=clinic_id)
    if not eligible:
        return []

    cur = conn.cursor()
    if clinic_id is not None:
        cur.execute(
            "SELECT topic_key FROM visual_assets WHERE clinic_id = ? OR clinic_id IS NULL",
            (clinic_id,),
        )
    else:
        cur.execute("SELECT topic_key FROM visual_assets")
    existing_keys = {row[0] for row in cur.fetchall() if row[0]}

    missing: list[dict[str, Any]] = []
    for tree in eligible:
        doc_id = tree.get("doc_id")
        if not doc_id:
            continue
        try:
            t_key = normalize_tree_topic_key(doc_id)
        except ValueError:
            continue
        if t_key not in existing_keys:
            missing.append(tree)

    missing.sort(key=lambda t: str(t.get("doc_id") or ""))
    if limit is not None:
        if limit <= 0:
            return []
        missing = missing[:limit]
    return missing


def autodraft_tree_to_pending(
    conn: sqlite3.Connection,
    tree: dict[str, Any],
    llm_call: Optional[Callable[[str], str]] = None,
) -> dict[str, Any]:
    """為單一臨床推理樹自動生成視覺解說卡草稿並寫入 visual_assets 為 pending 狀態。

    設計與安全約束：
    1. 狀態約束：絕不寫入 approved 或已發布狀態，review_status 恆為 pending。
    2. 冪等與保護：同一 topic_key 若在 visual_assets 已存在列，不得覆寫，直接回傳 {"status": "skipped", "code": "already_exists"}。
    3. 例外防禦：任何例外（含格式錯誤、LLM 例外、SQL 錯誤）皆被安全捕捉，不中斷外部批次，回傳 {"status": "failed", "code": str}。
    """
    from .writer import has_visual_assets_table

    try:
        if not isinstance(tree, dict):
            return {"status": "failed", "code": "invalid_argument"}

        doc_id = tree.get("doc_id")
        if not doc_id or not isinstance(doc_id, str):
            return {"status": "failed", "code": "missing_doc_id"}

        try:
            topic_key = normalize_tree_topic_key(doc_id)
        except ValueError:
            return {"status": "failed", "code": "schema_error"}

        if not has_visual_assets_table(conn):
            return {"status": "failed", "code": "missing_table"}

        clinic_id = tree.get("clinic_id")

        # 檢查同一 topic_key 是否已存在列（嚴禁覆寫）
        cur = conn.cursor()
        if clinic_id is not None:
            cur.execute(
                "SELECT 1 FROM visual_assets WHERE topic_key = ? AND (clinic_id = ? OR clinic_id IS NULL)",
                (topic_key, clinic_id),
            )
        else:
            cur.execute("SELECT 1 FROM visual_assets WHERE topic_key = ?", (topic_key,))
        if cur.fetchone() is not None:
            return {"status": "skipped", "code": "already_exists"}

        # 檢查醫師覆寫模板
        override = _lookup_template_override(conn, clinic_id, topic_key)
        tree_copy = dict(tree)
        if override is not None:
            if override not in BLUEPRINTS:
                return {"status": "failed", "code": "unknown_blueprint"}
            tree_copy["template_override"] = override

        act_llm = llm_call or _default_visual_llm
        prompt = build_tree_visual_prompt(tree_copy)
        resolved_title = _resolve_tree_title(tree_copy)
        fallback_title = f"{resolved_title}原理圖解" if not resolved_title.endswith("原理") else resolved_title

        ir, code = _generate_candidate(act_llm, prompt, topic_key, fallback_title, max_attempts=3)
        if ir is None:
            return {"status": "failed", "code": code}

        meta_dict: dict[str, Any] = {
            "origin": "pageindex_tree",
            "tree_id": tree_copy.get("id"),
            "doc_id": doc_id,
            "tree_version": tree_copy.get("content_version", 1),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "generator_pid": os.getpid(),
            "source": "nightly_autodraft",
        }

        asset = {
            "clinic_id": clinic_id,
            "topic_key": topic_key,
            "title": ir["title"],
            "keywords": ir["keywords"],
            "ir": ir,
            "metadata": meta_dict,
        }

        # 寫入 visual_assets，upsert_assets 自動設定 review_status='pending', source_type='llm_generated'
        upsert_res = upsert_assets(conn, [asset], source_type="llm_generated", commit=True)

        # 嚴格驗證：確認寫入之記錄 review_status 為 pending，絕非 approved
        cur.execute("SELECT review_status FROM visual_assets WHERE topic_key = ?", (topic_key,))
        row = cur.fetchone()
        if row and row[0] != "pending":
            conn.rollback()
            return {"status": "failed", "code": "invalid_status_not_pending"}

        return {"status": "ok", "code": "ok", "topic_key": topic_key, **upsert_res}
    except LocalLLMUnavailableError:
        return {"status": "failed", "code": "llm_unavailable"}
    except Exception as e:
        return {"status": "failed", "code": f"{type(e).__name__}: {e}"}

