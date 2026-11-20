#!/usr/bin/env python3
"""掃描 data/visual/nhi400_manifest.json（或指定 manifest）之解剖／器官錯配項目。"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any

DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "data" / "visual" / "nhi400_manifest.json"

# 每個 s1_organ 對應「合理應該出現的解剖／臨床關鍵字」與「明顯錯配的解剖／部位關鍵字」
ORGAN_RULES: dict[str, dict[str, Any]] = {
    "dental_periodontal": {
        "desc": "牙周骨組織缺損與導引組織再生",
        "expected_any": ("牙周", "齒槽骨", "骨缺損", "植體周圍", "牙齦萎縮", "牙冠增長", "齒槽脊", "骨髓炎", "骨隆凸", "根尖囊腫"),
        "mismatch_keywords": (
            "念珠菌", "鵝口瘡", "口炎", "黏液囊腫", "舌下腺", "扁平苔蘚", "白斑",
            "顳顎關節", "三叉神經", "顏面神經", "阻生智齒", "齒列矯正", "多生牙",
            "牙齦纖維", "牙齦瘤", "乾槽症",
        ),
    },
    "dental_oral": {
        "desc": "口腔黏膜／齒列／唾液腺病變",
        "expected_any": ("牙", "齒", "口腔", "口瘡", "口炎", "念珠菌", "鵝口瘡", "黏液囊腫", "扁平苔蘚", "白斑", "唾液腺", "舌", "顳顎關節", "乾槽", "三叉神經"),
        "mismatch_keywords": ("視網膜", "肺", "支氣管", "腎", "膀胱", "攝護腺", "陰道", "子宮"),
    },
    "ophthalmic_retina": {
        "desc": "視網膜／眼底結構",
        "expected_any": ("視網膜", "黃斑", "玻璃體", "眼底", "視神經", "飛蚊", "脈絡膜"),
        "mismatch_keywords": (
            "結膜", "角膜", "眼瞼", "麥粒腫", "針眼", "霰粒腫", "乾眼", "淚腺",
            "白內障", "水晶體", "青光眼", "眼壓", "近視", "散光", "老花", "斜視", "弱視",
        ),
    },
    "ophthalmic_anterior": {
        "desc": "眼表角結膜・眼瞼・前房光學",
        "expected_any": ("眼", "角膜", "結膜", "眼瞼", "淚", "白內障", "青光眼", "視力", "近視", "散光", "弱視", "斜視", "麥粒腫", "霰粒腫"),
        "mismatch_keywords": ("視網膜", "黃斑", "玻璃體", "飛蚊", "牙", "胃", "肝", "腎"),
    },
    "ent_airway": {
        "desc": "耳鼻喉／上呼吸道結構",
        "expected_any": ("鼻", "喉", "咽", "扁桃", "聲帶", "氣管", "耳", "中耳", "內耳", "眩暈", "鼻竇", "腺樣體", "梅尼爾", "前庭"),
        "mismatch_keywords": ("胃", "腸", "肝", "腎", "膀胱", "攝護腺", "子宮", "皮膚", "關節"),
    },
    "respiratory_mucosa": {
        "desc": "呼吸道黏膜結構",
        "expected_any": ("肺", "支氣管", "氣喘", "呼吸道", "咳嗽", "鼻炎", "鼻竇", "咽喉", "胸悶", "痰", "呼吸", "流感", "感冒"),
        "mismatch_keywords": (
            "胃", "腸", "肝", "膽", "胰", "腎", "膀胱", "尿", "攝護腺", "陰道", "子宮",
            "皮膚", "濕疹", "蕁麻疹", "甲溝", "帶狀皰疹", "糖尿病", "高血壓", "痛風",
            "甲狀腺", "貧血", "骨質疏鬆", "失眠", "焦慮", "偏頭痛", "心臟", "心律",
        ),
    },
    "gi_tract": {
        "desc": "消化道黏膜與肝膽胰",
        "expected_any": ("胃", "腸", "食道", "反流", "幽門", "膽", "肝", "胰", "肛門", "肛裂", "便秘", "痔", "疝氣", "吸收"),
        "mismatch_keywords": ("視網膜", "黃斑", "白內障", "牙周", "攝護腺", "陰道"),
    },
    "vascular_metabolic": {
        "desc": "血管內皮與循環微環境",
        "expected_any": ("高血壓", "心", "動脈", "靜脈", "血栓", "淋巴", "血管", "貧血", "血紅素", "血小板", "微循環", "自律神經", "頭痛", "眩暈", "失眠", "神經", "症候群", "過動", "強迫", "認知", "焦慮", "憂鬱", "創傷後", "痙攣"),
        "mismatch_keywords": ("牙周", "齒槽骨", "視網膜", "角膜", "扁桃腺"),
    },
    "endocrine_receptor": {
        "desc": "內分泌受體與代謝恆定",
        "expected_any": ("糖尿病", "血糖", "耐糖", "三酸甘油酯", "代謝", "甲狀腺", "副甲狀腺", "泌乳素", "荷爾蒙", "胰島素", "痛風", "尿酸", "高血脂", "高膽固醇", "骨質疏鬆", "多囊", "腎上腺", "維生素", "乳房", "女乳", "乳腺", "高血壓", "過動"),
        "mismatch_keywords": ("牙周", "視網膜", "氣管"),
    },
    "skin_barrier": {
        "desc": "表皮真皮屏障修復",
        "expected_any": ("皮膚", "濕疹", "蕁麻疹", "癬", "帶狀皰疹", "乾癬", "異位性", "甲溝", "粉瘤", "脂肪", "毛囊", "痤瘡", "蜂窩性", "潰瘍", "肉芽腫", "癢疹", "天疱瘡", "角化", "汗皰疹", "汗腺", "多汗", "紫斑", "黑色素", "雞眼", "皰疹", "疥瘡", "圓禿"),
        "mismatch_keywords": ("牙周", "視網膜", "胃", "肝"),
    },
    "uro_pelvic": {
        "desc": "泌尿生殖道黏膜與排尿功能",
        "expected_any": ("尿", "膀胱", "腎", "攝護腺", "前列腺", "陰道", "子宮", "卵巢", "包皮", "龜頭", "巴氏腺", "夜尿", "排卵", "月經"),
        "mismatch_keywords": ("耳", "鼻", "牙", "肺", "支氣管", "胃", "頸椎", "腰椎"),
    },
    "uro_genital": {
        "desc": "泌尿／生殖系統結構",
        "expected_any": ("尿", "膀胱", "腎", "攝護腺", "前列腺", "陰道", "子宮", "卵巢", "精", "包皮", "龜頭", "骨盆", "陰囊"),
        "mismatch_keywords": ("眼", "耳", "鼻", "牙", "肺", "支氣管", "胃", "頸椎", "腰椎"),
    },
    "joint_spine": {
        "desc": "關節／脊椎骨骼結構",
        "expected_any": ("關節", "椎", "骨", "肌", "筋膜", "腱", "韌帶", "軟骨", "滑囊", "足底", "網球肘", "高爾夫球肘", "腕隧道", "五十肩", "纖維肌痛", "神經", "頭痛", "生長痛", "脂肪墊", "網球腿", "增生", "PRP"),
        "mismatch_keywords": ("眼", "耳", "鼻", "牙", "胃", "肝", "肺", "尿", "陰道"),
    },
}


def audit_manifest(manifest_path: Path) -> dict[str, Any]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("items", [])

    findings: list[dict[str, Any]] = []
    by_organ = Counter()
    mismatch_by_organ = Counter()

    for it in items:
        arch = it.get("archetype") or {}
        organ = arch.get("s1_organ") or "UNKNOWN"
        by_organ[organ] += 1
        rule = ORGAN_RULES.get(organ)
        if not rule:
            continue

        text = " ".join(
            [
                str(it.get("disease_name") or ""),
                str(it.get("clean_name") or ""),
                str(it.get("clinical_feature") or ""),
                " ".join(it.get("keywords") or []),
            ]
        )
        hit_mismatch = [kw for kw in rule["mismatch_keywords"] if kw in text]
        hit_expected = [kw for kw in rule["expected_any"] if kw in text]

        if hit_mismatch or not hit_expected:
            mismatch_by_organ[organ] += 1
            findings.append(
                {
                    "id": it.get("id"),
                    "icd10": it.get("icd10"),
                    "clean_name": it.get("clean_name") or it.get("disease_name"),
                    "category": it.get("category"),
                    "s1_organ": organ,
                    "theme_name": arch.get("theme_name"),
                    "reason": (
                        f"含非對應部位詞 {hit_mismatch}"
                        if hit_mismatch
                        else f"未命中預期器官關鍵字 ({'/'.join(rule['expected_any'][:4])}...)"
                    ),
                }
            )

    return {
        "total": len(items),
        "mismatch_count": len(findings),
        "by_organ": dict(by_organ),
        "mismatch_by_organ": dict(mismatch_by_organ),
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="稽核衛教圖解 manifest 解剖／器官錯配項目")
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--json", action="store_true", help="以 JSON 格式輸出")
    p.add_argument("--strict", action="store_true", help="有任一錯配即回傳 exit code 1")
    args = p.parse_args(argv)

    report = audit_manifest(args.manifest)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if (args.strict and report["mismatch_count"] > 0) else 0

    print(f"總筆數: {report['total']} | 疑似解剖錯配: {report['mismatch_count']}")
    print("各器官總數 / 疑似錯配數:")
    for organ, cnt in sorted(report["by_organ"].items(), key=lambda x: -x[1]):
        m_cnt = report["mismatch_by_organ"].get(organ, 0)
        print(f"  - {organ}: {cnt} 筆（疑似錯配 {m_cnt} 筆）")

    print("\n疑似錯配明細:")
    for f in report["findings"]:
        print(
            f"  [{f['id']}] ({f['icd10']}) {f['clean_name']} "
            f"| organ={f['s1_organ']} ({f['theme_name']}) | {f['reason']}"
        )
    return 1 if (args.strict and report["mismatch_count"] > 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
