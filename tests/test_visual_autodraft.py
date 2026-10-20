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
    """驗證提示詞正確帶入推理樹資訊與禁止規則。"""
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
    assert "process_diagram" in prompt
    assert "contrast" in prompt
    assert "timeline" in prompt
    assert "因人而異" in prompt


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
