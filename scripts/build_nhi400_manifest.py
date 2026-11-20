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
    """根據次專科解剖結構與病理特徵，精準映射至對應器官圖元與藍圖（避免跨科錯配）。"""
    system = item.get("system", "")
    category = item.get("category", "")
    name = item.get("name", "")
    keywords = item.get("keywords", [])
    feat = item.get("clinical_feature", "")
    text = f"{name} {feat} {' '.join(keywords)}"

    # 1. 中醫特種療法（針刀、透刺、經絡深層沾黏）
    if system == "tcm" or any(k in text for k in ("針刀", "穴", "經絡", "氣血", "辨證", "證型")):
        return {
            "s1_organ": "tcm_special_acup",
            "s2_left_mode": "tcm_deep_adhesion",
            "s2_right_mode": "acupotomy_micro_release",
            "s3_connector": "meridian_unblock_healing",
            "theme_name": "深部經筋沾黏鬆解與經絡調和",
        }

    # 2. 泌尿生殖與骨盆靜脈叢（置於牙科之前，避免包皮念珠菌等誤入牙科）
    if any(k in text for k in ("精索", "陰囊", "包皮", "龜頭", "攝護腺", "前列腺", "陰道", "子宮", "卵巢", "巴氏腺", "骨盆", "尿失禁", "夜尿", "膀胱", "尿道", "輸尿管", "腎結石", "血尿", "頻尿")):
        if any(k in text for k in ("精索", "靜脈曲張", "骨盆", "陰囊")):
            return {
                "s1_organ": "uro_genital",
                "s2_left_mode": "venous_plexus_reflux",
                "s2_right_mode": "venous_ligation_clear",
                "s3_connector": "pelvic_microflow_restore",
                "theme_name": "骨盆微循環回流與靜脈叢減壓",
            }
        return {
            "s1_organ": "uro_pelvic",
            "s2_left_mode": "mucosal_irritant_surge",
            "s2_right_mode": "barrier_hydration_shield",
            "s3_connector": "homeostasis_control",
            "theme_name": "泌尿生殖道黏膜與排尿功能調控",
        }

    # 3. 牙科：區分「牙周骨組織」vs「口腔黏膜／唾液腺／齲齒／顳顎關節／齒列」
    if system == "dental" or any(k in text for k in ("牙齒", "牙周", "牙齦", "牙髓", "牙冠", "牙關", "齲齒", "蛀牙", "拔牙", "多生牙", "齒列", "口腔念珠菌", "鵝口瘡", "口炎", "口瘡", "唾液腺", "舌下腺", "顳顎關節")):
        is_periodontal_bone = (
            any(k in text for k in ("牙周", "齒槽骨", "骨缺損", "植體周圍", "牙齦萎縮", "牙冠增長", "齒槽脊", "骨髓炎", "骨隆凸", "根尖囊腫"))
            and not any(k in text for k in ("念珠菌", "鵝口瘡", "黏液囊腫", "舌下腺", "扁平苔蘚", "白斑", "乾槽症", "顳顎關節", "阻生", "多生牙", "咀嚼肌", "牙關", "牙齦纖維", "牙齦瘤"))
        )
        if is_periodontal_bone:
            return {
                "s1_organ": "dental_periodontal",
                "s2_left_mode": "periodontal_bone_defect",
                "s2_right_mode": "gtr_guided_regeneration",
                "s3_connector": "bone_graft_integration",
                "theme_name": "牙周骨組織缺損與導引組織再生",
            }
        return {
            "s1_organ": "dental_oral",
            "s2_left_mode": "mucosal_irritant_surge",
            "s2_right_mode": "barrier_hydration_shield",
            "s3_connector": "homeostasis_control",
            "theme_name": "口腔黏膜／齒列／唾液腺病變與局部照護",
        }

    # 3. 內分泌、代謝與自體免疫荷爾蒙受體（優先於眼科，避免高膽固醇角膜弓誤入眼科）
    if any(k in text for k in ("糖尿病", "甲狀腺", "副甲狀腺", "泌乳素", "荷爾蒙", "胰島素", "痛風", "尿酸", "高血脂", "高膽固醇", "骨質疏鬆", "多囊", "腎上腺", "維生素", "乳房", "女乳", "乳腺")):
        return {
            "s1_organ": "endocrine_receptor",
            "s2_left_mode": "mucosal_irritant_surge",
            "s2_right_mode": "barrier_hydration_shield",
            "s3_connector": "homeostasis_control",
            "theme_name": "內分泌受體訊號與代謝恆定調控",
        }

    # 4. 眼科：區分「眼底視網膜」vs「角膜／結膜／眼瞼／前房水晶體」
    if not any(k in text for k in ("過動症", "注意力不足")) and any(k in text for k in ("眼", "視網膜", "玻璃體", "黃斑", "飛蚊", "角膜", "結膜", "麥粒腫", "霰粒腫", "青光眼", "白內障", "淚", "視力", "近視", "散光", "弱視", "斜視")):
        if any(k in text for k in ("視網膜", "黃斑", "玻璃體", "飛蚊", "眼底", "視神經", "脈絡膜")):
            return {
                "s1_organ": "ophthalmic_retina",
                "s2_left_mode": "vitreous_drusen_degeneration",
                "s2_right_mode": "optical_barrier_shield",
                "s3_connector": "retinal_epithelium_repair",
                "theme_name": "眼底視網膜感光與光學防護",
            }
        return {
            "s1_organ": "ophthalmic_anterior",
            "s2_left_mode": "mucosal_irritant_surge",
            "s2_right_mode": "barrier_hydration_shield",
            "s3_connector": "homeostasis_control",
            "theme_name": "眼表角結膜・眼瞼・前房光學照護",
        }

    # 5. 消化道與肝膽胰（含咽喉反流、腹股溝疝氣；排除動脈粥狀硬化膽固醇、強直性脊椎炎、網球腿腓腸肌）
    if not any(k in text for k in ("動脈粥狀硬化", "強直性脊椎炎", "網球腿", "腓腸肌")) and any(k in text for k in ("胃", "腸", "食道", "反流", "幽門", "膽囊", "膽道", "膽結石", "肝", "胰", "肛門", "肛裂", "便秘", "痔", "疝氣", "潰瘍性結腸", "吸收不良")):
        return {
            "s1_organ": "gi_tract",
            "s2_left_mode": "mucosal_irritant_surge",
            "s2_right_mode": "barrier_hydration_shield",
            "s3_connector": "homeostasis_control",
            "theme_name": "消化道黏膜屏障與肝膽腸胃功能調控",
        }

    # 7. 呼吸道黏膜（氣喘／支氣管／肺優先於耳鼻喉）
    if any(k in text for k in ("肺", "支氣管", "氣喘", "呼吸道", "胸悶", "痰")):
        return {
            "s1_organ": "respiratory_mucosa",
            "s2_left_mode": "mucosal_irritant_surge",
            "s2_right_mode": "barrier_hydration_shield",
            "s3_connector": "homeostasis_control",
            "theme_name": "呼吸道黏膜發炎機轉與屏障調控",
        }

    # 8. 耳鼻喉氣道（排除胃食道反流與下呼吸道氣喘）
    if any(k in text for k in ("氣道", "喉", "聲帶", "耳咽", "鼻甲", "鼻竇", "鼻咽", "鼻中隔", "鼻道", "外耳道", "哮吼", "中耳", "內耳", "眩暈", "耳鳴", "聽力", "扁桃")):
        return {
            "s1_organ": "ent_airway",
            "s2_left_mode": "airway_laryngeal_edema",
            "s2_right_mode": "airway_patency_restore",
            "s3_connector": "airway_mucosa_calm",
            "theme_name": "耳鼻喉黏膜充血與氣道管腔通暢",
        }

    # 9. 皮膚與軟組織屏障（置於心血管之前，避免老年性紫斑症/嗜中性皮膚症被「血管」搶走）
    if any(k in text for k in ("皮膚", "濕疹", "蕁麻疹", "癬", "帶狀皰疹", "乾癬", "異位性", "甲溝", "粉瘤", "脂肪瘤", "毛囊", "痤瘡", "痘", "蜂窩性", "潰瘍", "肉芽腫", "天疱瘡", "角化", "汗皰疹", "多汗", "紫斑")):
        return {
            "s1_organ": "skin_barrier",
            "s2_left_mode": "mucosal_irritant_surge",
            "s2_right_mode": "barrier_hydration_shield",
            "s3_connector": "homeostasis_control",
            "theme_name": "表皮真皮屏障修復與局部發炎緩解",
        }

    # 10. 肌骨關節與脊椎神經力學（置於心血管之前，排除慢性疲勞與三叉神經痛）
    if not any(k in text for k in ("慢性疲勞", "三叉神經")) and any(k in text for k in ("肌肉", "筋膜", "腱膜", "腓腸肌", "網球腿", "梨狀肌", "鈣化", "半月板", "關節", "類風濕", "脊椎", "椎間盤", "韌帶", "肌腱", "軟骨", "腱鞘", "滑囊", "跟骨", "阿基里斯腱", "扁平足", "足底", "髕骨", "纖維肌痛", "神經痛", "偏頭痛", "腕隧道", "網球肘")):
        return {
            "s1_organ": "joint_spine",
            "s2_left_mode": "mass",
            "s2_right_mode": "minimal_incision",
            "s3_connector": "structural_rehab",
            "theme_name": "肌骨軟組織力學與解剖減壓",
        }

    # 11. 心血管與周邊微循環
    if any(k in text for k in ("高血壓", "心搏", "心律", "二尖瓣", "心臟", "動脈", "靜脈", "血栓", "淋巴水腫", "血管", "心肌", "腦中風", "貧血", "血紅素", "血小板", "三叉神經")):
        return {
            "s1_organ": "vascular_metabolic",
            "s2_left_mode": "venous_plexus_reflux",
            "s2_right_mode": "venous_ligation_clear",
            "s3_connector": "homeostasis_control",
            "theme_name": "血管內皮血流動力與循環微環境調控",
        }

    # 12. 系統性／神經精神／血液代謝其餘次專科歸入循環代謝或內分泌恆定（不再誤歸呼吸道）
    return {
        "s1_organ": "vascular_metabolic",
        "s2_left_mode": "mucosal_irritant_surge",
        "s2_right_mode": "barrier_hydration_shield",
        "s3_connector": "homeostasis_control",
        "theme_name": "次專科全身微循環與系統恆定調控",
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
