#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/build_nhi400_manifest.py

建構健保第 201 至 400 項專科疾病動畫標準任務清單 (data/visual/nhi400_manifest.json)：
1. 讀取 data/nhi_primary_care_201_400.json（剛好 200 項次級盛行專科疾病）。
2. 每項映射至 Phase 40 次專科藍圖（眼科、耳鼻喉、泌尿生殖、進階牙周、中醫特種療法）。
3. 輸出含標準 topic_key、title、keywords、archetype 映射之任務清單（剛好 200 筆，index 201..400）。
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = ROOT / "data" / "nhi_primary_care_201_400.json"
OUTPUT_PATH = ROOT / "data" / "visual" / "nhi400_manifest.json"


def _clean_slug(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:64] or "nhi-disease"


def map_nhi400_archetype(item: Dict[str, Any]) -> Dict[str, Any]:
    """根據次專科解剖結構與病理特徵，映射至 Phase 40 擴充圖元與藍圖。"""
    system = item.get("system", "")
    category = item.get("category", "")
    name = item.get("name", "")
    keywords = item.get("keywords", [])
    feat = item.get("clinical_feature", "")
    text = f"{name} {category} {feat} {' '.join(keywords)}"

    # 1. 眼科頭頸
    if "眼" in text or "視網膜" in text or "玻璃體" in text or "黃斑" in text or "飛蚊" in text:
        return {
            "s1_organ": "ophthalmic_retina",
            "s2_left_mode": "vitreous_drusen_degeneration",
            "s2_right_mode": "optical_barrier_shield",
            "s3_connector": "retinal_epithelium_repair",
            "theme_name": "眼底視網膜感光與光學防護",
        }

    # 2. 耳鼻喉呼吸氣道
    if "氣道" in text or "喉" in text or "聲帶" in text or "耳咽" in text or "鼻甲" in text or "哮吼" in text:
        return {
            "s1_organ": "ent_airway",
            "s2_left_mode": "airway_laryngeal_edema",
            "s2_right_mode": "airway_patency_restore",
            "s3_connector": "airway_mucosa_calm",
            "theme_name": "呼吸道黏膜充血與氣道管腔通暢",
        }

    # 3. 泌尿骨盆與生殖
    if "精索" in text or "膀胱" in text or "靜脈曲張" in text or "骨盆" in text or "尿失禁" in text or "陰囊" in text:
        return {
            "s1_organ": "uro_genital",
            "s2_left_mode": "venous_plexus_reflux",
            "s2_right_mode": "venous_ligation_clear",
            "s3_connector": "pelvic_microflow_restore",
            "theme_name": "骨盆微循環回流與靜脈叢減壓",
        }

    # 4. 牙科進階牙周與顎面外科
    if system == "dental" or "牙周" in text or "根尖" in text or "拔牙" in text or "乾槽" in text or "骨缺損" in text:
        return {
            "s1_organ": "dental_periodontal",
            "s2_left_mode": "periodontal_bone_defect",
            "s2_right_mode": "gtr_guided_regeneration",
            "s3_connector": "bone_graft_integration",
            "theme_name": "牙周骨組織缺損與導引組織再生",
        }

    # 5. 中醫特種療法（針刀、透刺、長強、經絡深層沾黏）
    if system == "tcm" or "針刀" in text or "穴" in text or "經絡" in text or "氣血" in text:
        return {
            "s1_organ": "tcm_special_acup",
            "s2_left_mode": "tcm_deep_adhesion",
            "s2_right_mode": "acupotomy_micro_release",
            "s3_connector": "meridian_unblock_healing",
            "theme_name": "深部經筋沾黏鬆解與經絡調和",
        }

    # 6. 西醫肌肉骨骼痛症
    if "肌肉" in text or "筋膜" in text or "梨狀肌" in text or "鈣化" in text or "半月板" in text:
        return {
            "s1_organ": "joint_spine",
            "s2_left_mode": "mass",
            "s2_right_mode": "minimal_incision",
            "s3_connector": "structural_rehab",
            "theme_name": "肌骨軟組織力學與解剖減壓",
        }

    # 7. 預設通用醫學機轉
    return {
        "s1_organ": "respiratory_mucosa",
        "s2_left_mode": "mucosal_irritant_surge",
        "s2_right_mode": "barrier_hydration_shield",
        "s3_connector": "homeostasis_control",
        "theme_name": "次專科臨床病理機轉與照護調控",
    }


def build_manifest() -> List[Dict[str, Any]]:
    assert INPUT_PATH.exists(), f"找不到種子檔案：{INPUT_PATH}"
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        seeds = json.load(f)

    manifest: List[Dict[str, Any]] = []
    for idx, item in enumerate(seeds, start=201):
        item_id = str(item.get("id", f"I{idx}")).lower()
        icd_raw = _clean_slug(str(item.get("icd10") or ""))
        slug_base = f"nhi-{item_id}-{icd_raw}" if icd_raw else f"nhi-{item_id}"
        topic_key = _clean_slug(slug_base)

        raw_name = item.get("name", "專科疾病")
        clean_name = re.sub(r"（.*?）|\(.*?\)", "", raw_name).strip() or raw_name

        archetype = map_nhi400_archetype(item)

        entry = {
            "index": idx,
            "id": item.get("id"),
            "system": item.get("system"),
            "category": item.get("category"),
            "disease_name": raw_name,
            "clean_name": clean_name,
            "title": f"{clean_name[:12]}衛教圖解",
            "topic_key": topic_key,
            "icd10": item.get("icd10"),
            "alias": item.get("alias", []),
            "keywords": item.get("keywords", [])[:4],
            "clinical_feature": item.get("clinical_feature", ""),
            "recommended_blueprint": item.get("recommended_blueprint", "pathology_mechanism"),
            "archetype": archetype,
        }
        manifest.append(entry)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return manifest


if __name__ == "__main__":
    items = build_manifest()
    print(f"✅ 成功產出 201-400 衛教動畫 Manifest：{OUTPUT_PATH}（共 {len(items)} 筆任務）")
