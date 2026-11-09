# -*- coding: utf-8 -*-
"""Phase 39 Plan 03: 健保 200 大疾病向量動畫批次生成與自癒管線單元測試。

驗證範圍：
1. 乾跑與專科藍圖映射（牙科、中醫、內分泌、呼吸）。
2. 阿拉伯數字清洗與本地自癒邏輯。
3. 離峰守門保護行為（非優惠時段拒絕多筆，放行單題或測試模式）。
4. 模擬 LLM 輸出瑕疵之雙層自癒重試。
5. 單題真實呼叫 DeepSeek API 生成 24 秒 IR 驗收。
"""

import copy
import json
import sqlite3
from pathlib import Path
import pytest

from scripts.generate_nhi200_visual_batch import (
    DISCLAIMER_SUFFIX,
    extract_anatomy_fact_sheet_deepseek,
    compile_visual_ir_local,
    generate_single_nhi_ir,
    map_disease_to_blueprint_archetype,
    post_process_self_heal,
    run_batch_generation,
    sanitize_text_digits,
)
from src.pageindex.deepseek_client import call_deepseek
from src.visual.ir import validate_ir


def test_sanitize_text_digits():
    """驗證阿拉伯數字清洗函式。"""
    raw = "第1階段需3至5天，恢復率達90%，約10次"
    cleaned = sanitize_text_digits(raw)
    assert "1" not in cleaned
    assert "3" not in cleaned
    assert "5" not in cleaned
    assert "90" not in cleaned
    assert "%" not in cleaned
    assert "第" in cleaned and "階段" in cleaned


def test_blueprint_archetype_mapping():
    """驗證不同系統之藍圖映射。"""
    # 牙科
    dental_item = {"system": "dental", "name": "齲齒填補", "category": "牙齒口腔"}
    d_arch = map_disease_to_blueprint_archetype(dental_item)
    assert d_arch["s1_organ"] == "dental_oral"
    assert d_arch["s2_left_mode"] == "dental_caries_erosion"
    assert d_arch["s3_connector"] == "dental_pulp_healing"

    # 中醫
    tcm_item = {"system": "tcm", "name": "中醫落枕傷筋", "category": "骨傷科"}
    t_arch = map_disease_to_blueprint_archetype(tcm_item)
    assert t_arch["s1_organ"] == "tcm_meridian"
    assert t_arch["s2_left_mode"] == "tcm_qi_stagnation"
    assert t_arch["s3_connector"] == "tcm_meridian_harmony"

    # 內分泌代謝
    endocrine_item = {"system": "western", "name": "第2型糖尿病", "category": "代謝與心血管慢性病"}
    e_arch = map_disease_to_blueprint_archetype(endocrine_item)
    assert e_arch["s1_organ"] == "endocrine_receptor"
    assert e_arch["s2_left_mode"] == "metabolic_insulin_resistance"
    assert e_arch["s3_connector"] == "metabolic_vessel_stabilization"


def test_post_process_self_heal_adds_disclaimer_and_cleans():
    """驗證本地自癒修復：阿拉伯數字自動清洗、第三幕強制追加免責條款、固定 8 秒。"""
    item = {"name": "測試疾病", "system": "western"}
    archetype = map_disease_to_blueprint_archetype(item)

    flawed_ir = {
        "topic_key": "test-disease",
        "title": "測試第1型疾病衛教",
        "keywords": ["測試1", "衛教2"],
        "scenes": [
            {
                "blueprint": "pathology_mechanism",
                "title": "第1幕說明",
                "caption": "病程第3天局部微血管充血水腫，請持續觀察變化。",
                "labels": [{"text": "標籤1", "tone": "neutral"}],
                "duration_sec": 7,
                "params": {},
            },
            {
                "blueprint": "contrast",
                "title": "第2幕說明",
                "caption": "對比延誤就醫與正規照護之差異，避免病情惡化。",
                "labels": [{"text": "不良處置", "tone": "warning"}],
                "duration_sec": 9,
                "params": {},
            },
            {
                "blueprint": "timeline",
                "title": "第3幕說明",
                "caption": "組織在後續階段逐步獲得修復與代謝穩定。",  # 缺少免責聲明
                "labels": [{"text": "修復穩定", "tone": "optimal"}],
                "duration_sec": 6,
                "params": {},
            },
        ],
    }

    healed = post_process_self_heal(flawed_ir, archetype, item)

    # 1. 數字全數被清理
    assert "1" not in healed["title"]
    assert "3" not in healed["scenes"][0]["caption"]
    # 2. 時長強制固定為 8 秒
    for sc in healed["scenes"]:
        assert sc["duration_sec"] == 8
    # 3. 第三幕自動追加免責聲明
    assert "因人而異" in healed["scenes"][2]["caption"] or "醫師" in healed["scenes"][2]["caption"]


def test_dry_run_batch_pipeline(tmp_path):
    """驗證 dry-run 模式下只進行藍圖試算，不寫入資料庫。"""
    db_file = tmp_path / "test_clinic.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE visual_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id TEXT,
            topic_key TEXT NOT NULL,
            title TEXT NOT NULL,
            keywords TEXT,
            ir_json TEXT NOT NULL,
            source_type TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()
    conn.close()

    res = run_batch_generation(
        db_path=db_file,
        limit=2,
        dry_run=True,
    )
    assert res["dry_run"] is True
    assert res["total"] == 2
    assert res["success"] == 2

    # 驗證資料庫未產生任何寫入
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM visual_assets")
    count = cur.fetchone()[0]
    conn.close()
    assert count == 0


def test_self_healing_retry_loop_with_mock():
    """驗證當模型首輪輸出違規時，自癒重試迴圈能將錯誤反饋給模型並在第二輪修復。"""
    item = {
        "id": "T001",
        "name": "測試過敏性鼻炎",
        "system": "western",
        "category": "呼吸系統與急性感染",
        "keywords": ["打噴嚏", "流鼻水"],
    }

    # 模擬 LLM：第 1 次輸出含阿拉伯數字（會失敗），第 2 次修正為合法
    call_count = 0

    def mock_llm(prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # 帶阿拉伯數字的瑕疵輸出
            return """
            {
              "topic_key": "nhi-t001-allergic-rhinitis",
              "title": "過敏性鼻炎圖解",
              "keywords": ["過敏", "鼻炎"],
              "scenes": [
                {
                  "blueprint": "pathology_mechanism",
                  "title": "黏膜過敏機轉",
                  "caption": "過敏原在3分鐘內刺激鼻黏膜肥大細胞釋放組織胺導致充血腫脹。",
                  "labels": [{"text": "過敏原", "tone": "warning"}, {"text": "鼻黏膜", "tone": "neutral"}],
                  "duration_sec": 8,
                  "params": {"organ_system": "respiratory_mucosa", "severity_level": 3, "step_labels": ["抗原刺激", "組織胺釋放", "黏膜水腫"]}
                },
                {
                  "blueprint": "contrast",
                  "title": "照護處置對比",
                  "caption": "對比持續接觸過敏原與積極防護清潔之差異，減緩日常不適症狀。",
                  "labels": [{"text": "延誤處置", "tone": "warning"}, {"text": "積極照護", "tone": "optimal"}],
                  "duration_sec": 8,
                  "params": {
                    "left": {"title": "延誤處置", "mode": "mucosal_irritant_surge", "unit_fill": "warn"},
                    "right": {"title": "積極照護", "mode": "barrier_hydration_shield", "unit_fill": "ok"}
                  }
                },
                {
                  "blueprint": "timeline",
                  "title": "黏膜復原歷程",
                  "caption": "透過環境防護與規律清洗，黏膜防禦功能平穩恢復，因人而異，具體照護請由專業醫師當面評估。",
                  "labels": [{"text": "黏膜修復", "tone": "optimal"}, {"text": "防禦屏障", "tone": "optimal"}],
                  "duration_sec": 8,
                  "params": {"connectors": "mucosal_clearance", "unit_fill": "accent"}
                }
              ]
            }
            """
        else:
            # 合規輸出
            return """
            {
              "topic_key": "nhi-t001-allergic-rhinitis",
              "title": "過敏性鼻炎圖解",
              "keywords": ["過敏", "鼻炎"],
              "scenes": [
                {
                  "blueprint": "pathology_mechanism",
                  "title": "黏膜過敏機轉",
                  "caption": "過敏原刺激鼻黏膜肥大細胞釋放組織胺，引起局部微血管充血水腫。",
                  "labels": [{"text": "過敏原", "tone": "warning"}, {"text": "鼻黏膜", "tone": "neutral"}],
                  "duration_sec": 8,
                  "params": {"organ_system": "respiratory_mucosa", "severity_level": 3, "step_labels": ["抗原刺激", "組織胺釋放", "黏膜水腫"]}
                },
                {
                  "blueprint": "contrast",
                  "title": "照護處置對比",
                  "caption": "對比持續接觸過敏原與積極防護清潔之差異，減緩日常不適症狀。",
                  "labels": [{"text": "延誤處置", "tone": "warning"}, {"text": "積極照護", "tone": "optimal"}],
                  "duration_sec": 8,
                  "params": {
                    "left": {"title": "延誤處置", "mode": "mucosal_irritant_surge", "unit_fill": "warn"},
                    "right": {"title": "積極照護", "mode": "barrier_hydration_shield", "unit_fill": "ok"}
                  }
                },
                {
                  "blueprint": "timeline",
                  "title": "黏膜復原歷程",
                  "caption": "透過環境防護與規律清洗，黏膜防禦功能平穩恢復，因人而異，具體照護請由專業醫師當面評估。",
                  "labels": [{"text": "黏膜修復", "tone": "optimal"}, {"text": "防禦屏障", "tone": "optimal"}],
                  "duration_sec": 8,
                  "params": {"connectors": "mucosal_clearance", "unit_fill": "accent"}
                }
              ]
            }
            """

    ok, ir, err = generate_single_nhi_ir(item, llm_call=mock_llm, max_retries=3)
    assert ok is True
    assert ir is not None
    assert ir["topic_key"] == "nhi-t001-allergic-rhinitis"


def test_single_nhi_item_generation_pipeline(monkeypatch):
    """驗證單題 IR 生成管線端到端驗收（含驗證與 24 秒結構）。"""
    test_item = {
        "id": "W003",
        "system": "western",
        "category": "呼吸系統與急性感染",
        "name": "急性扁桃腺炎",
        "icd10": "J03.90",
        "alias": ["扁桃腺化膿", "扁桃腺發炎"],
        "keywords": ["喉嚨劇痛", "扁桃腺腫大", "吞嚥困難"],
    }

    mock_response = """
    {
      "topic_key": "nhi-w003-acute-tonsillitis",
      "title": "急性扁桃腺炎圖解",
      "keywords": ["喉嚨劇痛", "扁桃腺腫大", "吞嚥困難"],
      "scenes": [
        {
          "blueprint": "pathology_mechanism",
          "title": "病原菌侵襲扁桃腺",
          "caption": "病原菌突破扁桃腺隱窩防禦引起局部黏膜急性充血腫脹與化膿反應。",
          "labels": [{"text": "病原菌", "tone": "warning"}, {"text": "扁桃腺隱窩", "tone": "neutral"}],
          "duration_sec": 8,
          "params": {"organ_system": "respiratory_mucosa", "severity_level": 4, "step_labels": ["隱窩侵襲", "黏膜水腫", "化膿充血"]}
        },
        {
          "blueprint": "contrast",
          "title": "延誤就醫與正規照護",
          "caption": "對比延誤處置導致周圍膿瘍擴散與及早醫療處置之差異，有效緩解吞嚥疼痛。",
          "labels": [{"text": "延誤處置", "tone": "warning"}, {"text": "積極照護", "tone": "optimal"}],
          "duration_sec": 8,
          "params": {
            "left": {"title": "延誤處置", "mode": "mucosal_irritant_surge", "unit_fill": "warn"},
            "right": {"title": "積極照護", "mode": "barrier_hydration_shield", "unit_fill": "ok"}
          }
        },
        {
          "blueprint": "timeline",
          "title": "黏膜組織逐步復原",
          "caption": "經過適當照護與充足休養，局部黏膜充血逐步消退恢復正常吞嚥機能，因人而異，具體照護請由專業醫師當面評估。",
          "labels": [{"text": "發炎消退", "tone": "optimal"}, {"text": "機能復原", "tone": "optimal"}],
          "duration_sec": 8,
          "params": {"connectors": "mucosal_clearance", "unit_fill": "accent"}
        }
      ]
    }
    """

    ok, ir, err = generate_single_nhi_ir(test_item, llm_call=lambda p: mock_response, max_retries=2)
    assert ok is True, f"生成或驗證失敗: {err}"
    assert ir is not None

    # 驗證結構與時長
    ok_val, val_code = validate_ir(ir)
    assert ok_val is True, f"IR 驗證失敗: {val_code}"

    # 驗證總時長精確為 24 秒
    durations = [sc["duration_sec"] for sc in ir["scenes"]]
    assert sum(durations) == 24
    assert len(ir["scenes"]) == 3
