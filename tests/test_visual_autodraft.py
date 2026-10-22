"""
Phase 31 Task 1 & 2: PageIndex 推理樹自動生成視覺解說卡草稿測試 (test_visual_autodraft.py)。
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import pytest

from tests.conftest import apply_visual_migration
from src.pageindex.tree_review import (
    has_tree_review_status,
    TREE_APPROVED,
    TREE_PENDING,
    TREE_REJECTED,
)
from src.pageindex.llm_lock import GENERATION_LOCK
from src.visual.autodraft import (
    autodraft_from_tree,
    build_tree_visual_prompt,
    fetch_eligible_trees,
    normalize_tree_topic_key,
    parse_and_build_tree_ir,
)
from scripts.autodraft_visual_from_trees import main as cli_main, PROD_DB_PATH


VALID_MODEL_JSON = """
{
  "title": "海芙音波緊緻原理",
  "keywords": ["海芙音波", "音波拉提", "緊緻拉提"],
  "scenes": [
    {
      "blueprint": "process_diagram",
      "title": "聚焦超音波作用",
      "caption": "透過高強度聚焦超音波能量傳遞至筋膜層，於組織形成微細熱凝結點以啟動自然修復機轉。",
      "labels": [
        {"text": "聚焦能量", "tone": "neutral"},
        {"text": "筋膜加熱", "tone": "optimal"}
      ],
      "params": {
        "source": {"label": "音波探頭", "fill": "accent"},
        "particles": 6,
        "container_layers": [
          {"label": "表皮層", "fill": "pale", "weight": 2, "keep": false},
          {"label": "筋膜層", "fill": "accent", "weight": 3, "keep": true},
          {"label": "肌肉層", "fill": "neutral", "weight": 2, "keep": false}
        ],
        "step_labels": ["表皮穿透", "筋膜聚焦", "熱能刺激"]
      }
    },
    {
      "blueprint": "contrast",
      "title": "施作方式比較",
      "caption": "醫師精準調控能量並分層施打，能提供均勻拉提感受，相較單點過度施打更為合適穩定。",
      "labels": [
        {"text": "單點過度", "tone": "warning"},
        {"text": "分層均勻", "tone": "optimal"}
      ],
      "params": {
        "left": {
          "title": "單點過度",
          "note": "熱能累積過高",
          "mode": "mass",
          "core_effect": "dim",
          "core_label": "表皮負擔",
          "footnote": "單點重覆施打容易造成局部不適",
          "unit_fill": "warn"
        },
        "right": {
          "title": "多層均勻",
          "note": "多層次分散",
          "mode": "layered",
          "rows": 3,
          "per_row": 5,
          "footnote": "均勻分散傳導有助於組織漸進緊緻",
          "unit_fill": "ok"
        }
      }
    },
    {
      "blueprint": "timeline",
      "title": "膠原新生進程",
      "caption": "術後初期組織緊縮，隨時間推移深層膠原逐漸重組，實際維持時間因人而異需由醫師評估。",
      "labels": [
        {"text": "初期緊繃", "tone": "neutral"},
        {"text": "漸進緊緻", "tone": "optimal"}
      ],
      "params": {
        "milestones": ["熱刺激期", "新生重組", "輪廓維持"],
        "unit_effect": "mature",
        "connectors": "vessels",
        "units": 3,
        "unit_fill": "ok"
      }
    }
  ]
}
"""


def _seed_tree(
    conn: sqlite3.Connection,
    *,
    doc_id: str = "test-hifu-lifting",
    clinic_id: str | None = None,
    category: str = "special",
    title: str = "海芙音波拉提",
    review_status: str = TREE_APPROVED,
    source_type: str = "llm_generated",
) -> int:
    """在 page_index_trees 種下一筆推理樹記錄。"""
    cur = conn.cursor()
    cur.execute("DELETE FROM page_index_trees WHERE doc_id = ?", (doc_id,))
    cur.execute("PRAGMA table_info(page_index_trees)")
    cols = [r[1] for r in cur.fetchall()]

    col_names = ["doc_id", "clinic_id", "category", "title", "summary_text", "pre_op", "procedure", "post_op_short", "maintenance", "source_type"]
    vals = [
        doc_id,
        clinic_id,
        category,
        title,
        "聚焦超音波緊緻拉提技術",
        "評估臉部鬆弛度與脂肪厚度",
        "分層傳遞超音波聚焦熱凝結點",
        "加強保濕防曬避免過度搓揉",
        "定期維持保養並維持正常作息",
        source_type,
    ]

    if "review_status" in cols:
        col_names.append("review_status")
        vals.append(review_status)

    placeholders = ", ".join(["?"] * len(vals))
    col_str = ", ".join(col_names)
    cur.execute(f"INSERT INTO page_index_trees ({col_str}) VALUES ({placeholders})", tuple(vals))
    conn.commit()
    return cur.lastrowid


def test_normalize_tree_topic_key():
    """驗證 normalize_tree_topic_key 規則與邊界。"""
    assert normalize_tree_topic_key("hifu-lifting") == "tree-hifu-lifting"
    assert normalize_tree_topic_key("tree-hifu-lifting") == "tree-hifu-lifting"
    assert normalize_tree_topic_key("  Laser-Skin  ") == "tree-laser-skin"

    # 非法長度或字元
    with pytest.raises(ValueError, match="schema_error"):
        normalize_tree_topic_key("a" * 70)
    with pytest.raises(ValueError, match="schema_error"):
        normalize_tree_topic_key("invalid_char$#@")
    with pytest.raises(ValueError, match="schema_error"):
        normalize_tree_topic_key(123)  # type: ignore


def test_fetch_eligible_trees_filters_unapproved(isolated_db_path: Path):
    """驗證 fetch_eligible_trees 僅回傳符合可見性（已核准）之推理樹。"""
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        t1 = _seed_tree(conn, doc_id="approved-tree-1", review_status=TREE_APPROVED, clinic_id="3503190424")
        t2 = _seed_tree(conn, doc_id="pending-tree-2", review_status=TREE_PENDING, clinic_id="3503190424")
        t3 = _seed_tree(conn, doc_id="rejected-tree-3", review_status=TREE_REJECTED)

        # 1. 查詢所有合格樹
        eligible = fetch_eligible_trees(conn)
        eligible_doc_ids = {t["doc_id"] for t in eligible}
        assert "approved-tree-1" in eligible_doc_ids
        assert "pending-tree-2" not in eligible_doc_ids
        assert "rejected-tree-3" not in eligible_doc_ids

        # 2. 指定 tree_id 或 doc_id 查詢
        res_t1 = fetch_eligible_trees(conn, tree_id=t1)
        assert len(res_t1) == 1
        assert res_t1[0]["doc_id"] == "approved-tree-1"

        res_t2 = fetch_eligible_trees(conn, tree_id=t2)
        assert res_t2 == []

        res_t3 = fetch_eligible_trees(conn, doc_id="rejected-tree-3")
        assert res_t3 == []

        # 3. 診所篩選
        res_c1 = fetch_eligible_trees(conn, clinic_id="3503190424")
        assert any(t["doc_id"] == "approved-tree-1" for t in res_c1)
        res_c2 = fetch_eligible_trees(conn, clinic_id="3503264627")
        assert not any(t["doc_id"] == "approved-tree-1" for t in res_c2)
    finally:
        conn.close()


def test_build_tree_visual_prompt():
    """驗證提示詞正確帶入推理樹資訊、推斷契合之解剖機轉模板與禁止規則。"""
    tree = {
        "title": "海芙音波拉提",
        "doc_id": "hifu-lifting",
        "summary_text": "聚焦超音波緊緻拉提技術",
        "pre_op": "評估臉部鬆弛度",
        "procedure": "分層傳遞能量",
        "post_op_short": "注意保濕防曬",
        "maintenance": "規律作息",
    }
    prompt = build_tree_visual_prompt(tree)
    assert "海芙音波拉提" in prompt
    assert "聚焦超音波緊緻拉提技術" in prompt
    assert "零數字原則" in prompt
    assert "skin_energy" in prompt
    assert "contrast" in prompt
    assert "timeline" in prompt
    assert "因人而異" in prompt

    # 驗證脂肪移植主題仍推斷 process_diagram
    fat_tree = {"title": "自體脂肪補臉", "doc_id": "fat-grafting", "summary_text": "抽取純化自體脂肪"}
    fat_prompt = build_tree_visual_prompt(fat_tree)
    assert "process_diagram" in fat_prompt


def test_parse_and_build_tree_ir_success():
    """驗證合法 JSON 能正確解析為 Typed IR 且無數字、完全合規。"""
    raw = f"```json\n{VALID_MODEL_JSON}\n```"
    ir, code = parse_and_build_tree_ir(raw, topic_key="tree-hifu-lifting", fallback_title="海芙音波")
    assert code == "ok"
    assert ir is not None
    assert ir["topic_key"] == "tree-hifu-lifting"
    assert len(ir["scenes"]) == 3
    assert ir["scenes"][0]["blueprint"] == "process_diagram"
    assert ir["scenes"][1]["blueprint"] == "contrast"
    assert ir["scenes"][2]["blueprint"] == "timeline"
    assert ir["scenes"][0]["params"]["source"]["label"] == "音波探頭"
    assert ir["scenes"][2]["params"]["milestones"] == ["熱刺激期", "新生重組", "輪廓維持"]


def test_parse_and_build_tree_ir_zero_pollution_enforcement():
    """驗證缺少文字型 params 時會直接拒絕，絕不使用寫死之自體脂肪預設文字。"""
    bad_data = json.loads(VALID_MODEL_JSON)
    # 移除 source.label
    bad_data["scenes"][0]["params"]["source"]["label"] = ""
    ir, code = parse_and_build_tree_ir(json.dumps(bad_data), "tree-test", "測試")
    assert ir is None
    assert code in ("schema_error", "param_error")

    # 移除 milestones
    bad_data2 = json.loads(VALID_MODEL_JSON)
    del bad_data2["scenes"][2]["params"]["milestones"]
    ir2, code2 = parse_and_build_tree_ir(json.dumps(bad_data2), "tree-test", "測試")
    assert ir2 is None
    assert code2 in ("schema_error", "param_error")


def test_parse_and_build_tree_ir_digit_and_forbidden_checks():
    """驗證包含阿拉伯數字或缺少收尾語意時被拒絕。"""
    # 1. 包含阿拉伯數字 3
    bad_digits = json.loads(VALID_MODEL_JSON)
    bad_digits["scenes"][0]["caption"] = "透過聚焦能量作用於筋膜層達到 3 倍刺激效果以利組織健康修復。"
    ir1, code1 = parse_and_build_tree_ir(json.dumps(bad_digits), "tree-test", "測試")
    assert ir1 is None
    assert code1 == "forbidden_phrase"

    # 2. 第三場景缺少「因人而異」或「醫師評估」收尾詞
    bad_closing = json.loads(VALID_MODEL_JSON)
    bad_closing["scenes"][2]["caption"] = "術後初期組織緊縮，隨時間推移深層膠原逐漸重組，組織狀態便會逐步達到一定程度的穩定。"
    ir2, code2 = parse_and_build_tree_ir(json.dumps(bad_closing), "tree-test", "測試")
    assert ir2 is None
    assert code2 == "forbidden_phrase"

    # 3. topic_key 本身含數字（如 tree-3d-lifting）不應被零數字規則誤殺，且 right.rows/per_row 正確保留
    custom_data = json.loads(VALID_MODEL_JSON)
    custom_data["scenes"][1]["params"]["right"]["rows"] = 2
    custom_data["scenes"][1]["params"]["right"]["per_row"] = 4
    ir3, code3 = parse_and_build_tree_ir(json.dumps(custom_data), "tree-3d-lifting", "立體拉提")
    assert code3 == "ok"
    assert ir3 is not None
    assert ir3["topic_key"] == "tree-3d-lifting"
    assert ir3["scenes"][1]["params"]["right"]["rows"] == 2
    assert ir3["scenes"][1]["params"]["right"]["per_row"] == 4

    # 4. 非脂肪主題若殘留引擎預設脂肪移植文字（如「中心缺血」或「抽取之脂肪組織」）必須拒絕
    polluted = json.loads(VALID_MODEL_JSON)
    polluted["scenes"][1]["params"]["left"]["core_label"] = "中心缺血"
    ir4, code4 = parse_and_build_tree_ir(json.dumps(polluted), "tree-hifu-lifting", "海芙音波")
    assert ir4 is None
    assert code4 == "forbidden_phrase"


def test_autodraft_from_tree_e2e_isolated(isolated_db_path: Path):
    """端到端驗證由已核准推理樹生成草稿並成功寫入 visual_assets（狀態 pending）。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        tree_id = _seed_tree(conn, doc_id="test-hifu-lifting", clinic_id="3503190424", review_status=TREE_APPROVED)

        def mock_llm(_prompt: str) -> str:
            return f"<think>思考中</think>\n```json\n{VALID_MODEL_JSON}\n```"

        res = autodraft_from_tree(conn, tree_id, llm_call=mock_llm, db_path=isolated_db_path)
        assert res["status"] == "ok"
        assert res["topic_key"] == "tree-test-hifu-lifting"
        assert res["clinic_id"] == "3503190424"
        assert res["review_status"] == "pending"
        assert res["inserted"] == 1

        # 檢查資料庫內容
        cur = conn.cursor()
        cur.execute("SELECT review_status, source_type, clinic_id FROM visual_assets WHERE topic_key = 'tree-test-hifu-lifting'")
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "pending"
        assert row[1] == "llm_generated"
        assert row[2] == "3503190424"
    finally:
        conn.close()


def test_autodraft_unapproved_tree_rejected(isolated_db_path: Path):
    """驗證未核准推理樹被拒絕生成。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        t_pend = _seed_tree(conn, doc_id="unapproved-tree", review_status=TREE_PENDING)
        res = autodraft_from_tree(conn, t_pend, db_path=isolated_db_path)
        assert res["status"] == "error"
        assert res["code"] == "tree_not_approved"

        # 不存在的 tree_id 回傳 not_found
        res_non = autodraft_from_tree(conn, 999999, db_path=isolated_db_path)
        assert res_non["status"] == "not_found"
    finally:
        conn.close()


def test_autodraft_busy_handling(isolated_db_path: Path):
    """驗證排程互斥鎖生效時回傳 busy。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        tree_id = _seed_tree(conn, doc_id="hifu-lifting", review_status=TREE_APPROVED)
        # 佔用鎖
        assert GENERATION_LOCK.acquire(blocking=False)
        try:
            res = autodraft_from_tree(conn, tree_id, db_path=isolated_db_path)
            assert res["status"] == "busy"
            assert res["code"] == "busy"
        finally:
            GENERATION_LOCK.release()
    finally:
        conn.close()


def test_autodraft_cli(isolated_db_path: Path, capsys: pytest.CaptureFixture):
    """驗證 CLI 參數、正式庫拒絕與唯讀預覽模式。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    _seed_tree(conn, doc_id="test-hifu-lifting", review_status=TREE_APPROVED)
    conn.close()

    # 1. 目標為正式庫且未帶 --allow-prod-db：結束碼 2
    exit_code_prod = cli_main(["--db", str(PROD_DB_PATH)])
    assert exit_code_prod == 2
    captured = capsys.readouterr()
    assert "【操作拒絕】目標為正式資料庫" in captured.err

    # 2. --dry-run 唯讀預覽：結束碼 0
    exit_code_dry = cli_main(["--db", str(isolated_db_path), "--dry-run"])
    assert exit_code_dry == 0
    cap_dry = capsys.readouterr()
    assert "【預覽模式】" in cap_dry.out
    assert "test-hifu-lifting" in cap_dry.out

    # 3. 指定不存在的 --doc-id：結束碼 1
    exit_code_none = cli_main(["--db", str(isolated_db_path), "--dry-run", "--doc-id", "non-existent"])
    assert exit_code_none == 1


def test_infer_scene1_blueprint_all_topics():
    """驗證 5 大解剖機轉與常見療程推斷正確性。"""
    from src.visual.autodraft import infer_scene1_blueprint

    # 1. 皮秒雷射 -> laser_action (shatter)
    bp, info = infer_scene1_blueprint({"title": "皮秒雷射", "doc_id": "laser-skin-resurfacing", "summary_text": "黑色素沉著改善"})
    assert bp == "laser_action"
    assert info["params_template"]["mode"] == "shatter"

    # 2. 飛梭雷射 -> laser_action (fractional)
    bp, info = infer_scene1_blueprint({"title": "飛梭雷射", "doc_id": "fractional-laser", "summary_text": "毛孔凹疤修復"})
    assert bp == "laser_action"
    assert info["params_template"]["mode"] == "fractional"

    # 3. 音波拉提 -> skin_energy (focused)
    bp, info = infer_scene1_blueprint({"title": "音波拉提", "doc_id": "hifu-lifting", "summary_text": "聚焦超音波SMAS筋膜層"})
    assert bp == "skin_energy"
    assert info["params_template"]["mode"] == "focused"

    # 4. 電波拉皮 -> skin_energy (volumetric)
    bp, info = infer_scene1_blueprint({"title": "電波拉皮", "doc_id": "electrowave-facelift", "summary_text": "容積式真皮層加熱緊緻"})
    assert bp == "skin_energy"
    assert info["params_template"]["mode"] == "volumetric"

    # 5. 肉毒桿菌素 -> neuromuscular
    bp, info = infer_scene1_blueprint({"title": "肉毒桿菌素注射", "doc_id": "botox-injection", "summary_text": "改善動態表情紋"})
    assert bp == "neuromuscular"

    # 6. 玻尿酸 -> dermal_support
    bp, info = infer_scene1_blueprint({"title": "玻尿酸填充", "doc_id": "hyaluronic-acid-filler", "summary_text": "凹陷部位立體支撐"})
    assert bp == "dermal_support"

    # 7. 自體脂肪 -> process_diagram
    bp, info = infer_scene1_blueprint({"title": "自體脂肪移植", "doc_id": "fat-grafting", "summary_text": "脂肪純化與分層移植"})
    assert bp == "process_diagram"

    # 8. 中下臉 SMAS 筋膜深層拉皮 -> deep_plane_facelift
    bp, info = infer_scene1_blueprint({"title": "中下臉 SMAS 筋膜深層拉皮手術", "doc_id": "mid-lower-smas-facelift", "summary_text": "深層間隙解離維持韌帶與骨膜錨定"})
    assert bp == "deep_plane_facelift"
    assert info["params_template"]["smas_label"] == "SMAS筋膜瓣"

    # 9. 天鵝頸闊頸肌縫合拉皮術 -> corset_platysmaplasty
    bp, info = infer_scene1_blueprint({"title": "天鵝頸闊頸肌縫合拉皮術", "doc_id": "swan-neck-cervicoplasty", "summary_text": "下巴天然皮摺微創切口與闊頸肌馬甲對縫"})
    assert bp == "corset_platysmaplasty"
    assert info["params_template"]["muscle_label"] == "兩側闊頸肌"


def test_parse_and_build_tree_ir_with_new_blueprints():
    """驗證以新解剖機轉模板（如 neuromuscular、dermal_support、laser_action、skin_energy）組裝之 IR 合法解析。"""
    neuromuscular_json = """
    {
      "title": "肉毒桿菌素除皺原理",
      "keywords": ["肉毒桿菌", "動態紋", "除皺放鬆"],
      "scenes": [
        {
          "blueprint": "neuromuscular",
          "title": "神經訊號傳導調節",
          "caption": "透過微量作用於神經肌肉接合處，暫時阻斷乙醯膽鹼釋放，使過度緊繃的肌肉放鬆以撫平動態摺痕。",
          "labels": [
            {"text": "神經末梢", "tone": "neutral"},
            {"text": "肌肉放鬆", "tone": "optimal"}
          ],
          "params": {
            "nerve_label": "運動神經末梢",
            "muscle_label": "過度收縮肌肉",
            "surface_label": "動態表情皺紋",
            "blocker_fill": "ok",
            "step_labels": ["精準微量注射", "調節神經訊號", "肌肉放鬆撫平"]
          }
        },
        {
          "blueprint": "contrast",
          "title": "劑量與分點比較",
          "caption": "由專業醫師評估採微量多點放置，保留自然表情靈活度，避免單點集中過量造成僵硬感。",
          "labels": [
            {"text": "單點過量", "tone": "warning"},
            {"text": "微量多點", "tone": "optimal"}
          ],
          "params": {
            "left": {
              "title": "單點過量",
              "note": "過度集中擴散",
              "mode": "mass",
              "core_effect": "dim",
              "core_label": "表情僵硬",
              "footnote": "單點注射過量易擴散影響周圍表情",
              "unit_fill": "warn"
            },
            "right": {
              "title": "微量多點",
              "note": "精準分層控制",
              "mode": "layered",
              "rows": 3,
              "per_row": 5,
              "footnote": "精準劑量分佈能維持自然面部神韻",
              "unit_fill": "ok"
            }
          }
        },
        {
          "blueprint": "timeline",
          "title": "舒張與維持時程",
          "caption": "注射後數日逐漸發揮舒張放鬆作用，平滑表情細紋，整體維持時程因人而異需由醫師評估。",
          "labels": [
            {"text": "注射初期", "tone": "neutral"},
            {"text": "平穩撫平", "tone": "optimal"}
          ],
          "params": {
            "milestones": ["初期放鬆", "平滑穩定", "定期保養"],
            "unit_effect": "steady",
            "connectors": "none",
            "units": 3,
            "unit_fill": "ok"
          }
        }
      ]
    }
    """
    ir, code = parse_and_build_tree_ir(neuromuscular_json, topic_key="tree-botox-injection", fallback_title="肉毒桿菌素注射")
    assert code == "ok"
    assert ir is not None
    assert ir["scenes"][0]["blueprint"] == "neuromuscular"
    assert ir["scenes"][2]["params"]["connectors"] == "none"


def test_surgical_procedures_infer_surgical_action_blueprint():
    """Plan 32-02：截骨、正顎、削骨、隆鼻、眼袋優先匹配 surgical_action；一般脂肪處置不受影響。"""
    from src.visual.autodraft import infer_scene1_blueprint
    from src.visual.blueprints import validate_params

    cases = {
        "下巴美型手術（3D客製人工骨植入與下巴截骨成型術）": "mandible",
        "3D 數位導航正顎手術（雙顎 LeFort I 與下顎枝截骨成型術）": "mandible",
        # 標題同時含顴骨與下顎骨角，依規則先命中下顎（單一場景僅能呈現一個解剖目標）
        "顏面輪廓削骨手術（顴骨弓內推縮窄與下顎骨角削減塑型）": "mandible",
        "顴骨內推削骨手術": "malar_bone",
        "結構式自體軟骨全方位隆鼻手術": "general_surgery",
        "全方位美眸眼整形手術（無痕內開眼袋移位）": "general_surgery",
    }
    for title, expected_target in cases.items():
        bp, info = infer_scene1_blueprint({"doc_id": "x", "title": title, "summary_text": ""})
        assert bp == "surgical_action", title
        params = info["params_template"]
        assert params["anatomy_target"] == expected_target, title
        ok, code = validate_params("surgical_action", params)
        assert ok is True, (title, code)

    bp, _ = infer_scene1_blueprint({"doc_id": "autologous", "title": "自體脂肪移植", "summary_text": ""})
    assert bp == "process_diagram"


# ---- Phase 33 Plan 33-01：專科對照與修復歷程推斷 ----

_CONTRAST_TREES = {
    "抽脂": ("tissue_trauma_torn_vessel", "ultrasonic_emulsification", "全方位抽脂體雕手術"),
    "眼": ("scar_contracture_ectropion", "transconjunctival_fat_reposition", "全方位美眸眼整形手術（無痕內開眼袋移位）"),
    "鼻": ("silicone_extrusion_erythema", "cartilage_triangular_strut", "結構式自體軟骨全方位隆鼻手術"),
    "隆乳": ("capsular_contracture_ball", "dual_plane_natural_teardrop", "假體隆乳雕塑手術"),
    "微整": ("nodule_clumping", "micro_droplet_diffusion", "玻尿酸皮下填充微整形雕塑"),
}

_TIMELINE_TREES = {
    "bone_healing": "3D 數位導航正顎手術（下顎枝截骨成型術）",
    "nerve_regeneration": "中下臉 SMAS 深層拉皮手術",
    "bruise_metabolism": "肉毒桿菌素注射與微整療程",
    "scar_maturation": "雙眼皮與隆鼻手術切口",
    "skin_retraction": "非侵入音波拉提療程",
}


def test_contrast_specialties_select_symmetric_modes_and_validate():
    from src.visual.autodraft import infer_scene2_contrast, select_contrast_modes
    from src.visual.blueprints import enum_values, validate_params

    for label, (left, right, title) in _CONTRAST_TREES.items():
        tree = {"doc_id": f"x-{label}", "title": title, "summary_text": "", "procedure": ""}
        picked = select_contrast_modes(tree)
        assert picked is not None, label
        assert (picked[0], picked[1]) == (left, right), label
        assert left in enum_values("contrast", "mode", "left")
        assert right in enum_values("contrast", "mode", "right")
        info = infer_scene2_contrast(tree)
        assert info["params"]["left"]["mode"] == left
        assert info["params"]["right"]["mode"] == right
        ok, code = validate_params("contrast", info["params"])
        assert ok is True, (label, code)
        assert 20 <= len(info["caption"]) <= 120
        assert not any(ch.isdigit() for ch in info["caption"])


def test_contrast_general_fallback_unchanged():
    from src.visual.autodraft import infer_scene2_contrast

    tree = {"doc_id": "autologous-fat-grafting", "title": "自體脂肪移植", "summary_text": "", "procedure": ""}
    info = infer_scene2_contrast(tree)
    assert info["params"]["left"]["mode"] == "mass"
    assert info["params"]["right"]["mode"] == "layered"


def test_timeline_specialties_select_connectors_and_validate():
    from src.visual.autodraft import infer_scene3_timeline
    from src.visual.blueprints import validate_params

    cases = {
        "bone_healing": "3D 數位導航正顎手術（下顎枝截骨成型術）",
        "nerve_regeneration": "中下臉 SMAS 深層拉皮手術",
        "bruise_metabolism": "肉毒桿菌素注射與微整療程",
        "scar_maturation": "雙眼皮與隆鼻手術切口",
        "skin_retraction": "非侵入音波拉提療程",
    }
    for connector, title in cases.items():
        tree = {"doc_id": f"t-{connector}", "title": title, "summary_text": "", "procedure": ""}
        info = infer_scene3_timeline(tree)
        assert info["params"]["connectors"] == connector, (connector, info["params"]["connectors"])
        assert len(info["params"]["milestones"]) == 3
        assert all(len(m) <= 8 and not any(ch.isdigit() for ch in m) for m in info["params"]["milestones"])
        assert "因人而異" in info["caption"] and 20 <= len(info["caption"]) <= 120
        ok, code = validate_params("timeline", info["params"])
        assert ok is True, (connector, code)


def test_prompt_carries_specialty_mode_recommendations():
    from src.visual.autodraft import build_tree_visual_prompt

    tree = {"doc_id": "x", "title": "全方位抽脂體雕手術", "summary_text": "", "procedure": "", "pre_op": "", "post_op_short": "", "maintenance": ""}
    prompt = build_tree_visual_prompt(tree)
    assert "tissue_trauma_torn_vessel" in prompt
    assert "ultrasonic_emulsification" in prompt
    assert "8. 對照與歷程列舉" in prompt


def test_parser_keeps_new_modes_instead_of_resetting_to_defaults():
    """自癒整形器：新列舉值必須被保留（白名單來自規格，不再硬編碼舊值）。"""
    import json as _json
    from src.visual.autodraft import (
        infer_scene1_blueprint, infer_scene2_contrast, infer_scene3_timeline, parse_and_build_tree_ir,
    )

    tree = {"doc_id": "x", "title": "全方位抽脂體雕手術", "summary_text": "", "procedure": ""}
    s1_bp, s1 = infer_scene1_blueprint(tree)
    s2 = infer_scene2_contrast(tree)
    s3 = infer_scene3_timeline(tree)

    def _scene(bp, title, caption, labels, params):
        return {"blueprint": bp, "title": title, "caption": caption, "labels": labels, "params": params}

    ir_json = _json.dumps({
        "title": "抽脂體雕原理圖解",
        "keywords": ["抽脂", "體雕"],
        "scenes": [
            _scene(s1_bp, s1["title"], "抽吸與處置機轉的說明文字，用於測試解析器保留既有模式。", [{"text": "抽吸", "tone": "neutral"}], s1["params_template"]),
            _scene("contrast", s2["title"], s2["caption"], s2["labels"], s2["params"]),
            _scene("timeline", s3["title"], s3["caption"], s3["labels"], s3["params"]),
        ],
    }, ensure_ascii=False)

    ir, code = parse_and_build_tree_ir(ir_json, topic_key="tree-test-liposuction", fallback_title="全方位抽脂體雕手術")
    assert code == "ok", code
    assert ir["scenes"][1]["params"]["left"]["mode"] == "tissue_trauma_torn_vessel"
    assert ir["scenes"][1]["params"]["right"]["mode"] == "ultrasonic_emulsification"
    assert ir["scenes"][2]["params"]["connectors"] == "skin_retraction"


def test_parse_and_build_tree_ir_surgical_action():
    """驗證 surgical_action 專科動作圖元在解析器中能正確整形並保留骨骼神經參數。"""
    import json as _json
    from src.visual.autodraft import parse_and_build_tree_ir, infer_scene1_blueprint

    tree = {"doc_id": "test-genioplasty", "title": "下巴截骨美型手術", "summary_text": "下顎骨截骨滑移並以純鈦剛性固定"}
    s1_bp, s1_info = infer_scene1_blueprint(tree)
    assert s1_bp == "surgical_action"
    assert s1_info["params_template"]["anatomy_target"] == "mandible"

    raw_json = _json.dumps({
        "title": "下巴截骨成型原理圖解",
        "keywords": ["下顎截骨", "神經保護", "純鈦板釘"],
        "scenes": [
            {
                "blueprint": "surgical_action",
                "title": "外科機轉與骨骼處置",
                "caption": "手術自口內切口進入並在骨膜下精密剝離，全程保護頦神經並完成截骨滑移與純鈦板釘剛性固定。",
                "labels": [{"text": "頦神經保護", "tone": "neutral"}, {"text": "口內隱痕", "tone": "optimal"}],
                "params": {
                    "anatomy_target": "mandible",
                    "bone_label": "下顎骨端",
                    "nerve_label": "頦神經",
                    "nerve_status": "protected",
                    "incision_label": "口內隱痕",
                    "fixation_label": "純鈦板釘",
                    "bone_shift_mm": 6,
                    "protect_nerve": True,
                    "step_labels": ["口內切口進入", "神經保護處置", "穩定固定完成"],
                },
            },
            {
                "blueprint": "contrast",
                "title": "手術方式對比說明",
                "caption": "相較於傳統大切口拉扯組織與明顯痕跡，口內微創小孔徑能減輕組織張力並促進癒合。",
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
            },
            {
                "blueprint": "timeline",
                "title": "骨骼修復歷程",
                "caption": "術後初期骨痂形成，隨後骨小樑緻密並達到咬合穩固，恢復狀況因人而異需由醫師當面評估。",
                "labels": [{"text": "骨痂形成", "tone": "neutral"}, {"text": "咬合穩固", "tone": "optimal"}],
                "params": {
                    "milestones": ["骨痂形成", "骨小樑緻密", "咬合穩固"],
                    "unit_effect": "mature",
                    "connectors": "bone_healing",
                    "units": 3,
                    "unit_fill": "accent",
                },
            },
        ],
    }, ensure_ascii=False)

    ir, code = parse_and_build_tree_ir(raw_json, topic_key="tree-test-genioplasty", fallback_title="下巴截骨美型手術")
    assert code == "ok", code
    assert ir is not None
    assert ir["scenes"][0]["blueprint"] == "surgical_action"
    assert ir["scenes"][0]["params"]["anatomy_target"] == "mandible"
    assert ir["scenes"][0]["params"]["bone_shift_mm"] == 6
    assert ir["scenes"][0]["params"]["protect_nerve"] is True
    assert ir["scenes"][1]["blueprint"] == "contrast"
    assert ir["scenes"][2]["blueprint"] == "timeline"
    assert ir["scenes"][2]["params"]["connectors"] == "bone_healing"
