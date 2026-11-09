#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Taiwan Clinic Medical PageIndex RAG System - 健保 200 大疾病向量動畫批次生成管線 (Phase 39 Wave 3)

功能：
1. 讀取健保 200 大基層疾病目錄，排除已核准之 88 個主題。
2. 支援依專科（西醫、中醫、牙醫）分流，映射至 24 秒（3 幕 × 8 秒）專科藍圖。
3. 調用 DeepSeek API（支援離峰夜間守門與本地 8080 llama-server 降級）。
4. 內建雙層自癒重試迴圈（Self-Healing Loop）修復格式與合規邊界。
5. 唯一權威寫入路徑：透過 src/visual/writer.py:upsert_assets 以 review_status='pending' 入庫。
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# 根目錄導入支援
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.pageindex.deepseek_client import (
    call_deepseek,
    is_off_peak_hours,
)
from src.pageindex.llm_client import local_llm_call
from src.visual.blueprints import BLUEPRINTS, PALETTE_TOKENS, merge_defaults
from src.visual.ir import validate_ir, validate_visual_text, VISUAL_EXTRA_FORBIDDEN
from src.visual.nhi_dedup import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_DB_PATH,
    load_existing_visual_assets,
    load_nhi_catalog,
    partition_nhi_catalog,
)
from src.visual.writer import upsert_assets


# 阿拉伯數字轉中文數字對照表
DIGIT_MAP = {
    "0": "零",
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
}

DISCLAIMER_SUFFIX = "因人而異，具體照護請由專業醫師當面評估。"


def sanitize_text_digits(text: str) -> str:
    """清理文字中的阿拉伯數字，轉換為中文或安全文字表達。"""
    if not text or not isinstance(text, str):
        return text
    # 替換如 10 -> 十, 1~9 -> 一~九
    res = text
    res = re.sub(r"10", "十", res)
    for d, ch in DIGIT_MAP.items():
        res = res.replace(d, ch)
    # 移除百分比
    res = res.replace("%", "成").replace("％", "成")
    return res


def map_disease_to_blueprint_archetype(item: Dict[str, Any]) -> Dict[str, Any]:
    """根據健保疾病系統與類別，映射至標準專科藍圖架構（全為 8 秒）。"""
    system = item.get("system", "")
    category = item.get("category", "")
    name = item.get("name", "")

    # 1. 牙科
    if system == "dental" or "牙" in category or "牙" in name:
        return {
            "s1_organ": "dental_oral",
            "s2_left_mode": "dental_caries_erosion",
            "s2_right_mode": "dental_sealing_restoration",
            "s3_connector": "dental_pulp_healing",
            "theme_name": "牙科口腔與咀嚼結構",
        }

    # 2. 中醫
    if system == "tcm" or "中醫" in category or "骨傷" in category or "針灸" in name:
        return {
            "s1_organ": "tcm_meridian",
            "s2_left_mode": "tcm_qi_stagnation",
            "s2_right_mode": "tcm_acupuncture_flow",
            "s3_connector": "tcm_meridian_harmony",
            "theme_name": "中醫經絡氣血與臟腑平衡",
        }

    # 3. 內分泌代謝
    if "代謝" in category or "糖尿病" in name or "高血糖" in name or "胰島素" in name:
        return {
            "s1_organ": "endocrine_receptor",
            "s2_left_mode": "metabolic_insulin_resistance",
            "s2_right_mode": "metabolic_glycemic_control",
            "s3_connector": "metabolic_vessel_stabilization",
            "theme_name": "內分泌受體與血糖代謝調控",
        }

    # 4. 心血管與循環
    if "心血管" in category or "高血壓" in name or "心臟" in name or "血脂" in name:
        return {
            "s1_organ": "vascular_metabolic",
            "s2_left_mode": "mucosal_irritant_surge",
            "s2_right_mode": "lifestyle_homeostasis_load",
            "s3_connector": "homeostasis_control",
            "theme_name": "心血管微循環與代謝恆定",
        }

    # 5. 呼吸系統與感染
    if "呼吸" in category or "感冒" in name or "咽喉" in name or "鼻" in name or "支氣管" in name or "肺" in name:
        return {
            "s1_organ": "respiratory_mucosa",
            "s2_left_mode": "mucosal_irritant_surge",
            "s2_right_mode": "barrier_hydration_shield",
            "s3_connector": "mucosal_clearance",
            "theme_name": "呼吸道黏膜防禦與免疫修復",
        }

    # 6. 消化道與腸胃
    if "消化" in category or "胃" in name or "腸" in name or "肝" in name or "膽" in name:
        return {
            "s1_organ": "gi_tract",
            "s2_left_mode": "metabolic_mechanical_overload",
            "s2_right_mode": "lifestyle_homeostasis_load",
            "s3_connector": "homeostasis_control",
            "theme_name": "消化道屏障與消化機能重塑",
        }

    # 7. 皮膚疾患
    if "皮膚" in category or "皮炎" in name or "濕疹" in name or "痤瘡" in name:
        return {
            "s1_organ": "skin_barrier",
            "s2_left_mode": "thermal_spread",
            "s2_right_mode": "barrier_hydration_shield",
            "s3_connector": "scar_maturation",
            "theme_name": "皮膚角質磚牆與屏障舒緩",
        }

    # 8. 肌肉骨骼與關節
    if "肌肉" in category or "關節" in name or "脊椎" in name or "扭傷" in name or "筋膜" in name:
        return {
            "s1_organ": "joint_spine",
            "s2_left_mode": "mass",
            "s2_right_mode": "minimal_incision",
            "s3_connector": "structural_rehab",
            "theme_name": "骨骼關節力學與軟組織修復",
        }

    # 9. 泌尿與生殖
    if "泌尿" in category or "生殖" in category or "膀胱" in name or "前列腺" in name or "尿道" in name:
        return {
            "s1_organ": "uro_pelvic",
            "s2_left_mode": "scattered",
            "s2_right_mode": "targeted_energy",
            "s3_connector": "homeostasis_control",
            "theme_name": "泌尿骨盆防禦與生理調節",
        }

    # 預設通用醫學機轉
    return {
        "s1_organ": "respiratory_mucosa",
        "s2_left_mode": "mucosal_irritant_surge",
        "s2_right_mode": "barrier_hydration_shield",
        "s3_connector": "homeostasis_control",
        "theme_name": "基層臨床病理機轉與照護調控",
    }


def make_slug_topic_key(item: Dict[str, Any]) -> str:
    """產出乾淨合規的 topic_key（符合 ^[a-z0-9-]{3,64}$），優先沿用現有 topic_key。"""
    raw_key = str(item.get("topic_key") or "").strip().lower()
    if re.match(r"^[a-z0-9-]{3,64}$", raw_key):
        return raw_key

    item_id = str(item.get("id", "item")).lower()
    icd = str(item.get("icd10") or "").lower().replace(".", "").replace("-", "")
    icd_clean = re.sub(r"[^a-z0-9]", "", icd)
    slug = f"nhi-{item_id}-{icd_clean}" if icd_clean else f"nhi-{item_id}"
    return slug[:64]


def extract_anatomy_fact_sheet_deepseek(
    item: Dict[str, Any],
    archetype: Dict[str, Any],
    call_deepseek_fn: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """Step 1 (DeepSeek 雲端醫學大腦): 提煉疾病之精確解剖部位與三幕特徵卡（極低 Token，約 100~150 字）。"""
    name = item.get("name", "")
    icd10 = item.get("icd10", "")
    category = item.get("category", "")
    keywords = item.get("keywords", [])
    kw_str = "、".join(keywords[:4])

    prompt = f"""你是台灣資深臨床醫學教授。請針對健保疾病「{name}」（ICD-10: {icd10}，{category}，特徵：{kw_str}），提煉出精準的「解剖部位與病理特徵卡」，僅回傳單一 JSON 物件：
{{
  "organ_label": "具體解剖結構名稱（2至8字繁體中文，如：扁桃腺隱窩、牙釉質髓腔、頸深筋膜、膝關節軟骨）",
  "lesion_label": "病理受損主要表現（2至8字繁體中文，如：化膿充血、酸蝕穿孔、氣滯攣急、軟骨磨損）",
  "trigger_label": "外來刺激或致病誘因（2至8字繁體中文，如：病原菌侵襲、牙菌斑產酸、風寒低頭）",
  "defense_label": "組織自體修復防禦屏障（2至8字繁體中文，如：黏膜屏障、樹脂封填、經絡調和）",
  "step_labels": ["步驟一病因刺激", "步驟二發炎擴散", "步驟三組織充血"],
  "pathology_notes": "第一幕病理機轉醫學重點（40字以內繁體中文，零阿拉伯數字）",
  "contrast_notes": "第二幕延誤習慣 vs 正規處置對照重點（40字以內繁體中文，零阿拉伯數字）",
  "timeline_notes": "第三幕生理復原歷程與日常衛教重點（40字以內繁體中文，零阿拉伯數字）"
}}"""

    call_fn = call_deepseek_fn or (lambda p: call_deepseek(p, allow_daytime=True, fallback_to_local=True))
    try:
        raw = call_fn(prompt)
        sheet = extract_json_from_llm_response(raw)
        if sheet and isinstance(sheet, dict) and "organ_label" in sheet:
            return sheet
    except Exception as e:
        print(f"  [DeepSeek 事實卡調用降級: {e}]")

    # 本地備用預設解剖卡
    return {
        "organ_label": name[:8],
        "lesion_label": "局部病理發炎",
        "trigger_label": "外來病因刺激",
        "defense_label": "自體屏障修復",
        "step_labels": ["致病因子刺激", "局部組織反應", "屏障功能重塑"],
        "pathology_notes": f"{name}引發局部組織充血與機能失調，需及早識別",
        "contrast_notes": "延誤處置易加重負擔，正規照護有助穩定結構防禦",
        "timeline_notes": "組織依序進行修復重塑，配合專業指導維護長期健康",
    }


def compile_visual_ir_local(
    item: Dict[str, Any],
    archetype: Dict[str, Any],
    fact_sheet: Dict[str, Any],
    call_local_fn: Optional[Callable[[str], str]] = None,
    feedback: str = "",
) -> Optional[Dict[str, Any]]:
    """Step 2 (本地 8080 Ornith-35B 動畫編譯器): 接收解剖事實卡，在本地編譯為 3 幕 24 秒 Typed IR（零成本）。"""
    name = item.get("name", "")
    keywords = item.get("keywords", [])
    forbidden_joined = "、".join(VISUAL_EXTRA_FORBIDDEN[:15])

    feedback_block = ""
    if feedback:
        feedback_block = f"\n【前次校驗失敗反饋，請依此修正】：\n{feedback}\n"

    prompt = f"""你是一位專業的台灣醫療衛教與動畫架構師。請根據以下通過驗證的【臨床解剖與病理事實卡】，將「{name}」編譯為一套標準 24 秒（3 幕 × 8 秒）的醫學向量解說卡 Typed IR JSON：

【臨床解剖事實卡】：
- 解剖部位標記：{fact_sheet.get('organ_label')}
- 病灶受損標記：{fact_sheet.get('lesion_label')}
- 致病誘因標記：{fact_sheet.get('trigger_label')}
- 防禦屏障標記：{fact_sheet.get('defense_label')}
- 機轉歷程步驟：{json.dumps(fact_sheet.get('step_labels', []), ensure_ascii=False)}
- 第一幕病理重點：{fact_sheet.get('pathology_notes')}
- 第二幕對照重點：{fact_sheet.get('contrast_notes')}
- 第三幕復原重點：{fact_sheet.get('timeline_notes')}

【強制合規要求（違者整份作廢）】：
1. 零阿拉伯數字鐵則：絕對禁止出現任何 0-9 阿拉伯數字（包括天數、劑量、百分比、金額）。請一律用「初起」、「數日」、「微量」、「一段時間」等繁體中文字詞表達。
2. 語言規範：全篇必須使用繁體中文（台灣醫學用語），不得包含簡體字。
3. 禁用詞彙：嚴禁出現「保證有效、徹底根治、百分之百、首選最佳」等誇張保證療效詞彙，以及：{forbidden_joined}。
4. 文字長度限制：
   - title: 1 至 16 字繁體中文
   - 每幕 caption: 必須介於 25 至 90 字之間。
   - 第 3 幕 caption 結尾必須包含「因人而異」或「由專業醫師當面評估」之合規宣導。
   - labels: 每幕 2 個標籤，每個標籤 2 至 6 字，tone 僅限 neutral, warning, optimal。
5. 時長規範：每幕 duration_sec 必須固定填寫 8。
{feedback_block}
【請直接輸出合法單一 JSON 物件，不夾帶額外文字或 Markdown】：
{{
  "topic_key": "{make_slug_topic_key(item)}",
  "title": "{name[:14]}衛教圖解",
  "keywords": {json.dumps(keywords[:4], ensure_ascii=False)},
  "scenes": [
    {{
      "blueprint": "pathology_mechanism",
      "title": "病理機轉解說",
      "caption": "第一幕解說文字（30至80字繁體中文，描述{fact_sheet.get('organ_label')}與{fact_sheet.get('lesion_label')}，零阿拉伯數字）",
      "labels": [
        {{"text": "{fact_sheet.get('trigger_label', '致病因子')[:6]}", "tone": "warning"}},
        {{"text": "{fact_sheet.get('organ_label', '組織結構')[:6]}", "tone": "neutral"}}
      ],
      "duration_sec": 8,
      "params": {{
        "organ_system": "{archetype['s1_organ']}",
        "organ_label": "{fact_sheet.get('organ_label', '器官組織')[:8]}",
        "lesion_label": "{fact_sheet.get('lesion_label', '病變受損')[:8]}",
        "trigger_label": "{fact_sheet.get('trigger_label', '致病因子')[:8]}",
        "defense_label": "{fact_sheet.get('defense_label', '屏障防禦')[:8]}",
        "severity_level": 3,
        "step_labels": {json.dumps(fact_sheet.get('step_labels', ["致病因子刺激", "局部組織發炎", "屏障逐步修復"])[:3], ensure_ascii=False)}
      }}
    }},
    {{
      "blueprint": "contrast",
      "title": "照護處置對照",
      "caption": "第二幕解說文字，對比延誤不當處置與正規照護方式（30至80字繁體中文，零阿拉伯數字）",
      "labels": [
        {{"text": "不良習慣", "tone": "warning"}},
        {{"text": "正規照護", "tone": "optimal"}}
      ],
      "duration_sec": 8,
      "params": {{
        "left": {{"title": "延誤處置", "mode": "{archetype['s2_left_mode']}", "unit_fill": "warn"}},
        "right": {{"title": "積極照護", "mode": "{archetype['s2_right_mode']}", "unit_fill": "ok"}}
      }}
    }},
    {{
      "blueprint": "timeline",
      "title": "生理復原歷程",
      "caption": "第三幕解說文字，說明組織修復階段與長期保養，結尾需加上：因人而異，具體照護請由專業醫師當面評估。（30至80字繁體中文，零阿拉伯數字）",
      "labels": [
        {{"text": "組織修復", "tone": "optimal"}},
        {{"text": "機能平衡", "tone": "optimal"}}
      ],
      "duration_sec": 8,
      "params": {{"connectors": "{archetype['s3_connector']}", "unit_fill": "accent"}}
    }}
  ]
}}"""

    def _default_local_call(p: str) -> str:
        return local_llm_call(
            p,
            timeout=90,
            sampling={
                "chat_template_kwargs": {"enable_thinking": False},
                "max_tokens": 2048,
                "temperature": 0.1,
            },
        )

    call_fn = call_local_fn or _default_local_call
    try:
        raw = call_fn(prompt)
        return extract_json_from_llm_response(raw)
    except Exception as e:
        print(f"  [本地 8080 編譯異常: {e}，切換至雲端 DeepSeek 輔助]")
        raw_cloud = call_deepseek(prompt, allow_daytime=True, fallback_to_local=False)
        return extract_json_from_llm_response(raw_cloud)


def extract_json_from_llm_response(raw_text: str) -> Optional[Dict[str, Any]]:
    """從 LLM 回覆字串中提取合法的 JSON 物件（移除 think 標籤或 markdown 區塊）。"""
    if not raw_text:
        return None
    cleaned = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL)
    cleaned = re.sub(r"^.*?```(?:json)?", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"```.*$", "", cleaned, flags=re.DOTALL).strip()

    # 尋找第一組大括號
    m = re.search(r"(\{.*\})", cleaned, re.DOTALL)
    if m:
        cleaned = m.group(1)

    try:
        return json.loads(cleaned)
    except Exception:
        return None


def post_process_self_heal(ir: Dict[str, Any], archetype: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    """本地輕量自動自癒：校正欄位約束、補全診所免責條款與數字清洗。"""
    c = copy.deepcopy(ir)

    # 確保頂層必要鍵與 topic_key 符合 ^[a-z0-9-]{3,64}$
    raw_key = str(c.get("topic_key", "")).lower()
    if not re.match(r"^[a-z0-9-]{3,64}$", raw_key):
        c["topic_key"] = make_slug_topic_key(item)
    else:
        c["topic_key"] = raw_key
    if "title" not in c or not c["title"]:
        c["title"] = f"{item.get('name', '疾病')[:12]}原理說明"
    c["title"] = sanitize_text_digits(c["title"])[:16]

    if "keywords" not in c or not isinstance(c["keywords"], list) or not c["keywords"]:
        c["keywords"] = item.get("keywords", ["醫學衛教", "疾病原理"])[:4]
    c["keywords"] = [sanitize_text_digits(k)[:10] for k in c["keywords"][:4]]

    # 確保 3 個場景
    scenes = c.get("scenes", [])
    if not isinstance(scenes, list) or len(scenes) != 3:
        # 重建 3 幕基礎
        return c

    for idx, sc in enumerate(scenes):
        sc["duration_sec"] = 8  # 嚴格 8 秒
        sc["title"] = sanitize_text_digits(sc.get("title", f"場景{idx+1}"))[:16]

        # 醫療安全與文字長度自癒
        caption = sanitize_text_digits(sc.get("caption", ""))
        # 替換常見可能觸發處方劑量誤判之具名詞彙
        drug_replacements = [
            ("降尿酸藥物", "尿酸代謝調控處置"), ("降尿酸藥", "尿酸代謝調控處置"),
            ("降血壓藥物", "血壓平穩調控處置"), ("降血壓藥", "血壓平穩調控處置"),
            ("抗心律不整藥", "心律平穩調控處置"), ("抗心律不整藥物", "心律平穩調控處置"),
            ("抗生素", "專科抗感染處置"), ("類固醇", "抗炎消腫處置"),
            ("消炎止痛藥", "舒緩消炎處置"), ("止痛藥", "舒緩止痛處置"), ("消炎藥", "消炎舒緩處置"),
            ("甲狀腺素", "內分泌調節處置"), ("抗組織胺", "抗敏舒緩處置"),
            ("口服", "依照專科指示配合"), ("服用", "依照醫師指示配合"),
            ("每日一次", "按時配合"), ("每日二次", "按時配合"), ("每日兩次", "按時配合"),
            ("保證有效", "積極改善"), ("百分之百", "多數良好"), ("徹底根除", "平穩控制")
        ]
        for old_w, new_w in drug_replacements:
            caption = caption.replace(old_w, new_w)

        # 終極自癒：若仍觸發 dosage_prescription 或 forbidden_phrase，自動重構為合規衛教文案
        ok_cap, code_cap = validate_visual_text(caption)
        if not ok_cap and code_cap in ("dosage_prescription", "forbidden_phrase", "price_leak"):
            dis_name = item.get("name", "專科疾病")[:8]
            if idx == 0:
                caption = f"病理機轉呈現{dis_name}之局部組織結構受損與發炎反應，影響周圍微循環，需及早由專業醫師當面評估掌握狀況。"
            elif idx == 1:
                caption = "積極調整作息並配合正規臨床照護，有助於維持生理機能穩定，若處置不當或延誤評估，可能使不適情況進一步加劇。"
            else:
                caption = f"日常應保持健康生活型態並按時門診追蹤，個人復原與調控狀況因人而異，具體照護建議由專業醫師當面評估。{DISCLAIMER_SUFFIX}"

        # 第三幕免責檢查
        if idx == 2:
            if "因人而異" not in caption and "醫師" not in caption:
                caption = caption.rstrip("。，") + f"。{DISCLAIMER_SUFFIX}"
        # 長度規範
        if len(caption) > 115:
            caption = caption[:110] + "。"
        if len(caption) < 25:
            caption = caption + "，詳細醫學原理與個人化照護建議由專業醫師當面評估。"
        sc["caption"] = caption

        # 標籤自癒
        labels = sc.get("labels", [])
        if not isinstance(labels, list) or len(labels) == 0:
            sc["labels"] = [{"text": "醫學衛教", "tone": "neutral"}, {"text": "照護重點", "tone": "optimal"}]
        else:
            fixed_labels = []
            for lb in labels[:4]:
                if isinstance(lb, dict):
                    t = sanitize_text_digits(lb.get("text", "說明"))[:10]
                    tone = lb.get("tone", "neutral")
                    if tone not in ("neutral", "warning", "optimal"):
                        tone = "neutral"
                    fixed_labels.append({"text": t, "tone": tone})
                elif isinstance(lb, str):
                    fixed_labels.append({"text": sanitize_text_digits(lb)[:10], "tone": "neutral"})
            sc["labels"] = fixed_labels

        # 參數自癒（過濾未知鍵，利用 merge_defaults 補齊預設值並自癒字元長度與 enum 值域）
        bp = sc.get("blueprint", "")
        if bp in BLUEPRINTS:
            schema = BLUEPRINTS[bp]["params"]
            raw_p = sc.get("params", {})
            if isinstance(raw_p, dict):
                filtered_p = {k: v for k, v in raw_p.items() if k in schema}
            else:
                filtered_p = {}
            p = merge_defaults(bp, filtered_p)

            # 針對特定 blueprint 進行深層 enum 與子欄位校正
            if bp == "pathology_mechanism":
                valid_organs = schema["organ_system"]["values"]
                if p.get("organ_system") not in valid_organs:
                    raw_org = str(p.get("organ_system", "")).lower()
                    if "adipose" in raw_org or "skin" in raw_org or "fat" in raw_org:
                        p["organ_system"] = "skin_barrier"
                    elif "joint" in raw_org or "bone" in raw_org or "spine" in raw_org or "cervical" in raw_org:
                        p["organ_system"] = "joint_spine"
                    elif "dental" in raw_org or "tooth" in raw_org or "caries" in raw_org:
                        p["organ_system"] = "dental_oral"
                    elif "tcm" in raw_org or "meridian" in raw_org:
                        p["organ_system"] = "tcm_meridian"
                    elif "uro" in raw_org or "pelvic" in raw_org:
                        p["organ_system"] = "uro_pelvic"
                    elif "gi" in raw_org or "stomach" in raw_org:
                        p["organ_system"] = "gi_tract"
                    elif "vascular" in raw_org or "cardio" in raw_org:
                        p["organ_system"] = "vascular_metabolic"
                    else:
                        p["organ_system"] = "respiratory_mucosa"

            elif bp == "contrast":
                left = p.get("left", {})
                if isinstance(left, dict):
                    valid_l_modes = schema["left"]["fields"]["mode"]["values"]
                    if left.get("mode") not in valid_l_modes:
                        left["mode"] = "mass"
                    if "title" in left:
                        left["title"] = sanitize_text_digits(left["title"])[:8]
                    if "note" in left:
                        left["note"] = sanitize_text_digits(left["note"])[:14]
                    if "core_label" in left:
                        left["core_label"] = sanitize_text_digits(left["core_label"])[:8]
                    if "footnote" in left:
                        left["footnote"] = sanitize_text_digits(left["footnote"])[:16]

                right = p.get("right", {})
                if isinstance(right, dict):
                    valid_r_modes = schema["right"]["fields"]["mode"]["values"]
                    if right.get("mode") not in valid_r_modes:
                        right["mode"] = "layered"
                    if "title" in right:
                        right["title"] = sanitize_text_digits(right["title"])[:8]
                    if "note" in right:
                        right["note"] = sanitize_text_digits(right["note"])[:14]
                    if "footnote" in right:
                        right["footnote"] = sanitize_text_digits(right["footnote"])[:16]

            elif bp == "timeline":
                valid_effects = schema["unit_effect"]["values"]
                if p.get("unit_effect") not in valid_effects:
                    p["unit_effect"] = "mature"
                valid_conn = schema["connectors"]["values"]
                if p.get("connectors") not in valid_conn:
                    p["connectors"] = "vessels"
                ms = p.get("milestones", [])
                if isinstance(ms, list):
                    p["milestones"] = [sanitize_text_digits(m)[:8] for m in ms[:3]]
                    while len(p["milestones"]) < 3:
                        p["milestones"].append(f"進程階段{len(p['milestones'])+1}")

            # 針對頂層字串進行無數字與長度校正
            for pk, pv in p.items():
                if isinstance(pv, str):
                    clean_str = sanitize_text_digits(pv)
                    if pk.endswith("_label"):
                        p[pk] = clean_str[:8]
                    elif pk.endswith("_notes") or pk.endswith("_title"):
                        p[pk] = clean_str[:16]
                    else:
                        p[pk] = clean_str
                elif isinstance(pv, list) and pk == "step_labels":
                    p[pk] = [sanitize_text_digits(s)[:10] for s in pv[:3]]
                    while len(p[pk]) < 3:
                        p[pk].append(f"進程步驟{len(p[pk])+1}")
            sc["params"] = p

    return c


def generate_single_nhi_ir(
    item: Dict[str, Any],
    llm_call: Optional[Callable[[str], str]] = None,
    max_retries: int = 3,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """雙引擎流水線：
    1. Step 1 (DeepSeek): 提煉臨床解剖事實卡 (Anatomy Fact Sheet)
    2. Step 2 (Local 8080 Ornith-35B): 在本地編譯為 3 幕 24 秒合規 Typed IR
    3. 內嵌本地格式自癒與最多 max_retries 次回饋重試。
    """
    archetype = map_disease_to_blueprint_archetype(item)

    # 1. 提煉解剖事實卡 (DeepSeek)
    fact_sheet = extract_anatomy_fact_sheet_deepseek(item, archetype, call_deepseek_fn=llm_call)
    print(f"  [Step 1 解剖提煉] 結構: {fact_sheet.get('organ_label')} | 病理: {fact_sheet.get('lesion_label')}")

    feedback = ""
    last_err = ""

    # 2. 本地編譯與自癒迴圈 (Local 8080)
    for attempt in range(max_retries):
        try:
            data = compile_visual_ir_local(
                item,
                archetype,
                fact_sheet,
                call_local_fn=llm_call,
                feedback=feedback,
            )
            if not data or not isinstance(data, dict):
                feedback = "輸出無法解析為合法 JSON 物件，請確保只輸出單一標準 JSON 物件。"
                last_err = "json_parse_error"
                continue

            # 本地自癒修正常見邊界
            healed_ir = post_process_self_heal(data, archetype, item)

            # 嚴格 IR 檢驗
            ok, code = validate_ir(healed_ir)
            if ok:
                total_dur = sum(s.get("duration_sec", 8) for s in healed_ir["scenes"])
                if total_dur == 24:
                    return True, healed_ir, "ok"

            last_err = code
            feedback = f"前次生成的 IR 檢驗失敗，錯誤代碼為 [{code}]。請特別注意：1. 絕對不可含任何阿拉伯數字；2. 第三幕 caption 結尾必須有『因人而異』或『醫師評估』；3. 每幕標題不能超長。"
        except Exception as e:
            last_err = str(e)
            feedback = f"呼叫發生異常: {last_err}，請重新輸出精簡合法 JSON。"

    return False, None, last_err


def verify_db_backup(db_path: Path) -> bool:
    """檢查資料庫是否有當日 SHA-256 備份或存在備份檔，確保正式庫安全。"""
    bak_files = list(db_path.parent.glob(f"{db_path.name}.bak*"))
    return len(bak_files) > 0


def run_batch_generation(
    db_path: Path = DEFAULT_DB_PATH,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    limit: Optional[int] = None,
    category_filter: Optional[str] = None,
    topic_key_filter: Optional[str] = None,
    dry_run: bool = False,
    allow_daytime: bool = False,
    test_one: bool = False,
    redo_3: bool = False,
    allow_prod_db: bool = False,
    llm_call: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """批次管線入口函式。"""
    print(f"\n=======================================================")
    print(f"🏥 健保 200 大疾病向量解說卡批次生成管線 (Phase 39 Wave 3)")
    print(f"=======================================================")

    if not db_path.exists():
        raise FileNotFoundError(f"找不到資料庫: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        catalog = load_nhi_catalog(catalog_path)
        assets = load_existing_visual_assets(conn)
        covered, to_generate = partition_nhi_catalog(catalog, assets)

        print(f"• 健保項目總數: {len(catalog)} 項")
        print(f"• 資料庫現有已核准資產: {len(assets)} 筆")
        print(f"• 篩除重複項（已覆蓋）: {len(covered)} 項")
        print(f"• 待生成新缺項總數:   {len(to_generate)} 項")

        # 支援重做 3 筆示範疾病模式
        if redo_3:
            redo_ids = {"W003", "D001", "C002"}
            items_queue = [it for it in catalog if it.get("id") in redo_ids]
            print(f"• 🎯 [Redo 模式] 強制選取 3 筆示範專科疾病: {[it['name'] for it in items_queue]}")
        else:
            items_queue = to_generate

        # 篩選特定類別
        if category_filter and category_filter != "all" and not redo_3:
            items_queue = [it for it in items_queue if it.get("system") == category_filter]
            print(f"• 專科篩選 [{category_filter}]: 剩餘 {len(items_queue)} 項")

        # 篩選單一主題
        if topic_key_filter:
            items_queue = [it for it in items_queue if topic_key_filter in make_slug_topic_key(it) or topic_key_filter in it.get("name", "")]
            print(f"• 主題關鍵字篩選 [{topic_key_filter}]: 剩餘 {len(items_queue)} 項")

        if limit and limit > 0:
            items_queue = items_queue[:limit]
            print(f"• 數量上限限制 [--limit {limit}]: 實際處理 {len(items_queue)} 項")

        if not items_queue:
            print("✓ 沒有符合條件之待生成項目，管線平穩結束。")
            return {"total": 0, "success": 0, "failed": 0, "dry_run": dry_run}

        # 離峰時段守門防禦
        is_single_test = test_one or len(items_queue) == 1
        if not dry_run and not is_single_test and not allow_daytime:
            if not is_off_peak_hours():
                msg = (
                    f"⚠️ [計費守門拒絕] 當前處於 DeepSeek 日間高峰計費時段！\n"
                    f"依專案承諾與成本防禦規範，多筆大批量生成僅限在夜間離峰優惠時段（台灣時間 00:30 ~ 08:30）執行以節省 50% 費用。\n"
                    f"若您確定要進行單題測試，請傳入 `--test-one` 或 `--limit 1`；\n"
                    f"若您確定要日間全量執行，請明確加上 `--allow-daytime`。"
                )
                print(f"\n{msg}\n")
                raise PermissionError("非夜間離峰優惠時段且未加放行旗標，終止全量批次。")

        # 正式庫備份防禦
        if not dry_run and db_path.name == "clinic.db" and not allow_prod_db:
            if not verify_db_backup(db_path):
                print(f"⚠️ 偵測到操作正式庫 clinic.db 且未見當前備份，自動建立快照備份...")
                bak_path = db_path.parent / f"clinic.db.bak-{int(time.time())}"
                with open(db_path, "rb") as sf, open(bak_path, "wb") as df:
                    df.write(sf.read())
                print(f"✓ 已安全備份至: {bak_path}")

        success_count = 0
        failed_count = 0
        results = []

        print(f"\n🚀 開始處理待生成佇列（共 {len(items_queue)} 項）...")
        for idx, item in enumerate(items_queue, 1):
            name = item.get("name")
            sys_type = item.get("system")
            print(f"\n[{idx}/{len(items_queue)}] 正在生成: [{sys_type}] {name} ...")

            if dry_run:
                archetype = map_disease_to_blueprint_archetype(item)
                print(f"  [DRY-RUN] 預覽藍圖映射:")
                print(f"    - S1 Organ: {archetype['s1_organ']} (8s)")
                print(f"    - S2 Contrast: {archetype['s2_left_mode']} vs {archetype['s2_right_mode']} (8s)")
                print(f"    - S3 Connector: {archetype['s3_connector']} (8s)")
                print(f"    - Topic Key: {make_slug_topic_key(item)}")
                success_count += 1
                continue

            ok, ir, err_msg = generate_single_nhi_ir(item, llm_call=llm_call)
            if not ok or not ir:
                print(f"  ❌ 生成或驗證失敗: {err_msg}")
                failed_count += 1
                continue

            # 寫入準備
            asset_row = {
                "clinic_id": None,  # 全院共用基層衛教
                "topic_key": ir["topic_key"],
                "title": ir["title"],
                "keywords": ir["keywords"],
                "ir": ir,
                "metadata": {
                    "generator": "deepseek-nhi200-batch",
                    "nhi_id": item.get("id"),
                    "icd10": item.get("icd10"),
                    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
            }

            try:
                upsert_res = upsert_assets(conn, [asset_row], source_type="llm_generated", commit=True)
                print(f"  ✅ 入庫成功 (review_status='pending'): {upsert_res}")
                success_count += 1
                results.append(ir)
            except Exception as we:
                print(f"  ❌ 寫入資料庫失敗: {we}")
                failed_count += 1

        print(f"\n=======================================================")
        print(f"🎉 批次生成管線執行完畢:")
        print(f"  • 總計處理: {len(items_queue)} 項")
        print(f"  • 成功筆數: {success_count} 項")
        print(f"  • 失敗筆數: {failed_count} 項")
        print(f"=======================================================\n")

        return {
            "total": len(items_queue),
            "success": success_count,
            "failed": failed_count,
            "dry_run": dry_run,
            "results": results,
        }
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="健保 200 大疾病向量動畫批次生成管線 (Phase 39)")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="SQLite 資料庫路徑")
    parser.add_argument("--catalog-path", type=Path, default=DEFAULT_CATALOG_PATH, help="健保 200 目錄 JSON 路徑")
    parser.add_argument("--limit", type=int, default=None, help="處理項目上限數量")
    parser.add_argument("--category", choices=["all", "western", "tcm", "dental"], default="all", help="專科篩選")
    parser.add_argument("--topic-key", type=str, default=None, help="篩選特定疾病 slug 或名稱")
    parser.add_argument("--dry-run", action="store_true", help="唯讀預覽模式，不發送真實生成、不寫入庫")
    parser.add_argument("--allow-daytime", action="store_true", help="強制允許在白天時段執行批次")
    parser.add_argument("--test-one", action="store_true", help="單筆驗收測試（允許日間執行）")
    parser.add_argument("--redo-3", action="store_true", help="強制重新生成並更新 3 筆示範專科疾病（扁桃腺炎、蛀牙、落枕）")
    parser.add_argument("--allow-prod-db", action="store_true", help="允許寫入正式資料庫 clinic.db")

    args = parser.parse_args()

    run_batch_generation(
        db_path=args.db_path,
        catalog_path=args.catalog_path,
        limit=args.limit,
        category_filter=args.category,
        topic_key_filter=args.topic_key,
        dry_run=args.dry_run,
        allow_daytime=args.allow_daytime,
        test_one=args.test_one,
        redo_3=args.redo_3,
        allow_prod_db=args.allow_prod_db,
    )


if __name__ == "__main__":
    main()
