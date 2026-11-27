"""固定模式快照回歸測試（Phase 57-02 T2 驗收）。

目的：確認 nhi200／nhi400 批次腳本在 blueprint_mode="fixed"（預設）下的輸出，
與改接前的版本逐欄相同。基準檔 tests/fixtures/nhi_fixed_snapshot.json 由改接前（git HEAD）
的程式以同一份 collect() 產生，因此本測試是行為等價性檢查，而非自我一致性檢查。

重新產生基準檔的方式：在改接前的程式樹中執行 collect()，並寫入上述路徑（見 57-02 SUMMARY）。
"""

import inspect
import json
from pathlib import Path

from scripts import generate_nhi200_visual_batch as n200
from scripts import generate_nhi400_visual_batch as n400
from src.visual.blueprints import BLUEPRINTS

FIXTURE = Path(__file__).parent / "fixtures" / "nhi_fixed_snapshot.json"


def _call(fn, *args, **kwargs):
    """只傳入函式簽名支援的關鍵字參數，使同一份輸入可同時跑改接前與改接後的程式。
    是否真的有傳入 blueprint_mode，由 test_blueprint_mode_flag_is_wired 另行保證。"""
    params = inspect.signature(fn).parameters
    return fn(*args, **{k: v for k, v in kwargs.items() if k in params})


def _fake_local_llm(prompt: str) -> str:
    payload = {
        "topic_key": "nhi-001-hypertension",
        "title": "高血壓衛教圖解",
        "keywords": ["高血壓", "血管"],
        "scenes": [
            {
                "blueprint": "pathology_mechanism",
                "title": "病理機轉解說",
                "caption": "血管組織在高壓血流衝擊下，管壁承受極大張力，須持續由專業醫師當面評估。",
                "labels": [{"text": "高壓血流", "tone": "warning"}, {"text": "血管組織", "tone": "neutral"}],
                "duration_sec": 8,
                "params": BLUEPRINTS["pathology_mechanism"]["defaults"],
            },
            {
                "blueprint": "contrast",
                "title": "照護處置對照",
                "caption": "延誤處置易加重負擔，規律照護有助穩定結構防禦，詳細照護建議由專業醫師當面評估。",
                "labels": [{"text": "延誤處置", "tone": "warning"}, {"text": "規律追蹤", "tone": "optimal"}],
                "duration_sec": 8,
                "params": BLUEPRINTS["contrast"]["defaults"],
            },
            {
                "blueprint": "timeline",
                "title": "長期復原進程",
                "caption": "血管結構逐步穩定，配合專業醫事人員指導維持健康，個人化處置因人而異。",
                "labels": [{"text": "初起穩定", "tone": "neutral"}, {"text": "長期維護", "tone": "optimal"}],
                "duration_sec": 8,
                "params": BLUEPRINTS["timeline"]["defaults"],
            },
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def collect() -> dict:
    """以固定輸入、fixed 模式跑批次產生路徑，回傳 JSON 可序列化的結果。"""
    item200 = {
        "id": "nhi-001",
        "name": "高血壓",
        "clean_name": "高血壓",
        "category": "循環系統",
        "keywords": ["高血壓", "血管", "血壓計"],
    }
    archetype200 = {
        "s1_organ": "vascular_metabolic",
        "s2_left_mode": "延誤處置",
        "s2_right_mode": "規律追蹤",
        "s3_connector": "循序漸進",
    }
    fact200 = {
        "organ_label": "血管組織",
        "lesion_label": "動脈硬化",
        "trigger_label": "高壓血流",
        "defense_label": "內皮修復",
        "step_labels": ["血壓上升", "管壁受壓", "組織修復"],
        "pathology_notes": "病理機轉備註",
        "contrast_notes": "對照備註",
        "timeline_notes": "時間軸備註",
    }
    items400 = [
        {"index": 201, "topic_key": "nhi-201-glaucoma", "disease_name": "青光眼",
         "category": "眼部疾患", "keywords": ["青光眼", "視神經", "眼壓"]},
        {"index": 202, "topic_key": "nhi-202-gerd", "disease_name": "胃食道逆流",
         "category": "消化系統", "keywords": ["胃酸", "食道", "逆流"]},
        {"index": 203, "topic_key": "nhi-203-acne", "disease_name": "痘痘",
         "category": "皮膚", "keywords": ["痘痘", "皮脂", "毛囊"]},
        {"index": 204, "topic_key": "nhi-204-tooth", "disease_name": "牙周病",
         "category": "口腔", "keywords": ["牙齦", "牙周", "牙菌斑"]},
    ]

    results: dict = {
        "nhi200_compile_local": _call(
            n200.compile_visual_ir_local,
            item200,
            archetype200,
            fact200,
            call_local_fn=_fake_local_llm,
            blueprint_mode="fixed",
        )
    }
    for it in items400:
        ok, ir, code = _call(
            n400.generate_single_item_with_self_healing,
            it,
            mock_mode=True,
            blueprint_mode="fixed",
        )
        results[f"nhi400_{it['topic_key']}"] = {"ok": ok, "ir": ir, "code": code}

    # 正規化為純 JSON 型別（tuple→list 等），與基準檔比對時才不會因型別表示差異誤判。
    return json.loads(json.dumps(results, ensure_ascii=False, default=str))


def test_blueprint_mode_flag_is_wired():
    """確認改接後兩支腳本確實接受 blueprint_mode，避免 _call 的過濾把旗標靜默丟掉。"""
    assert "blueprint_mode" in inspect.signature(n200.compile_visual_ir_local).parameters
    assert "blueprint_mode" in inspect.signature(n200.generate_single_nhi_ir).parameters
    assert "blueprint_mode" in inspect.signature(n400.generate_single_item_with_self_healing).parameters


def test_fixed_mode_output_matches_pre_change_snapshot():
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    actual = collect()
    assert set(actual) == set(expected)
    for key in expected:
        assert actual[key] == expected[key], f"快照不一致：{key}"


def test_fixed_mode_keeps_pathology_mechanism_first_scene():
    """fixed 模式下所有樣本第一幕皆為 pathology_mechanism（與改接前行為一致）。"""
    actual = collect()
    assert actual["nhi200_compile_local"]["scenes"][0]["blueprint"] == "pathology_mechanism"
    for key, val in actual.items():
        if key.startswith("nhi400_"):
            assert val["ir"]["scenes"][0]["blueprint"] == "pathology_mechanism", key
