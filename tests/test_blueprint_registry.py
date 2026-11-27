"""藍圖查表註冊表與複合放行閘門單元測試（Phase 57 57-02 T5）。

驗證項目：
1. 每個 registry 規則命中與無命中 None
2. 具體規則優先於通用規則
3. registry 檔案 SHA-256 凍結比對
4. 證據特徵詞錨定檢驗
5. 複合放行閘門判定（查表命中、LLM + 錨定、無錨定攔截）
6. 過渡期 classifier 模式強制作隔離守門
"""

import hashlib
from pathlib import Path
import pytest

from src.visual.blueprint_registry import (
    TOPIC_BLUEPRINT_REGISTRY,
    BLUEPRINT_EVIDENCE_KEYWORDS,
    lookup_blueprint,
    verify_evidence_keywords,
    is_auto_acceptable,
    filter_for_batch_publishing,
)

# 凍結之 SHA-256 雜湊值（規則更動時需更新決策紀錄與本常數）
FROZEN_REGISTRY_SHA256 = "f5e1b322572e47b55bb821c2f2b21c9172f95c6a41606631041ab69fa6576d89"
REGISTRY_FILE_PATH = Path(__file__).resolve().parent.parent / "src/visual/blueprint_registry.py"


def test_registry_sha256_frozen():
    """雜湊凍結測試：驗證 blueprint_registry.py 之 SHA-256 與常數完全相符。"""
    assert REGISTRY_FILE_PATH.exists(), f"找不到檔案：{REGISTRY_FILE_PATH}"
    actual_sha = hashlib.sha256(REGISTRY_FILE_PATH.read_bytes()).hexdigest()
    assert (
        actual_sha == FROZEN_REGISTRY_SHA256
    ), f"查表規則庫已被變更！預期 SHA-256: {FROZEN_REGISTRY_SHA256}，實際: {actual_sha}。更動需經 T4 審定。"


def test_lookup_blueprint_hits_all_rules():
    """驗證每組 registry 規則均有至少一個具體命中測試。"""
    cases = [
        # A. 外科與微創處置
        ("未感染粉瘤微創手術", "cyst_excision"),
        ("甲溝炎嵌甲甲床重整", "nail_matrix"),
        ("微創螺旋刀頂漿腺狐臭", "subdermal_curettage"),
        ("微創脂肪瘤抽吸切除", "subdermal_curettage"),
        ("中下臉 SMAS 筋膜深層拉皮手術", "deep_plane_facelift"),
        ("雙下巴闊頸肌馬甲式拉提", "corset_platysmaplasty"),
        ("3D數位導航正顎手術", "surgical_action"),
        ("顏面輪廓削骨成型", "surgical_action"),
        ("下巴截骨成型術", "surgical_action"),
        # C. 能量、光學與微整
        ("Thermage FLX 鳳凰電波緊膚", "skin_energy"),
        ("Ultraformer 音波拉提", "skin_energy"),
        ("黃金微針電波拉提", "skin_energy"),
        ("皮秒雷射除斑", "laser_action"),
        ("微創飛梭雷射", "laser_action"),
        ("Triton 海神雙波長雷射除毛", "laser_action"),
        ("Endolift 光纖內提拉", "laser_action"),
        ("肉毒桿菌瘦小臉", "neuromuscular"),
        ("玻尿酸法令紋填充", "dermal_support"),
        ("洢蓮絲膠原蛋白增生劑", "dermal_support"),
        ("Hydrafacial 海菲秀深層清潔煥膚", "process_diagram"),
        ("水光針保濕導入", "process_diagram"),
        # B. 健保常見輕症與病理機轉
        ("急性上呼吸道感染", "pathology_mechanism"),
        ("流行性感冒", "pathology_mechanism"),
        ("過敏性鼻炎", "pathology_mechanism"),
        ("原發性高血壓", "pathology_mechanism"),
        ("第二型糖尿病", "pathology_mechanism"),
        ("高尿酸血症與痛風", "pathology_mechanism"),
        ("急性胃腸炎", "pathology_mechanism"),
        ("胃食道逆流", "pathology_mechanism"),
    ]

    for title, expected_bp in cases:
        matched = lookup_blueprint(title=title)
        assert matched == expected_bp, f"主題「{title}」查表結果應為 {expected_bp}，但得到 {matched}"


def test_lookup_blueprint_unmatched_returns_none():
    """驗證未命中任何白名單規則的主題回傳 None（由後續 LLM 處理）。"""
    assert lookup_blueprint(title="自體軟骨重建手術") is None
    assert lookup_blueprint(title="未定專科複合諮詢") is None
    assert lookup_blueprint(title="") is None


def test_lookup_blueprint_specificity_order():
    """驗證具體專科規則優先於通用規則命中。"""
    # 「粉瘤切除手術」應優先命中 cyst_excision，而非通用 surgical_action
    assert lookup_blueprint("粉瘤切除手術") == "cyst_excision"
    # 「嵌甲甲床重整手術」應優先命中 nail_matrix，而非通用 surgical_action
    assert lookup_blueprint("嵌甲手術") == "nail_matrix"
    # 「頂漿腺狐臭手術」應優先命中 subdermal_curettage，而非通用 surgical_action
    assert lookup_blueprint("頂漿腺狐臭切除手術") == "subdermal_curettage"
    # 「微針電波」應命中 skin_energy
    assert lookup_blueprint("黃金微針電波拉皮手術") == "skin_energy"


def test_verify_evidence_keywords():
    """驗證藍圖特徵詞錨定檢驗邏輯。"""
    # 1. laser_action 包含雷射/光束等特徵詞
    assert verify_evidence_keywords("laser_action", "利用極短脈衝光束擊碎黑色素") is True
    assert verify_evidence_keywords("laser_action", "以二氧化碳汽化微光束治療") is True
    # 缺少雷射特徵詞 -> False
    assert verify_evidence_keywords("laser_action", "手術切除組織並精密縫合") is False

    # 2. skin_energy 包含電波/音波/探頭等
    assert verify_evidence_keywords("skin_energy", "探頭將立體高頻電波容積式傳導至真皮層") is True
    assert verify_evidence_keywords("skin_energy", "利用聚焦超音波能量作用於筋膜層") is True
    # 缺少能量特徵詞 -> False
    assert verify_evidence_keywords("skin_energy", "以細針注射藥物於肌肉層") is False

    # 3. other 一律合格
    assert verify_evidence_keywords("other", "") is True
    assert verify_evidence_keywords("other", "任何字串") is True


def test_is_auto_acceptable_gate():
    """驗證複合放行閘門（Multi-Signal Gate）。"""
    # 1. 查表命中直接合格
    reg_hit = {"source": "registry", "blueprint": "skin_energy"}
    assert is_auto_acceptable(reg_hit) is True

    # 2. LLM 輸出 ok 且證據具備特徵詞 -> 放行
    llm_valid = {
        "source": "llm",
        "status": "ok",
        "blueprint": "laser_action",
        "evidence_span": "皮秒雷射利用極短脈衝光束擊碎黑色素",
    }
    assert is_auto_acceptable(llm_valid) is True

    # 3. LLM 輸出 ok 但證據無特徵詞 -> 不予放行
    llm_no_anchor = {
        "source": "llm",
        "status": "ok",
        "blueprint": "laser_action",
        "evidence_span": "手術切除組織並精密縫合",
    }
    assert is_auto_acceptable(llm_no_anchor) is False

    # 4. LLM 狀態為 invalid_evidence 或 low_confidence -> 不予放行
    llm_bad_status = {
        "source": "llm",
        "status": "invalid_evidence",
        "blueprint": "laser_action",
        "evidence_span": "雷射光束",
    }
    assert is_auto_acceptable(llm_bad_status) is False


def test_filter_for_batch_publishing_quarantine():
    """驗證過渡期在 classifier 模式下一律標記 needs_review: true 且阻斷自動入庫。"""
    # 即使為可自動接受之項目，在 classifier 模式下亦強制隔離
    ir_sample = {"topic_key": "test-disease", "scenes": [{"blueprint": "skin_energy"}]}
    can_publish, reason = filter_for_batch_publishing(ir_sample, blueprint_mode="classifier")
    assert can_publish is False
    assert reason == "classifier_quarantine"
    assert ir_sample.get("needs_review") is True

    # fixed 模式下維持正常放行
    ir_fixed = {"topic_key": "test-disease", "scenes": [{"blueprint": "pathology_mechanism"}]}
    can_pub_fixed, reason_fixed = filter_for_batch_publishing(ir_fixed, blueprint_mode="fixed")
    assert can_pub_fixed is True
    assert reason_fixed == "ok"
