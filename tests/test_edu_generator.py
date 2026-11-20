"""Phase 53-02: `edu_schema` 與 `edu_generator` 單元測試（Mock LLM）。"""

from __future__ import annotations

import json
import sqlite3

import pytest

from src.visual.blueprints import default_params
from src.visual.edu_generator import build_upgraded_ir, generate_edu_content
from src.visual.edu_schema import ensure_edu_columns


def _sample_existing_ir() -> dict:
    p1 = default_params("pathology_mechanism")
    p1["organ_system"] = "gi_tract"
    p1["anatomy_target"] = "大腸結腸憩室病"
    p1["organ_label"] = "乙狀結腸"
    return {
        "topic_key": "nhi-w225-k57-30",
        "title": "大腸結腸憩室病衛教圖解",
        "keywords": ["大腸憩室病", "高纖飲食", "憩室炎"],
        "scenes": [
            {
                "blueprint": "pathology_mechanism",
                "title": "結腸壁囊袋形成機轉",
                "caption": "纖維攝取不足造成腸腔壓力升高，黏膜從肌肉層縫隙向外突出形成小囊袋。",
                "labels": [{"text": "腸壓升高", "tone": "warning"}, {"text": "黏膜突出", "tone": "neutral"}],
                "duration_sec": 8.0,
                "params": p1,
            },
            {
                "blueprint": "contrast",
                "title": "照護處置對照",
                "caption": "初期飲食調整與急性發炎評估在臨床處置上各有重點，需由醫師判斷。",
                "labels": [{"text": "飲食調整", "tone": "optimal"}, {"text": "感染評估", "tone": "warning"}],
                "duration_sec": 8.0,
                "params": default_params("contrast"),
            },
            {
                "blueprint": "timeline",
                "title": "生理復原歷程",
                "caption": "規律追蹤與生活調整有助維持腸道健康，恢復程度因人而異，需由醫師當面評估。",
                "labels": [{"text": "規律追蹤", "tone": "optimal"}],
                "duration_sec": 8.0,
                "params": default_params("timeline"),
            },
        ],
    }


def _mock_llm_payload(bad_phrase: str = "") -> str:
    data = {
        "topic_key": "nhi-w225-k57-30",
        "title": "大腸結腸憩室病衛教圖解",
        "definition": {
            "summary": "憩室是指结肠壁黏膜向外观突出形成小囊袋，好发于乙状结肠。",
            "anatomy_note": "黏膜與黏膜下層從肌肉層縫隙擠出，屬於假性憩室。",
            "key_point": f"大腸憩室病多為良性構造變化，日常高纖飲食很重要。{bad_phrase}",
        },
        "comparison": {
            "left_title": "憩室病",
            "right_title": "憩室炎",
            "rows": [
                {"aspect": "定義", "left_value": "有憩室但沒有發炎", "right_value": "憩室發炎或細菌感染"},
                {"aspect": "處理", "left_value": "高纖飲食與多喝水調整", "right_value": "需醫師評估抗生素或住院"},
            ],
        },
        "causes_risks": {
            "flow_steps": ["纖維攝取不足", "糞便乾硬腸壓升", "黏膜突出成囊袋"],
            "risk_factors": ["60歲以上高齡", "低纖維飲食", "水分不足便祕", "缺乏運動"],
        },
        "symptoms_complications": {
            "symptoms": ["左下腹持續疼痛", "發燒畏寒", "腹脹或排便改變"],
            "complications": [
                {"name": "出血", "description": "可能出現便血或黑便"},
                {"name": "穿孔與膿腫", "description": "腸壁破洞或局部感染化膿"},
            ],
        },
        "diagnosis": {
            "methods": [
                {"method": "電腦斷層(CT)", "purpose": "評估急性憩室炎與是否有膿腫或穿孔"},
                {"method": "結腸鏡", "purpose": "觀察憩室分布，但急性發炎期須謹慎使用"},
            ]
        },
        "prevention_myth": {
            "tips": ["每天攝取足量蔬果與全穀類", "每天喝水 2000-3000cc", "每週至少 150 分鐘中等強度運動"],
            "myth_buster": "研究證實坚果與種子並不會增加憩室炎風險，重點在於足夠纖維與水分。",
        },
        "red_flags_takeaway": {
            "red_flags": ["劇烈且持續腹痛", "高燒畏寒", "大量便血或黑便"],
            "takeaway": "多吃纖維多喝水，腹痛發燒快就醫。",
        },
        "animation_hints": {
            "s1_trigger_label": "低纖高腸壓",
            "s1_lesion_label": "黏膜囊袋突出",
            "s1_defense_label": "腸壁減壓修復",
            "s1_step_labels": ["低纖導致腸壓升", "黏膜擠出肌肉層", "高纖飲水降腸壓"],
            "s1_caption": "纖維攝取不足使腸道壓力升高60%以上，黏膜從肌肉層縫隙向外膨出形成囊袋。",
            "s2_left_title": "憩室病觀察",
            "s2_left_note": "無發炎高纖調整",
            "s2_right_title": "急性憩室炎",
            "s2_right_note": "左下腹痛速就醫",
            "s2_caption": "單純憩室病多無不適，若糞便卡住引發細菌感染則可能演變為急性憩室炎。",
            "s3_care_items": ["高纖蔬果全穀", "每日足量飲水", "規律適度運動", "養成排便習慣"],
            "s3_red_flags": ["劇烈持續腹痛", "高燒畏寒", "大量便血黑便"],
            "s3_myth_note": "坚果種子不會增加憩室炎風險",
            "s3_takeaway": "多吃纖維多喝水，腹痛發燒快就醫。",
            "s3_caption": "日常維持高纖飲食與飲水有助預防發作，出現紅旗症狀應立即就醫檢查。",
        },
    }
    return json.dumps(data, ensure_ascii=False)


def test_generate_edu_and_upgrade_ir_locks_anatomy() -> None:
    existing = _sample_existing_ir()
    edu = generate_edu_content(
        "nhi-w225-k57-30",
        "大腸結腸憩室病衛教圖解",
        existing,
        llm_call=lambda _p: _mock_llm_payload(),
    )
    # 驗證簡體字已轉正體、生理數字仍保留於 edu_json
    assert "結腸" in edu.definition.summary
    assert "堅果" in edu.prevention_myth.myth_buster
    assert "2000-3000cc" in edu.prevention_myth.tips[1]

    upgraded = build_upgraded_ir(existing, edu)
    # 強制鎖定 Phase 52 解剖器官欄位
    assert upgraded["scenes"][0]["params"]["organ_system"] == "gi_tract"
    assert upgraded["scenes"][0]["params"]["anatomy_target"] == "大腸結腸憩室病"
    # 幕 3 升級為 care_redflag，且數字/%已安全轉換
    assert upgraded["scenes"][2]["blueprint"] == "care_redflag"
    assert "堅果" in upgraded["scenes"][2]["params"]["myth_note"]
    assert "60%" not in upgraded["scenes"][0]["caption"]


def test_compliance_rejects_forbidden_phrase() -> None:
    existing = _sample_existing_ir()
    with pytest.raises(ValueError, match="保證療效禁詞"):
        generate_edu_content(
            "nhi-w225-k57-30",
            "大腸結腸憩室病衛教圖解",
            existing,
            llm_call=lambda _p: _mock_llm_payload("保證有效根治"),
        )


def test_ensure_edu_columns_idempotent() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE visual_assets (id INTEGER PRIMARY KEY, topic_key TEXT)")
    ensure_edu_columns(conn)
    ensure_edu_columns(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(visual_assets)").fetchall()}
    assert "edu_json" in cols
    assert "edu_updated_at" in cols
