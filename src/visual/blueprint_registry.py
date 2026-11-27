"""臨床主題與疾病動畫第一幕藍圖查表註冊表與放行閘門模組（Phase 57 57-02 T5）。

本模組落實：
1. 依據 57-02-DECISIONS.md（A1/B2/C1）與 PHYSICIAN-LABELING-GUIDE.md 建立確定性查表
2. 藍圖特徵詞錨定檢驗（Blueprint Semantic Anchor Verification）
3. 複合放行閘門（Multi-Signal Auto-Accept Gate）
4. 過渡期零風險守門機制

【防火牆規範】：
本模組規則僅能來自官方決策與客觀醫學指引，嚴禁根據黃金集個別題目的除錯錯誤進行反向 hardcode。
模組內容建立完成後進行 SHA-256 凍結。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from src.visual.blueprint_classifier import (
    CLASSIFIER_ALLOWED_BLUEPRINTS,
    normalize_text_for_comparison,
)

# 1. 藍圖特徵關鍵字註冊表（用於證據片段特徵詞錨定）
# 每一藍圖至少須含以下核心臨床特徵詞之一，否則判定為 invalid_evidence
BLUEPRINT_EVIDENCE_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "laser_action": (
        "雷射", "光束", "光纖", "波長", "脈衝", "奈米", "色素", "擊碎", "微光束", "光熱", "汽化", "除毛"
    ),
    "skin_energy": (
        "電波", "音波", "微針", "探頭", "熱能", "熱凝", "聚焦", "高頻", "容積式", "超音波", "凝結"
    ),
    "neuromuscular": (
        "肉毒", "神經", "肌肉", "收縮", "放鬆", "動態紋", "針頭", "注射"
    ),
    "dermal_support": (
        "玻尿酸", "填充", "注入", "皮下", "真皮深層", "支撐", "容積", "回填", "凹陷", "鈍針"
    ),
    "cyst_excision": (
        "粉瘤", "囊腫", "囊壁", "囊腔", "角質", "剝離", "囊袋", "排空", "表皮樣"
    ),
    "nail_matrix": (
        "嵌甲", "甲床", "甲母質", "甲板", "肉芽", "側邊甲", "剪除", "電燒", "趾神經"
    ),
    "subdermal_curettage": (
        "螺旋刀", "頂漿腺", "刮除", "抽吸", "脂肪瘤", "旋轉刀", "皮下組織", "負壓", "鈍頭"
    ),
    "deep_plane_facelift": (
        "拉皮", "SMAS", "筋膜", "深層平面", "骨膜", "懸吊", "錨定", "耳前", "韌帶鬆解", "顴骨韌帶"
    ),
    "corset_platysmaplasty": (
        "闊頸肌", "馬甲", "對縫", "頸前", "頸角", "束帶"
    ),
    "surgical_action": (
        "截骨", "骨鋸", "鈦板", "鈦釘", "固定", "切骨", "下顎", "顴骨", "正顎", "神經保護", "頦神經"
    ),
    "pathology_mechanism": (
        "發炎", "感染", "黏膜", "病原", "充血", "水腫", "組織胺", "受損", "病理", "病因",
        "硬化", "纖維化", "增生", "積液", "胰島素", "血糖", "血壓", "血脂", "尿酸", "膽固醇", "脂肪堆積"
    ),
    "process_diagram": (
        "步驟", "流程", "階段", "水渦漩", "清潔", "煥膚", "精華", "導入", "端頭", "負壓"
    ),
    "other": (),
}

# 2. 確定性主題與處置查表註冊表 (TOPIC_BLUEPRINT_REGISTRY)
# 有序列表：較具體的專科微創規則置於前，通用規則置於後
# 依據 57-02-DECISIONS.md (A1, B2, C1) 建立客觀映射
TOPIC_BLUEPRINT_REGISTRY: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    # --- A. 外科與專屬微創處置 (A1 決定) ---
    (("粉瘤", "表皮樣囊腫", "皮脂腺囊腫", "囊腫切除"), "cyst_excision"),
    (("嵌甲", "甲溝炎", "指甲矯治", "甲床重整"), "nail_matrix"),
    (("狐臭", "頂漿腺", "螺旋刀", "脂肪瘤", "副乳抽吸"), "subdermal_curettage"),
    (("深層平面拉皮", "深層拉皮", "SMAS筋膜拉皮", "SMAS拉皮"), "deep_plane_facelift"),
    (("闊頸肌", "馬甲式拉提", "雙下巴闊頸肌"), "corset_platysmaplasty"),
    (("正顎", "削骨", "下巴截骨", "顴骨內推", "下顎角削減", "截骨成型"), "surgical_action"),

    # --- C. 能量、光學與注射微整 (C1 決定) ---
    (("微針電波", "黃金微針", "鳳凰電波", "電波拉皮", "音波拉提", "媚必提", "聚焦超音波"), "skin_energy"),
    (("皮秒雷射", "飛梭雷射", "雷射除毛", "雙波長雷射", "光纖內提拉", "海神雷射", "二氧化碳雷射"), "laser_action"),
    (("肉毒桿菌", "肉毒注射", "肉毒瘦臉", "肉毒除皺"), "neuromuscular"),
    (("玻尿酸", "洢蓮絲", "膠原蛋白增生劑", "微整填充", "淚溝填充"), "dermal_support"),
    (("海菲秀", "水渦漩", "水光針", "深層清潔煥膚", "果酸煥膚"), "process_diagram"),

    # --- B. 健保常見疾病與病理機轉 (B2 決定) ---
    ((
        "流行性感冒", "感冒", "上呼吸道感染", "急性咽喉炎", "咽喉炎", "扁桃腺炎",
        "過敏性鼻炎", "急性支氣管炎", "支氣管炎", "急性鼻竇炎", "鼻竇炎",
        "急性中耳炎", "中耳炎", "氣喘", "原發性高血壓", "高血壓",
        "第二型糖尿病", "糖尿病", "高脂血症", "高膽固醇", "痛風", "高尿酸血症",
        "非酒精性脂肪肝", "脂肪肝", "慢性腎臟", "急性胃腸炎", "胃腸炎",
        "胃食道逆流", "胃炎", "十二指腸炎"
    ), "pathology_mechanism"),
)


def lookup_blueprint(title: str = "", icd_name: str = "") -> Optional[str]:
    """根據主題名稱或 ICD 疾病名稱執行確定性白名單查表。

    比對原則：
    - 將 title 與 icd_name 組合後進行規格化
    - 依序比對 TOPIC_BLUEPRINT_REGISTRY 中的關鍵字清單
    - 優先命中者直接回傳藍圖代碼；完全未命中回傳 None。
    """
    text = f"{title or ''} {icd_name or ''}".strip()
    if not text:
        return None

    norm_text = text.lower()
    for keywords, blueprint in TOPIC_BLUEPRINT_REGISTRY:
        for kw in keywords:
            if kw.lower() in norm_text:
                return blueprint

    return None


def verify_evidence_keywords(blueprint: str, evidence_span: str) -> bool:
    """檢驗證據片段是否包含該藍圖的必要臨床特徵詞（特徵詞錨定檢驗）。

    規則：
    - 若 blueprint == 'other'，不需特徵詞，一律合格。
    - 若 blueprint 在特徵詞表中，evidence_span 必須包含清單中的至少一項特徵詞。
    """
    if blueprint == "other":
        return True

    if blueprint not in BLUEPRINT_EVIDENCE_KEYWORDS:
        return False

    keywords = BLUEPRINT_EVIDENCE_KEYWORDS[blueprint]
    if not keywords:
        return True

    clean_evidence = normalize_text_for_comparison(evidence_span)
    for kw in keywords:
        norm_kw = normalize_text_for_comparison(kw)
        if norm_kw and norm_kw in clean_evidence:
            return True

    return False


def is_auto_acceptable(result: Dict[str, Any]) -> bool:
    """複合放行閘門（Multi-Signal Auto-Accept Gate）。

    放行條件（任一）：
    1. 命中白名單查表（source == "registry"）
    2. LLM 分類結果 status == "ok" 且通過特徵詞錨定檢驗（verify_evidence_keywords 為 True）

    依決策明確排除信心門檻 0.85（實測無效）。
    """
    if not isinstance(result, dict):
        return False

    source = result.get("source")
    if source == "registry":
        bp = result.get("blueprint")
        return bool(bp and bp in CLASSIFIER_ALLOWED_BLUEPRINTS)

    status = result.get("status")
    bp = result.get("blueprint")
    ev = result.get("evidence_span", "")

    if status == "ok" and bp in CLASSIFIER_ALLOWED_BLUEPRINTS:
        return verify_evidence_keywords(bp, ev)

    return False


def filter_for_batch_publishing(ir: Dict[str, Any], blueprint_mode: str = "fixed") -> Tuple[bool, str]:
    """過渡期批次發布守門策略。

    過渡期規定（57-02-T5）：
    - 在 classifier 模式下，即使項目判定為可自動接受，也一律強制標記 needs_review: true，
      並阻斷自動發布入庫（跳過入庫，僅寫離線 JSON），達成實體入庫 0% 風險。
    - 在 fixed 模式下維持正常流程。
    """
    if not isinstance(ir, dict):
        return False, "invalid_ir"

    if blueprint_mode == "classifier":
        # 過渡期硬性隔離
        ir["needs_review"] = True
        return False, "classifier_quarantine"

    # fixed 模式正常守門
    if ir.get("needs_review"):
        return False, "needs_review"

    return True, "ok"
